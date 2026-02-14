"""
Render Engine for Audiobooker.

Synthesizes chapters to audio. Accepts an injected TTSEngine for testability;
defaults to the real voice-soundboard DialogueEngine when none is provided.
"""

import json
import logging
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from audiobooker.renderer.protocols import TTSEngine, SynthesisResult

if TYPE_CHECKING:
    from audiobooker.project import AudiobookProject
    from audiobooker.models import Chapter, CastingTable

# Structured logger for render operations
logger = logging.getLogger("audiobooker.renderer")


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

@dataclass
class RenderLog:
    """Structured log entry for chapter rendering."""
    chapter_index: int
    chapter_title: str
    utterance_count: int
    total_chars: int
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
    output_path: str = ""
    status: str = "pending"  # pending | success | error
    error_message: str = ""
    error_utterance_index: int = -1
    error_speaker: str = ""
    error_text_preview: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    def log(self):
        if self.status == "error":
            logger.error(f"RENDER_FAIL: {self.to_json()}")
        else:
            logger.info(f"RENDER_OK: {self.to_json()}")


# ---------------------------------------------------------------------------
# Real engine factory (lazy import — no top-level voice_soundboard dep)
# ---------------------------------------------------------------------------

class _VoiceSoundboardEngine:
    """Wraps voice-soundboard's DialogueEngine to satisfy TTSEngine protocol."""

    def __init__(self):
        try:
            from voice_soundboard.dialogue.engine import DialogueEngine
        except ImportError:
            raise ImportError(
                "voice-soundboard is required for rendering. "
                "Ensure it's installed and accessible:\n"
                "  pip install -e F:/AI/voice-soundboard"
            )
        self._engine = DialogueEngine()

    def synthesize(
        self,
        script: str,
        voices: dict[str, str],
        output_path: Path,
        progress_callback: Optional[Callable] = None,
    ) -> SynthesisResult:
        result = self._engine.synthesize(
            script=script,
            voices=voices,
            output_path=output_path,
            progress_callback=progress_callback,
        )
        return SynthesisResult(
            audio_path=result.audio_path,
            duration_seconds=result.duration_seconds,
        )


def get_default_engine() -> TTSEngine:
    """Create the real voice-soundboard TTS engine (lazy)."""
    return _VoiceSoundboardEngine()


# ---------------------------------------------------------------------------
# Chapter rendering
# ---------------------------------------------------------------------------

def render_chapter(
    chapter: "Chapter",
    casting: "CastingTable",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    *,
    engine: Optional[TTSEngine] = None,
) -> Path:
    """
    Render a single chapter to audio.

    Args:
        chapter: Chapter with compiled utterances.
        casting: CastingTable for voice mapping.
        output_path: Output audio file path.
        progress_callback: Callback(current_utterance, total_utterances).
        engine: Injected TTSEngine (defaults to voice-soundboard).

    Returns:
        Path to rendered audio file.
    """
    from audiobooker.casting.dialogue import utterances_to_script

    if not chapter.utterances:
        raise ValueError(f"Chapter {chapter.index} has no utterances. Compile first.")

    total_chars = sum(len(u.text) for u in chapter.utterances)
    render_log = RenderLog(
        chapter_index=chapter.index,
        chapter_title=chapter.title,
        utterance_count=len(chapter.utterances),
        total_chars=total_chars,
        start_time=time.time(),
    )

    current_utterance_idx = 0  # initialized before try block

    try:
        script = utterances_to_script(chapter.utterances, casting)
        voice_mapping = casting.get_voice_mapping()

        if engine is None:
            engine = get_default_engine()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def internal_progress(current: int, total: int, speaker: str = ""):
            nonlocal current_utterance_idx
            current_utterance_idx = current - 1
            if progress_callback:
                progress_callback(current, total)

        result = engine.synthesize(
            script=script,
            voices=voice_mapping,
            output_path=output_path,
            progress_callback=internal_progress,
        )

        chapter.audio_path = result.audio_path
        chapter.duration_seconds = result.duration_seconds

        render_log.end_time = time.time()
        render_log.duration_seconds = result.duration_seconds
        render_log.output_path = str(result.audio_path)
        render_log.status = "success"
        render_log.log()

        return result.audio_path

    except Exception as e:
        render_log.end_time = time.time()
        render_log.status = "error"
        render_log.error_message = str(e)

        if current_utterance_idx < len(chapter.utterances):
            failing = chapter.utterances[current_utterance_idx]
            render_log.error_utterance_index = current_utterance_idx
            render_log.error_speaker = failing.speaker
            render_log.error_text_preview = failing.text[:80]

        render_log.log()
        raise


# ---------------------------------------------------------------------------
# Project rendering
# ---------------------------------------------------------------------------

def render_project(
    project: "AudiobookProject",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    *,
    engine: Optional[TTSEngine] = None,
    assembler: Optional[Callable] = None,
) -> Path:
    """
    Render all chapters and assemble final audiobook.

    Args:
        project: AudiobookProject to render.
        output_path: Output file path (.m4b or .mp3).
        progress_callback: Callback(current_chapter, total_chapters, status).
        engine: Injected TTSEngine (defaults to voice-soundboard).
        assembler: Injected assembly function (defaults to assemble_m4b).

    Returns:
        Path to final audiobook file.
    """
    from audiobooker.renderer.output import assemble_m4b as _default_assembler

    if assembler is None:
        assembler = _default_assembler

    output_path = Path(output_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="audiobooker_"))

    logger.info(
        f"RENDER_START: project={project.title!r} "
        f"chapters={len(project.chapters)} output={output_path}"
    )

    try:
        chapter_audio_paths = []
        total_render_time = 0.0

        for i, chapter in enumerate(project.chapters):
            if progress_callback:
                progress_callback(i + 1, len(project.chapters), f"Rendering: {chapter.title}")

            if chapter.is_rendered and chapter.audio_path and chapter.audio_path.exists():
                logger.info(f"RENDER_SKIP: chapter={i} title={chapter.title!r} (already rendered)")
                chapter_audio_paths.append(chapter.audio_path)
                continue

            chapter_path = temp_dir / f"chapter_{i:03d}.wav"
            start = time.time()
            render_chapter(chapter, project.casting, chapter_path, engine=engine)
            elapsed = time.time() - start
            total_render_time += elapsed

            chapter_audio_paths.append(chapter_path)

        if progress_callback:
            progress_callback(len(project.chapters), len(project.chapters), "Assembling audiobook...")

        logger.info(
            f"RENDER_ASSEMBLE: chapters={len(chapter_audio_paths)} "
            f"total_render_time={total_render_time:.1f}s"
        )

        chapter_info = [
            (path, chapter.title, chapter.duration_seconds)
            for path, chapter in zip(chapter_audio_paths, project.chapters)
        ]

        assembly = assembler(
            chapter_files=chapter_info,
            output_path=output_path,
            title=project.title,
            author=project.author,
            chapter_pause_ms=project.config.chapter_pause_ms,
        )

        project.output_path = assembly.output_path

        total_duration = sum(c.duration_seconds for c in project.chapters)
        if not assembly.chapters_embedded:
            logger.warning(
                f"RENDER_COMPLETE_NO_CHAPTERS: output={assembly.output_path} "
                f"duration={total_duration:.1f}s reason={assembly.chapter_error!r}"
            )
        else:
            logger.info(f"RENDER_COMPLETE: output={assembly.output_path} duration={total_duration:.1f}s")

        return assembly.output_path

    except Exception as e:
        logger.error(f"RENDER_PROJECT_FAIL: error={e}")
        raise

    finally:
        pass
