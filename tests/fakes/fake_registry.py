"""Fake voice registry for testing voice suggestion logic.

Shared across test_voice_suggester.py and test_phase5_features.py
to eliminate duplication (F-TEST-B-008).
"""

from __future__ import annotations


DEFAULT_VOICES = [
    "af_heart", "af_jessica", "af_sky",
    "am_eric", "am_fenrir", "am_onyx",
    "bf_alice", "bf_emma",
    "bm_george", "bm_lewis",
]


class FakeRegistry:
    """Minimal voice registry that returns a fixed voice list."""

    def __init__(self, voice_list: list[str]):
        self._voices = voice_list

    def list_voices(self) -> list[str]:
        return self._voices


def make_fake_registry(voices: list[str] | None = None) -> FakeRegistry:
    """Create a FakeRegistry with the given or default voice list."""
    if voices is None:
        voices = list(DEFAULT_VOICES)
    registry = FakeRegistry(voices)
    # Verify return type matches protocol
    result = registry.list_voices()
    assert isinstance(result, list), f"list_voices() must return list, got {type(result)}"
    return registry
