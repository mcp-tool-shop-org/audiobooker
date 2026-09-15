"""
Render Engine for Audiobooker.

Synthesizes chapters to audio. Accepts an injected TTSEngine for testability;
defaults to the real voice-soundboard DialogueEngine when none is provided.

Supports persistent chapter cache with manifest-driven resume.
"""

import errno
import json
import logging
import os
import shutil
import threading
import time
import uuid
from xml.sax.saxutils import escape as _xml_escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from audiobooker.errors import AudiobookerError, ErrorDetail
from audiobooker import formats as audio_formats
from audiobooker.labels import chapter_label
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

# F-7a3c91e2: both sets are DERIVED from audiobooker.formats, the one table.
# They were hand-maintained lists that drifted apart from four others.
#
# _FFMPEG_FORMATS used to exclude 'wav', with the comment "'wav' chapters are
# written directly by the TTS engine and need no ffmpeg step." True of a
# CHAPTER and false of a BOOK: concatenating chapter WAVs into one file is an
# ffmpeg job like every other format. So `--format wav` skipped the preflight
# whose entire purpose is to fail before a render rather than after it, then
# rendered the whole book -- every second of it paid for -- and hit the
# missing-ffmpeg wall at assembly.
_FFMPEG_FORMATS = set(audio_formats.FFMPEG_FORMATS)

# FT-RENDER-M-006: all output formats the renderer knows how to assemble.
VALID_OUTPUT_FORMATS = set(audio_formats.ALL_FORMAT_NAMES)


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

# FEAT-PROD-011: the air between two speakers. This used to be a literal
# inside preprocess_ssml, which is why the incremental path could lose it
# without anything noticing -- there was nothing to share. Both paths now
# read this, so the pause cannot differ by which cache mode you chose.
SPEAKER_CHANGE_BREAK_MS = 750


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


def _pause_break_ms(text: str) -> int:
    """Parse a PAUSE utterance's text (``pause:1000ms`` / ``pause:2s``) to ms.

    Compile stores pauses as ``pause:{duration_ms}ms``. Unknown shapes fall
    back to ``SPEAKER_CHANGE_BREAK_MS`` rather than speaking the marker.
    """
    raw = (text or "").strip().lower()
    if raw.startswith("pause:"):
        raw = raw[len("pause:"):]
    if raw.endswith("ms"):
        try:
            return max(0, int(float(raw[:-2])))
        except ValueError:
            return SPEAKER_CHANGE_BREAK_MS
    if raw.endswith("s"):
        try:
            return max(0, int(float(raw[:-1]) * 1000))
        except ValueError:
            return SPEAKER_CHANGE_BREAK_MS
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return SPEAKER_CHANGE_BREAK_MS


def _utterance_type_name(utt: object) -> str:
    """``UtteranceType.value`` or empty for duck-typed / legacy utterances."""
    ut = getattr(utt, "utterance_type", None)
    if ut is None:
        return ""
    return getattr(ut, "value", ut) or ""


def _ssml_voice_id(
    speaker: str, voices: Optional[dict[str, str]]
) -> Optional[str]:
    """Resolve a <voice name> from a speaker→voice mapping."""
    if not voices:
        return None
    if speaker in voices:
        return voices[speaker]
    from audiobooker.models import CastingTable
    return voices.get(CastingTable.normalize_key(speaker))


def preprocess_ssml(
    utterances: list["Utterance"],
    emotion_preset: str = "neutral",
    voices: Optional[dict[str, str]] = None,
) -> str:
    """
    Transform utterances into an SSML document.

    Inserts:
    - <speak> wrapper
    - <break> tags at paragraph boundaries (between utterances)
    - <break> for UtteranceType.PAUSE (from ``pause:1000ms`` text)
    - skipped DIRECTION / SFX (non-speech, matching utterances_to_script)
    - <voice name> from the resolved voice id when ``voices`` is provided
    - <emphasis> for emotion-tagged text (FT-CAST-023: emphasis level scales
      with the utterance's intensity; FT-CAST-026: the base emphasis map is
      selected by ``emotion_preset``)
    - <prosody rate> for narrator (medium) vs dialogue (slightly faster)

    Regression contract: with ``emotion_preset='neutral'`` (default) and
    utterances whose ``intensity`` is None (or absent on legacy models), the
    emphasis levels are byte-identical to the historical engine. Voice tags
    are added only when ``voices`` is passed, so callers that omit it keep
    the historical SSML.

    Args:
        utterances: List of Utterance objects to convert.
        emotion_preset: Emotion preset selecting the emphasis map (FT-CAST-026).
        voices: Optional speaker→voice-id mapping. When given, each spoken
            utterance is wrapped in ``<voice name="...">``.

    Returns:
        SSML string wrapped in <speak> tags.
    """
    if not utterances:
        return "<speak></speak>"

    parts: list[str] = []
    prev_speaker: str | None = None

    for utt in utterances:
        utt_type = _utterance_type_name(utt)

        # F-82d65329: PAUSE must emit <break>, not spoken "pause:1000ms".
        # DIRECTION is non-speech ([SFX] on the tagged-line path).
        if utt_type == "pause":
            parts.append(f'<break time="{_pause_break_ms(utt.text)}ms"/>')
            continue
        if utt_type == "direction":
            continue

        # Insert paragraph break between speaker changes
        if prev_speaker is not None and utt.speaker != prev_speaker:
            parts.append(f'<break time="{SPEAKER_CHANGE_BREAK_MS}ms"/>')

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

        inner = f'<prosody rate="{rate}">{text}</prosody>'
        voice_id = _ssml_voice_id(utt.speaker, voices)
        if voice_id:
            inner = f'<voice name="{_xml_escape(voice_id)}">{inner}</voice>'
        parts.append(inner)

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
        # F-0b11d4e5: filter by chapter.index, matching exclude_ranges.
        # Enumerate position disagrees with chapter.index on a gapped or
        # already-filtered list, so `--chapters 4` kept the wrong chapter
        # while `--exclude-chapters 4` dropped the right one.
        if any(getattr(ch, "index", None) is not None for ch in chapters):
            chapters = [
                ch for ch in chapters
                if getattr(ch, "index", None) is not None and ch.index in include_set
            ]
        else:
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


def _assembler_accepted_kwargs(assembler: Callable) -> Optional[set[str]]:
    """The keyword names ``assembler`` declares, or None if unknowable.

    RH-B-001: the render path used to discover unsupported assembler kwargs by
    calling and catching TypeError, then stripping kwargs from the END of a
    fixed list until the call type-checked. ``normalize`` was appended last,
    so it was always the first thing dropped — silently, for every format but
    m4b. Binding by signature makes "this assembler cannot do that" a fact the
    caller can act on BEFORE the call.

    Returns None when the signature cannot be read (a C callable) or when the
    assembler declares ``**kwargs`` (it accepts anything by construction).
    """
    import inspect

    try:
        params = inspect.signature(assembler).parameters
    except (TypeError, ValueError):
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return None
    return {
        name for name, p in params.items()
        if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }


def engine_is_thread_safe(engine: TTSEngine) -> bool:
    """Whether ``engine.synthesize()`` may be called from several threads.

    RH-B-003: ``--jobs N`` drove ``synthesize()`` on ONE shared engine
    instance from N pool workers, and neither ``protocols.TTSEngine`` nor the
    ``capabilities()`` key set said whether that was allowed. Almost every
    real TTS backend is stateful (a loaded torch/ONNX model, a session
    object, one HTTP connection, a global voice register), so a third-party
    engine registered through the ``audiobooker.tts_engines`` entry point was
    entered concurrently by construction. The failure is not a clean
    exception — it is interleaved or cross-voiced audio in some chapters,
    which passes the size and duration checks and is only found on
    listen-back, hours later.

    Opt-in only: an engine must return ``{"thread_safe": True}`` from
    ``capabilities()``. Anything else — the key absent, a non-True value, no
    ``capabilities()`` method at all, or a method that raises — is treated as
    NOT thread-safe.
    """
    try:
        caps = engine.capabilities()
    except Exception:  # pragma: no cover - a broken engine is not thread-safe
        return False
    if not isinstance(caps, dict):
        return False
    return caps.get("thread_safe", False) is True


