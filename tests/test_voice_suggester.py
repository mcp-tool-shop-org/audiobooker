"""Tests for the voice suggestion engine.

Covers: basic suggestion ranking, gender inference, narrator preference,
diversity penalty, suggest_all, edge cases (empty registry).
"""

from __future__ import annotations


from audiobooker.casting.voice_suggester import (
    VoiceSuggester,
    _get_voice_info,
)
from tests.fakes.fake_registry import make_fake_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(voices=None):
    """Create a fake voice registry."""
    return make_fake_registry(voices)


# ---------------------------------------------------------------------------
# Basic ranking
# ---------------------------------------------------------------------------

class TestBasicRanking:
    """Tests for basic suggestion ranking."""

    def test_returns_max_suggestions(self):
        """suggest_for_speaker returns at most max_suggestions."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=3)
        result = suggester.suggest_for_speaker("Alice")
        assert len(result.suggestions) == 3

    def test_returns_fewer_when_registry_small(self):
        """Fewer voices than max_suggestions returns what's available."""
        reg = _make_registry(["af_heart", "am_eric"])
        suggester = VoiceSuggester(registry=reg, max_suggestions=5)
        result = suggester.suggest_for_speaker("Alice")
        assert len(result.suggestions) == 2

    def test_scores_normalized(self):
        """All scores are between 0.0 and 1.0."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=10)
        result = suggester.suggest_for_speaker("narrator", is_narrator=True)
        for s in result.suggestions:
            assert 0.0 <= s.score <= 1.0, f"Score {s.score} out of range for {s.voice_id}"

    def test_deterministic(self):
        """Same inputs produce same rankings."""
        reg = _make_registry()
        s1 = VoiceSuggester(registry=reg).suggest_for_speaker("Alice")
        s2 = VoiceSuggester(registry=reg).suggest_for_speaker("Alice")
        assert [s.voice_id for s in s1.suggestions] == [s.voice_id for s in s2.suggestions]

    def test_every_suggestion_has_reason(self):
        """Every suggestion includes a non-empty reason string."""
        reg = _make_registry()
        result = VoiceSuggester(registry=reg).suggest_for_speaker("Bob")
        for s in result.suggestions:
            assert isinstance(s.reason, str)
            assert len(s.reason) > 0


# ---------------------------------------------------------------------------
# Gender inference
# ---------------------------------------------------------------------------

class TestGenderInference:
    """Tests for gender-based voice suggestion."""

    def test_female_cues_prefer_female_voices(self):
        """Sample utterances with female pronouns prefer female voices."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=3)
        result = suggester.suggest_for_speaker(
            "Sarah",
            sample_utterances=["she whispered", "her eyes were wide", "the woman turned"],
        )
        # Top suggestion should be a female voice (af_ or bf_ prefix)
        assert result.top is not None
        assert result.top.voice_id.startswith(("af_", "bf_")), (
            f"Expected female voice for female cues, got {result.top.voice_id}"
        )

    def test_male_cues_prefer_male_voices(self):
        """Sample utterances with male pronouns prefer male voices."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=3)
        result = suggester.suggest_for_speaker(
            "Marcus",
            sample_utterances=["he shouted", "his fist clenched", "the man stood", "the lord spoke"],
        )
        assert result.top is not None
        assert result.top.voice_id.startswith(("am_", "bm_")), (
            f"Expected male voice for male cues, got {result.top.voice_id}"
        )


# ---------------------------------------------------------------------------
# Narrator preference
# ---------------------------------------------------------------------------

class TestNarratorPreference:
    """Tests for narrator voice preference."""

    def test_narrator_prefers_narrator_tag(self):
        """is_narrator=True prefers voices with 'narrator' tag."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=3)
        result = suggester.suggest_for_speaker("narrator", is_narrator=True)
        assert result.top is not None
        assert "narrator" in result.top.tags, (
            f"Top narrator suggestion should have 'narrator' tag, got {result.top.tags}"
        )

    def test_dialogue_speaker_prefers_dialogue_tag(self):
        """Non-narrator speakers may prefer 'dialogue' tagged voices."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=5)
        result = suggester.suggest_for_speaker("Alice", is_narrator=False)
        # At least one suggestion should have dialogue tag
        has_dialogue = any("dialogue" in s.tags for s in result.suggestions)
        assert has_dialogue, "Expected at least one dialogue-tagged voice in suggestions"


# ---------------------------------------------------------------------------
# Diversity penalty
# ---------------------------------------------------------------------------

class TestDiversityPenalty:
    """Tests for already-cast diversity penalty."""

    def test_already_cast_voice_penalized(self):
        """Already-cast voices are penalized and not top suggestion."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=5)
        result = suggester.suggest_for_speaker(
            "Alice",
            already_cast={"narrator": "af_heart"},
        )
        assert result.top is not None
        assert result.top.voice_id != "af_heart"

    def test_no_duplicates_in_suggest_all(self):
        """suggest_all avoids reusing top voice across speakers."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=1)
        results = suggester.suggest_all(["narrator", "Alice", "Bob"])
        top_voices = [r.top.voice_id for r in results if r.top]
        assert len(top_voices) == len(set(top_voices)), (
            f"Duplicate top voices found: {top_voices}"
        )


# ---------------------------------------------------------------------------
# suggest_all
# ---------------------------------------------------------------------------

class TestSuggestAll:
    """Tests for batch suggestion."""

    def test_suggest_all_returns_per_speaker(self):
        """suggest_all returns one SpeakerSuggestions per input speaker."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg)
        results = suggester.suggest_all(["narrator", "Alice", "Bob"])
        assert len(results) == 3
        assert results[0].speaker == "narrator"
        assert results[1].speaker == "Alice"
        assert results[2].speaker == "Bob"

    def test_suggest_all_with_utterances(self):
        """suggest_all uses speaker_utterances for gender inference."""
        reg = _make_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=1)
        results = suggester.suggest_all(
            ["Alice"],
            speaker_utterances={"Alice": ["she said softly", "her voice trembled"]},
        )
        assert len(results) == 1
        assert results[0].top is not None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_registry(self):
        """Empty registry returns empty suggestions."""
        reg = _make_registry([])
        suggester = VoiceSuggester(registry=reg)
        result = suggester.suggest_for_speaker("Alice")
        assert result.suggestions == []
        assert result.top is None

    def test_single_voice_registry(self):
        """Registry with one voice returns that voice."""
        reg = _make_registry(["af_heart"])
        suggester = VoiceSuggester(registry=reg, max_suggestions=3)
        result = suggester.suggest_for_speaker("Alice")
        assert len(result.suggestions) == 1
        assert result.top.voice_id == "af_heart"

    def test_voice_info_parsing(self):
        """_get_voice_info correctly parses voice ID prefixes."""
        info = _get_voice_info("af_heart")
        assert info.gender == "female"
        assert info.accent == "american"

        info = _get_voice_info("bm_george")
        assert info.gender == "male"
        assert info.accent == "british"

    def test_unknown_voice_prefix(self):
        """Unknown voice prefix returns 'unknown' gender."""
        info = _get_voice_info("zz_unknown_voice")
        assert info.gender == "unknown"
        assert info.accent == "unknown"
