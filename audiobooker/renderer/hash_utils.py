"""
Stable hashing for render cache invalidation.

Only audio-affecting inputs go into hashes — cosmetic changes
(project title, author, timestamps) do not bust the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from audiobooker.models import Chapter, CastingTable, Character, ProjectConfig, Utterance


def sha256_text(s: str) -> str:
    """SHA-256 of a UTF-8 string, returned as hex digest."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_json(obj: dict | list) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_text(canonical)


def chapter_text_hash(chapter: "Chapter") -> str:
    """Hash the text content that affects audio output.

    F-RENDER-B-017: Includes compiled utterance data (speaker + text + emotion)
    when available, since those directly affect the rendered audio.
    Falls back to raw_text when chapter is not yet compiled.

    FEAT-PROD-003: ``intensity`` is keyed too. It was measurably missing: an
    utterance's graded intensity picks the SSML emphasis band in
    ``engine._emphasis_for`` (``<emphasis level="reduced">`` below 0.34,
    ``"moderate"`` below 0.67, the preset's full level above it), so two
    utterances differing only in intensity emit different SSML and therefore
    different audio — while hashing to the same digest. Grading an emotion on
    a finished book reported "Cached" for every chapter and shipped the
    ungraded audio. ``None`` is preserved distinctly from ``0.0`` (a bare
    emotion is not a zero-intensity one), matching ``utterance_hash``.
    """
    if chapter.utterances:
        # Hash the compiled utterance data — this is what actually gets rendered
        utterance_data = [
            {
                "speaker": u.speaker,
                "text": u.text,
                "emotion": u.emotion or "",
                "intensity": getattr(u, "intensity", None),
                # F-0da2d3a9: PAUSE/DIRECTION/FOOTNOTE vs speech with the same
                # speaker+text is a different waveform (tagged-line path emits
                # [PAUSE]/[SFX]; SSML emits <break> / skips). Leaving the type
                # out reported Cached after a review flipped a pause into
                # narration.
                "type": _utterance_type_value(u),
            }
            for u in chapter.utterances
        ]
        return sha256_json(utterance_data)
    return sha256_text(chapter.raw_text)


def _utterance_type_value(utterance: object) -> str:
    """Stable string for Utterance.utterance_type (enum or duck-typed)."""
    ut = getattr(utterance, "utterance_type", None)
    if ut is None:
        return ""
    return getattr(ut, "value", ut) or ""


def _delivery_knobs(character: Optional["Character"]) -> dict:
    """Audio-affecting per-speaker synthesizer knobs, with Character defaults.

    F-14251d01: utterances_to_script emits {speed}/{pitch}/{emphasis} whenever
    a CastingTable is passed, but utterance_hash previously keyed only
    speaker+text+emotion+intensity+voice+params. Retuning Character.speed
    therefore missed the CHAPTER cache (casting_hash includes these) and then
    HIT every utterance sub-cache, stitching the old-speed WAVs under the new
    casting_hash.
    """
    if character is None:
        return {"speed": 1.0, "pitch_shift": 0.0, "emphasis": 1.0}
    return {
        "speed": getattr(character, "speed", 1.0),
        "pitch_shift": getattr(character, "pitch_shift", 0.0),
        "emphasis": getattr(character, "emphasis", 1.0),
    }


def _character_for_speaker(
    casting: Optional["CastingTable"], speaker: str
) -> Optional["Character"]:
    """Resolve the Character whose delivery knobs reach the synthesizer."""
    if casting is None:
        return None
    key = casting.normalize_key(speaker)
    if key in casting.characters:
        return casting.characters[key]
    return casting.resolve_alias(speaker)


