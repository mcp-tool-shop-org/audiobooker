"""
Render Engine for Audiobooker.

Synthesizes chapters to audio. Accepts an injected TTSEngine for testability;
defaults to the real voice-soundboard DialogueEngine when none is provided.

Supports persistent chapter cache with manifest-driven resume.
"""

import json
import logging
import os
import shutil
import threading
import time
from xml.sax.saxutils import escape as _xml_escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from audiobooker.renderer.protocols import TTSEngine, SynthesisResult

if TYPE_CHECKING:
    from audiobooker.project import AudiobookProject
    from audiobooker.models import Chapter, CastingTable, Utterance


# ---------------------------------------------------------------------------
# FT-RENDER-015: SSML preprocessing
# ---------------------------------------------------------------------------

# Emotion → SSML emphasis level mapping
_EMOTION_EMPHASIS = {
    "angry": "strong",
    "excited": "strong",
    "whisper": "reduced",
    "nervous": "moderate",
    "sad": "moderate",
    "happy": "strong",
    "somber": "moderate",
    "calm": "reduced",
}

# Narrator vs dialogue prosody rates
_NARRATOR_RATE = "medium"
_DIALOGUE_RATE = "105%"


def preprocess_ssml(utterances: list["Utterance"]) -> str:
    """
    Transform utterances into an SSML document.

    Inserts:
    - <speak> wrapper
    - <break> tags at paragraph boundaries (between utterances)
    - <emphasis> for emotion-tagged text
    - <prosody rate> for narrator (medium) vs dialogue (slightly faster)

    Args:
        utterances: List of Utterance objects to convert.

    Returns:
        SSML string wrapped in <speak> tags.
    """
    if not utterances:
        return "<speak></speak>"

    parts: list[str] = []
    prev_speaker: str | None = None

    for utt in utterances:
        # Insert paragraph break between speaker changes
        if prev_speaker is not None and utt.speaker != prev_speaker:
            parts.append('<break time="750ms"/>')

        # Determine prosody rate: narrator = medium, dialogue = slightly faster
        is_narrator = utt.speaker.lower() in ("narrator", "narration")
        rate = _NARRATOR_RATE if is_narrator else _DIALOGUE_RATE

        # Build the inner text with optional emphasis.
        # ENGINE-A-004: escape XML metacharacters (&, <, >) so utterance text
        # containing them produces well-formed SSML.
        text = _xml_escape(utt.text)
        if utt.emotion:
            level = _EMOTION_EMPHASIS.get(utt.emotion.lower(), "moderate")
            text = f'<emphasis level="{level}">{text}</emphasis>'

        # Wrap in prosody
        parts.append(f'<prosody rate="{rate}">{text}</prosody>')

        prev_speaker = utt.speaker

    body = "\n".join(parts)
    return f"<speak>\n{body}\n</speak>"


# ---------------------------------------------------------------------------
# FT-RENDER-017: Chapter range parsing
# ---------------------------------------------------------------------------

def parse_chapter_ranges(range_str: str) -> set[int]:
    """
    Parse chapter range strings like '1-14,21-30' into a set of 0-based indices.

    Input uses 1-based chapter numbers (user-facing), output is 0-based indices.

    Examples:
        '1-5'       -> {0, 1, 2, 3, 4}
        '1,3,5'     -> {0, 2, 4}
        '1-3,7-9'   -> {0, 1, 2, 6, 7, 8}
        '5'         -> {4}
    """
    indices: set[int] = set()
    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str.strip())
            end = int(end_str.strip())
            if start < 1 or end < start:
                raise ValueError(f"Invalid chapter range: {part!r}")
            indices.update(range(start - 1, end))  # convert to 0-based
        else:
            num = int(part)
            if num < 1:
                raise ValueError(f"Invalid chapter number: {num}")
            indices.add(num - 1)  # convert to 0-based
    return indices


