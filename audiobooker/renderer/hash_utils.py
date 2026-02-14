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
    from audiobooker.models import Chapter, CastingTable, ProjectConfig


def sha256_text(s: str) -> str:
    """SHA-256 of a UTF-8 string, returned as hex digest."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_json(obj: dict | list) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_text(canonical)


def chapter_text_hash(chapter: "Chapter") -> str:
    """Hash the text content that affects audio output."""
    return sha256_text(chapter.raw_text)


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
