"""
Stage C HUMANIZATION regression tests — casting / NLP observability.

Covers three UX/observability fixes:

1. Low-confidence voice suggestions: VoiceSuggestion.low_confidence is True
   when the pick has no real matching signal (only "default suggestion" /
   "curated voice"), so the CLI / auto-apply can flag or skip blind guesses.
2. Near-miss emotion accumulation: EmotionInferencer.last_run_stats records
   how many utterances fell just below the confidence threshold, without
   breaking the bare-int return contract of apply_to_utterances().
3. Speaker resolver stats: ResolutionStats carries a low_confidence list of
   borderline fuzzy matches suitable for CLI surfacing.

No network / ffmpeg / voice-soundboard — registries and NLP adapters are
faked in-process.
"""

from __future__ import annotations

from audiobooker.casting.voice_suggester import (
    VoiceSuggester,
    VoiceSuggestion,
    audition_voices,
)
from audiobooker.nlp.emotion import EmotionInferencer, EmotionRunStats
from audiobooker.nlp.speaker_resolver import (
    LowConfidenceMatch,
    ResolutionStats,
    SpeakerResolver,
)
from audiobooker.models import (
    CastingTable,
    Chapter,
    Utterance,
    UtteranceType,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FixedRegistry:
    """Voice registry returning a fixed list (no voice-soundboard)."""

    def __init__(self, voices: list[str]) -> None:
        self._voices = voices

    def list_voices(self) -> list[str]:
        return self._voices


def _make_fake_adapter(quotes):
    from audiobooker.nlp.booknlp_adapter import BookNLPResult

    class _FakeAdapter:
        def is_available(self):
            return True

        def analyze(self, text):
            return BookNLPResult(
                quotes=quotes or [],
                speakers=list({q.speaker for q in (quotes or [])}),
                success=True,
            )

    return _FakeAdapter()


# ---------------------------------------------------------------------------
# Fix 1 — Low-confidence voice suggestions
# ---------------------------------------------------------------------------

class TestLowConfidenceVoiceSuggestions:
    def test_field_defaults_false(self):
        """low_confidence defaults to False on VoiceSuggestion."""
        s = VoiceSuggestion(voice_id="x", score=0.5, reason="default suggestion")
        assert s.low_confidence is False

    def test_no_signal_picks_flagged_low_confidence(self):
        """
        When no candidate has any gender/role/archetype/style signal, every
        suggestion is flagged low_confidence even though the normalized score
        sits at ~0.50 and looks like a real match.
        """
        # Voice ids with no known prefix and not in _VOICE_NOTES -> no signal.
        registry = _FixedRegistry(["zz_unknown1", "zz_unknown2", "zz_unknown3"])
        suggester = VoiceSuggester(registry=registry)

        # "Zephyr" is in neither the male nor female curated name list, and the
        # utterances carry no age/archetype cues -> nothing to match on.
        result = suggester.suggest_for_speaker("Zephyr", sample_utterances=["Hi."])

        assert result.suggestions, "expected suggestions to be returned"
        for s in result.suggestions:
            assert s.low_confidence is True
            assert s.reason == "default suggestion"
            # The normalized score still looks plausible — exactly why the flag
            # matters for blind auto-apply.
            assert 0.45 <= s.score <= 0.55

    def test_curated_only_is_low_confidence(self):
        """A pick whose only reason is 'curated voice' is still low-confidence."""
        # af_heart is in _VOICE_NOTES (curated, narrator-tagged). For a
        # non-narrator speaker with no gender/style signal it earns only the
        # curated-voice bonus — no real matching reason.
        registry = _FixedRegistry(["af_heart"])
        suggester = VoiceSuggester(registry=registry)

        result = suggester.suggest_for_speaker("Zephyr")
        top = result.top
        assert top is not None
        assert top.reason == "curated voice"
        assert top.low_confidence is True

    def test_real_signal_not_flagged(self):
        """A pick with a genuine gender match is NOT low-confidence."""
        registry = _FixedRegistry(["af_heart", "am_onyx"])
        suggester = VoiceSuggester(registry=registry)

        # "Mary" is in the curated female-name list -> gender signal exists.
        result = suggester.suggest_for_speaker("Mary")
        top = result.top
        assert top is not None
        assert top.low_confidence is False
        assert "gender match" in top.reason

    def test_audition_exposes_low_confidence(self):
        """audition_voices() surfaces the low_confidence flag in its dicts."""
        registry = _FixedRegistry(["zz_unknown1", "zz_unknown2"])
        rows = audition_voices(
            "Zephyr",
            CastingTable(),
            sample_utterances=["A line."],
            registry=registry,
        )
        assert rows, "expected audition rows"
        for row in rows:
            assert "low_confidence" in row
            assert row["low_confidence"] is True


# ---------------------------------------------------------------------------
# Fix 2 — Near-miss emotion accumulation
# ---------------------------------------------------------------------------

class TestNearMissEmotionAccumulation:
    def test_int_return_contract_preserved(self):
        """apply_to_utterances still returns a bare int (applied count)."""
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        utts = [Utterance(speaker="A", text="I am terrified!", emotion=None)]
        applied = inf.apply_to_utterances(utts)
        assert isinstance(applied, int)
        assert applied == 1  # "terrified" is >= threshold

    def test_last_run_stats_populated(self):
        """last_run_stats is an EmotionRunStats reflecting the run."""
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        utts = [
            Utterance(speaker="A", text="I am terrified!", emotion=None),
            Utterance(speaker="B", text="Hello there.", emotion=None),
        ]
        inf.apply_to_utterances(utts)
        stats = inf.last_run_stats
        assert isinstance(stats, EmotionRunStats)
        assert stats.applied == 1
        assert stats.examined == 2

    def test_near_miss_counted(self):
        """
        An utterance whose best candidate sits below the threshold is counted
        as a near-miss (not applied, not silently discarded).
        """
        # "annoyed" lexicon confidence is 0.7. With threshold 0.75 it's a
        # near-miss: a real candidate that infer() leaves as neutral.
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        utts = [Utterance(speaker="A", text="She was annoyed by the noise.", emotion=None)]
        applied = inf.apply_to_utterances(utts)

        assert applied == 0  # below threshold -> not applied
        assert utts[0].emotion is None  # conservatively left unset
        stats = inf.last_run_stats
        assert stats.near_miss == 1
        assert stats.near_miss_labels.get("angry") == 1

    def test_high_threshold_turns_match_into_near_miss(self):
        """Raising the threshold reclassifies an otherwise-applied match."""
        # "terrified" scores 0.9. With threshold 0.91 it becomes a near-miss.
        inf = EmotionInferencer(mode="rule", threshold=0.91)
        utts = [Utterance(speaker="A", text="I am terrified!", emotion=None)]
        applied = inf.apply_to_utterances(utts)
        assert applied == 0
        assert inf.last_run_stats.near_miss == 1
        assert inf.last_run_stats.near_miss_labels.get("fearful") == 1

    def test_no_signal_is_not_near_miss(self):
        """Plain text with no emotional signal is not a near-miss."""
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        utts = [Utterance(speaker="A", text="He walked to the door.", emotion=None)]
        inf.apply_to_utterances(utts)
        assert inf.last_run_stats.near_miss == 0
        assert inf.last_run_stats.near_miss_labels == {}

    def test_explicit_emotion_not_examined(self):
        """Utterances with an existing emotion are skipped, not examined."""
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        utts = [Utterance(speaker="A", text="annoyed", emotion="happy")]
        inf.apply_to_utterances(utts)
        assert inf.last_run_stats.examined == 0
        assert inf.last_run_stats.near_miss == 0

    def test_stats_reset_between_runs(self):
        """last_run_stats reflects only the most recent pass."""
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        inf.apply_to_utterances(
            [Utterance(speaker="A", text="She was annoyed.", emotion=None)]
        )
        assert inf.last_run_stats.near_miss == 1
        # Second run with no near-miss should reset the counter.
        inf.apply_to_utterances(
            [Utterance(speaker="A", text="He walked away.", emotion=None)]
        )
        assert inf.last_run_stats.near_miss == 0


# ---------------------------------------------------------------------------
# Fix 3 — Speaker resolver low-confidence list
# ---------------------------------------------------------------------------

class TestResolutionStatsLowConfidence:
    def test_stats_has_low_confidence_list(self):
        """ResolutionStats exposes a low_confidence list (default empty)."""
        stats = ResolutionStats()
        assert stats.low_confidence == []
        assert hasattr(stats, "speakers_resolved")
        assert hasattr(stats, "nlp_errors")

    def test_borderline_match_recorded(self):
        """
        A resolution accepted at the fuzzy threshold but below the
        low-confidence band is recorded in stats.low_confidence.
        """
        from audiobooker.nlp.booknlp_adapter import QuoteAttribution

        # Quote text differs from the utterance enough that the fuzzy ratio
        # (~0.857) lands in [FUZZY_THRESHOLD, LOW_CONFIDENCE_BAND).
        quote_text = "What do you mean by that"
        utt_text = "What did you mean by this"
        fake = _make_fake_adapter(
            [QuoteAttribution(quote_text=quote_text, speaker="Marcus", start=0, end=24, confidence=0.9)]
        )
        resolver = SpeakerResolver(mode="on", adapter=fake)

        chapter = Chapter(index=2, title="Ch3", raw_text=f'"{utt_text}"')
        chapter.utterances = [
            Utterance(
                speaker="unknown",
                text=utt_text,
                utterance_type=UtteranceType.DIALOGUE,
                line_index=7,
            ),
        ]

        stats = resolver.resolve([chapter], CastingTable())
        assert stats.speakers_resolved == 1
        assert chapter.utterances[0].speaker == "Marcus"
        # The match was borderline -> flagged for human review.
        assert len(stats.low_confidence) == 1
        low = stats.low_confidence[0]
        assert isinstance(low, LowConfidenceMatch)
        assert low.speaker == "Marcus"
        assert low.chapter_index == 2
        assert low.line_index == 7
        assert resolver.FUZZY_THRESHOLD <= low.confidence < resolver.LOW_CONFIDENCE_BAND

    def test_exact_match_not_low_confidence(self):
        """A clean exact match (confidence 1.0) is not flagged low-confidence."""
        from audiobooker.nlp.booknlp_adapter import QuoteAttribution

        fake = _make_fake_adapter(
            [QuoteAttribution(quote_text="Hello there", speaker="Marcus", start=0, end=11, confidence=0.9)]
        )
        resolver = SpeakerResolver(mode="on", adapter=fake)

        chapter = Chapter(index=0, title="Ch1", raw_text='"Hello there"')
        chapter.utterances = [
            Utterance(speaker="unknown", text="Hello there", utterance_type=UtteranceType.DIALOGUE),
        ]

        stats = resolver.resolve([chapter], CastingTable())
        assert stats.speakers_resolved == 1
        assert stats.low_confidence == []
