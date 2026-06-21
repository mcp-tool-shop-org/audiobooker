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


# Canonical install instruction for the voice-soundboard TTS dependency.
# Shown whenever rendering is attempted without it installed.
VOICE_SOUNDBOARD_INSTALL_HINT = (
    "Install with: pip install voice-soundboard  "
    "(or: pip install audiobooker-ai[render])"
)

# Output formats that require ffmpeg for assembly. 'wav' chapters are written
# directly by the TTS engine and need no ffmpeg step.
_FFMPEG_FORMATS = {"m4b", "m4a", "mp3", "opus", "ogg", "flac"}

# FT-RENDER-M-006: all output formats the renderer knows how to assemble.
VALID_OUTPUT_FORMATS = {"m4b", "m4a", "mp3", "wav", "opus", "ogg", "flac"}


# ---------------------------------------------------------------------------
# FT-RENDER-015: SSML preprocessing
# ---------------------------------------------------------------------------

# Emotion → SSML emphasis level mapping.
# This is the DEFAULT ('neutral' preset) map and the historical behavior: it is
# the emphasis used for a bare emotion whose intensity is None. Changing these
# values changes regression-critical output, so don't.
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

# FT-CAST-026: Per-preset emphasis maps. 'neutral' IS _EMOTION_EMPHASIS, so a
# render with preset='neutral' (the default) is byte-identical to the historical
# engine. Other packs scale the same emotions hotter or cooler. Emotions absent
# from a pack's map fall back to _EMOTION_EMPHASIS, then to "moderate".
_EMOTION_EMPHASIS_PRESETS: dict[str, dict[str, str]] = {
    "neutral": _EMOTION_EMPHASIS,
    "literary": {
        # Restrained reading: pull the loudest emotions down a notch.
        "angry": "moderate",
        "excited": "moderate",
        "happy": "moderate",
        "sad": "moderate",
        "whisper": "reduced",
        "calm": "reduced",
        "somber": "moderate",
        "nervous": "moderate",
    },
    "dramatic": {
        # Bigger swings for a performance read.
        "angry": "strong",
        "excited": "strong",
        "happy": "strong",
        "sad": "strong",
        "fearful": "strong",
        "whisper": "reduced",
        "calm": "reduced",
        "somber": "moderate",
        "nervous": "moderate",
    },
    "children": {
        # Bright and lively, but soft on the scary stuff.
        "happy": "strong",
        "excited": "strong",
        "sad": "moderate",
        "fearful": "reduced",
        "whisper": "reduced",
        "calm": "reduced",
    },
}

# FT-CAST-023: intensity → emphasis ceiling. A low-intensity emotion is read
# softer than the same emotion at full strength. Bands:
#   intensity is None        -> use the preset/default map verbatim (today's
#                               behavior; regression-critical).
#   intensity <  LOW_BAND    -> "reduced"  (barely-there)
#   intensity <  MID_BAND    -> "moderate"
#   intensity >= MID_BAND    -> the preset/default map (full strength)
_INTENSITY_LOW_BAND = 0.34
_INTENSITY_MID_BAND = 0.67

# Narrator vs dialogue prosody rates
_NARRATOR_RATE = "medium"
_DIALOGUE_RATE = "105%"


def _emphasis_for(
    emotion: str,
    intensity: Optional[float],
    preset: str = "neutral",
) -> str:
    """
    Resolve the SSML emphasis level for an (emotion, intensity) pair.

    FT-CAST-023 + FT-CAST-026.

    Regression contract: when ``intensity is None`` and ``preset == 'neutral'``
    this returns exactly ``_EMOTION_EMPHASIS.get(emotion.lower(), "moderate")``
    — identical to the historical engine.

    Args:
        emotion: Emotion label (already known to be truthy by the caller).
        intensity: Graded intensity 0.0-1.0, or None for "unspecified".
        preset: Emotion preset name selecting the base emphasis map.

    Returns:
        SSML emphasis level: "reduced" | "moderate" | "strong".
    """
    emo = emotion.lower()
    base_map = _EMOTION_EMPHASIS_PRESETS.get(preset, _EMOTION_EMPHASIS)
    # Per-preset map first, then the historical default map, then "moderate".
    full_level = base_map.get(emo) or _EMOTION_EMPHASIS.get(emo, "moderate")

    # None / unspecified intensity → today's behavior (full preset level).
    if intensity is None:
        return full_level

    if intensity < _INTENSITY_LOW_BAND:
        return "reduced"
    if intensity < _INTENSITY_MID_BAND:
        return "moderate"
    return full_level