class _SerializedEngine:
    """Wraps a TTSEngine so only one thread is inside ``synthesize()``.

    RH-B-003. Everything other than ``synthesize`` is delegated untouched, so
    ``capabilities()``/``list_voices()`` still work. The wrapper is applied
    ONLY inside the render loop and never to the object used to compute the
    render-params hash — ``hash_utils._resolve_engine_name`` keys an injected
    engine by its class identity, so wrapping before hashing would invalidate
    every cached chapter the moment a user passed ``--jobs 2``.
    """

    __slots__ = ("_engine", "_lock")

    def __init__(self, engine: TTSEngine) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    def synthesize(self, *args, **kwargs):
        with self._lock:
            return self._engine.synthesize(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._engine, name)

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

        voice_mapping = casting.get_voice_mapping()

        # FT-RENDER-015: Use SSML preprocessing if engine supports it
        if should_use_ssml(engine):
            # FT-CAST-026: select the emphasis map by the active emotion preset.
            # Defaults to 'neutral', which reproduces the historical emphasis
            # levels exactly (regression-critical).
            script = preprocess_ssml(
                chapter.utterances, emotion_preset, voices=voice_mapping
            )
            logger.info(f"RENDER_SSML: chapter={chapter.index} using SSML preprocessing")
        else:
            # FEAT-PROD-003 (adjacent find): `casting` used to be omitted here.
            # utterances_to_script only emits the per-character {speed:1.4}
            # {pitch:-0.3} {emphasis:1.7} hints when it is given a casting
            # table, so Character.speed / pitch_shift / emphasis — validated in
            # models.py, round-tripped through casting JSON and CSV, and
            # emitted by the utterance-level incremental path, which DOES pass
            # casting — reached synthesis from nowhere on the default render
            # path. The two paths also disagreed about it, so opting into the
            # utterance cache silently changed the audio.
            #
            # Byte-identical for a default cast: the hint is only emitted when
            # a value differs from its default (speed != 1.0, pitch_shift !=
            # 0.0, emphasis != 1.0). casting_hash now keys all three, so a
            # character whose delivery is retuned invalidates rather than
            # re-serving the old performance.
            script = utterances_to_script(chapter.utterances, casting)

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
    emotion_preset: str = "neutral",
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
        emotion_preset: FT-CAST-026 emotion preset selecting the SSML emphasis
            map, mirroring ``render_chapter``. FEAT-PROD-009: without this the
            opt-in path silently dropped the project's preset, so turning the
            cache on quietly reverted every emphasis level to 'neutral'.

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
    try:
        utt_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # COORD-B-002 follow-up. The sibling fix below guards the per-utterance
        # WAV *filename* overflowing MAX_PATH. This is one level up: on a deep
        # enough project the cache DIRECTORY CHAIN alone
        # (<project>/.audiobooker/cache/chapters/chapter_NNNN_utterances)
        # exceeds the ceiling, and mkdir fails before any filename exists.
        #
        # It was the only failure path in this function that produced a raw,
        # unstructured OSError — every other one raises a RenderError with a
        # code and a hint, so the caller got a bare stack trace exactly where
        # the cause is least guessable.
        #
        # Same code as the filename case: it is one problem with one remedy,
        # and splitting it would make callers handle two codes for it. The
        # MESSAGE differs, because there is no utterance index yet — nothing
        # has been read or synthesized at this point, so naming one would be
        # inventing detail.
        path_diagnosis = _diagnose_windows_path_length(e)
        if path_diagnosis:
            raise RenderError(
                f"Chapter {chapter.index}: the render cache directory could "
                f"not be created — {path_diagnosis}",
                code="CACHE_PATH_TOO_LONG",
                hint=(
                    "Shorten the project's directory path, or enable Windows "
                    "long-path support, then re-run. Nothing has been "
                    "rendered yet, so no work is lost."
                ),
                retryable=False,
            ) from e
        raise RenderError(
            f"Chapter {chapter.index}: could not create the render cache "
            f"directory {utt_dir}: {e}",
            code="CACHE_DIR_UNWRITABLE",
            hint=(
                "Check that the project directory exists and is writable, "
                "and that no other process is holding it open."
            ),
            retryable=True,
        ) from e
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
    # FEAT-PROD-011: gap_before[i] is the silence, in ms, that belongs
    # between utterance i-1 and utterance i. preprocess_ssml emits its
    # <break> only when it can see a PREVIOUS speaker, and this path hands
    # it one utterance at a time -- so prev_speaker is None on the only
    # iteration, every time, and the break was never emitted. Opting into
    # the cache silently removed every pause in the book.
    #
    # The pause is inserted at stitch time rather than prepended to a
    # neighbour's script: baking it into utterance i's WAV would make those
    # bytes depend on utterance i-1, so editing one line would invalidate
    # the line after it too. That coupling is the thing a per-utterance
    # cache exists to avoid.
    gap_before: list[int] = []

    for idx, utt in enumerate(chapter.utterances):
        prev = chapter.utterances[idx - 1] if idx else None
        gap_before.append(
            SPEAKER_CHANGE_BREAK_MS
            if prev is not None and prev.speaker != utt.speaker
            else 0
        )
        voice, _emotion = casting.get_voice(utt.speaker)
        uhash = _utterance_hash(utt, voice, render_params_hash, casting=casting)
        # COORD-B-002 (wave 5): the ON-DISK filename only needs enough of the
        # hash to make a same-directory collision negligible -- it does NOT
        # need cache-key-grade uniqueness, because the cache key IS the full
        # `uhash` below (manifest.get_entry / UtteranceCacheEntry.utterance_
        # hash), never the filename. The full 64-hex digest spent half of
        # Windows' MAX_PATH for no correctness benefit: 68 of the ~91-char
        # ``.wav.tmp`` scratch name was ``utt_`` + the digest alone. 16 hex
        # chars (64 bits) reclaims 48 characters and is still enormously
        # more than any one chapter's utterance count could plausibly
        # collide against (birthday bound: >100,000 utterances in a single
        # chapter for even a one-in-a-billion chance) -- but be precise
        # about what a collision would actually do, since it is NOT the
        # same failure as a full-hash collision: two different utterances
        # whose first 16 hex chars matched would share one filename, so the
        # SECOND one synthesized would silently overwrite the first's WAV
        # on disk. The first entry's manifest record (keyed on the full,
        # collision-free `uhash`) would still say "valid" -- is_valid() only
        # stats the file, it never re-hashes its contents -- so this
        # degrades to silently serving the wrong audio for the first
        # utterance, not a clean cache miss. Negligible at book-sized
        # utterance counts, but a real (if vanishingly unlikely) mechanism,
        # so it is written down rather than hand-waved.
        target = utt_dir / f"utt_{uhash[:16]}.wav"

        # Backward compatibility: this does NOT invalidate anything already
        # on disk. `entry.is_valid()` (UtteranceCacheEntry, cache_manifest.py)
        # stats whatever path is stored in the OLD manifest's `wav_path` --
        # it never recomputes a filename from the hash -- and every OLD
        # entry was written with the full-hash filename, which still exists
        # untouched. So an existing manifest keeps resolving its (longer,
        # pre-fix) filenames exactly as before; only utterances synthesized
        # from here on get the shorter name. No manifest version bump is
        # needed because the on-disk filename was never part of the cache
        # contract -- only `wav_path` (a stored, opaque string) is.
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
            #
            # FEAT-PROD-009: "identical to the chapter path" has to include
            # WHICH format. render_chapter picks SSML for an SSML-capable
            # engine and the tagged-line script otherwise; this path always
            # chose the tagged-line script, so opting into the cache changed
            # the markup handed to the engine — and dropped the emotion preset
            # and intensity grading that only live in the SSML branch.
            from audiobooker.casting.dialogue import utterances_to_script
            if should_use_ssml(engine):
                script = preprocess_ssml(
                    [utt], emotion_preset, voices=voice_mapping
                )
            else:
                script = utterances_to_script([utt], casting)
            tmp = _chapter_tmp_path(target)
            try:
                result = engine.synthesize(
                    script=script,
                    voices=voice_mapping,
                    output_path=tmp,
                )
            except Exception as e:
                tmp.unlink(missing_ok=True)
                # COORD-B-002: a too-long cache path surfaces as an ordinary
                # OSError (e.g. FileNotFoundError: [Errno 2]) indistinguishable
                # in type/errno from a real TTS engine failure -- reporting it
                # as "failed to synthesize" sends the user to audit their
                # voice model and audio setup, neither of which is broken.
                # _diagnose_windows_path_length only speaks up when the
                # evidence (a long failing path) actually supports it; it
                # returns None for a genuine engine failure, which falls
                # through to the original message unchanged.
                path_diagnosis = _diagnose_windows_path_length(e)
                if path_diagnosis:
                    raise RenderError(
                        f"Chapter {chapter.index} utterance {idx} "
                        f"({utt.speaker!r}): {path_diagnosis}",
                        code="CACHE_PATH_TOO_LONG",
                        hint=(
                            "Shorten the project's directory path, or enable "
                            "Windows long-path support, then re-run. This is "
                            "not a TTS/voice problem, so switching engines or "
                            "voices will not help."
                        ),
                        retryable=False,
                    ) from e
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

            try:
                utt_size = target.stat().st_size
            except OSError:
                utt_size = 0
            manifest.set_entry(
                UtteranceCacheEntry(
                    utterance_hash=uhash,
                    wav_path=str(target),
                    duration_s=result.duration_seconds,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    size_bytes=utt_size,
                )
            )
            save_utterance_manifest(manifest, manifest_path)

        if progress_callback:
            progress_callback(idx + 1, total)

    # Stitch the per-utterance WAVs into the chapter WAV (cheap concat copy),
    # with the speaker-change silences spliced back in between them.
    _stitch_utterance_wavs(
        ordered_wavs, output_path, gap_before_ms=gap_before, runner=runner
    )
    # FEAT-PROD-011: the gaps are real audio in the file, so the reported
    # duration has to include them -- chapter marks are placed from these
    # numbers, and an under-report walks every later mark forward.
    total_duration += sum(gap_before) / 1000.0

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


def _write_silence_wav(path: Path, duration_ms: int, like: Path) -> Path:
    """Write ``duration_ms`` of silence matching ``like``'s WAV format.

    FEAT-PROD-011 / F-671abba9. Canonical implementation lives in output.py
    so chapter-concat silence and utterance-stitch silence cannot drift.
    """
    from audiobooker.renderer.output import _write_silence_wav as _impl
    return _impl(path, duration_ms, like)