def utterance_hash(
    utterance: "Utterance",
    voice: str,
    render_params_hash: str,
    casting: Optional["CastingTable"] = None,
    *,
    speed: Optional[float] = None,
    pitch_shift: Optional[float] = None,
    emphasis: Optional[float] = None,
) -> str:
    """FT-RENDER-P-004: per-utterance cache key.

    Combines everything that affects a single utterance's audio: its speaker,
    text, emotion + graded intensity, utterance type (PAUSE vs speech), the
    resolved voice ID, the per-speaker delivery knobs (speed / pitch_shift /
    emphasis), and the chapter's render-params hash. Two utterances that
    produce byte-identical audio hash to the same key; changing any
    audio-affecting field busts only that one utterance's sub-cache entry.

    Args:
        utterance: The utterance to key.
        voice: The resolved voice ID for this utterance's speaker.
        render_params_hash: The chapter's render_params_hash (ties the
            utterance cache to the same TTS knobs the chapter cache uses).
        casting: Optional CastingTable used to resolve per-speaker delivery
            knobs when they are not passed explicitly.
        speed / pitch_shift / emphasis: Explicit knobs; override the
            resolved Character when given.

    Returns:
        Hex SHA-256 digest uniquely identifying this utterance's audio.
    """
    knobs = _delivery_knobs(_character_for_speaker(casting, utterance.speaker))
    if speed is not None:
        knobs["speed"] = speed
    if pitch_shift is not None:
        knobs["pitch_shift"] = pitch_shift
    if emphasis is not None:
        knobs["emphasis"] = emphasis
    obj = {
        "speaker": utterance.speaker,
        "text": utterance.text,
        "emotion": utterance.emotion or "",
        # None intensity is preserved distinctly from 0.0 so a bare emotion and
        # a fully-graded one never collide.
        "intensity": getattr(utterance, "intensity", None),
        "type": _utterance_type_value(utterance),
        "voice": voice,
        "params": render_params_hash,
        "speed": knobs["speed"],
        "pitch_shift": knobs["pitch_shift"],
        "emphasis": knobs["emphasis"],
    }
    return sha256_json(obj)


def _character_cache_record(character) -> dict:
    """The audio-affecting fields of one casting entry.

    FEAT-PROD-003: ``speed``, ``pitch_shift`` and ``emphasis`` are keyed
    alongside voice+emotion. They are not decorative — ``utterances_to_script``
    emits them as ``{speed:1.4} {pitch:-0.3} {emphasis:1.7}`` hints whenever a
    casting table is passed, which is the script both the utterance-level
    incremental path and (as of this wave) the chapter path synthesize from.
    Leaving them out of the key meant retuning a character's delivery scored a
    cache HIT on every chapter and re-served the old performance.

    ``getattr`` defaults keep a legacy/duck-typed Character without these
    fields hashing exactly as it did before rather than raising mid-render.
    """
    return {
        "voice": character.voice,
        "emotion": character.emotion,
        "speed": getattr(character, "speed", 1.0),
        "pitch_shift": getattr(character, "pitch_shift", 0.0),
        "emphasis": getattr(character, "emphasis", 1.0),
    }


def _chapter_casting_keys(
    casting: "CastingTable", chapter: "Chapter"
) -> Optional[set[str]]:
    """Normalized casting keys a chapter's utterances actually resolve to.

    Returns None when the scope cannot be established (the chapter is not
    compiled, so there are no speakers to read), which the caller treats as
    "hash the whole table" — the historical, always-correct-but-coarse answer.

    Alias resolution matters here: a chapter whose speaker is an alias is
    served by the aliased Character, so that Character's entry — not a
    non-existent one under the alias — is what must be keyed.
    """
    utterances = getattr(chapter, "utterances", None)
    if not utterances:
        return None

    keys: set[str] = set()
    for utt in utterances:
        speaker = getattr(utt, "speaker", "") or ""
        key = casting.normalize_key(speaker)
        if key in casting.characters:
            keys.add(key)
            continue
        alias_char = casting.resolve_alias(speaker)
        if alias_char is not None:
            keys.add(casting.normalize_key(alias_char.name))
            continue
        # Uncast speaker: it falls back to the narrator (or the fallback
        # voice). Both of those are keyed unconditionally below, so there is
        # nothing chapter-specific left to add — but recording the raw key
        # keeps "this chapter contains an uncast speaker" in the digest, so
        # CASTING that speaker later is a miss rather than a silent hit.
        keys.add(key)
    return keys


