"""Tests for voice registry.

Covers: validate_voices with valid/missing IDs, VoiceNotFoundError formatting,
behavior when voice-soundboard not installed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from audiobooker.casting.voice_registry import (
    get_available_voices,
    validate_voices,
    VoiceNotFoundError,
)


class TestValidateVoices:
    """Tests for validate_voices function."""

    def test_all_present(self):
        """validate_voices returns empty list when all voices exist."""
        available = {"af_heart", "bm_george", "af_bella"}
        missing = validate_voices({"af_heart", "bm_george"}, available)
        assert missing == []

    def test_some_missing(self):
        """validate_voices returns sorted list of missing voice IDs."""
        available = {"af_heart", "bm_george"}
        missing = validate_voices({"af_heart", "fake_voice", "zzz_voice"}, available)
        assert missing == ["fake_voice", "zzz_voice"]

    def test_all_missing(self):
        """All voices missing returns all sorted."""
        available = {"af_heart"}
        missing = validate_voices({"unknown_a", "unknown_b"}, available)
        assert missing == ["unknown_a", "unknown_b"]

    def test_empty_requested(self):
        """Empty requested set returns empty."""
        missing = validate_voices(set(), {"af_heart"})
        assert missing == []

    def test_empty_available(self):
        """Empty available set means all are missing."""
        missing = validate_voices({"af_heart"}, set())
        assert missing == ["af_heart"]


class TestVoiceNotFoundError:
    """Tests for VoiceNotFoundError."""

    def test_error_message_includes_missing(self):
        """Error message includes missing voice IDs."""
        err = VoiceNotFoundError(missing=["fake_voice"], available_count=20)
        msg = str(err)
        assert "fake_voice" in msg

    def test_error_message_includes_count(self):
        """Error message includes available count."""
        err = VoiceNotFoundError(missing=["x"], available_count=42)
        assert "42 voices available" in str(err)

    def test_error_message_includes_help(self):
        """Error message includes help text about listing voices."""
        err = VoiceNotFoundError(missing=["x"], available_count=10)
        assert "audiobooker voices" in str(err)

    def test_multiple_missing_formatted(self):
        """Multiple missing voices are comma-separated."""
        err = VoiceNotFoundError(missing=["voice_a", "voice_b"], available_count=5)
        msg = str(err)
        assert "voice_a" in msg
        assert "voice_b" in msg

    def test_error_attributes(self):
        """Error has missing and available_count attributes."""
        err = VoiceNotFoundError(missing=["a", "b"], available_count=10)
        assert err.missing == ["a", "b"]
        assert err.available_count == 10


class TestVoiceSoundboardNotInstalled:
    """Tests for behavior when voice-soundboard is not installed."""

    def test_get_available_voices_raises_import_error(self):
        """get_available_voices raises ImportError when voice-soundboard missing."""
        with patch.dict("sys.modules", {"voice_soundboard": None, "voice_soundboard.config": None}):
            with pytest.raises(ImportError, match="voice-soundboard"):
                get_available_voices()