def _stitch_utterance_wavs(
    wavs: list[Path],
    output_path: Path,
    *,
    gap_before_ms: Optional[list[int]] = None,
    runner: Optional[Callable] = None,
) -> Path:
    """Concatenate per-utterance WAVs into one chapter WAV via ffmpeg concat.

    Uses ``-c copy`` (no re-encode) — the utterance WAVs share the engine's
    sample format, so this is a cheap remux.

    ``gap_before_ms[i]`` is silence to splice in *before* ``wavs[i]``; the
    first entry is ignored (nothing precedes it). Omitting the argument
    concatenates the WAVs back to back, which is the historical behaviour.
    """
    if not wavs:
        raise RenderError(
            "Cannot stitch an empty utterance list into a chapter WAV.",
            code="RUNTIME_RENDER",
        )

    if gap_before_ms is None:
        gap_before_ms = [0] * len(wavs)
    elif len(gap_before_ms) != len(wavs):
        raise RenderError(
            f"gap_before_ms has {len(gap_before_ms)} entries for "
            f"{len(wavs)} utterance WAVs.",
            code="RUNTIME_RENDER",
        )

    # Interleave the silences. Written before the single-WAV shortcut below
    # so that shortcut stays correct: one WAV can have no gaps by
    # construction, and a lone segment needs no concat at all.
    segments: list[Path] = []
    gap_dir = output_path.parent / "_gaps"
    for i, wav in enumerate(wavs):
        if i and gap_before_ms[i] > 0:
            segments.append(_write_silence_wav(
                gap_dir / f"gap_{i:04d}_{gap_before_ms[i]}ms.wav",
                gap_before_ms[i],
                like=wav,
            ))
        segments.append(wav)
    wavs = segments

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
            # FEAT-PROD-009: name the output format explicitly. ffmpeg infers
            # it from the output EXTENSION, and the render path hands this
            # function a per-process scratch name ending in ".wav.tmp"
            # (_chapter_tmp_path) — ".tmp" is not a format ffmpeg knows, so
            # every real stitch would have died on "Unable to find a suitable
            # output format". It never surfaced because nothing called this
            # function outside tests, and the tests inject a fake runner that
            # writes the file itself. The output is a WAV by construction
            # (these are the engine's own per-utterance WAVs, concatenated
            # with -c copy), so stating it costs nothing and removes the
            # dependency on how the caller spells its temp file.
            "-f", "wav",
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

# Identity of THIS interpreter process, minted once at import. A PID alone is
# ambiguous in both directions: the OS recycles PIDs (a dead render's PID can
# be re-used by an unrelated process, making a stale lock look live), and the
# old "lock_pid == os.getpid() means stale" shortcut treated this process's own
# LIVE lock as garbage — two renders in one process happily shared a cache.
# pid + token answers "is this lock mine, and is it still running?" exactly.
_PROCESS_TOKEN = uuid.uuid4().hex


