"""
Render Engine for Audiobooker.

Synthesizes chapters to audio using voice-soundboard's DialogueEngine.
This module imports and uses voice-soundboard directly (same-machine).
"""

import json
import logging
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from audiobooker.project import AudiobookProject
    from audiobooker.models import Chapter, CastingTable

# Structured logger for render operations
logger = logging.getLogger("audiobooker.renderer")


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
        """Serialize to JSON for structured logging."""
        return json.dumps(asdict(self), ensure_ascii=False)

    def log(self):
        """Log this entry at appropriate level."""
        if self.status == "error":
            logger.error(f"RENDER_FAIL: {self.to_json()}")
        else:
            logger.info(f"RENDER_OK: {self.to_json()}")


def get_dialogue_engine():
    """
    Get or create the DialogueEngine from voice-soundboard.

    Raises ImportError with helpful message if voice-soundboard
    is not available.
    """
    try:
        from voice_soundboard.dialogue.engine import DialogueEngine
        return DialogueEngine()
    except ImportError:
        raise ImportError(
            "voice-soundboard is required for rendering. "
            "Ensure it's installed and accessible:\n"
            "  pip install -e F:/AI/voice-soundboard"
        )


def render_chapter(
    chapter: "Chapter",
    casting: "CastingTable",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """
    Render a single chapter to audio.

    Args:
        chapter: Chapter with compiled utterances
        casting: CastingTable for voice mapping
        output_path: Output audio file path
        progress_callback: Callback(current_utterance, total_utterances)

    Returns:
        Path to rendered audio file
    """
    from audiobooker.casting.dialogue import utterances_to_script

    if not chapter.utterances:
        raise ValueError(f"Chapter {chapter.index} has no utterances. Compile first.")

    # Create render log
    total_chars = sum(len(u.text) for u in chapter.utterances)
    render_log = RenderLog(
        chapter_index=chapter.index,
        chapter_title=chapter.title,
        utterance_count=len(chapter.utterances),
        total_chars=total_chars,
        start_time=time.time(),
    )

    try:
        # Convert utterances to script
        script = utterances_to_script(chapter.utterances, casting)

        # Get voice mapping
        voice_mapping = casting.get_voice_mapping()

        # Get engine and synthesize
        engine = get_dialogue_engine()

        # Create output directory
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Track current utterance for error reporting
        current_utterance_idx = 0

        # Synthesize with progress tracking
        def internal_progress(current: int, total: int, speaker: str):
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

        # Update chapter metadata
        chapter.audio_path = result.audio_path
        chapter.duration_seconds = result.duration_seconds

        # Update render log
        render_log.end_time = time.time()
        render_log.duration_seconds = result.duration_seconds
        render_log.output_path = str(result.audio_path)
        render_log.status = "success"
        render_log.log()

        return result.audio_path

    except Exception as e:
        # Log failure with context
        render_log.end_time = time.time()
        render_log.status = "error"
        render_log.error_message = str(e)

        # Try to identify the failing utterance
        if current_utterance_idx < len(chapter.utterances):
            failing_utterance = chapter.utterances[current_utterance_idx]
            render_log.error_utterance_index = current_utterance_idx
            render_log.error_speaker = failing_utterance.speaker
            render_log.error_text_preview = failing_utterance.text[:80]

        render_log.log()
        raise


def render_project(
    project: "AudiobookProject",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """
    Render all chapters and assemble final audiobook.

    Args:
        project: AudiobookProject to render
        output_path: Output file path (.m4b or .mp3)
        progress_callback: Callback(current_chapter, total_chapters, status)

    Returns:
        Path to final audiobook file
    """
    from audiobooker.renderer.output import assemble_m4b

    output_path = Path(output_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="audiobooker_"))

    logger.info(f"RENDER_START: project={project.title!r} chapters={len(project.chapters)} output={output_path}")

    try:
        # Render each chapter
        chapter_audio_paths = []
        total_render_time = 0.0

        for i, chapter in enumerate(project.chapters):
            if progress_callback:
                progress_callback(i + 1, len(project.chapters), f"Rendering: {chapter.title}")

            # Skip if already rendered and file exists
            if chapter.is_rendered and chapter.audio_path.exists():
                logger.info(f"RENDER_SKIP: chapter={i} title={chapter.title!r} (already rendered)")
                chapter_audio_paths.append(chapter.audio_path)
                continue

            # Render chapter
            chapter_path = temp_dir / f"chapter_{i:03d}.wav"
            start = time.time()
            render_chapter(chapter, project.casting, chapter_path)
            elapsed = time.time() - start
            total_render_time += elapsed

            chapter_audio_paths.append(chapter_path)

        if progress_callback:
            progress_callback(len(project.chapters), len(project.chapters), "Assembling audiobook...")

        logger.info(f"RENDER_ASSEMBLE: chapters={len(chapter_audio_paths)} total_render_time={total_render_time:.1f}s")

        # Assemble final file
        chapter_info = [
            (path, chapter.title, chapter.duration_seconds)
            for path, chapter in zip(chapter_audio_paths, project.chapters)
        ]

        assembly = assemble_m4b(
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
        # Cleanup temp files (keep if output format uses them)
        # For now, leave them for debugging
        pass


def render_chapter_streaming(
    chapter: "Chapter",
    casting: "CastingTable",
    on_utterance_complete: Optional[Callable[[int, bytes], None]] = None,
):
    """
    Render a chapter with streaming output.

    Yields audio data as each utterance is synthesized,
    enabling real-time playback during generation.

    Args:
        chapter: Chapter with compiled utterances
        casting: CastingTable for voice mapping
        on_utterance_complete: Callback(utterance_index, audio_bytes)

    Yields:
        Tuple of (utterance_index, audio_samples, sample_rate)
    """
    from audiobooker.casting.dialogue import utterances_to_script

    if not chapter.utterances:
        raise ValueError(f"Chapter {chapter.index} has no utterances. Compile first.")

    script = utterances_to_script(chapter.utterances, casting)
    voice_mapping = casting.get_voice_mapping()

    engine = get_dialogue_engine()

    for i, turn in enumerate(engine.synthesize_streaming(script, voice_mapping)):
        if on_utterance_complete and turn.audio_samples is not None:
            # Convert to bytes for callback
            import soundfile as sf
            import io
            buffer = io.BytesIO()
            sf.write(buffer, turn.audio_samples, 24000, format="WAV")
            on_utterance_complete(i, buffer.getvalue())

        yield i, turn.audio_samples, 24000