def preprocess_ssml(
    utterances: list["Utterance"],
    emotion_preset: str = "neutral",
) -> str:
    """
    Transform utterances into an SSML document.

    Inserts:
    - <speak> wrapper
    - <break> tags at paragraph boundaries (between utterances)
    - <emphasis> for emotion-tagged text (FT-CAST-023: emphasis level scales
      with the utterance's intensity; FT-CAST-026: the base emphasis map is
      selected by ``emotion_preset``)
    - <prosody rate> for narrator (medium) vs dialogue (slightly faster)

    Regression contract: with ``emotion_preset='neutral'`` (default) and
    utterances whose ``intensity`` is None (or absent on legacy models), the
    emphasis levels are byte-identical to the historical engine.

    Args:
        utterances: List of Utterance objects to convert.
        emotion_preset: Emotion preset selecting the emphasis map (FT-CAST-026).

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
            # FT-CAST-023: intensity is None on legacy/bare-emotion utterances,
            # which keeps the historical emphasis level (regression-critical).
            intensity = getattr(utt, "intensity", None)
            level = _emphasis_for(utt.emotion, intensity, emotion_preset)
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
                f"{VOICE_SOUNDBOARD_INSTALL_HINT}"
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


# FT-ENGINE-001: Pluggable TTS engine registry.
#
# Third parties register engines via the 'audiobooker.tts_engines' entry-point
# group (pyproject.toml owns the built-in 'voice-soundboard' registration so the
# default resolves through the very same path a plugin would). Resolution order:
#
#   explicit name arg  >  AUDIOBOOKER_ENGINE env var  >  DEFAULT_ENGINE_NAME
#
# The built-in voice-soundboard engine is ALWAYS available as a hard fallback,
# even when the entry-point metadata can't be read (editable installs, partial
# metadata, etc.) — so get_default_engine(None) is byte-identical to the
# historical behavior regardless of whether the package metadata is present.
ENGINE_ENTRY_POINT_GROUP = "audiobooker.tts_engines"
DEFAULT_ENGINE_NAME = "voice-soundboard"
ENGINE_ENV_VAR = "AUDIOBOOKER_ENGINE"


def _load_engine_entry_points() -> dict[str, object]:
    """Return {name: EntryPoint} for the audiobooker.tts_engines group.

    Tolerant of every importlib.metadata API shape (3.10 dict-style vs 3.12
    selectable) and of metadata being entirely absent — returns {} on failure.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - importlib.metadata always present on 3.10+
        return {}

    try:
        eps = entry_points()
        # Python 3.10/3.11: entry_points() returns a dict-like keyed by group.
        # Python 3.12+: it returns a SelectableGroups supporting select(group=).
        if hasattr(eps, "select"):
            selected = eps.select(group=ENGINE_ENTRY_POINT_GROUP)
        else:  # pragma: no cover - legacy dict API
            selected = eps.get(ENGINE_ENTRY_POINT_GROUP, [])
        return {ep.name: ep for ep in selected}
    except Exception as exc:  # pragma: no cover - defensive: never let discovery crash
        logger.debug(f"ENGINE_DISCOVERY_FAILED: {exc}")
        return {}


def list_registered_engines() -> list[str]:
    """List the names of all registered TTS engines (sorted).

    Always includes the built-in 'voice-soundboard' even if its entry point
    can't be read from package metadata.
    """
    names = set(_load_engine_entry_points())
    names.add(DEFAULT_ENGINE_NAME)
    return sorted(names)


