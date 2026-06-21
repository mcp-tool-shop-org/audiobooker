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
        msg = (
            f"Voice IDs not found: {names}\n"
            f"  {available_count} voices available. "
            f"Run 'audiobooker voices' to list them.\n"
            f"  To skip validation, set validate_voices_on_render=false in project config."
        )
        super().__init__(msg)
        # Structured error shape (code/message/hint/cause/retryable)
        self.code = "INPUT_VOICE_NOT_FOUND"
        self.hint = "Run 'audiobooker voices' to list available IDs, or set validate_voices_on_render=false."
        self.cause = None
        self.retryable = False

    def structured(self) -> dict:
        """Return the canonical error shape as a dict."""
        return {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "retryable": self.retryable,
        }


def get_available_voices(engine: object | None = None) -> set[str]:
    """
    Query the active TTS engine (or voice-soundboard) for available voice IDs.

    FT-ENGINE-001: when ``engine`` exposes a ``list_voices()`` method, its
    result is used (a pluggable engine advertises its own catalog). Otherwise
    — including the default ``engine=None`` path and engines that don't
    implement ``list_voices()`` — this falls back to importing the
    voice-soundboard catalog, exactly as before.

    Args:
        engine: Optional TTS engine. When it has a ``list_voices()`` method,
            that method supplies the voice IDs. Defaults to None, which
            preserves the historical voice-soundboard import behavior.

    Returns:
        Set of available voice ID strings.

    Raises:
        ImportError: If no engine is given (or the engine lacks ``list_voices``)
            and voice-soundboard is not installed.
    """
    # FT-ENGINE-001: prefer an engine that advertises its own voices. Callers
    # must tolerate the method's absence, so probe with hasattr() rather than
    # assuming it exists on the Protocol.
    if engine is not None and hasattr(engine, "list_voices"):
        voices = engine.list_voices()
        # Engines return a list (voice_suggester protocol); normalize to a set
        # so downstream set algebra (validate_voices) keeps working unchanged.
        return set(voices)

    try:
        from voice_soundboard.config import VOICES
        return set(VOICES.keys())
    except ImportError:
        raise ImportError(
            "voice-soundboard is required for voice validation. "
            "Install with: pip install voice-soundboard"
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
        Returns empty list with warning if voice-soundboard is not installed.
    """
    if available is None:
        try:
            available = get_available_voices()
        except ImportError:
            logger.warning(
                "voice-soundboard not installed — skipping voice validation"
            )
            return []

    # Filter out empty/whitespace-only voice IDs and log affected characters
    empty_ids = {v for v in voice_ids if not v or not v.strip()}
    if empty_ids:
        logger.warning(
            "Filtered %d empty/whitespace voice IDs during validation", len(empty_ids),
        )
    voice_ids = {v for v in voice_ids if v and v.strip()}
    return sorted(voice_ids - available)