def filter_chapters_by_selection(
    chapters: list,
    include_ranges: Optional[str] = None,
    exclude_ranges: Optional[str] = None,
) -> list:
    """
    Filter chapters by --chapters and --exclude-chapters range strings.

    Args:
        chapters: List of Chapter objects (or any list).
        include_ranges: Comma-separated ranges to include (1-based). If None, include all.
        exclude_ranges: Comma-separated ranges to exclude (1-based). If None, exclude none.

    Returns:
        Filtered list of chapters.
    """
    if include_ranges:
        include_set = parse_chapter_ranges(include_ranges)
        chapters = [ch for i, ch in enumerate(chapters) if i in include_set]

    if exclude_ranges:
        exclude_set = parse_chapter_ranges(exclude_ranges)
        # Re-index based on original chapter.index attribute if available
        chapters = [
            ch for ch in chapters
            if getattr(ch, "index", None) is None or ch.index not in exclude_set
        ]
        # Fallback for objects without index attr
        if all(getattr(ch, "index", None) is None for ch in chapters):
            original_indices = set(range(len(chapters)))
            keep = original_indices - exclude_set
            chapters = [ch for i, ch in enumerate(chapters) if i in keep]

    return chapters


def should_use_ssml(engine: TTSEngine) -> bool:
    """Check if the engine supports SSML via capabilities()."""
    try:
        caps = engine.capabilities()
        return bool(caps.get("ssml", False))
    except (AttributeError, TypeError):
        return False

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
        if engine is None:
            engine = get_default_engine()

        # FT-RENDER-015: Use SSML preprocessing if engine supports it
        if should_use_ssml(engine):
            script = preprocess_ssml(chapter.utterances)
            logger.info(f"RENDER_SSML: chapter={chapter.index} using SSML preprocessing")
        else:
            script = utterances_to_script(chapter.utterances)

        voice_mapping = casting.get_voice_mapping()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        _last_heartbeat = [time.time()]

        def internal_progress(current: int, total: int, **kwargs):
            nonlocal current_utterance_idx
            current_utterance_idx = max(0, current - 1)
            # F-RENDER-B-003: Heartbeat log every 30s during synthesis
            now = time.time()
            if now - _last_heartbeat[0] >= 30.0:
                logger.info(
                    f"RENDER_HEARTBEAT: chapter={chapter.index} "
                    f"utterance={current}/{total} elapsed={now - render_log.start_time:.0f}s"
                )
                _last_heartbeat[0] = now
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
# FT-RENDER-010: Render lockfile
# ---------------------------------------------------------------------------

LOCKFILE_NAME = ".render.lock"


def _is_pid_running(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False


def _acquire_render_lock(cache_root: Path) -> Path:
    """
    Create .render.lock containing PID + timestamp.
    Checks for stale locks (PID no longer running) and removes them.
    Raises RenderError if another render is genuinely active.
    """
    lock_path = cache_root / LOCKFILE_NAME

    if lock_path.exists():
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_pid = lock_data.get("pid", -1)
            if _is_pid_running(lock_pid) and lock_pid != os.getpid():
                raise RenderError(
                    f"Another render is already running (PID {lock_pid}, "
                    f"started {lock_data.get('started_at', 'unknown')}). "
                    f"If this is stale, delete {lock_path}"
                )
            else:
                logger.info(f"RENDER_LOCK: Removing stale lock (PID {lock_pid} not running)")
                lock_path.unlink(missing_ok=True)
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"RENDER_LOCK: Corrupt lockfile at {lock_path}, removing")
            lock_path.unlink(missing_ok=True)

    lock_data = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    logger.info(f"RENDER_LOCK: Acquired {lock_path} (PID {os.getpid()})")
    return lock_path


def _release_render_lock(lock_path: Path) -> None:
    """Release the render lockfile."""
    try:
        lock_path.unlink(missing_ok=True)
        logger.info(f"RENDER_LOCK: Released {lock_path}")
    except OSError as e:
        logger.warning(f"RENDER_LOCK: Failed to release {lock_path}: {e}")


# ---------------------------------------------------------------------------
# FT-RENDER-011: Casting completeness validation
# ---------------------------------------------------------------------------