def casting_hash(
    casting: "CastingTable", chapter: Optional["Chapter"] = None
) -> str:
    """Hash the voice assignments that affect a render's audio output.

    FEAT-OUT-001: pass ``chapter`` to scope the digest to the characters that
    chapter actually speaks. Without it this hashes the WHOLE casting table,
    so recasting one character invalidated every chapter in the book —
    measured on a two-chapter book where Bob appears in one: changing only
    Bob's voice re-synthesized both. On a 40-chapter book, fixing one
    side character's voice cost a full re-render.

    The narrator entry, the default-narrator name and ``fallback_voice_id``
    are always included: any speaker the chapter does not have a cast entry
    for resolves through one of them, so a change there can affect any
    chapter. ``unknown_character_behavior`` is included for the same reason —
    it decides WHICH of those fallbacks a missing speaker lands on.

    An uncompiled chapter (or ``chapter=None``) falls back to the whole
    table: coarse, but never wrong.
    """
    keys = _chapter_casting_keys(casting, chapter) if chapter is not None else None

    if keys is None:
        selected = dict(casting.characters)
    else:
        # Always-relevant entries: whatever an uncast speaker would resolve to.
        always = {
            casting.normalize_key(casting.default_narrator),
            casting.normalize_key("narrator"),
        }
        selected = {
            k: c for k, c in casting.characters.items() if k in keys or k in always
        }

    obj = {
        "characters": {
            k: _character_cache_record(c) for k, c in sorted(selected.items())
        },
        "fallback_voice_id": casting.fallback_voice_id,
    }
    if keys is not None:
        # Only present on the scoped digest, so an existing whole-table hash
        # is unchanged by the scoping machinery itself (it still changes from
        # the per-character fields above, which the manifest bump covers).
        obj["default_narrator"] = casting.normalize_key(casting.default_narrator)
        obj["unknown_character_behavior"] = casting.unknown_character_behavior
        obj["speakers"] = sorted(keys)
    return sha256_json(obj)


DEFAULT_ENGINE_NAME = "voice-soundboard"
ENGINE_ENV_VAR = "AUDIOBOOKER_ENGINE"
# Built-in wrapper class identity. Kept as a string pair so this module never
# imports engine.py (engine.py imports hash_utils).
_BUILTIN_ENGINE_IDENTITY = ("audiobooker.renderer.engine", "_VoiceSoundboardEngine")


def _canonical_engine_instance_name(engine: object) -> str:
    """Map an injected TTS engine instance to its cache-key name.

    F-568f1603: CLI ``render --dry-run`` hashes the engine NAME string;
    ``render --engine NAME`` hashes ``get_default_engine(name)`` (an
    instance). Without this, ``voice-soundboard`` and
    ``_VoiceSoundboardEngine()`` produced different render_params_hash
    values, so dry-run and the real render disagreed about Cached.

    Registered engines (entry-point name matches the class) hash as that
    name. Anonymous injected fakes keep ``{module}.{qualname}``.
    """
    cls = type(engine)
    module = getattr(cls, "__module__", "") or ""
    qualname = getattr(cls, "__qualname__", "") or cls.__name__
    if (module, qualname) == _BUILTIN_ENGINE_IDENTITY:
        return DEFAULT_ENGINE_NAME

    target = f"{module}:{qualname}"
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        if hasattr(eps, "select"):
            selected = eps.select(group="audiobooker.tts_engines")
        else:  # pragma: no cover - legacy dict API (3.10/3.11)
            selected = eps.get("audiobooker.tts_engines", [])
        for ep in selected:
            value = getattr(ep, "value", None)
            if value == target:
                return ep.name
            # Some EntryPoint objects expose module/attr instead of value.
            ep_mod = getattr(ep, "module", None)
            ep_attr = getattr(ep, "attr", None)
            if ep_mod and ep_attr and f"{ep_mod}:{ep_attr}" == target:
                return ep.name
    except Exception:  # pragma: no cover - metadata reads must never crash a hash
        pass
    return f"{module}.{qualname}"


def _engine_distribution_version(name: str) -> str:
    """Best-effort version of the distribution providing a TTS engine.

    Resolved from the ``audiobooker.tts_engines`` entry point's owning
    distribution when readable, else from a distribution named after the
    engine itself. Returns "unknown" when nothing can be read — never raises,
    because a missing version must degrade the cache key's precision, not
    break the render.
    """
    try:
        from importlib.metadata import entry_points, version
    except ImportError:  # pragma: no cover - always present on 3.10+
        return "unknown"

    dist_name: Optional[str] = None
    try:
        eps = entry_points()
        if hasattr(eps, "select"):
            selected = eps.select(group="audiobooker.tts_engines")
        else:  # pragma: no cover - legacy dict API (3.10/3.11)
            selected = eps.get("audiobooker.tts_engines", [])
        for ep in selected:
            if ep.name == name:
                dist = getattr(ep, "dist", None)
                dist_name = getattr(dist, "name", None) or getattr(dist, "version", None)
                if getattr(dist, "version", None):
                    return str(dist.version)
                break
    except Exception:  # pragma: no cover - metadata reads must never crash a render
        dist_name = None

    for candidate in (dist_name, name):
        if not candidate:
            continue
        try:
            return str(version(candidate))
        except Exception:
            continue
    return "unknown"


