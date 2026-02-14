"""
Voice registry — queries voice-soundboard for available voice IDs.

Provides a single abstraction point for voice availability checks,
making it easy to mock in tests.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("audiobooker.casting")


class VoiceNotFoundError(Exception):
    """Raised when one or more voice IDs are not available."""

    def __init__(
        self,
        missing: list[str],
        available_count: int,
    ) -> None:
        self.missing = missing
        self.available_count = available_count
        names = ", ".join(missing)
        super().__init__(
            f"Voice IDs not found: {names}\n"
            f"  {available_count} voices available. "
            f"Run 'audiobooker voices' to list them.\n"
            f"  To skip validation, set validate_voices_on_render=false in project config."
        )


def get_available_voices() -> set[str]:
    """
    Query voice-soundboard for available voice IDs.

    Returns:
        Set of available voice ID strings.

    Raises:
        ImportError: If voice-soundboard is not installed.
    """
    try:
        from voice_soundboard.config import VOICES
        return set(VOICES.keys())
    except ImportError:
        raise ImportError(
            "voice-soundboard is required for voice validation. "
            "Install with: pip install -e F:/AI/voice-soundboard"
        )


def validate_voices(
    voice_ids: set[str],
    available: set[str] | None = None,
) -> list[str]:
    """
    Check which voice IDs are missing from the available set.

    Args:
        voice_ids: Voice IDs to validate.
        available: Available voices (queries registry if None).

    Returns:
        List of missing voice IDs (empty if all valid).
    """
    if available is None:
        available = get_available_voices()
    return sorted(voice_ids - available)