def get_default_engine(name: Optional[str] = None) -> TTSEngine:
    """Resolve a TTS engine by name, env var, or the built-in default.

    FT-ENGINE-001 pluggable engine registry. Resolution order:

        1. ``name`` argument (when given)
        2. ``AUDIOBOOKER_ENGINE`` environment variable
        3. ``DEFAULT_ENGINE_NAME`` ('voice-soundboard')

    Registered engines are looked up via the ``audiobooker.tts_engines``
    entry-point group. The built-in voice-soundboard engine is ALWAYS available
    as a hard fallback, so a bare ``get_default_engine()`` (or
    ``get_default_engine("voice-soundboard")``) is byte-identical to the
    historical behavior and never depends on package metadata being readable.

    Args:
        name: Explicit engine name. None falls through to the env var / default.

    Returns:
        An instantiated TTSEngine.

    Raises:
        EngineNotFoundError: If a *named* engine (from the arg or env var) is
            not registered. The built-in default never raises this.
    """
    # Resolve the requested name through the precedence chain. An empty/blank
    # env var is treated as unset.
    requested = name
    if requested is None:
        env_name = os.environ.get(ENGINE_ENV_VAR)
        if env_name and env_name.strip():
            requested = env_name.strip()
    if requested is None:
        requested = DEFAULT_ENGINE_NAME

    # The built-in always resolves to the in-process class — no metadata needed.
    if requested == DEFAULT_ENGINE_NAME:
        return _VoiceSoundboardEngine()

    # Otherwise look the name up in the registered entry points.
    registered = _load_engine_entry_points()
    ep = registered.get(requested)
    if ep is None:
        installed = sorted(set(registered) | {DEFAULT_ENGINE_NAME})
        raise EngineNotFoundError(requested, installed)

    engine_cls = ep.load()
    return engine_cls()