def _resolve_engine_name(config: "ProjectConfig", engine: object = None) -> str:
    """Resolve the name of the engine that will actually synthesize.

    Mirrors ``cli._resolve_engine`` + ``engine.get_default_engine``:

        injected engine instance > project config (when non-default)
        > AUDIOBOOKER_ENGINE > 'voice-soundboard'

    An injected instance is keyed by its registered entry-point / config name
    when one exists (the built-in wrapper hashes as ``voice-soundboard``, not
    ``audiobooker.renderer.engine._VoiceSoundboardEngine``). Class identity is
    the fallback for anonymous injected fakes that have no entry point.
    """
    if engine is not None:
        if isinstance(engine, str):
            return engine
        return _canonical_engine_instance_name(engine)

    cfg_name = getattr(config, "tts_engine", None)
    if cfg_name and cfg_name != DEFAULT_ENGINE_NAME:
        return str(cfg_name)

    env_name = os.environ.get(ENGINE_ENV_VAR)
    if env_name and env_name.strip():
        return env_name.strip()

    return cfg_name or DEFAULT_ENGINE_NAME


def engine_identity(config: "ProjectConfig", engine: object = None) -> dict[str, str]:
    """The (name, version) pair identifying the engine for cache purposes."""
    name = _resolve_engine_name(config, engine)
    return {"name": name, "version": _engine_distribution_version(name)}


def render_params_hash(
    config: "ProjectConfig",
    *,
    engine: object = None,
    output_profile: Optional[str] = None,
) -> str:
    """Hash config knobs that affect TTS output (not assembly-only settings).

    The TTS engine is part of this key. It is user-selectable three ways
    (``--engine``, ``AUDIOBOOKER_ENGINE``, ``ProjectConfig.tts_engine``) and is
    the single largest determinant of what the audio sounds like: leaving it
    out meant re-rendering with a different engine scored a cache HIT on every
    chapter and silently served the *previous* engine's audio. The engine's
    distribution version is keyed too, so a plugin upgrade that changes its
    voices invalidates rather than blends.

    ``output_profile`` is keyed for the same reason: 'acx' masters at a
    different sample rate and loudness than 'podcast', so switching profiles
    must not re-serve the other profile's audio.

    ``emotion_preset`` is keyed for exactly the same reason, and was missing.
    It is not cosmetic and it is not dead: ``_render_project_impl`` reads it
    off the config and hands it to ``render_chapter``, which hands it to
    ``preprocess_ssml``, which resolves the emphasis level through
    ``_EMOTION_EMPHASIS_PRESETS``. Measured: 'literary' pulls angry/excited/
    happy down from "strong" to "moderate" (5 of the 9 mapped emotions differ
    from 'neutral'), so the emitted SSML genuinely changes — yet all four
    presets returned a byte-identical digest. Switching preset on a finished
    book reported "Cached" for every chapter, changed nothing, and exited 0.

    Args:
        config: The project config.
        engine: Optional injected TTSEngine instance (or an engine name). When
            given it wins over the config/env name — it is what will actually
            render.
        output_profile: Effective mastering profile. Defaults to
            ``config.output_profile``; render_project passes its own kwarg,
            which may differ from the stored config value.
    """
    identity = engine_identity(config, engine)
    profile = output_profile if output_profile is not None else getattr(
        config, "output_profile", "podcast"
    )
    obj = {
        "sample_rate": config.sample_rate,
        "narrator_pause_ms": config.narrator_pause_ms,
        "dialogue_pause_ms": config.dialogue_pause_ms,
        "engine": identity["name"],
        "engine_version": identity["version"],
        "output_profile": profile,
        "emotion_preset": getattr(config, "emotion_preset", "neutral"),
        # FEAT-PROD-009: the utterance-level cache synthesizes one utterance
        # per engine call and concatenates the results, where the chapter path
        # makes a single whole-chapter call. Same text, same voices, but not
        # the same waveform (the chapter SSML's inter-speaker <break> has no
        # equivalent across a concat boundary). Toggling the flag must
        # therefore miss rather than re-serve the other path's audio.
        "utterance_cache": bool(getattr(config, "utterance_cache", False)),
    }
    return sha256_json(obj)
