"""
Stable hashing for render cache invalidation.

Only audio-affecting inputs go into hashes — cosmetic changes
(project title, author, timestamps) do not bust the cache.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

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


def render_params_hash(config: "ProjectConfig") -> str:
    """Hash config knobs that affect TTS output (not assembly-only settings)."""
    obj = {
        "sample_rate": config.sample_rate,
        "narrator_pause_ms": config.narrator_pause_ms,
        "dialogue_pause_ms": config.dialogue_pause_ms,
    }
    return sha256_json(obj)