class EngineNotFoundError(RuntimeError):
    """FT-ENGINE-001: a named TTS engine is not registered."""

    def __init__(self, name: str, installed: list[str]) -> None:
        self.name = name
        self.installed = installed
        message = (
            f"Unknown TTS engine {name!r}. "
            f"Installed: {', '.join(installed)}. "
            f"Install a plugin, e.g. pip install audiobooker-piper."
        )
        super().__init__(message)
        # Structured error shape (code/message/hint/retryable) — matches the
        # rest of the renderer's error surface.
        self.code = "INPUT_UNKNOWN_ENGINE"
        self.hint = (
            "Install a TTS engine plugin (e.g. pip install audiobooker-piper) "
            f"or set {ENGINE_ENV_VAR} to one of: {', '.join(installed)}."
        )
        self.retryable = False

    def structured(self) -> dict:
        """Return the canonical error shape as a dict."""
        return {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "retryable": self.retryable,
        }


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
    emotion_preset: str = "neutral",
) -> Path:
    """
    Render a single chapter to audio.

    Args:
        chapter: Chapter with compiled utterances.
        casting: CastingTable for voice mapping.
        output_path: Output audio file path.
        progress_callback: Callback(current_utterance, total_utterances).
        engine: Injected TTSEngine (defaults to voice-soundboard).
        emotion_preset: FT-CAST-026 emotion preset selecting the SSML emphasis
            map. 'neutral' (default) reproduces historical emphasis levels.

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
            # FT-CAST-026: select the emphasis map by the active emotion preset.
            # Defaults to 'neutral', which reproduces the historical emphasis
            # levels exactly (regression-critical).
            script = preprocess_ssml(chapter.utterances, emotion_preset)
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
# FT-RENDER-P-004: Utterance-level incremental cache (OPT-IN, namespaced)
# ---------------------------------------------------------------------------
#
# DEFAULT: OFF. render_chapter() (above) is completely untouched — the chapter
# cache path is byte-identical when this feature is unused. Nothing in
# render_project() calls into this path unless an opt-in flag is threaded
# through by the integration layer (cli/project, which this agent does not own).
#
# When ON, a chapter is synthesized one utterance at a time. Each utterance's
# WAV is sub-cached under its utterance_hash (speaker+text+emotion+intensity+
# voice+params). Re-rendering a chapter after editing one line only
# re-synthesizes that one utterance; the rest are reused from the sub-cache and
# the chapter WAV is re-stitched with a cheap ffmpeg concat (-c copy).
#
# The utterance manifest is namespaced (render_v2_utterance.json, its own
# version) so old render_v1.json chapter manifests still load unchanged.


@dataclass
class IncrementalRenderResult:
    """Outcome of an utterance-level incremental chapter render."""
    audio_path: Path
    duration_seconds: float
    utterances_total: int = 0
    utterances_synthesized: int = 0
    utterances_reused: int = 0


def render_chapter_incremental(
    chapter: "Chapter",
    casting: "CastingTable",
    output_path: Path,
    *,
    engine: Optional[TTSEngine] = None,
    cache_root: Path,
    render_params_hash: str,
    runner: Optional[Callable] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> IncrementalRenderResult:
    """
    FT-RENDER-P-004: Render a chapter utterance-by-utterance with a sub-cache.

    OPT-IN. This is never reached by the default render path — the chapter
    cache stays byte-identical unless a caller explicitly opts in.

    Each utterance is synthesized individually into a per-chapter utterance
    directory, keyed on its ``utterance_hash``. Unchanged utterances are reused
    from a prior run; only changed/new utterances hit the TTS engine. The
    per-utterance WAVs are then concatenated into ``output_path`` with ffmpeg
    ``concat -c copy`` (cheap — no re-encode).

    Args:
        chapter: Compiled chapter (utterances required).
        casting: CastingTable for voice resolution.
        output_path: Final chapter WAV path.
        engine: Injected TTSEngine (defaults to voice-soundboard).
        cache_root: Render cache root (utterance WAVs + manifest live under it).
        render_params_hash: The chapter's render-params hash (ties utterance
            keys to the same TTS knobs the chapter cache uses).
        runner: Injected FFmpegRunner-like callable holder for the concat step
            (defaults to RealFFmpegRunner). Tests pass a fake.
        progress_callback: Callback(current_utterance, total_utterances).

    Returns:
        IncrementalRenderResult with the stitched WAV path, duration, and
        synthesize/reuse accounting.

    Raises:
        ValueError: If the chapter has no utterances.
        RenderError: If synthesis or stitching fails.
    """
    from audiobooker.renderer.cache_manifest import (
        UtteranceCacheEntry,
        UtteranceCacheManifest,
        get_utterance_manifest_path,
        get_utterance_wav_dir,
        load_utterance_manifest,
        save_utterance_manifest,
    )
    from audiobooker.renderer.hash_utils import utterance_hash as _utterance_hash

    if not chapter.utterances:
        raise ValueError(
            f"Chapter {chapter.index} has no utterances. Compile first."
        )

    if engine is None:
        engine = get_default_engine()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    utt_dir = get_utterance_wav_dir(cache_root, chapter.index)
    utt_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = get_utterance_manifest_path(cache_root, chapter.index)

    manifest = load_utterance_manifest(manifest_path)
    if manifest is None:
        manifest = UtteranceCacheManifest()

    voice_mapping = casting.get_voice_mapping()
    total = len(chapter.utterances)
    synthesized = 0
    reused = 0
    total_duration = 0.0
    ordered_wavs: list[Path] = []

    for idx, utt in enumerate(chapter.utterances):
        voice, _emotion = casting.get_voice(utt.speaker)
        uhash = _utterance_hash(utt, voice, render_params_hash)
        target = utt_dir / f"utt_{uhash}.wav"

        entry = manifest.get_entry(uhash)
        if entry is not None and entry.is_valid():
            # Reuse the cached utterance WAV — no engine call.
            reused += 1
            total_duration += entry.duration_s
            ordered_wavs.append(Path(entry.wav_path))
        else:
            # Synthesize just this utterance. A single-utterance script keeps the
            # engine contract identical to the chapter path (same tagged-line
            # format), only narrower in scope.
            from audiobooker.casting.dialogue import utterances_to_script
            script = utterances_to_script([utt], casting)
            tmp = target.with_suffix(".wav.tmp")
            try:
                result = engine.synthesize(
                    script=script,
                    voices=voice_mapping,
                    output_path=tmp,
                )
            except Exception as e:
                tmp.unlink(missing_ok=True)
                raise RenderError(
                    f"Chapter {chapter.index} utterance {idx} "
                    f"({utt.speaker!r}) failed to synthesize: {e}",
                    code="RUNTIME_RENDER",
                ) from e

            try:
                os.replace(str(tmp), str(target))
            except OSError:
                shutil.move(str(tmp), str(target))

            synthesized += 1
            total_duration += result.duration_seconds
            ordered_wavs.append(target)

            manifest.set_entry(
                UtteranceCacheEntry(
                    utterance_hash=uhash,
                    wav_path=str(target),
                    duration_s=result.duration_seconds,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            save_utterance_manifest(manifest, manifest_path)

        if progress_callback:
            progress_callback(idx + 1, total)

    # Stitch the per-utterance WAVs into the chapter WAV (cheap concat copy).
    _stitch_utterance_wavs(ordered_wavs, output_path, runner=runner)

    chapter.audio_path = output_path
    chapter.duration_seconds = total_duration

    logger.info(
        f"RENDER_INCREMENTAL: chapter={chapter.index} "
        f"utterances={total} synthesized={synthesized} reused={reused} "
        f"duration={total_duration:.1f}s"
    )

    return IncrementalRenderResult(
        audio_path=output_path,
        duration_seconds=total_duration,
        utterances_total=total,
        utterances_synthesized=synthesized,
        utterances_reused=reused,
    )


def _stitch_utterance_wavs(
    wavs: list[Path],
    output_path: Path,
    *,
    runner: Optional[Callable] = None,
) -> Path:
    """Concatenate per-utterance WAVs into one chapter WAV via ffmpeg concat.

    Uses ``-c copy`` (no re-encode) — the utterance WAVs share the engine's
    sample format, so this is a cheap remux. A single WAV is just copied.
    """
    if not wavs:
        raise RenderError(
            "Cannot stitch an empty utterance list into a chapter WAV.",
            code="RUNTIME_RENDER",
        )

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    if len(wavs) == 1:
        shutil.copy(str(wavs[0]), str(output_path))
        return output_path

    # Build a concat list file (one 'file ...' line per utterance WAV).
    import tempfile
    concat_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            concat_file = Path(f.name)
            for wav in wavs:
                escaped = str(Path(wav).absolute().as_posix()).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        result = runner.run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ])
        if result.returncode != 0:
            raise RenderError(
                f"Failed to stitch chapter WAV from utterances: {result.stderr}",
                code="RUNTIME_RENDER",
            )
        return output_path
    finally:
        if concat_file is not None:
            concat_file.unlink(missing_ok=True)


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
    bitrate: Optional[str] = None,
    output_profile: str = "podcast",
    split: bool = False,
    **kwargs,
) -> Path:
    """
    Render all chapters and assemble final audiobook.

    Chapter WAVs are persisted to a stable cache directory so that
    failures are non-catastrophic and reruns skip completed work.

    Args:
        project: AudiobookProject to render.
        output_path: Output file path (.m4b / .mp3 / .opus / .flac / ...).
        progress_callback: Callback(current_chapter, total_chapters, status).
        engine: Injected TTSEngine (defaults to voice-soundboard).
        assembler: Injected assembly function (defaults based on format).
        cache_root: Override cache directory (default: derive from project).
        resume: If True, skip chapters whose cache entries are still valid.
        from_chapter: Start rendering from this chapter index (0-based).
        allow_partial: If True, assemble even if some chapters failed.
        jobs: Number of parallel render workers (default 1).
        force: If True, bypass casting completeness validation.
        output_format: Override output format
            ('m4b', 'mp3', 'wav', 'opus', 'flac').
        cover_art: Optional path to cover art image (JPG/PNG). When None,
            defaults to project.metadata.cover_art_path if that file exists
            (FT-RENDER-M-002).
        normalize: If True, run loudness mastering with ``output_profile``.
        bitrate: Encoding bitrate override (e.g. "192k"). Defaults to the
            profile's bitrate (FT-RENDER-M-003).
        output_profile: 'podcast' (EBU R128 -16 LUFS) or 'acx' (loudnorm
            I=-20:TP=-3:LRA=11, 44.1k/192k) (FT-ACX-001).
        split: If True for AAC output, emit per-chapter .m4a files plus an
            index playlist instead of a single m4b (FT-RENDER-M-007).

    Returns:
        Path to final audiobook file.

    Raises:
        RenderError: If a chapter fails (unless allow_partial is True)
            or if no chapters render successfully.
    """
    from audiobooker.renderer.output import (
        assemble_m4b as _m4b_assembler,
        assemble_mp3 as _mp3_assembler,
        assemble_opus as _opus_assembler,
        assemble_flac as _flac_assembler,
        assemble_m4a_split as _m4a_split_assembler,
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

    # FT-RENDER-003 / FT-RENDER-M-006 / FT-RENDER-M-007: Select assembler by
    # format. 'split' on an AAC format emits per-chapter .m4a files.
    fmt = output_format or project.config.output_format
    _builtin_assemblers = (
        _m4b_assembler, _mp3_assembler, _opus_assembler,
        _flac_assembler, _m4a_split_assembler,
    )
    if assembler is None:
        if split and fmt in ("m4b", "m4a"):
            assembler = _m4a_split_assembler
        elif fmt == "mp3":
            assembler = _mp3_assembler
        elif fmt in ("opus", "ogg"):
            assembler = _opus_assembler
        elif fmt == "flac":
            assembler = _flac_assembler
        else:
            assembler = _m4b_assembler

    # ENGINE-C-001: ffmpeg preflight. When the output format needs ffmpeg for
    # assembly, fail fast BEFORE rendering the whole book — otherwise the user
    # waits through a full render only to hit a missing-ffmpeg wall at assembly.
    # Skipped when a custom assembler is injected (tests / non-ffmpeg backends).
    if assembler in _builtin_assemblers and fmt in _FFMPEG_FORMATS:
        from audiobooker.renderer.output import check_ffmpeg
        if not check_ffmpeg():
            raise RenderError(
                "ffmpeg is required to assemble the audiobook but was not found "
                f"on PATH (output format: {fmt}).",
                code="DEP_FFMPEG_MISSING",
                retryable=True,
                hint=(
                    "Install ffmpeg (https://ffmpeg.org/download.html), then "
                    "re-run audiobooker render — already-rendered chapters are "
                    "cached and will be skipped."
                ),
            )

    output_path = Path(output_path)

    # FT-RENDER-M-002: Auto-cover. When no cover was supplied, fall back to the
    # project's metadata cover_art_path if that file exists, and log which
    # source we used so it's never a silent surprise.
    if cover_art is None:
        meta = getattr(project, "metadata", None)
        meta_cover = getattr(meta, "cover_art_path", None) if meta else None
        if meta_cover is not None and Path(meta_cover).exists():
            cover_art = str(meta_cover)
            logger.info(f"RENDER_COVER: using project metadata cover {cover_art}")
        elif meta_cover is not None:
            logger.warning(
                f"RENDER_COVER: project metadata cover path does not exist "
                f"({meta_cover}); rendering without a cover."
            )
    elif cover_art:
        logger.info(f"RENDER_COVER: using supplied cover {cover_art}")

    # FT-ACX-001 / FT-RENDER-M-003: resolve the effective bitrate from the
    # profile default when the caller didn't pin one.
    from audiobooker.renderer.output import _resolve_loudnorm_profile
    _profile = _resolve_loudnorm_profile(output_profile)
    effective_bitrate = bitrate or _profile["bitrate"]
    # ACX is a retail master — always run loudness normalization for it.
    effective_normalize = normalize or (output_profile == "acx")

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
                # ENGINE-C-004: use the monotonic completed count for the bar
                # position (not i+1, which is non-monotonic under as_completed),
                # while keeping the chapter title in the status string.
                with manifest_lock:
                    done_count = tracker.completed_count + tracker.failed_count
                status = tracker.format_chapter_status(i, f"Rendering: {chapter.title}")
                progress_callback(done_count, len(project.chapters), status)

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
                # ENGINE-C-004: also read a monotonic completed count under the
                # lock. Under as_completed(), chapters finish out of order, so
                # using each chapter's own index (i+1) makes the progress bar
                # jump backwards. completed_count+failed_count only ever rises.
                with manifest_lock:
                    manifest.set_entry(entry)
                    save_manifest(manifest, manifest_path)
                    summary.rendered += 1
                    done_count = tracker.completed_count + tracker.failed_count

                if progress_callback:
                    status = tracker.format_chapter_status(i, f"Rendered: {chapter.title}")
                    progress_callback(done_count, len(project.chapters), status)

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

        # FT-RENDER-006 / FT-RENDER-M-*: Pass the rich assembler kwargs when the
        # assembler accepts them. Injected test assemblers only take the base
        # five positional kwargs, so optional kwargs are stripped on TypeError.
        base_kwargs = dict(
            chapter_files=ok_paths,
            output_path=output_path,
            title=project.title,
            author=project.author,
            chapter_pause_ms=project.config.chapter_pause_ms,
        )
        # Optional kwargs, attempted in addition to base_kwargs. Order matters:
        # they're stripped one group at a time on TypeError, most-specific last.
        optional_kwargs = dict(
            metadata=getattr(project, "metadata", None),
            loudnorm_profile=output_profile,
        )
        # Bitrate kwarg name differs across assemblers: assemble_m4b takes
        # aac_bitrate, the others take bitrate. Pick whichever the assembler
        # actually accepts so the bitrate is never silently dropped. When the
        # assembler only declares **kwargs (no named bitrate param), default to
        # the generic 'bitrate' name.
        try:
            import inspect
            _params = inspect.signature(assembler).parameters
            _names = set(_params)
            _has_var_kw = any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in _params.values()
            )
            if "aac_bitrate" in _names:
                optional_kwargs["aac_bitrate"] = effective_bitrate
            elif "bitrate" in _names or _has_var_kw:
                optional_kwargs["bitrate"] = effective_bitrate
        except (TypeError, ValueError):
            optional_kwargs["bitrate"] = effective_bitrate
        if cover_art:
            optional_kwargs["cover_art"] = cover_art
        if effective_normalize:
            optional_kwargs["normalize"] = effective_normalize

        def _call_assembler():
            """Call the assembler, degrading optional kwargs on TypeError."""
            attempt = dict(base_kwargs, **optional_kwargs)
            # Drop optional kwargs from the end until the call type-checks.
            droppable = list(optional_kwargs.keys())
            while True:
                try:
                    return assembler(**attempt)
                except TypeError:
                    if not droppable:
                        raise
                    drop = droppable.pop()
                    attempt.pop(drop, None)

        try:
            assembly = _call_assembler()
        except RuntimeError as assembly_err:
            # ENGINE-C-001: assembly can fail on missing ffmpeg AFTER a full,
            # successful render. Wrap it in RenderError so the recoverable path
            # (chapters are cached on disk) is surfaced instead of a raw
            # RuntimeError — re-running skips the cached WAVs.
            if "ffmpeg" in str(assembly_err).lower():
                raise RenderError(
                    "Chapters rendered successfully, but assembling the "
                    f"audiobook failed: {assembly_err}",
                    summary=summary,
                    code="DEP_FFMPEG_MISSING",
                    retryable=True,
                    hint=(
                        "Install ffmpeg (https://ffmpeg.org/download.html), then "
                        "re-run audiobooker render — your rendered chapters are "
                        "cached and will be skipped, so only assembly re-runs."
                    ),
                ) from assembly_err
            raise

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


# ---------------------------------------------------------------------------
# FT-RENDER-M-009: Retail sample
# ---------------------------------------------------------------------------

def render_sample(
    project: "AudiobookProject",
    *,
    from_chapter: int = 0,
    start_seconds: float = 0.0,
    duration: float = 180.0,
    output_path: Optional[Path] = None,
    output_profile: str = "podcast",
    bitrate: Optional[str] = None,
    engine: Optional[TTSEngine] = None,
    cache_root: Optional[Path] = None,
) -> Path:
    """
    FT-RENDER-M-009: Produce a short, retail-ready audiobook sample.

    Trims ``duration`` seconds (starting at ``start_seconds``) from a single
    chapter and masters it with the chosen profile/bitrate, tagging it as a
    "Retail Sample". The chapter's rendered WAV is reused from the render
    cache when present; otherwise the chapter is rendered on the fly.

    Args:
        project: AudiobookProject (chapters should be compiled).
        from_chapter: Chapter index (0-based) to sample from.
        start_seconds: Offset into the chapter to start the sample.
        duration: Sample length in seconds (ACX retail samples are ~1-5 min).
        output_path: Output file path. Defaults to ``<title>_sample.<ext>``
            where the extension follows the profile (m4b/m4a → .m4a).
        output_profile: 'podcast' or 'acx' mastering profile.
        bitrate: Encoding bitrate override (defaults to the profile bitrate).
        engine: Injected TTSEngine (for rendering an uncached chapter / tests).
        cache_root: Override cache directory (default: derive from project).

    Returns:
        Path to the rendered sample file.

    Raises:
        RenderError: If the chapter index is out of range, the chapter cannot
            be rendered, or ffmpeg is unavailable.
        ValueError: If duration <= 0.
    """
    from audiobooker.renderer.output import (
        check_ffmpeg,
        _resolve_loudnorm_profile,
        _sanitize_metadata_value,
    )
    from audiobooker.renderer.cache_manifest import (
        load_manifest, get_cache_root, get_manifest_path, get_chapter_wav_path,
    )
    from audiobooker.renderer.hash_utils import (
        chapter_text_hash, casting_hash, render_params_hash,
    )

    if duration <= 0:
        raise ValueError(f"Sample duration must be positive, got {duration}.")
    if from_chapter < 0 or from_chapter >= len(project.chapters):
        raise RenderError(
            f"Sample chapter index {from_chapter} out of range "
            f"(0-{len(project.chapters) - 1}).",
            code="SAMPLE_BAD_CHAPTER",
            retryable=False,
        )

    if not check_ffmpeg():
        raise RenderError(
            "ffmpeg is required to master a retail sample but was not found "
            "on PATH.",
            code="DEP_FFMPEG_MISSING",
            retryable=True,
            hint="Install ffmpeg (https://ffmpeg.org/download.html), then re-run.",
        )

    from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
    runner = RealFFmpegRunner()

    profile = _resolve_loudnorm_profile(output_profile)
    effective_bitrate = bitrate or profile["bitrate"]
    sample_rate = profile["sample_rate"]
    loudnorm_filter = profile["loudnorm"]

    chapter = project.chapters[from_chapter]

    # Resolve cache root for cache reuse.
    if cache_root is None:
        project_dir = _resolve_project_dir(project)
        cache_root = get_cache_root(project_dir)

    # --- Locate the chapter WAV: reuse cache when valid, else render fresh ---
    chapter_wav: Optional[Path] = None
    cached_path = get_chapter_wav_path(cache_root, from_chapter)
    manifest_path = get_manifest_path(cache_root)
    manifest = load_manifest(manifest_path)
    if manifest is not None:
        entry = manifest.get_entry(from_chapter)
        if entry is not None:
            try:
                valid = entry.is_valid(
                    chapter_text_hash(chapter),
                    casting_hash(project.casting),
                    render_params_hash(project.config),
                )
            except Exception:
                valid = False
            if valid:
                chapter_wav = Path(entry.wav_path)
                logger.info(
                    f"SAMPLE_CACHE_HIT: chapter={from_chapter} reusing {chapter_wav}"
                )

    if chapter_wav is None and cached_path.exists() and cached_path.stat().st_size > 1024:
        # WAV present on disk even without a manifest entry — reuse it.
        chapter_wav = cached_path
        logger.info(f"SAMPLE_CACHE_DISK: reusing on-disk chapter WAV {chapter_wav}")

    if chapter_wav is None:
        # Render the chapter fresh into the cache location.
        if not chapter.is_compiled:
            raise RenderError(
                f"Chapter {from_chapter} ({chapter.title!r}) is not compiled — "
                f"compile the project before sampling.",
                code="SAMPLE_NOT_COMPILED",
                retryable=False,
            )
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"SAMPLE_RENDER: rendering chapter {from_chapter} for sample")
        render_chapter(chapter, project.casting, cached_path, engine=engine)
        chapter_wav = cached_path

    # --- Output path / extension ---
    if output_path is None:
        from audiobooker.project import _sanitize_filename
        ext = "m4a"
        output_path = Path(f"{_sanitize_filename(project.title)}_sample.{ext}")
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Trim + master in a single ffmpeg pass ---
    safe_title = _sanitize_metadata_value(f"{project.title} (Retail Sample)")
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{max(0.0, start_seconds):.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(chapter_wav),
        "-af", loudnorm_filter,
        "-c:a", "aac",
        "-b:a", effective_bitrate,
        "-ar", sample_rate,
        "-metadata", f"title={safe_title}",
        "-metadata", "comment=Retail Sample",
        "-metadata", f"album={_sanitize_metadata_value(project.title)}",
    ]
    if project.author:
        cmd.extend(["-metadata", f"artist={_sanitize_metadata_value(project.author)}"])
    cmd.append(str(output_path))

    result = runner.run(cmd)
    if result.returncode != 0:
        raise RenderError(
            f"Failed to master retail sample: {result.stderr.strip()[:300]}",
            code="SAMPLE_MASTER_FAIL",
            retryable=True,
        )

    logger.info(
        f"SAMPLE_COMPLETE: output={output_path} chapter={from_chapter} "
        f"start={start_seconds:.1f}s duration={duration:.1f}s profile={output_profile}"
    )
    return output_path


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

    # ENGINE-C-003: words/wpm yields playback length, not render wall-time —
    # label it as the resulting audiobook length so users aren't misled into
    # expecting the render to take this long.
    print(f"Audiobook length: {est_str} ({total_words_render:,} words to render)")
    print(f"Estimated disk usage:  ~{est_disk_mb:.0f} MB (chapter WAVs)")
    print(f"{'='*60}")


def _log_summary(summary: RenderSummary) -> None:
    """Log the render summary."""
    logger.info(
        f"RENDER_SUMMARY: rendered={summary.rendered} "
        f"cached={summary.skipped_cached} failed={summary.failed} "
        f"total={summary.total} cache={summary.cache_dir}"
    )
