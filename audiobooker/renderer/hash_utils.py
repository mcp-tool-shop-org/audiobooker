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
    from audiobooker.models import Chapter, CastingTable, ProjectConfig, Utterance


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
    """
    if chapter.utterances:
        # Hash the compiled utterance data — this is what actually gets rendered
        utterance_data = [
            {"speaker": u.speaker, "text": u.text, "emotion": u.emotion or ""}
            for u in chapter.utterances
        ]
        return sha256_json(utterance_data)
    return sha256_text(chapter.raw_text)


def utterance_hash(
    utterance: "Utterance",
    voice: str,
    render_params_hash: str,
) -> str:
    """FT-RENDER-P-004: per-utterance cache key.

    Combines everything that affects a single utterance's audio: its speaker,
    text, emotion + graded intensity, the resolved voice ID, and the chapter's
    render-params hash (sample rate / pauses). Two utterances that produce
    byte-identical audio hash to the same key; changing any audio-affecting
    field busts only that one utterance's sub-cache entry, leaving its
    neighbors reusable.

    Args:
        utterance: The utterance to key.
        voice: The resolved voice ID for this utterance's speaker.
        render_params_hash: The chapter's render_params_hash (ties the
            utterance cache to the same TTS knobs the chapter cache uses).

    Returns:
        Hex SHA-256 digest uniquely identifying this utterance's audio.
    """
    obj = {
        "speaker": utterance.speaker,
        "text": utterance.text,
        "emotion": utterance.emotion or "",
        # None intensity is preserved distinctly from 0.0 so a bare emotion and
        # a fully-graded one never collide.
        "intensity": getattr(utterance, "intensity", None),
        "voice": voice,
        "params": render_params_hash,
    }
    return sha256_json(obj)


def casting_hash(casting: "CastingTable") -> str:
    """Hash the voice assignments that affect audio output."""
    obj = {
        "characters": {
            k: {"voice": c.voice, "emotion": c.emotion}
            for k, c in sorted(casting.characters.items())
        },
        "fallback_voice_id": casting.fallback_voice_id,
    }
    return sha256_json(obj)


DEFAULT_ENGINE_NAME = "voice-soundboard"
ENGINE_ENV_VAR = "AUDIOBOOKER_ENGINE"


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

    An injected instance is keyed by its class identity: two different engine
    classes must never share a cache entry even when neither came from a name.
    """
    if engine is not None:
        if isinstance(engine, str):
            return engine
        cls = type(engine)
        return f"{cls.__module__}.{cls.__qualname__}"

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
    }
    return sha256_json(obj)