def _is_pid_running(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False


def _chapter_tmp_path(target_path: Path) -> Path:
    """Per-process scratch name for a chapter WAV.

    Two processes rendering into the same cache both wrote
    ``chapter_0000.wav.tmp`` and clobbered each other's partial output. Keep
    the ``.wav.tmp`` tail (cleanup globs and tests match on it) and make the
    middle unique per process.
    """
    return target_path.with_name(
        f"{target_path.stem}.{os.getpid()}.{_PROCESS_TOKEN[:8]}{target_path.suffix}.tmp"
    )


# COORD-B-002 (wave 5): Windows' MAX_PATH is 260 characters (drive + '\' +
# up to 259 usable chars + a NUL terminator). A cache path built under a
# deeply-nested project directory (a synced OneDrive tree, a nested series
# folder) can cross that line during ``render_chapter_incremental``.
_WINDOWS_MAX_PATH = 260


def _diagnose_windows_path_length(exc: BaseException) -> Optional[str]:
    """Best-effort check for a Windows MAX_PATH overflow behind an OSError.

    Measured directly (wave-5 COORD-B-002 probe, CPython 3.14 / Windows 11)
    rather than assumed:

    - A too-long path failing through a plain ``open()`` -- exactly what a
      TTS engine does when it writes ``output_path`` -- comes back as
      ``FileNotFoundError: [Errno 2] No such file or directory`` with
      ``winerror`` sitting at ``None``.
    - An ordinary, genuinely-missing parent directory (nothing to do with
      length) produces the IDENTICAL exception type, errno, and winerror.
    - Windows' one unambiguous code for this, ERROR_FILENAME_EXCED_RANGE
      (WinError 206), showed up in testing for a long *nested-mkdir* chain
      but NOT for an over-length leaf filename via ``open()`` -- so it
      cannot be relied on as the trigger either; it is checked only as an
      extra (never load-bearing) signal.

    So there is no errno that unambiguously means "too long" for the case
    this function exists to catch, and path length is a heuristic, not
    proof: a very deep but otherwise valid project could raise this same
    error for a reason that has nothing to do with length (a permissions
    change, a vanished network mount). This function only speaks up when
    the OS actually told us which path it choked on (``exc.filename``) and
    that path is at or past the MAX_PATH ceiling -- and the message it
    returns says "likely", never "is", for exactly that reason.

    Returns a human-readable, hedged explanation when path length looks
    responsible, else None -- meaning "say nothing", never a guessed cause.
    """
    if os.name != "nt" or not isinstance(exc, OSError):
        return None

    path = exc.filename
    if not path:
        return None
    length = len(str(path))

    is_unambiguous_winerror = getattr(exc, "winerror", None) == 206  # ERROR_FILENAME_EXCED_RANGE
    if not is_unambiguous_winerror:
        if exc.errno != errno.ENOENT or length < _WINDOWS_MAX_PATH:
            return None

    return (
        f"likely a Windows path-length (MAX_PATH) problem, not a TTS engine "
        f"failure: the cache path is {length} characters long (Windows' "
        f"default ceiling is {_WINDOWS_MAX_PATH}). Move the project to a "
        f"shorter directory, or enable Windows long-path support (Windows "
        f"10 1607+: set HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem"
        f"\\LongPathsEnabled to 1, then sign out/in -- Python has declared "
        f"itself long-path-aware since 3.6, so the OS-level setting is the "
        f"only piece missing once it's turned on)."
    )


def _write_lockfile(lock_path: Path) -> bool:
    """Atomically create the lockfile. False when it already exists.

    O_CREAT|O_EXCL is a single atomic syscall: exactly one of two racing
    processes can win it. The previous exists()-then-write_text() pair left a
    window in which both saw "no lock" and both wrote one.
    """
    payload = json.dumps({
        "pid": os.getpid(),
        "token": _PROCESS_TOKEN,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _acquire_render_lock(cache_root: Path) -> Path:
    """
    Atomically create .render.lock containing PID + process token + timestamp.

    Reclaims a lock only when it can be PROVEN dead — the writing process is
    gone, or the PID matches but the token does not (so the PID was recycled
    and the original writer is gone). Anything else is treated as a live
    render and raises RenderError.
    """
    lock_path = cache_root / LOCKFILE_NAME

    for _attempt in (0, 1):
        if _write_lockfile(lock_path):
            logger.info(f"RENDER_LOCK: Acquired {lock_path} (PID {os.getpid()})")
            return lock_path

        # Someone else holds it. Decide whether it is live or reclaimable.
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(f"RENDER_LOCK: Corrupt lockfile at {lock_path}, removing")
            lock_path.unlink(missing_ok=True)
            continue

        lock_pid = lock_data.get("pid", -1)
        lock_token = lock_data.get("token")

        if lock_token == _PROCESS_TOKEN:
            # Our own process already holds it — a second concurrent render
            # against the same cache. The old code deleted this lock because
            # the PID matched; that is precisely the collision the lock exists
            # to prevent.
            raise RenderError(
                f"This process is already rendering into {cache_root} "
                f"(lock held since {lock_data.get('started_at', 'unknown')}). "
                f"Run one render per cache directory at a time."
            )

        if _is_pid_running(lock_pid) and lock_pid != os.getpid():
            raise RenderError(
                f"Another render is already running (PID {lock_pid}, "
                f"started {lock_data.get('started_at', 'unknown')}). "
                f"If this is stale, delete {lock_path}"
            )

        # Either the writer is gone, or its PID was recycled into us (same PID,
        # different token) — the original render is dead either way.
        logger.info(
            f"RENDER_LOCK: Removing stale lock (PID {lock_pid} is not the "
            f"process that wrote it)"
        )
        lock_path.unlink(missing_ok=True)

    raise RenderError(
        f"Could not acquire the render lock at {lock_path} — another render "
        f"keeps re-creating it. Delete the file if no render is running."
    )


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


def _validate_project_voices(project: "AudiobookProject", engine=None) -> None:
    """Run the project's voice-ID gate, honoring ``validate_voices_on_render``.

    Thin adapter so the renderer -- the one chokepoint every render path goes
    through -- enforces the same check ``Project.render()`` does, without
    duplicating the collection/lookup logic that lives on the project.

    Duck-typed on purpose: ``render_project`` is called with stand-in project
    objects in tests, and a missing ``config`` or ``_validate_voices`` must
    never turn into a render failure.

    Raises:
        VoiceNotFoundError: If any referenced voice ID is unavailable.
    """
    config = getattr(project, "config", None)
    if not getattr(config, "validate_voices_on_render", False):
        return
    validator = getattr(project, "_validate_voices", None)
    if not callable(validator):
        return
    validator(engine=engine)


# FEAT-PROD-004: the output destination is the one preflight nobody wrote.
# The gauntlet above this checks casting completeness, every voice ID, the
# ffmpeg binary, dialogue-attribution quality and even that --cover exists --
# and then synthesizes the entire book before discovering it cannot write the
# file. Measured on a 6-chapter book: all three unwritable-destination cases
# (missing parent directory, destination is a directory, parent path is a
# file) synthesized 6/6 chapters first and escaped as a bare FileNotFoundError
# or PermissionError with no code, no hint, and nothing saying the chapters
# are cached and a corrected re-run is nearly free.
_WRITE_PROBE_NAME = ".audiobooker-write-probe"


def _preflight_output_destination(output_path: Path, *, split: bool = False) -> None:
    """Fail fast when the finished book could not be written where it is going.

    Runs BEFORE the render loop, so a typo'd path costs nothing instead of a
    whole book's synthesis. Deliberately non-destructive: an existing output
    file is opened for append and closed, never truncated, and the writability
    probe is a uniquely-named temp file in the parent directory that is
    removed again. A missing parent directory is CREATED rather than rejected
    -- ffmpeg cannot create one, and refusing a path the user obviously meant
    would be worse than making it.

    Args:
        output_path: The final output path the assembler will be handed.
        split: True when the AAC split assembler is used, which treats
            ``output_path`` as a base name and writes a DIRECTORY from its
            stem. The thing that must be writable is then the parent and the
            stem-directory, not a file at ``output_path``.

    Raises:
        RenderError: code ``OUTPUT_UNWRITABLE``, naming the destination and
            the specific reason, with a hint that says the cached chapters
            survive a corrected re-run.
    """
    output_path = Path(output_path)
    target = output_path.parent / output_path.stem if split else output_path
    parent = target.parent if not split else output_path.parent

    def _fail(reason: str, cause: Optional[BaseException] = None) -> None:
        raise RenderError(
            f"Cannot write the audiobook to {output_path}: {reason}",
            code="OUTPUT_UNWRITABLE",
            retryable=True,
            hint=(
                "Fix the --output path (or the directory it lives in) and "
                "re-run. Nothing has been synthesized yet; any chapters "
                "already in the render cache are reused, so a corrected "
                "re-run costs almost nothing."
            ),
            cause=str(cause) if cause is not None else None,
        ) from cause

    # 1. The parent directory must exist, or be creatable.
    #
    # Creating it beats rejecting it: no assembler in renderer/output.py does
    # (grep for parent.mkdir there — nothing), so a missing directory is
    # today a hard failure at the very end, and the path the user typed is
    # almost always the path they meant. But creating a directory tree from a
    # TYPO silently is its own trap, so the recovery is logged at WARNING
    # rather than INFO: the CLI configures logging at WARNING by default, so
    # this is the one level where "I made a directory for you" actually
    # reaches the person who can tell a typo from an intention.
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            path_diagnosis = _diagnose_windows_path_length(e)
            if path_diagnosis:
                _fail(path_diagnosis, e)
            _fail(
                f"its directory {parent} does not exist and could not be "
                f"created ({e.strerror or e})",
                e,
            )
        logger.warning(
            f"RENDER_OUTPUT_DIR_CREATED: {parent} did not exist and was "
            f"created for the output {output_path.name!r}. If that is not "
            f"where you meant the book to go, stop now — nothing has been "
            f"synthesized yet."
        )
    elif not parent.is_dir():
        # A FILE sits where the directory should be. mkdir would raise
        # FileExistsError, which reads as "already there" -- say what is
        # actually wrong instead.
        _fail(f"{parent} is a file, not a directory")

    # 2. The destination itself must not already be a directory. ffmpeg's
    #    error for this is a bare PermissionError on Windows, which sends the
    #    user looking for an ACL problem that does not exist.
    if not split and target.is_dir():
        _fail(f"{target} is an existing directory, not a file")

    # 3. The parent must actually accept a new file. os.access() is advisory
    #    on Windows (it reports the read-only ATTRIBUTE, not the ACL), so
    #    probe by creating and removing a real file.
    probe = parent / f"{_WRITE_PROBE_NAME}-{uuid.uuid4().hex[:8]}"
    try:
        probe.touch()
    except OSError as e:
        path_diagnosis = _diagnose_windows_path_length(e)
        if path_diagnosis:
            _fail(path_diagnosis, e)
        _fail(f"its directory {parent} is not writable ({e.strerror or e})", e)
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best effort cleanup
            logger.debug(f"Could not remove write probe {probe}")

    # 4. An EXISTING output file must be replaceable. Append mode neither
    #    truncates nor changes the file; it just proves the handle can be had
    #    (a read-only file, or one held open by a player, fails here).
    if not split and target.exists():
        try:
            with open(target, "ab"):
                pass
        except OSError as e:
            _fail(
                f"the existing file cannot be overwritten ({e.strerror or e})",
                e,
            )

    logger.debug(f"RENDER_PREFLIGHT_OUTPUT_OK: {output_path}")


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
    # Indices of chapters that had no audio at assembly time and were dropped
    # because allow_partial was set. Non-empty means the output is INCOMPLETE.
    missing_chapters: list[int] = field(default_factory=list)
    # FT-ACX-001: master_check() report for an 'acx' render (None otherwise).
    acx_check: Optional[dict] = None

    # RH-B-002: assembly-level degradation. AssemblyResult already carried
    # these, and grep confirmed NO caller read any of them: when the
    # chapter-marker mux failed, assemble_m4b copied the chapterless AAC to
    # the .m4b and the renderer logged a WARNING — then handed back a summary
    # that looked exactly like a finished book. An audiobook with no chapter
    # navigation is retail-blocking for the format, and un-applied loudness
    # mastering disqualifies an ACX submission, so both now travel with the
    # summary (which reaches the CLI via RenderedOutputPath.render_summary).
    #
    # Defaults describe a NON-degraded render so a summary built by hand (or
    # by an older caller) never reads as broken.
    chapters_embedded: bool = True
    chapter_error: str = ""
    mastering_applied: bool = True
    mastering_error: str = ""

    @property
    def is_complete(self) -> bool:
        """True when every chapter made it into the assembled output.

        Deliberately still about CHAPTER COMPLETENESS only. The CLI's
        partial-render message is written in terms of dropped/failed chapter
        indices, so folding assembly degradation in here would print "some
        chapters are missing from the output" for a book that has every
        chapter but no chapter markers. Use ``is_retail_ready`` for the
        "can I sell this file" question.
        """
        return not self.failed and not self.missing_chapters

    @property
    def is_retail_ready(self) -> bool:
        """True when the output is complete AND undegraded.

        False when any chapter is missing, when chapter navigation could not
        be embedded, or when requested loudness mastering did not actually
        reach the shipped audio.
        """
        return (
            self.is_complete
            and self.chapters_embedded
            and self.mastering_applied
        )

    @property
    def degradations(self) -> list[str]:
        """Human-readable list of everything degraded about this render."""
        notes: list[str] = []
        if self.missing_chapters:
            human = ", ".join(str(i + 1) for i in self.missing_chapters)
            notes.append(f"{len(self.missing_chapters)} chapter(s) missing ({human})")
        if not self.chapters_embedded:
            detail = f": {self.chapter_error}" if self.chapter_error else ""
            notes.append(f"chapter navigation was NOT embedded{detail}")
        if not self.mastering_applied:
            detail = f": {self.mastering_error}" if self.mastering_error else ""
            notes.append(f"loudness mastering was NOT applied{detail}")
        return notes


class RenderedOutputPath(type(Path())):  # type: ignore[misc]
    """A Path that also carries the RenderSummary for the render that made it.

    ``render_project`` built a full RenderSummary and then threw it away,
    returning only the output path — the summary was reachable ONLY via
    RenderError, i.e. only when the render failed outright. Under
    ``allow_partial`` a short book therefore looked byte-identical to a
    complete one at the call site, and the CLI recorded status "success".

    Subclassing Path (rather than changing the return type) keeps every
    existing caller working: it compares equal to the plain Path, passes
    isinstance checks, and supports the whole Path API.
    """

    __slots__ = ("render_summary",)


def _attach_summary(path: Path, summary: "RenderSummary") -> Path:
    """Return ``path`` carrying ``summary``, degrading to a plain Path."""
    try:
        enriched = RenderedOutputPath(path)
        enriched.render_summary = summary
        return enriched
    except Exception:  # pragma: no cover - never fail a render over metadata
        logger.debug("RENDER_SUMMARY_ATTACH_FAILED: returning a plain Path")
        return path


# ---------------------------------------------------------------------------
# Project rendering (with persistent cache + resume)
# ---------------------------------------------------------------------------

def _render_project_impl(
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
    validate_voices: bool = True,
    utterance_cache: Optional[bool] = None,
    stitch_runner: Optional[Callable] = None,
    **kwargs,
) -> "RenderSummary":
    """
    Render all chapters and assemble final audiobook.

    Shared implementation behind ``render_project`` (returns the output path)
    and ``render_project_detailed`` (returns this RenderSummary).

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
        validate_voices: If True (the default), check every cast voice ID
            against the active catalog before rendering anything. Callers that
            already ran the gate pass False (``Project.render`` does) so the
            registry is not queried twice. NOT the same knob as ``force``,
            which only bypasses casting *completeness*.
        utterance_cache: FEAT-PROD-009 / FT-RENDER-P-004 — synthesize one
            utterance at a time and sub-cache each one, so editing a single
            line of dialogue in chapter 30 re-synthesizes that line instead of
            3,000 words. ``None`` (the default) reads
            ``project.config.utterance_cache``, which is the documented opt-in
            and defaults to False; pass True/False to override it for one
            render. Before this wave nothing read the flag and nothing called
            ``render_chapter_incremental`` — the feature was complete, tested,
            listed in CHANGELOG 2.1.0 and advertised in the README, and
            unreachable.
        stitch_runner: Injected FFmpegRunner-like holder used for the
            utterance concat step when ``utterance_cache`` is on. Tests pass a
            fake; None uses the real ffmpeg.

    Returns:
        RenderSummary with the output path and per-chapter accounting.

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
        assemble_wav as _wav_assembler,
    )
    from audiobooker.renderer.cache_manifest import (
        CacheManifest, ChapterCacheEntry, MANIFEST_VERSION,
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

    # Wave-3 residual 2: voice-ID gate. This lives HERE, not only in
    # Project.render(), because cli.py bypasses Project.render() entirely for
    # --cover/--normalize/--profile/--bitrate/--split/--engine (its
    # `needs_direct` branch) and for batch/make's _process_book — i.e. the gate
    # used to be skipped on exactly the longest, most elaborate renders, and a
    # typo'd voice surfaced hours in instead of immediately. Deliberately
    # above the ffmpeg preflight and below casting completeness: both are
    # cheap, local checks that should fail before a multi-hour synthesis.
    if validate_voices:
        _validate_project_voices(project, engine=engine)

    # FT-RENDER-003 / FT-RENDER-M-006 / FT-RENDER-M-007: Select assembler by
    # format. 'split' on an AAC format emits per-chapter .m4a files.
    fmt = output_format or project.config.output_format
    _by_name = {
        "assemble_m4b": _m4b_assembler,
        "assemble_mp3": _mp3_assembler,
        "assemble_opus": _opus_assembler,
        "assemble_flac": _flac_assembler,
        "assemble_wav": _wav_assembler,
        "assemble_m4a_split": _m4a_split_assembler,
    }
    _builtin_assemblers = tuple(_by_name.values())
    if assembler is None:
        if split and fmt in ("m4b", "m4a"):
            assembler = _m4a_split_assembler
        else:
            # F-7a3c91e2: a table lookup, not an if/elif chain ending in
            # `else: _m4b_assembler`. That fallthrough is what made
            # `--format wav` write AAC-in-MP4 bytes to a .wav path, and it
            # would silently do the same for any format added to an allowlist
            # without a branch here. An unknown format is now an error that
            # names the format and lists the real ones.
            try:
                assembler = _by_name[audio_formats.get(fmt).assembler]
            except KeyError:
                raise RenderError(
                    f"Unknown output format {fmt!r}. Valid formats: "
                    f"{', '.join(sorted(audio_formats.ALL_FORMAT_NAMES))}.",
                    code="CONFIG_INVALID_FORMAT",
                ) from None

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

    # FEAT-PROD-004: the destination gate. Placed with the other cheap,
    # local preflights and BEFORE the lockfile and the render loop, for the
    # same reason they are: a book costs hours and (against a paid TTS API)
    # money, and "where does this go" is answerable in microseconds.
    _preflight_output_destination(output_path, split=split)

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

    # FEAT-PROD-009: resolve the utterance-cache opt-in BEFORE the params
    # hash, because the hash keys it — the two synthesis strategies do not
    # produce the same waveform, so toggling the flag must miss.
    if utterance_cache is None:
        utterance_cache = bool(getattr(project.config, "utterance_cache", False))
    effective_config = project.config
    if utterance_cache != bool(getattr(project.config, "utterance_cache", False)):
        # An explicit kwarg override must reach the hash too, without
        # mutating the caller's config object.
        effective_config = replace(project.config, utterance_cache=utterance_cache)

    if engine is None:
        # Hash and synthesize must share one engine. get_default_engine()
        # without a name ignores config.tts_engine (env/default only), so a
        # None-engine render stored WAVs under a piper digest then later
        # CLI piper renders HIT the soundboard audio (F-9f81fbf2).
        engine = get_default_engine(getattr(effective_config, "tts_engine", None))

    # Compute current hashes. The engine and the effective output profile are
    # part of the render-params key — rendering the same text with a different
    # TTS engine or a different mastering profile must not hit the cache.
    #
    # FEAT-OUT-001: the casting digest is computed PER CHAPTER (see
    # _chapter_casting_hash below), scoped to the speakers that chapter
    # actually contains. There is deliberately no whole-table value cached
    # here any more: keeping one invites exactly the bug this fixes — a
    # later edit reaching for the convenient module-level name and writing a
    # book-wide digest into a per-chapter cache entry.
    current_params_hash = render_params_hash(
        effective_config, engine=engine, output_profile=output_profile
    )

    def _chapter_casting_hash(chapter: "Chapter") -> str:
        """Per-chapter casting digest (FEAT-OUT-001).

        Recasting one character used to re-render the whole book: measured on
        a two-chapter book where Bob speaks in one, changing only Bob's voice
        re-synthesized both. Scoping the digest to the chapter's own speakers
        (plus the narrator and fallback, which any uncast speaker resolves
        through) makes that one chapter.
        """
        return casting_hash(project.casting, chapter=chapter)

    # RH-B-003: --jobs N used to call synthesize() on ONE shared engine
    # instance from N pool workers with no thread-safety contract anywhere.
    # Serialize synthesize() unless the engine explicitly advertises
    # thread_safe=True. Done AFTER the params hash above on purpose: the hash
    # keys an injected engine by class identity, so wrapping first would
    # invalidate the whole chapter cache for any --jobs render.
    #
    # When `engine is None` each render_chapter() call builds its own default
    # engine, so there is nothing shared to protect.
    render_engine = engine
    if jobs > 1 and engine is not None and not engine_is_thread_safe(engine):
        logger.warning(
            f"RENDER_ENGINE_NOT_THREAD_SAFE: --jobs {jobs} was requested but "
            f"{type(engine).__name__} does not advertise "
            f"capabilities()['thread_safe'] == True. Calls to synthesize() "
            f"will be serialized behind a lock — chapter rendering will run "
            f"at single-thread speed. A stateful engine entered concurrently "
            f"produces interleaved or cross-voiced audio that passes every "
            f"size and duration check, so this is not a risk worth taking "
            f"silently. Engines that are genuinely safe should return "
            f"{{'thread_safe': True}} from capabilities()."
        )
        render_engine = _SerializedEngine(engine)

    # FT-CAST-026: the emphasis preset the chapters actually render with. This
    # was declared on ProjectConfig and accepted by render_chapter but threaded
    # by no caller, so every non-neutral preset was dead code.
    emotion_preset = getattr(project.config, "emotion_preset", "neutral")

    # Load or create manifest
    manifest = load_manifest(manifest_path) if resume else None
    if manifest is None:
        manifest = CacheManifest(book_title=project.title)
    elif manifest.version < MANIFEST_VERSION:
        # A pre-v3 manifest still LOADS (load_manifest only refuses FUTURE
        # versions) and every one of its entries misses on the new hashes, so
        # the cache self-heals. But entries written from here on are v3-keyed,
        # and leaving the file stamped v2 would advertise a schema it no
        # longer holds — the "an older audiobooker refuses a manifest it
        # cannot reproduce" guarantee only works if the stamp is honest.
        logger.info(
            f"RENDER_CACHE_UPGRADE: manifest v{manifest.version} -> "
            f"v{MANIFEST_VERSION}; entries keyed under the old schema "
            f"re-render once."
        )
        manifest.version = MANIFEST_VERSION

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
        # FEAT-PROD-012: two different numbers, and they are only equal
        # when the whole book is being rendered.
        #
        #   i             -- position in THIS run. `--chapters 1-2,4` hands
        #                    us a filtered project.chapters, so i runs
        #                    0,1,2 over three chapters of a four-chapter
        #                    book. It belongs to the progress bar and the
        #                    "[n/total]" display, which are about the run.
        #   chapter.index -- which chapter this IS, in the book. It belongs
        #                    to anything that identifies the chapter across
        #                    runs: the manifest key, the cache WAV
        #                    filename, the cache entry, the failure report,
        #                    and any log line that names a chapter.
        #
        # Using the position for identity meant `--chapters 4` wrote
        # chapter 4's audio to chapter_0000.wav -- chapter 1's cached file
        # -- and recorded it at manifest key 0. The hash check in
        # is_valid() kept that from ever being served AS chapter 1, so it
        # was never wrong audio; it destroyed the cache and re-charged the
        # user for TTS instead, on exactly the long books where anyone
        # reaches for a selection.
        #
        # The utterance-level cache in this same module already keyed off
        # chapter.index (get_utterance_wav_dir), so the two caches
        # disagreed with each other under a selection.
        chapters_to_render = []  # (position, chapter, hashes)
        for i, chapter in enumerate(project.chapters):
            # --from-chapter N is documented as a chapter number, so it is
            # compared against the chapter, not against our position in a
            # possibly-filtered list.
            if from_chapter is not None and chapter.index < from_chapter:
                if progress_callback:
                    progress_callback(i + 1, len(project.chapters), f"Skipping: {chapter.title}")
                continue

            current_text_hash = chapter_text_hash(chapter)
            chapter_casting_hash = _chapter_casting_hash(chapter)

            # Check cache
            if resume:
                existing = manifest.get_entry(chapter.index)
                if existing and existing.is_valid(current_text_hash, chapter_casting_hash, current_params_hash):
                    chapter.audio_path = Path(existing.wav_path)
                    chapter.duration_seconds = existing.duration_s
                    tracker.mark_cached(i, chapter.title, existing.duration_s)
                    logger.info(
                        f"RENDER_CACHE_HIT: chapter={chapter.index} "
                        f"title={chapter.title!r}"
                    )
                    summary.skipped_cached += 1

                    if progress_callback:
                        status = tracker.format_chapter_status(i, f"Cached: {chapter.title}")
                        progress_callback(i + 1, len(project.chapters), status)
                    continue

            chapters_to_render.append(
                (i, chapter, current_text_hash, chapter_casting_hash)
            )

        # ---- Phase 2: Render chapters (sequential or parallel) ----

        def _render_one_chapter(
            i: int, chapter: "Chapter", text_hash: str, chapter_casting_hash: str
        ) -> None:
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

            # Identity, not position -- see the note in phase 1.
            target_path = get_chapter_wav_path(cache_root, chapter.index)
            tmp_path = _chapter_tmp_path(target_path)

            start = time.time()
            try:
                if utterance_cache:
                    # FEAT-PROD-009: the opt-in utterance-level path. It keeps
                    # its own namespaced manifest (render_v2_utterance.json)
                    # per chapter, so the chapter cache below is written
                    # exactly as it always was and a project that turns the
                    # flag back off resumes from it unchanged.
                    inc = render_chapter_incremental(
                        chapter, project.casting, tmp_path,
                        engine=render_engine,
                        cache_root=cache_root,
                        render_params_hash=current_params_hash,
                        runner=stitch_runner,
                        emotion_preset=emotion_preset,
                    )
                    logger.info(
                        f"RENDER_UTTERANCE_CACHE: chapter={chapter.index} "
                        f"synthesized={inc.utterances_synthesized} "
                        f"reused={inc.utterances_reused}/{inc.utterances_total}"
                    )
                else:
                    render_chapter(
                        chapter, project.casting, tmp_path,
                        engine=render_engine, emotion_preset=emotion_preset,
                    )

                try:
                    os.replace(str(tmp_path), str(target_path))
                except OSError:
                    shutil.move(str(tmp_path), str(target_path))

                file_size = target_path.stat().st_size
                if file_size < 1024:
                    target_path.unlink(missing_ok=True)
                    raise RenderError(
                        f"Chapter {chapter.index} audio file is empty "
                        f"({file_size} bytes) - TTS may have failed or the "
                        "disk may be full"
                    )

                chapter.audio_path = target_path

                elapsed = time.time() - start
                tracker.finish_chapter(i, render_elapsed_s=elapsed)

                entry = ChapterCacheEntry(
                    chapter_index=chapter.index,
                    text_hash=text_hash,
                    casting_hash=chapter_casting_hash,
                    render_params_hash=current_params_hash,
                    wav_path=str(target_path),
                    duration_s=chapter.duration_seconds,
                    status="ok",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    # Record the size so a later truncation (disk full, power
                    # cut, half-copied file) is detectable on resume.
                    size_bytes=file_size,
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
                    f"RENDER_OK: chapter={chapter.index} title={chapter.title!r} "
                    f"elapsed={elapsed:.1f}s duration={chapter.duration_seconds:.1f}s"
                )

            except OSError as e:
                if e.errno in (28, 39, 112):
                    logger.error(
                        f"RENDER_DISK_FULL: chapter={chapter.index} - {e}"
                    )
                    # ENGINE-A-007: don't leave the partial .wav.tmp behind on a
                    # disk-full abort — it wastes the little space that remains.
                    tmp_path.unlink(missing_ok=True)
                    raise RenderError(
                        f"Disk full while rendering chapter {chapter.index} "
                        f"({chapter.title!r}). "
                        f"Free up space and re-run with: audiobooker render",
                        summary=summary,
                    ) from e
                _handle_chapter_failure(
                    i, chapter, e, text_hash,
                    tmp_path, tracker, manifest, manifest_path,
                    manifest_lock, failure_report, summary,
                    chapter_casting_hash, current_params_hash,
                    allow_partial,
                )

            except Exception as e:
                _handle_chapter_failure(
                    i, chapter, e, text_hash,
                    tmp_path, tracker, manifest, manifest_path,
                    manifest_lock, failure_report, summary,
                    chapter_casting_hash, current_params_hash,
                    allow_partial,
                )

        if jobs > 1 and len(chapters_to_render) > 1:
            # FT-RENDER-001: Parallel rendering
            logger.info(f"RENDER_PARALLEL: {jobs} workers for {len(chapters_to_render)} chapters")
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = {
                    pool.submit(_render_one_chapter, i, ch, th, chash): i
                    for i, ch, th, chash in chapters_to_render
                }
                try:
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
                except BaseException:
                    # FEAT-PROD-001. KeyboardInterrupt and SystemExit are
                    # BaseException, so neither clause above could see them —
                    # a Ctrl-C fell straight through to this pool's implicit
                    # shutdown(wait=True), which drains the ENTIRE queue
                    # before the interrupt reaches the caller. Measured on a
                    # 24-chapter run at --jobs 4: eight more chapters were
                    # synthesized after the interrupt. Against a paid TTS API
                    # that is money spent after the user said stop.
                    #
                    # Cancelling only affects QUEUED work. The `jobs` chapters
                    # already in flight cannot be stopped without engine
                    # cooperation, and waiting for them is correct — it is
                    # what leaves the cache consistent for the resume.
                    for f in futures:
                        f.cancel()
                    raise
        else:
            # Sequential rendering (default)
            for i, chapter, text_hash, chapter_chash in chapters_to_render:
                _render_one_chapter(i, chapter, text_hash, chapter_chash)

        # Verify all chapters are ready for assembly
        ok_paths = []
        missing_indices: list[int] = []
        for i, chapter in enumerate(project.chapters):
            if chapter.audio_path and chapter.audio_path.exists():
                ok_paths.append((chapter.audio_path, chapter.title, chapter.duration_seconds))
            elif not allow_partial:
                raise RenderError(
                    f"Chapter {chapter.index} ({chapter.title!r}) has no "
                    "audio - cannot assemble. Use --allow-partial or fix "
                    "and --resume.",
                    summary=summary,
                )
            else:
                # FEAT-PROD-012: chapter.index, not the loop position. The
                # CLI prints this list back to the user as the chapters
                # that are missing from their audiobook, so under
                # `--chapters` a position would name chapters that are
                # fine and stay silent about the ones that are not.
                missing_indices.append(chapter.index)

        if not ok_paths:
            raise RenderError("No chapters rendered successfully.", summary=summary)

        # A partial book is assembled and returned exactly like a complete one.
        # Say so, loudly and by chapter number, or the user ships a 29-of-30
        # chapter audiobook believing it finished.
        if missing_indices:
            summary.missing_chapters = list(missing_indices)
            human = ", ".join(str(i + 1) for i in missing_indices)
            logger.warning(
                f"RENDER_PARTIAL: assembling WITHOUT {len(missing_indices)} of "
                f"{len(project.chapters)} chapters (chapter numbers: {human}; "
                f"indices: {missing_indices}). --allow-partial suppressed the "
                f"failure — the output is INCOMPLETE. Fix the failures and "
                f"re-run with --resume to fill the gaps."
            )
            if progress_callback:
                progress_callback(
                    len(project.chapters), len(project.chapters),
                    f"WARNING: {len(missing_indices)} chapter(s) missing "
                    f"({human}) — output is incomplete.",
                )

        # Assembly
        if progress_callback:
            progress_callback(
                len(project.chapters), len(project.chapters), "Assembling audiobook..."
            )

        logger.info(f"RENDER_ASSEMBLE: chapters={len(ok_paths)} format={fmt}")

        # FT-RENDER-006 / FT-RENDER-M-*: Pass the rich assembler kwargs when the
        # assembler accepts them. Injected test assemblers only take the base
        # five positional kwargs.
        base_kwargs = dict(
            chapter_files=ok_paths,
            output_path=output_path,
            title=project.title,
            author=project.author,
            chapter_pause_ms=project.config.chapter_pause_ms,
        )

        # RH-B-001: bind optional kwargs by INSPECTING the signature, not by
        # calling and catching TypeError.
        #
        # The old loop built the optional kwargs in a fixed order, appended
        # `normalize` LAST, and on TypeError popped from the END until the
        # call type-checked. So `normalize` was always the first casualty —
        # and an assembler missing any one earlier kwarg lost every later one
        # too. `assemble_m4b` is the only assembler that used to accept
        # `normalize`, which meant `--normalize --format mp3|opus|flac` and
        # `--normalize --split` produced completely un-normalized audio with
        # no log line at any level. `--acx` forces normalization on, so an
        # "ACX retail master" in those formats shipped with none — and since
        # the kwarg never reached the assembler, AssemblyResult.
        # mastering_applied kept its True default and the
        # ACX_MASTER_NOT_APPLIED path could not fire.
        #
        # Signature binding makes an unsupported capability VISIBLE instead of
        # silently dropping it (see the normalize gap handling below).
        accepted = _assembler_accepted_kwargs(assembler)

        def _accepts(name: str) -> bool:
            # None => signature unreadable (e.g. a C callable); assume the
            # historical superset and let the call itself decide.
            return accepted is None or name in accepted

        optional_kwargs: dict = {}
        if _accepts("metadata"):
            optional_kwargs["metadata"] = getattr(project, "metadata", None)
        if _accepts("loudnorm_profile"):
            optional_kwargs["loudnorm_profile"] = output_profile
        # Bitrate kwarg name differs across assemblers: assemble_m4b takes
        # aac_bitrate, the others take bitrate. Pick whichever the assembler
        # actually accepts so the bitrate is never silently dropped.
        if accepted is not None and "aac_bitrate" in accepted:
            optional_kwargs["aac_bitrate"] = effective_bitrate
        elif _accepts("bitrate"):
            optional_kwargs["bitrate"] = effective_bitrate
        if cover_art and _accepts("cover_art"):
            optional_kwargs["cover_art"] = cover_art

        # The one capability we refuse to drop quietly. `accepted is None`
        # means the assembler declares **kwargs, so the signature cannot
        # prove support — the residual TypeError loop below re-opens this
        # flag if the kwarg is rejected at call time.
        normalize_supported = _accepts("normalize")
        if effective_normalize and normalize_supported:
            optional_kwargs["normalize"] = effective_normalize

        def _call_assembler():
            """Call the assembler with the kwargs its signature declares.

            F-e29a147c: the drop-and-retry loop below runs ONLY when the
            signature could not be read -- `accepted is None`, meaning a C
            callable or a `**kwargs` wrapper whose real shape is hidden. When
            the signature IS readable, every kwarg in `attempt` is one the
            assembler declares, so a binding TypeError is impossible by
            construction and any TypeError came from the assembler's own BODY.

            Retrying there is how this shipped a book with no metadata: an
            unrelated internal `TypeError` was read as "kwarg unsupported",
            four kwargs were stripped one at a time, and the render returned
            SUCCESS -- while logging a reason the signature disproves ("the
            m4b assembler does not accept 'normalize'" about an assembler
            that declares it). A wrong cause is worse than no cause; it sends
            the next reader to audit a signature that was never the problem.
            """
            nonlocal normalize_supported
            attempt = dict(base_kwargs, **optional_kwargs)
            if accepted is not None:
                # Signature-checked. Let a real error be a real error.
                return assembler(**attempt)
            droppable = list(optional_kwargs.keys())
            while True:
                try:
                    return assembler(**attempt)
                except TypeError:
                    if not droppable:
                        raise
                    drop = droppable.pop()
                    if drop in attempt:
                        logger.warning(
                            f"RENDER_ASSEMBLER_KWARG_DROPPED: {drop!r} was "
                            f"rejected by the {fmt} assembler and has been "
                            f"dropped."
                        )
                        if drop == "normalize":
                            normalize_supported = False
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

        # RH-B-002: carry the assembler's degradation flags onto the summary.
        # These existed on AssemblyResult and reached no caller.
        summary.chapters_embedded = bool(
            getattr(assembly, "chapters_embedded", True)
        )
        summary.chapter_error = str(getattr(assembly, "chapter_error", "") or "")
        summary.mastering_applied = bool(
            getattr(assembly, "mastering_applied", True)
        )
        summary.mastering_error = str(getattr(assembly, "mastering_error", "") or "")

        # RH-B-001: the assembler could not honour a requested normalization.
        # Never let that read as a success — the AssemblyResult default would
        # otherwise say mastering_applied=True for audio nothing normalized.
        if effective_normalize and not normalize_supported:
            summary.mastering_applied = False
            summary.mastering_error = (
                f"the {fmt} assembler "
                f"({getattr(assembler, '__name__', type(assembler).__name__)}) "
                f"does not accept 'normalize'"
            )
            logger.error(
                f"RENDER_MASTERING_UNSUPPORTED: loudness normalization was "
                f"requested (profile={output_profile}) but the selected {fmt} "
                f"assembler cannot apply it — {summary.mastering_error}. The "
                f"output is NOT loudness-normalized"
                + (
                    " and cannot meet the ACX retail spec."
                    if output_profile == "acx"
                    else "."
                )
            )

        total_duration = sum(dur for _, _, dur in ok_paths)

        # FT-RENDER-016: Post-render validation via ffprobe.
        # The expectation must come from the FULL chapter list, not from the
        # chapters that survived: summing ok_paths compares the short book
        # against itself, so the ratio is 1.0 by construction and a dropped
        # chapter can never be detected. Chapters with no audio contribute
        # their estimated duration so the shortfall actually shows up.
        expected_duration = sum(
            (ch.duration_seconds or _estimate_chapter_duration(ch))
            for ch in project.chapters
        )
        _post_render_validate(assembly.output_path, expected_duration)

        # FT-ACX-001: an 'acx' render is a RETAIL master. Verify it instead of
        # asserting it: master_check() existed but was wired only to the
        # standalone CLI command, so nothing on the render path ever measured
        # the file it had just produced.
        if output_profile == "acx":
            _verify_acx_master(assembly, summary, measure=assembler in _builtin_assemblers)

        if not summary.chapters_embedded:
            logger.warning(
                f"RENDER_COMPLETE_NO_CHAPTERS: output={assembly.output_path} "
                f"duration={total_duration:.1f}s reason={summary.chapter_error!r}"
            )
        else:
            logger.info(f"RENDER_COMPLETE: output={assembly.output_path} duration={total_duration:.1f}s")

        # RH-B-002: a stderr WARNING scrolls away, and no caller read the
        # AssemblyResult flags. Push one non-fatal line per degradation
        # through the renderer's own progress channel so a terminal-only
        # session still sees that the book shipped degraded.
        if progress_callback:
            for note in summary.degradations:
                if note.startswith("chapter navigation") or note.startswith(
                    "loudness mastering"
                ):
                    progress_callback(
                        len(project.chapters), len(project.chapters),
                        f"WARNING: {note} — the output is not retail-ready.",
                    )

        # Save failure report if any chapters failed
        if failure_report.failed_chapters:
            failure_report.rendered_ok = summary.rendered
            failure_report.cached_ok = summary.skipped_cached
            failure_report.save()

        _log_summary(summary)
        return summary

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


def render_project_detailed(
    project: "AudiobookProject",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    **kwargs,
) -> "RenderSummary":
    """Render a project and return the full RenderSummary.

    Prefer this over ``render_project`` whenever the caller needs to know
    whether the book is COMPLETE. ``summary.failed`` /
    ``summary.missing_chapters`` / ``summary.is_complete`` distinguish a
    partial render (assembled from fewer chapters than the project has,
    because ``allow_partial`` suppressed a failure) from a finished one.
    """
    return _render_project_impl(project, output_path, progress_callback, **kwargs)


def render_project(
    project: "AudiobookProject",
    output_path: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    **kwargs,
) -> Path:
    """Render all chapters and assemble the final audiobook.

    Returns the output path. The path also carries the render's
    ``render_summary`` (see ``RenderedOutputPath``), so a caller can tell a
    partial render from a complete one without changing its call shape::

        path = render_project(project, out, allow_partial=True)
        summary = getattr(path, "render_summary", None)
        if summary and not summary.is_complete:
            ...  # do NOT report this render as a success

    ``render_project_detailed`` returns that summary directly.

    See ``_render_project_impl`` for the full argument reference.
    """
    summary = _render_project_impl(project, output_path, progress_callback, **kwargs)
    return _attach_summary(summary.output_path, summary)


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
        from_chapter: Chapter identity (``chapter.index``, 0-based) to sample
            from — not a list subscript. Matches ``render_project`` /
            ``--from-chapter``.
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
    # F-813e9865: from_chapter is chapter.index, not a list subscript.
    # On a filtered/gapped list, project.chapters[from_chapter] would pick
    # the wrong chapter (or IndexError) and then write chapter_0000.wav.
    chapter = next(
        (c for c in project.chapters if getattr(c, "index", None) == from_chapter),
        None,
    )
    if chapter is None:
        available = [getattr(c, "index", i) for i, c in enumerate(project.chapters)]
        raise RenderError(
            f"Sample chapter index {from_chapter} not found "
            f"(available: {available}).",
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

    # Resolve cache root for cache reuse.
    if cache_root is None:
        project_dir = _resolve_project_dir(project)
        cache_root = get_cache_root(project_dir)

    # --- Locate the chapter WAV: reuse cache when valid, else render fresh ---
    # Identity is chapter.index (FEAT-PROD-012), never the list position.
    chapter_index = chapter.index
    chapter_wav: Optional[Path] = None
    cached_path = get_chapter_wav_path(cache_root, chapter_index)
    manifest_path = get_manifest_path(cache_root)
    manifest = load_manifest(manifest_path)
    if manifest is not None:
        entry = manifest.get_entry(chapter_index)
        if entry is not None:
            try:
                valid = entry.is_valid(
                    chapter_text_hash(chapter),
                    # FEAT-OUT-001: the render wrote this entry with a
                    # chapter-scoped casting digest, so the sample has to
                    # read it with one. Comparing against the whole-table
                    # hash rejected every entry the renderer had just
                    # written, and re-synthesized a chapter that was sitting
                    # in the cache.
                    casting_hash(project.casting, chapter=chapter),
                    render_params_hash(
                        project.config, engine=engine, output_profile=output_profile
                    ),
                )
            except Exception:
                valid = False
            if valid:
                chapter_wav = Path(entry.wav_path)
                logger.info(
                    f"SAMPLE_CACHE_HIT: chapter={chapter_index} reusing {chapter_wav}"
                )
            else:
                logger.info(
                    f"SAMPLE_CACHE_STALE: chapter={chapter_index} manifest entry "
                    f"failed validation — re-rendering instead of reusing "
                    f"{entry.wav_path!r}"
                )

    # Do not reuse a chapter WAV that has no size_bytes-backed manifest
    # entry. A kill mid-sample leaves a non-empty partial at cached_path;
    # st_size > 1024 used to serve that truncated file as the retail sample
    # (F-12572710). Miss and re-render instead.

    if chapter_wav is None:
        # Render the chapter fresh into the cache location.
        if not chapter.is_compiled:
            raise RenderError(
                f"Chapter {chapter_index} ({chapter.title!r}) is not compiled — "
                f"compile the project before sampling.",
                code="SAMPLE_NOT_COMPILED",
                retryable=False,
            )
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"SAMPLE_RENDER: rendering chapter {chapter_index} for sample")
        render_chapter(
            chapter, project.casting, cached_path,
            engine=engine,
            # FT-CAST-026: the sample must use the same emphasis preset the
            # book renders with, or the retail sample misrepresents the book.
            emotion_preset=getattr(project.config, "emotion_preset", "neutral"),
        )
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
        f"SAMPLE_COMPLETE: output={output_path} chapter={chapter_index} "
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
    """Handle a chapter render failure (shared between sequential and parallel paths).

    FEAT-PROD-012: ``i`` is this run's position and is only the tracker's
    display slot. Everything that says WHICH chapter failed -- the cache
    entry, the failure report, the summary list the CLI prints, the log
    line and the raised error -- uses ``chapter.index``, because under
    ``--chapters`` the two differ and a report naming the wrong chapter
    sends someone to debug one that rendered fine.
    """
    from audiobooker.renderer.cache_manifest import ChapterCacheEntry

    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)

    tracker.mark_failed(i, chapter.title)

    entry = ChapterCacheEntry(
        chapter_index=chapter.index,
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
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            error=error,
        )

        summary.failed += 1
        summary.failed_chapters.append({
            "index": chapter.index,
            "title": chapter.title,
            "error": str(error),
        })

    logger.error(
        f"RENDER_CHAPTER_FAIL: chapter={chapter.index} error={error}"
    )

    if not allow_partial:
        failure_report.rendered_ok = summary.rendered
        failure_report.cached_ok = summary.skipped_cached
        failure_report.save()

        raise RenderError(
            f"Chapter {chapter.index} ({chapter.title!r}) failed: {error}",
            summary=summary,
        ) from error


class RenderError(AudiobookerError, RuntimeError):
    """Rendering failed with recoverable context.

    Subclasses BOTH ``AudiobookerError`` (so ``code``/``hint``/``cause``/
    ``retryable``/``structured()`` come from the one canonical
    ``ErrorDetail``, and ``except AudiobookerError`` catches it) and
    ``RuntimeError`` (its historical base -- every existing
    ``except RuntimeError`` / ``except Exception`` call site keeps working
    unchanged).

    Wave-3 residual 5: SHIP_GATE.md's Gate B cites this class by name as
    evidence that the structured error shape ships, but it used to hand-roll
    the four attributes and its own ``structured()`` instead of belonging to
    the family. ``str(exc)`` is unchanged -- ``AudiobookerError.__init__``
    passes the same message to ``Exception.__init__`` -- so every assertion
    across the suite that reads the message still holds.
    """

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
        AudiobookerError.__init__(
            self,
            ErrorDetail(
                code=code,
                message=message,
                hint=hint,
                cause=cause,
                retryable=retryable,
            ),
        )
        self.summary = summary


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


def _verify_acx_master(assembly, summary: "RenderSummary", *, measure: bool = True) -> None:
    """Measure a finished 'acx' render against the ACX retail limits.

    Warns loudly rather than raising: the chapters are rendered and the file
    exists, so destroying a multi-hour render over a measurement is worse than
    telling the user exactly what to fix. The verdict is recorded on the
    summary so a caller can refuse to report the render as retail-ready.

    Args:
        assembly: The AssemblyResult just returned by the assembler.
        summary: The RenderSummary to record the verdict on.
        measure: Whether to actually run ``master_check`` on the output. False
            for an injected/custom assembler, whose output we do not own — the
            "was mastering even applied" verdict below is still recorded.
    """
    from audiobooker.renderer.output import master_check

    output = Path(getattr(assembly, "output_path", "") or "")

    # RH-B-001: this check MUST come before the is_file() guard. For mp3 and
    # --split the output is a DIRECTORY, so the guard returned first and the
    # "we shipped an ACX master with no loudness normalization" verdict was
    # unreachable for exactly the formats that could not normalize at all.
    mastering_applied = getattr(assembly, "mastering_applied", True)
    if not summary.mastering_applied:
        # The renderer already knows more than the assembler did (e.g. the
        # kwarg never reached it) — that verdict wins.
        mastering_applied = False
    if not mastering_applied:
        reason = (
            summary.mastering_error
            or getattr(assembly, "mastering_error", "")
            or "reason unknown"
        )
        summary.acx_check = {"passes": False, "failures": [reason]}
        summary.mastering_applied = False
        summary.mastering_error = reason
        logger.error(
            "ACX_MASTER_NOT_APPLIED: the ACX render shipped WITHOUT loudness "
            f"normalization — {reason}. It will not pass ACX review."
        )
        return

    if not measure:
        logger.info(
            "ACX_MASTER_CHECK: skipped — a custom assembler produced this "
            "output; mastering was reported as applied."
        )
        return

    if not output.is_file():
        # --split emits a directory of per-chapter files; there is no single
        # master to measure.
        logger.info(
            "ACX_MASTER_CHECK: skipped — output is not a single audio file "
            f"({output})"
        )
        return

    try:
        report = master_check(output, profile="acx")
    except Exception as e:  # pragma: no cover - measurement must never kill a render
        logger.warning(f"ACX_MASTER_CHECK_ERROR: could not measure output: {e}")
        return

    summary.acx_check = report
    if report.get("passes"):
        logger.info(
            f"ACX_MASTER_CHECK: PASS rms={report.get('measured_rms_db')} dB "
            f"peak={report.get('measured_peak_db')} dBTP "
            f"floor={report.get('measured_noise_floor_db')} dB"
        )
        return

    logger.warning(
        "ACX_MASTER_CHECK: the finished ACX master does NOT meet the "
        "measurable ACX limits: " + "; ".join(report.get("failures") or ["unknown"])
    )
    for note in report.get("warnings") or []:
        logger.warning(f"ACX_MASTER_CHECK: {note}")


def _estimate_chapter_duration(chapter: "Chapter", wpm: int = 150) -> float:
    """Rough spoken duration for a chapter that has no rendered audio.

    Used only to size the *expectation* in post-render validation, so that a
    chapter dropped by --allow-partial still shows up as a duration shortfall.
    """
    try:
        words = int(getattr(chapter, "word_count", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if words <= 0 or wpm <= 0:
        return 0.0
    return (words / float(wpm)) * 60.0


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
    *,
    engine: Optional[TTSEngine] = None,
    output_profile: str = "podcast",
) -> None:
    """
    FT-RENDER-004: Preview what would be rendered without actually rendering.

    Walks the cache-check loop and prints a summary table showing
    which chapters would be rendered vs cached, with estimates.

    Args:
        project: The project to preview.
        resume: Whether to consult the cache manifest (mirrors --resume).
        from_chapter: Start index (0-based); earlier chapters are "skipped".
        engine: The TTSEngine the real render would use. Part of the
            render-params cache key.
        output_profile: The mastering profile the real render would use
            ('podcast' or 'acx'). Also part of the cache key. Defaults to
            'podcast' to match ``_render_project_impl``'s own default.

    RH-B-004: this used to call ``render_params_hash(project.config)`` with
    NEITHER of those — a wave-2 change added them to the real render and did
    not update this sibling call site. The two functions therefore computed
    different keys for the same render, so ``render --acx --dry-run``
    reported every chapter already cached and the real ``--acx`` render then
    re-rendered the entire book. Any argument added to the real render's hash
    call MUST be added here in the same commit.
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

    # RH-B-004: same arguments as the real render, or the preview lies.
    # FEAT-OUT-001: which means the casting digest must be scoped per chapter
    # here too — a dry run that used the whole-table hash would predict a full
    # re-render after a single recast while the real render only touched the
    # chapters that character speaks in.
    current_params_hash = render_params_hash(
        project.config, engine=engine, output_profile=output_profile
    )

    manifest = load_manifest(manifest_path) if resume else None

    to_render = []
    cached = []
    skipped = []

    for i, chapter in enumerate(project.chapters):
        if from_chapter is not None and chapter.index < from_chapter:
            skipped.append((chapter.index, chapter.title, chapter.word_count))
            continue

        current_text_hash = chapter_text_hash(chapter)

        if resume and manifest:
            # FEAT-PROD-012: chapter.index, matching the real render.
            #
            # This line said `i` for one commit, with a comment arguing
            # that a preview must predict what the render actually does
            # even when that is wrong. The argument was sound and the
            # premise is now gone: the real render keys the manifest off
            # chapter.index, so this does too. They move together or the
            # preview lies — RH-B-004 above is the previous time these
            # two drifted, and it made `--acx --dry-run` report a fully
            # cached book that then re-rendered from scratch.
            existing = manifest.get_entry(chapter.index)
            if existing and existing.is_valid(
                current_text_hash,
                casting_hash(project.casting, chapter=chapter),
                current_params_hash,
            ):
                cached.append(
                    (chapter.index, chapter.title, chapter.word_count)
                )
                continue

        # chapter.index is the chapter's own place in the BOOK. Under a
        # selection the enumerate position is its place in the subset, so
        # printing `i` renumbered the survivors 0,1,2 and put "ch.3" beside
        # a chapter titled "Chapter 4".
        to_render.append((chapter.index, chapter.title, chapter.word_count))

    total_words_render = sum(wc for _, _, wc in to_render)
    wpm = project.config.estimated_wpm or 150

    print(f"\n{'='*60}")
    # ASCII: printed text, and a legacy Windows console (cp437/cp850,
    # what a bare cmd.exe runs) has no em-dash. See
    # tests/test_cli_output_is_console_safe.py.
    print(f"DRY RUN - {project.title}")
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
            # FEAT-UX-007: both numbering schemes. This table is the command
            # you run in order to decide what to pass NEXT, so a bare "[3]"
            # is the worst place in the CLI to leave the reader guessing
            # whether the follow-up is `-c 3` or `-c 4`.
            print(f"  {chapter_label(idx)} {title} ({wc:,} words)")
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