def validate_casting_completeness(
    project: "AudiobookProject",
    force: bool = False,
) -> list[str]:
    """
    Check if uncast speakers exceed 30% of dialogue utterances.

    Args:
        project: AudiobookProject with compiled chapters.
        force: If True, skip the check and return empty list.

    Returns:
        List of uncast speaker names (empty if OK or forced).

    Raises:
        RenderError: If >30% of dialogue utterances are uncast and force=False.
    """
    if force:
        return []

    uncast = project.get_uncast_speakers()
    if not uncast:
        return []

    # Count total dialogue utterances and uncast dialogue utterances
    total_utterances = 0
    uncast_utterances = 0
    for chapter in project.chapters:
        for utt in chapter.utterances:
            total_utterances += 1
            normalized = project.casting.normalize_key(utt.speaker)
            if normalized in uncast:
                uncast_utterances += 1

    if total_utterances == 0:
        return []

    ratio = uncast_utterances / total_utterances
    uncast_list = sorted(uncast)

    if ratio > 0.30:
        logger.warning(
            f"RENDER_CASTING_INCOMPLETE: {uncast_utterances}/{total_utterances} "
            f"utterances ({ratio:.0%}) map to uncast speakers: {uncast_list}"
        )
        raise RenderError(
            f"Casting incomplete: {ratio:.0%} of utterances ({uncast_utterances}/{total_utterances}) "
            f"map to uncast speakers: {', '.join(uncast_list)}.\n"
            f"Use --force to render anyway, or cast these speakers first."
        )
    elif uncast_list:
        logger.info(
            f"RENDER_CASTING_NOTE: {len(uncast_list)} uncast speakers "
            f"({ratio:.0%} of utterances): {uncast_list}"
        )

    return uncast_list


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
    failed_chapters: list[dict] = field(default_factory=list)


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
    jobs: int = 1,
    force: bool = False,
    output_format: Optional[str] = None,
    cover_art: Optional[str] = None,
    normalize: bool = False,
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
        assembler: Injected assembly function (defaults based on format).
        cache_root: Override cache directory (default: derive from project).
        resume: If True, skip chapters whose cache entries are still valid.
        from_chapter: Start rendering from this chapter index (0-based).
        allow_partial: If True, assemble even if some chapters failed.
        jobs: Number of parallel render workers (default 1).
        force: If True, bypass casting completeness validation.
        output_format: Override output format ('m4b', 'mp3', 'wav').
        cover_art: Optional path to cover art image (JPG/PNG) for embedding.

    Returns:
        Path to final audiobook file.

    Raises:
        RenderError: If a chapter fails (unless allow_partial is True)
            or if no chapters render successfully.
    """
    from audiobooker.renderer.output import (
        assemble_m4b as _m4b_assembler,
        assemble_mp3 as _mp3_assembler,
    )
    from audiobooker.renderer.cache_manifest import (
        CacheManifest, ChapterCacheEntry,
        load_manifest, save_manifest,
        get_cache_root, get_chapter_wav_path, get_manifest_path,
    )
    from audiobooker.renderer.hash_utils import (
        chapter_text_hash, casting_hash, render_params_hash,
    )
    from audiobooker.renderer.progress import RenderProgressTracker
    from audiobooker.renderer.failure_report import RenderFailureReport

    # FT-RENDER-011: Casting completeness validation
    validate_casting_completeness(project, force=force)

    # FT-RENDER-003: Select assembler based on format
    fmt = output_format or project.config.output_format
    if assembler is None:
        if fmt == "mp3":
            assembler = _mp3_assembler
        else:
            assembler = _m4b_assembler

    output_path = Path(output_path)

    # Determine cache root
    if cache_root is None:
        project_dir = _resolve_project_dir(project)
        cache_root = get_cache_root(project_dir)

    manifest_path = get_manifest_path(cache_root)

    # Ensure cache dirs exist (before lockfile)
    cache_root.mkdir(parents=True, exist_ok=True)
    (cache_root / "chapters").mkdir(exist_ok=True)
    (cache_root / "manifests").mkdir(exist_ok=True)

    # FT-RENDER-010: Acquire render lockfile
    lock_path = _acquire_render_lock(cache_root)

    logger.info(
        f"RENDER_START: project={project.title!r} "
        f"chapters={len(project.chapters)} output={output_path} "
        f"cache={cache_root} resume={resume} jobs={jobs} format={fmt}"
    )

    # Compute current hashes
    current_casting_hash = casting_hash(project.casting)
    current_params_hash = render_params_hash(project.config)

    # Load or create manifest
    manifest = load_manifest(manifest_path) if resume else None
    if manifest is None:
        manifest = CacheManifest(book_title=project.title)

    summary = RenderSummary(
        output_path=output_path,
        total=len(project.chapters),
        cache_dir=str(cache_root),
        manifest_path=str(manifest_path),
    )

    # Progress tracker + failure report
    tracker = RenderProgressTracker(total_chapters=len(project.chapters))
    failure_report = RenderFailureReport(
        book_title=project.title,
        total_chapters=len(project.chapters),
        cache_dir=str(cache_root),
        manifest_path=str(manifest_path),
    )

    # FT-RENDER-001: Lock for thread-safe manifest writes
    manifest_lock = threading.Lock()

    # F-RENDER-B-014: Check disk space before entering render loop
    try:
        disk = shutil.disk_usage(str(cache_root))
        free_mb = disk.free / (1024 * 1024)
        if free_mb < 500:
            logger.warning(
                f"RENDER_LOW_DISK: only {free_mb:.0f} MB free on {cache_root.drive or cache_root.anchor}. "
                f"Rendering may fail if disk fills up."
            )
            if progress_callback:
                progress_callback(
                    0, len(project.chapters),
                    f"WARNING: Low disk space ({free_mb:.0f} MB free). Rendering may fail.",
                )
    except OSError as disk_err:
        logger.warning(f"RENDER_DISK_CHECK_FAIL: {disk_err}")

    try:
        # ---- Phase 1: Identify chapters to render vs skip ----
        chapters_to_render = []  # (index, chapter)
        for i, chapter in enumerate(project.chapters):
            if from_chapter is not None and i < from_chapter:
                if progress_callback:
                    progress_callback(i + 1, len(project.chapters), f"Skipping: {chapter.title}")
                continue

            current_text_hash = chapter_text_hash(chapter)

            # Check cache
            if resume:
                existing = manifest.get_entry(i)
                if existing and existing.is_valid(current_text_hash, current_casting_hash, current_params_hash):
                    chapter.audio_path = Path(existing.wav_path)
                    chapter.duration_seconds = existing.duration_s
                    tracker.mark_cached(i, chapter.title, existing.duration_s)
                    logger.info(f"RENDER_CACHE_HIT: chapter={i} title={chapter.title!r}")
                    summary.skipped_cached += 1

                    if progress_callback:
                        status = tracker.format_chapter_status(i, f"Cached: {chapter.title}")
                        progress_callback(i + 1, len(project.chapters), status)
                    continue

            chapters_to_render.append((i, chapter, current_text_hash))

        # ---- Phase 2: Render chapters (sequential or parallel) ----

        def _render_one_chapter(i: int, chapter: "Chapter", text_hash: str) -> None:
            """Render a single chapter, updating shared state thread-safely."""
            tracker.start_chapter(i, chapter.title, word_count=chapter.word_count)

            if progress_callback:
                status = tracker.format_chapter_status(i, f"Rendering: {chapter.title}")
                progress_callback(i + 1, len(project.chapters), status)

            target_path = get_chapter_wav_path(cache_root, i)
            tmp_path = target_path.with_suffix(".wav.tmp")

            start = time.time()
            try:
                render_chapter(chapter, project.casting, tmp_path, engine=engine)

                try:
                    os.replace(str(tmp_path), str(target_path))
                except OSError:
                    shutil.move(str(tmp_path), str(target_path))

                file_size = target_path.stat().st_size
                if file_size < 1024:
                    target_path.unlink(missing_ok=True)
                    raise RenderError(
                        f"Chapter {i} audio file is empty ({file_size} bytes) "
                        f"— TTS may have failed or disk may be full"
                    )

                chapter.audio_path = target_path

                elapsed = time.time() - start
                tracker.finish_chapter(i, render_elapsed_s=elapsed)

                entry = ChapterCacheEntry(
                    chapter_index=i,
                    text_hash=text_hash,
                    casting_hash=current_casting_hash,
                    render_params_hash=current_params_hash,
                    wav_path=str(target_path),
                    duration_s=chapter.duration_seconds,
                    status="ok",
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                # FT-RENDER-001 / ENGINE-A-005: counter increment must be under
                # the lock — parallel workers otherwise lose increments via the
                # read-modify-write race on summary.rendered.
                with manifest_lock:
                    manifest.set_entry(entry)
                    save_manifest(manifest, manifest_path)
                    summary.rendered += 1

                logger.info(
                    f"RENDER_OK: chapter={i} title={chapter.title!r} "
                    f"elapsed={elapsed:.1f}s duration={chapter.duration_seconds:.1f}s"
                )

            except OSError as e:
                if e.errno in (28, 39, 112):
                    logger.error(f"RENDER_DISK_FULL: chapter={i} — {e}")
                    # ENGINE-A-007: don't leave the partial .wav.tmp behind on a
                    # disk-full abort — it wastes the little space that remains.
                    tmp_path.unlink(missing_ok=True)
                    raise RenderError(
                        f"Disk full while rendering chapter {i} ({chapter.title!r}). "
                        f"Free up space and re-run with: audiobooker render",
                        summary=summary,
                    ) from e
                _handle_chapter_failure(
                    i, chapter, e, text_hash,
                    tmp_path, tracker, manifest, manifest_path,
                    manifest_lock, failure_report, summary,
                    current_casting_hash, current_params_hash,
                    allow_partial,
                )

            except Exception as e:
                _handle_chapter_failure(
                    i, chapter, e, text_hash,
                    tmp_path, tracker, manifest, manifest_path,
                    manifest_lock, failure_report, summary,
                    current_casting_hash, current_params_hash,
                    allow_partial,
                )

        if jobs > 1 and len(chapters_to_render) > 1:
            # FT-RENDER-001: Parallel rendering
            logger.info(f"RENDER_PARALLEL: {jobs} workers for {len(chapters_to_render)} chapters")
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = {
                    pool.submit(_render_one_chapter, i, ch, th): i
                    for i, ch, th in chapters_to_render
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except RenderError:
                        if not allow_partial:
                            # Cancel remaining futures
                            for f in futures:
                                f.cancel()
                            raise
                    except Exception:
                        if not allow_partial:
                            for f in futures:
                                f.cancel()
                            raise
        else:
            # Sequential rendering (default)
            for i, chapter, text_hash in chapters_to_render:
                _render_one_chapter(i, chapter, text_hash)

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

        logger.info(f"RENDER_ASSEMBLE: chapters={len(ok_paths)} format={fmt}")

        # FT-RENDER-006: Pass cover_art to assembler if supported
        assembler_kwargs = dict(
            chapter_files=ok_paths,
            output_path=output_path,
            title=project.title,
            author=project.author,
            chapter_pause_ms=project.config.chapter_pause_ms,
        )
        if cover_art:
            assembler_kwargs["cover_art"] = cover_art
        if normalize:
            assembler_kwargs["normalize"] = normalize

        try:
            assembly = assembler(**assembler_kwargs)
        except TypeError:
            # Assembler doesn't accept cover_art — call without it
            assembler_kwargs.pop("cover_art", None)
            assembly = assembler(**assembler_kwargs)

        project.output_path = assembly.output_path
        summary.output_path = assembly.output_path

        total_duration = sum(dur for _, _, dur in ok_paths)

        # FT-RENDER-016: Post-render validation via ffprobe
        _post_render_validate(assembly.output_path, total_duration)

        if not assembly.chapters_embedded:
            logger.warning(
                f"RENDER_COMPLETE_NO_CHAPTERS: output={assembly.output_path} "
                f"duration={total_duration:.1f}s reason={assembly.chapter_error!r}"
            )
        else:
            logger.info(f"RENDER_COMPLETE: output={assembly.output_path} duration={total_duration:.1f}s")

        # Save failure report if any chapters failed
        if failure_report.failed_chapters:
            failure_report.rendered_ok = summary.rendered
            failure_report.cached_ok = summary.skipped_cached
            failure_report.save()

        _log_summary(summary)
        return assembly.output_path

    except RenderError:
        _log_summary(summary)
        raise

    except Exception as e:
        logger.error(f"RENDER_PROJECT_FAIL: error={e}")
        failure_report.rendered_ok = summary.rendered
        failure_report.cached_ok = summary.skipped_cached
        failure_report.add_failure(
            chapter_index=-1,
            chapter_title="(project-level)",
            error=e,
        )
        failure_report.save()
        _log_summary(summary)
        raise

    finally:
        # FT-RENDER-010: Always release lockfile
        _release_render_lock(lock_path)


def _handle_chapter_failure(
    i: int,
    chapter,
    error: Exception,
    text_hash: str,
    tmp_path: Path,
    tracker,
    manifest,
    manifest_path: Path,
    manifest_lock: threading.Lock,
    failure_report,
    summary: "RenderSummary",
    current_casting_hash: str,
    current_params_hash: str,
    allow_partial: bool,
) -> None:
    """Handle a chapter render failure (shared between sequential and parallel paths)."""
    from audiobooker.renderer.cache_manifest import ChapterCacheEntry

    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)

    tracker.mark_failed(i, chapter.title)

    entry = ChapterCacheEntry(
        chapter_index=i,
        text_hash=text_hash,
        casting_hash=current_casting_hash,
        render_params_hash=current_params_hash,
        wav_path="",
        status="failed",
        error_summary=str(error)[:200],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    # ENGINE-A-005: all shared-state mutations (manifest, failure report, and
    # summary counters) must happen under the lock so parallel workers don't
    # lose increments or corrupt the shared lists via concurrent appends.
    with manifest_lock:
        manifest.set_entry(entry)
        from audiobooker.renderer.cache_manifest import save_manifest
        save_manifest(manifest, manifest_path)

        failure_report.add_failure(
            chapter_index=i,
            chapter_title=chapter.title,
            error=error,
        )

        summary.failed += 1
        summary.failed_chapters.append({
            "index": i,
            "title": chapter.title,
            "error": str(error),
        })

    logger.error(f"RENDER_CHAPTER_FAIL: chapter={i} error={error}")

    if not allow_partial:
        failure_report.rendered_ok = summary.rendered
        failure_report.cached_ok = summary.skipped_cached
        failure_report.save()

        raise RenderError(
            f"Chapter {i} ({chapter.title!r}) failed: {error}",
            summary=summary,
        ) from error


class RenderError(RuntimeError):
    """Rendering failed with recoverable context."""

    def __init__(
        self,
        message: str,
        summary: Optional[RenderSummary] = None,
        *,
        code: str = "RUNTIME_RENDER",
        hint: str = "Check render_failure_report.json for details. Retry with --from-chapter to resume.",
        cause: Optional[str] = None,
        retryable: bool = True,
    ):
        super().__init__(message)
        self.summary = summary
        # Structured error shape (code/message/hint/cause/retryable)
        self.code = code
        self.hint = hint
        self.cause = cause
        self.retryable = retryable

    def structured(self) -> dict:
        """Return the canonical error shape as a dict."""
        d: dict = {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "retryable": self.retryable,
        }
        if self.cause:
            d["cause"] = self.cause
        return d


def _resolve_project_dir(project: "AudiobookProject") -> Path:
    """Derive the project directory for cache placement."""
    if project.project_path:
        return project.project_path.parent
    if project.source_path:
        return Path(project.source_path).parent
    # F-RENDER-B-011: Log warning when falling back to cwd
    logger.warning(
        "RENDER_PROJECT_DIR: No project_path or source_path set — "
        f"using current working directory ({Path.cwd()}) for cache. "
        "Save the project first to get a stable cache location."
    )
    return Path.cwd()


def _post_render_validate(output_path: Path, expected_duration: float) -> None:
    """
    FT-RENDER-016: Post-render validation.

    Runs ffprobe on the output file and checks:
    - File is non-zero size
    - Duration is within 10% of expected

    Logs warnings on mismatch but does not fail.
    """
    if not output_path.exists():
        logger.warning(f"POST_VALIDATE: Output file does not exist: {output_path}")
        return

    file_size = output_path.stat().st_size
    if file_size == 0:
        logger.warning(f"POST_VALIDATE: Output file is empty (0 bytes): {output_path}")
        return

    try:
        from audiobooker.renderer.output import get_audio_duration
        actual_duration = get_audio_duration(output_path)

        if actual_duration <= 0:
            logger.warning(f"POST_VALIDATE: Could not determine duration of {output_path}")
            return

        if expected_duration > 0:
            ratio = actual_duration / expected_duration
            if ratio < 0.9 or ratio > 1.1:
                logger.warning(
                    f"POST_VALIDATE: Duration mismatch for {output_path}: "
                    f"expected ~{expected_duration:.1f}s, got {actual_duration:.1f}s "
                    f"(ratio: {ratio:.2f}). Output may be truncated or padded."
                )
            else:
                logger.info(
                    f"POST_VALIDATE: Duration OK — expected ~{expected_duration:.1f}s, "
                    f"got {actual_duration:.1f}s"
                )
    except Exception as e:
        logger.warning(f"POST_VALIDATE: Validation error: {e}")


def dry_run_render(
    project: "AudiobookProject",
    resume: bool = True,
    from_chapter: Optional[int] = None,
) -> None:
    """
    FT-RENDER-004: Preview what would be rendered without actually rendering.

    Walks the cache-check loop and prints a summary table showing
    which chapters would be rendered vs cached, with estimates.
    """
    from audiobooker.renderer.cache_manifest import (
        load_manifest, get_cache_root, get_manifest_path,
    )
    from audiobooker.renderer.hash_utils import (
        chapter_text_hash, casting_hash, render_params_hash,
    )

    project_dir = _resolve_project_dir(project)
    cache_root = get_cache_root(project_dir)
    manifest_path = get_manifest_path(cache_root)

    current_casting_hash = casting_hash(project.casting)
    current_params_hash = render_params_hash(project.config)

    manifest = load_manifest(manifest_path) if resume else None

    to_render = []
    cached = []
    skipped = []

    for i, chapter in enumerate(project.chapters):
        if from_chapter is not None and i < from_chapter:
            skipped.append((i, chapter.title, chapter.word_count))
            continue

        current_text_hash = chapter_text_hash(chapter)

        if resume and manifest:
            existing = manifest.get_entry(i)
            if existing and existing.is_valid(current_text_hash, current_casting_hash, current_params_hash):
                cached.append((i, chapter.title, chapter.word_count))
                continue

        to_render.append((i, chapter.title, chapter.word_count))

    total_words_render = sum(wc for _, _, wc in to_render)
    wpm = project.config.estimated_wpm or 150

    print(f"\n{'='*60}")
    print(f"DRY RUN — {project.title}")
    print(f"{'='*60}")
    print(f"Total chapters: {len(project.chapters)}")
    print(f"  To render:  {len(to_render)}")
    print(f"  Cached:     {len(cached)}")
    if skipped:
        print(f"  Skipped:    {len(skipped)}")
    print()

    if to_render:
        print("Chapters to render:")
        for idx, title, wc in to_render:
            print(f"  [{idx}] {title} ({wc:,} words)")
        print()

    est_minutes = total_words_render / wpm
    if est_minutes >= 60:
        est_str = f"~{est_minutes / 60:.1f} hours"
    else:
        est_str = f"~{est_minutes:.0f} minutes"

    # Rough disk estimate: ~1 MB per minute of audio at 24kHz mono WAV
    est_disk_mb = est_minutes * 1.0

    print(f"Estimated render time: {est_str} ({total_words_render:,} words to render)")
    print(f"Estimated disk usage:  ~{est_disk_mb:.0f} MB (chapter WAVs)")
    print(f"{'='*60}")


def _log_summary(summary: RenderSummary) -> None:
    """Log the render summary."""
    logger.info(
        f"RENDER_SUMMARY: rendered={summary.rendered} "
        f"cached={summary.skipped_cached} failed={summary.failed} "
        f"total={summary.total} cache={summary.cache_dir}"
    )
