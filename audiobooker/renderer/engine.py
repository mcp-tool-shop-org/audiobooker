"""
Render Engine for Audiobooker.

Synthesizes chapters to audio. Accepts an injected TTSEngine for testability;
defaults to the real voice-soundboard DialogueEngine when none is provided.

Supports persistent chapter cache with manifest-driven resume.
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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
# Render summary (returned to caller for user-facing messages)
# ---------------------------------------------------------------------------

@dataclass
class RenderSummary:
    """Result of render_project with per-chapter accounting."""
    output_path: Path
    rendered: int = 0
    skipped_cached: int = 0
    failed: int = 0
    total: int = 0
    cache_dir: str = ""
    manifest_path: str = ""
    failed_chapters: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.failed_chapters is None:
            self.failed_chapters = []


# ---------------------------------------------------------------------------
# Project rendering (with persistent cache + resume)
# ---------------------------------------------------------------------------

def render_project(
    project: "AudiobookProject",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    *,
    engine: Optional[TTSEngine] = None,
    assembler: Optional[Callable] = None,
    cache_root: Optional[Path] = None,
    resume: bool = True,
    from_chapter: Optional[int] = None,
    allow_partial: bool = False,
) -> Path:
    """
    Render all chapters and assemble final audiobook.

    Chapter WAVs are persisted to a stable cache directory so that
    failures are non-catastrophic and reruns skip completed work.

    Args:
        project: AudiobookProject to render.
        output_path: Output file path (.m4b or .mp3).
        progress_callback: Callback(current_chapter, total_chapters, status).
        engine: Injected TTSEngine (defaults to voice-soundboard).
        assembler: Injected assembly function (defaults to assemble_m4b).
        cache_root: Override cache directory (default: derive from project).
        resume: If True, skip chapters whose cache entries are still valid.
        from_chapter: Start rendering from this chapter index (0-based).
        allow_partial: If True, assemble even if some chapters failed.

    Returns:
        Path to final audiobook file.
    """
    from audiobooker.renderer.output import assemble_m4b as _default_assembler
    from audiobooker.renderer.cache_manifest import (
        CacheManifest, ChapterCacheEntry,
        load_manifest, save_manifest,
        get_cache_root, get_chapter_wav_path, get_manifest_path,
    )
    from audiobooker.renderer.hash_utils import (
        chapter_text_hash, casting_hash, render_params_hash,
    )

    if assembler is None:
        assembler = _default_assembler

    output_path = Path(output_path)

    # Determine cache root
    if cache_root is None:
        project_dir = _resolve_project_dir(project)
        cache_root = get_cache_root(project_dir)

    manifest_path = get_manifest_path(cache_root)

    logger.info(
        f"RENDER_START: project={project.title!r} "
        f"chapters={len(project.chapters)} output={output_path} "
        f"cache={cache_root} resume={resume}"
    )

    # Compute current hashes
    current_casting_hash = casting_hash(project.casting)
    current_params_hash = render_params_hash(project.config)

    # Load or create manifest
    manifest = load_manifest(manifest_path) if resume else None
    if manifest is None:
        manifest = CacheManifest(book_title=project.title)

    # Ensure cache dirs exist
    cache_root.mkdir(parents=True, exist_ok=True)
    (cache_root / "chapters").mkdir(exist_ok=True)
    (cache_root / "manifests").mkdir(exist_ok=True)

    summary = RenderSummary(
        output_path=output_path,
        total=len(project.chapters),
        cache_dir=str(cache_root),
        manifest_path=str(manifest_path),
    )

    try:
        for i, chapter in enumerate(project.chapters):
            if from_chapter is not None and i < from_chapter:
                # Skip chapters before the requested start
                if progress_callback:
                    progress_callback(i + 1, len(project.chapters), f"Skipping: {chapter.title}")
                continue

            if progress_callback:
                progress_callback(i + 1, len(project.chapters), f"Rendering: {chapter.title}")

            current_text_hash = chapter_text_hash(chapter)

            # Check cache
            if resume:
                existing = manifest.get_entry(i)
                if existing and existing.is_valid(current_text_hash, current_casting_hash, current_params_hash):
                    # Cache hit — restore chapter state from cache
                    chapter.audio_path = Path(existing.wav_path)
                    chapter.duration_seconds = existing.duration_s
                    logger.info(f"RENDER_CACHE_HIT: chapter={i} title={chapter.title!r}")
                    summary.skipped_cached += 1
                    continue

            # Cache miss — render this chapter
            target_path = get_chapter_wav_path(cache_root, i)
            tmp_path = target_path.with_suffix(".wav.tmp")

            start = time.time()
            try:
                render_chapter(chapter, project.casting, tmp_path, engine=engine)

                # Atomic rename: tmp → final
                if target_path.exists():
                    target_path.unlink()
                os.rename(str(tmp_path), str(target_path))

                # Update chapter to point at cached path
                chapter.audio_path = target_path
                # duration_seconds is set by render_chapter

                elapsed = time.time() - start

                # Update manifest entry
                entry = ChapterCacheEntry(
                    chapter_index=i,
                    text_hash=current_text_hash,
                    casting_hash=current_casting_hash,
                    render_params_hash=current_params_hash,
                    wav_path=str(target_path),
                    duration_s=chapter.duration_seconds,
                    status="ok",
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                manifest.set_entry(entry)
                save_manifest(manifest, manifest_path)

                summary.rendered += 1
                logger.info(
                    f"RENDER_OK: chapter={i} title={chapter.title!r} "
                    f"elapsed={elapsed:.1f}s duration={chapter.duration_seconds:.1f}s"
                )

            except Exception as e:
                # Clean up partial tmp file
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)

                # Record failure in manifest (prior OK chapters are preserved)
                entry = ChapterCacheEntry(
                    chapter_index=i,
                    text_hash=current_text_hash,
                    casting_hash=current_casting_hash,
                    render_params_hash=current_params_hash,
                    wav_path="",
                    status="failed",
                    error_summary=str(e)[:200],
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                manifest.set_entry(entry)
                save_manifest(manifest, manifest_path)

                summary.failed += 1
                summary.failed_chapters.append({
                    "index": i,
                    "title": chapter.title,
                    "error": str(e),
                })

                logger.error(f"RENDER_CHAPTER_FAIL: chapter={i} error={e}")

                if not allow_partial:
                    raise RenderError(
                        f"Chapter {i} ({chapter.title!r}) failed: {e}",
                        summary=summary,
                    ) from e

        # Verify all chapters are ready for assembly
        ok_paths = []
        for i, chapter in enumerate(project.chapters):
            if chapter.audio_path and chapter.audio_path.exists():
                ok_paths.append((chapter.audio_path, chapter.title, chapter.duration_seconds))
            elif not allow_partial:
                raise RenderError(
                    f"Chapter {i} ({chapter.title!r}) has no audio — "
                    f"cannot assemble. Use --allow-partial or fix and --resume.",
                    summary=summary,
                )

        if not ok_paths:
            raise RenderError("No chapters rendered successfully.", summary=summary)

        # Assembly
        if progress_callback:
            progress_callback(
                len(project.chapters), len(project.chapters), "Assembling audiobook..."
            )

        logger.info(f"RENDER_ASSEMBLE: chapters={len(ok_paths)}")

        assembly = assembler(
            chapter_files=ok_paths,
            output_path=output_path,
            title=project.title,
            author=project.author,
            chapter_pause_ms=project.config.chapter_pause_ms,
        )

        project.output_path = assembly.output_path
        summary.output_path = assembly.output_path

        total_duration = sum(c.duration_seconds for c in project.chapters)
        if not assembly.chapters_embedded:
            logger.warning(
                f"RENDER_COMPLETE_NO_CHAPTERS: output={assembly.output_path} "
                f"duration={total_duration:.1f}s reason={assembly.chapter_error!r}"
            )
        else:
            logger.info(f"RENDER_COMPLETE: output={assembly.output_path} duration={total_duration:.1f}s")

        _log_summary(summary)
        return assembly.output_path

    except RenderError:
        _log_summary(summary)
        raise

    except Exception as e:
        logger.error(f"RENDER_PROJECT_FAIL: error={e}")
        _log_summary(summary)
        raise


class RenderError(RuntimeError):
    """Rendering failed with recoverable context."""

    def __init__(self, message: str, summary: Optional[RenderSummary] = None):
        super().__init__(message)
        self.summary = summary


def _resolve_project_dir(project: "AudiobookProject") -> Path:
    """Derive the project directory for cache placement."""
    if project.project_path:
        return project.project_path.parent
    if project.source_path:
        return Path(project.source_path).parent
    return Path.cwd()


def _log_summary(summary: RenderSummary) -> None:
    """Log the render summary."""
    logger.info(
        f"RENDER_SUMMARY: rendered={summary.rendered} "
        f"cached={summary.skipped_cached} failed={summary.failed} "
        f"total={summary.total} cache={summary.cache_dir}"
    )
