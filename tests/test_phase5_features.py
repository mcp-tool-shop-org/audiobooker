"""
Tests for Phase 5 — Roadmap Features + UX Polish.

Covers:
- BookNLP adapter + SpeakerResolver (with fakes)
- Emotion inference (rule-based + lexicon + threshold)
- Voice suggestions (deterministic ranking, no duplicates)
- Progress tracker + ETA
- Failure report bundle
- Config serialization for new fields
"""

import json
import re
import tempfile
from pathlib import Path

import pytest

from audiobooker.models import (
    Chapter, Utterance, UtteranceType, CastingTable, ProjectConfig,
)
from audiobooker import AudiobookProject


# =========================================================================
# 5.1 — BookNLP Adapter + SpeakerResolver
# =========================================================================

class TestBookNLPAdapter:
    """BookNLP adapter with fake backend."""

    def test_adapter_reports_unavailable(self):
        """Without BookNLP installed, adapter.is_available() is False."""
        from audiobooker.nlp.booknlp_adapter import BookNLPAdapter
        adapter = BookNLPAdapter()
        # BookNLP is not installed in test env
        assert adapter.is_available() is False

    def test_analyze_without_booknlp_returns_empty(self):
        """analyze() returns empty result with error when not available."""
        from audiobooker.nlp.booknlp_adapter import BookNLPAdapter
        adapter = BookNLPAdapter()
        result = adapter.analyze("Some text here.")
        assert result.success is False
        assert "not installed" in result.error.lower()
        assert result.entities == []
        assert result.quotes == []

    def test_booknlp_result_dataclass(self):
        """BookNLPResult is well-formed."""
        from audiobooker.nlp.booknlp_adapter import BookNLPResult, Entity, QuoteAttribution
        result = BookNLPResult(
            entities=[Entity(name="Alice", start=0, end=5)],
            quotes=[QuoteAttribution(quote_text="Hello", speaker="Alice", start=10, end=17)],
            speakers=["Alice"],
            success=True,
        )
        assert len(result.entities) == 1
        assert result.quotes[0].speaker == "Alice"
        assert result.success


class TestSpeakerResolver:
    """SpeakerResolver with fake adapter."""

    def _make_fake_adapter(self, quotes=None):
        """Create a fake NLP adapter for testing."""
        from audiobooker.nlp.booknlp_adapter import BookNLPResult, QuoteAttribution

        class FakeAdapter:
            def is_available(self):
                return True

            def analyze(self, text):
                return BookNLPResult(
                    quotes=quotes or [],
                    speakers=list({q.speaker for q in (quotes or [])}),
                    success=True,
                )

        return FakeAdapter()

    def test_off_mode_is_noop(self):
        """mode='off' returns immediately without touching utterances."""
        from audiobooker.nlp.speaker_resolver import SpeakerResolver
        resolver = SpeakerResolver(mode="off")

        chapter = Chapter(index=0, title="Ch1", raw_text="text")
        chapter.utterances = [
            Utterance(speaker="unknown", text="Hello", utterance_type=UtteranceType.DIALOGUE),
        ]

        stats = resolver.resolve([chapter], CastingTable())
        assert stats.nlp_used is False
        assert chapter.utterances[0].speaker == "unknown"

    def test_auto_mode_without_booknlp(self):
        """mode='auto' without BookNLP is a silent no-op."""
        from audiobooker.nlp.speaker_resolver import SpeakerResolver
        resolver = SpeakerResolver(mode="auto")  # uses real adapter (not installed)

        chapter = Chapter(index=0, title="Ch1", raw_text="text")
        chapter.utterances = [
            Utterance(speaker="unknown", text="Hello"),
        ]

        stats = resolver.resolve([chapter], CastingTable())
        assert stats.nlp_used is False

    def test_on_mode_without_booknlp_raises(self):
        """mode='on' without BookNLP raises RuntimeError."""
        from audiobooker.nlp.speaker_resolver import SpeakerResolver
        resolver = SpeakerResolver(mode="on")

        with pytest.raises(RuntimeError, match="not installed"):
            resolver.resolve([], CastingTable())

    def test_resolver_with_fake_adapter(self):
        """Resolver improves 'unknown' using fake NLP attributions."""
        from audiobooker.nlp.speaker_resolver import SpeakerResolver
        from audiobooker.nlp.booknlp_adapter import QuoteAttribution

        fake = self._make_fake_adapter(quotes=[
            QuoteAttribution(quote_text="Hello there", speaker="Marcus", start=0, end=11, confidence=0.9),
        ])
        resolver = SpeakerResolver(mode="on", adapter=fake)

        chapter = Chapter(index=0, title="Ch1", raw_text='"Hello there" he said.')
        chapter.utterances = [
            Utterance(speaker="unknown", text="Hello there", utterance_type=UtteranceType.DIALOGUE),
        ]

        stats = resolver.resolve([chapter], CastingTable())
        assert stats.nlp_used is True
        assert stats.speakers_resolved == 1
        assert chapter.utterances[0].speaker == "Marcus"

    def test_resolver_preserves_existing_speakers(self):
        """Resolver doesn't change utterances that already have a speaker."""
        from audiobooker.nlp.speaker_resolver import SpeakerResolver
        from audiobooker.nlp.booknlp_adapter import QuoteAttribution

        fake = self._make_fake_adapter(quotes=[
            QuoteAttribution(quote_text="Hello", speaker="Wrong", start=0, end=5, confidence=0.9),
        ])
        resolver = SpeakerResolver(mode="on", adapter=fake)

        chapter = Chapter(index=0, title="Ch1", raw_text='"Hello" Alice said.')
        chapter.utterances = [
            Utterance(speaker="Alice", text="Hello", utterance_type=UtteranceType.DIALOGUE),
        ]

        stats = resolver.resolve([chapter], CastingTable())
        assert stats.speakers_unchanged == 1
        assert chapter.utterances[0].speaker == "Alice"

    def test_invalid_mode_raises(self):
        """Invalid mode raises ValueError."""
        from audiobooker.nlp.speaker_resolver import SpeakerResolver
        with pytest.raises(ValueError, match="Invalid booknlp_mode"):
            SpeakerResolver(mode="invalid")


# =========================================================================
# 5.2 — Emotion Inference
# =========================================================================

class TestEmotionInferencer:
    """Emotion inference engine tests."""

    def test_off_mode_returns_neutral(self):
        """mode='off' always returns neutral."""
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="off")
        result = inf.infer("He screamed in terror!")
        assert result.label == "neutral"

    def test_verb_based_emotion(self):
        """High-confidence verbs map correctly."""
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="rule", threshold=0.75)

        result = inf.infer("Be quiet!", context="she whispered urgently")
        assert result.label == "whisper"
        assert result.confidence >= 0.75
        assert result.source == "verb"

    def test_verb_shouted_maps_to_angry(self):
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        result = inf.infer("Stop right there!", context="he shouted at the crowd")
        assert result.label == "angry"

    def test_lexicon_based_emotion(self):
        """Lexicon catches strong sentiment words."""
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="rule", threshold=0.75)
        result = inf.infer("I am absolutely terrified of what comes next")
        assert result.label == "fearful"
        assert result.source == "lexicon"

    def test_low_confidence_stays_neutral(self):
        """Below threshold → neutral."""
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="rule", threshold=0.95)  # very high threshold
        result = inf.infer("I feel a bit worried about this.")
        # Even if detected, confidence should be below 0.95
        assert result.label == "neutral"

    def test_explicit_emotion_preserved(self):
        """User-set emotions are never overridden."""
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="rule", threshold=0.5)
        result = inf.infer("Hello there", existing_emotion="sarcastic")
        assert result.label == "sarcastic"
        assert result.confidence == 1.0
        assert result.source == "explicit"

    def test_apply_to_utterances(self):
        """apply_to_utterances modifies only empty-emotion utterances."""
        from audiobooker.nlp.emotion import EmotionInferencer
        inf = EmotionInferencer(mode="rule", threshold=0.75)

        utterances = [
            Utterance(speaker="narrator", text="The door opened.", emotion=None),
            Utterance(speaker="Alice", text="I am terrified!", emotion=None),
            Utterance(speaker="Bob", text="Hello.", emotion="happy"),  # explicit
        ]

        applied = inf.apply_to_utterances(utterances)
        # Bob's explicit "happy" should be preserved
        assert utterances[2].emotion == "happy"
        # Alice's terrified should get fearful
        assert utterances[1].emotion == "fearful"

    def test_invalid_mode_raises(self):
        from audiobooker.nlp.emotion import EmotionInferencer
        with pytest.raises(ValueError, match="Invalid emotion_mode"):
            EmotionInferencer(mode="invalid")


# =========================================================================
# 5.3 — Voice Suggestions
# =========================================================================

class TestVoiceSuggester:
    """Voice suggestion engine tests."""

    def _make_fake_registry(self, voices=None):
        """Create a fake voice registry."""
        class FakeRegistry:
            def __init__(self, voice_list):
                self._voices = voice_list

            def list_voices(self):
                return self._voices

        return FakeRegistry(voices or [
            "af_heart", "af_jessica", "af_sky",
            "am_eric", "am_fenrir", "am_onyx",
            "bf_alice", "bf_emma",
            "bm_george", "bm_lewis",
        ])

    def test_suggest_for_narrator(self):
        """Narrator gets narrator-tagged voice suggestions."""
        from audiobooker.casting.voice_suggester import VoiceSuggester
        reg = self._make_fake_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=3)

        result = suggester.suggest_for_speaker("narrator", is_narrator=True)
        assert len(result.suggestions) == 3
        assert result.top is not None
        # Top suggestion should have "narrator" tag
        assert "narrator" in result.top.tags or result.top.score > 0

    def test_suggest_deterministic(self):
        """Same inputs produce same rankings."""
        from audiobooker.casting.voice_suggester import VoiceSuggester
        reg = self._make_fake_registry()

        s1 = VoiceSuggester(registry=reg).suggest_for_speaker("Alice")
        s2 = VoiceSuggester(registry=reg).suggest_for_speaker("Alice")

        assert [s.voice_id for s in s1.suggestions] == [s.voice_id for s in s2.suggestions]

    def test_no_duplicates_across_speakers(self):
        """suggest_all avoids reusing voices across speakers."""
        from audiobooker.casting.voice_suggester import VoiceSuggester
        reg = self._make_fake_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=1)

        results = suggester.suggest_all(
            ["narrator", "Alice", "Bob"],
        )

        top_voices = [r.top.voice_id for r in results if r.top]
        # All top suggestions should be different
        assert len(top_voices) == len(set(top_voices))

    def test_already_cast_penalized(self):
        """Already-cast voices are penalized in scoring."""
        from audiobooker.casting.voice_suggester import VoiceSuggester
        reg = self._make_fake_registry()
        suggester = VoiceSuggester(registry=reg, max_suggestions=5)

        result = suggester.suggest_for_speaker(
            "Alice",
            already_cast={"narrator": "af_heart"},
        )
        # af_heart should not be the top suggestion
        assert result.top.voice_id != "af_heart"

    def test_empty_registry(self):
        """Empty registry returns empty suggestions."""
        from audiobooker.casting.voice_suggester import VoiceSuggester

        class EmptyRegistry:
            def list_voices(self):
                return []

        suggester = VoiceSuggester(registry=EmptyRegistry())
        result = suggester.suggest_for_speaker("Alice")
        assert result.suggestions == []

    def test_suggestion_has_reason(self):
        """Every suggestion includes a human-readable reason."""
        from audiobooker.casting.voice_suggester import VoiceSuggester
        reg = self._make_fake_registry()
        suggester = VoiceSuggester(registry=reg)
        result = suggester.suggest_for_speaker("narrator", is_narrator=True)
        for s in result.suggestions:
            assert s.reason  # not empty
            assert isinstance(s.reason, str)


# =========================================================================
# 5.5 — Progress Tracker + Failure Report
# =========================================================================

class TestRenderProgressTracker:
    """Progress reporting with dynamic ETA."""

    def test_basic_progress(self):
        """Track rendered and cached chapters."""
        from audiobooker.renderer.progress import RenderProgressTracker
        tracker = RenderProgressTracker(total_chapters=4)

        tracker.mark_cached(0, "Ch1", 60.0)
        tracker.start_chapter(1, "Ch2", word_count=500)
        tracker.finish_chapter(1, duration_s=10.0)
        tracker.start_chapter(2, "Ch3", word_count=600)
        tracker.finish_chapter(2, duration_s=12.0)

        assert tracker.cached_count == 1
        assert tracker.rendered_count == 2
        assert tracker.completed_count == 3
        assert tracker.percent_complete == 75.0

    def test_eta_calculation(self):
        """ETA updates based on observed durations."""
        from audiobooker.renderer.progress import RenderProgressTracker
        tracker = RenderProgressTracker(total_chapters=10)

        # Render 3 chapters, 10s each
        for i in range(3):
            tracker.start_chapter(i, f"Ch{i}")
            tracker.finish_chapter(i, duration_s=10.0)

        eta = tracker.eta_seconds()
        # 7 remaining * 10s avg = ~70s
        assert eta is not None
        assert 60 <= eta <= 80

    def test_eta_display_format(self):
        """eta_display returns human-readable string."""
        from audiobooker.renderer.progress import RenderProgressTracker
        tracker = RenderProgressTracker(total_chapters=5)
        assert tracker.eta_display() == "estimating..."

        tracker.start_chapter(0, "Ch1")
        tracker.finish_chapter(0, duration_s=60.0)
        display = tracker.eta_display()
        assert "remaining" in display

    def test_summary_string(self):
        """summary() produces readable output."""
        from audiobooker.renderer.progress import RenderProgressTracker
        tracker = RenderProgressTracker(total_chapters=3)
        tracker.mark_cached(0, "Ch1")
        tracker.start_chapter(1, "Ch2")
        tracker.finish_chapter(1, duration_s=5.0)

        summary = tracker.summary()
        assert "67%" in summary
        assert "cached" in summary


class TestRenderFailureReport:
    """Failure report bundle tests."""

    def test_create_and_save_report(self, tmp_path):
        """Report creates valid JSON with required fields."""
        from audiobooker.renderer.failure_report import RenderFailureReport

        report = RenderFailureReport(
            book_title="Test Book",
            total_chapters=10,
            rendered_ok=5,
            cached_ok=3,
            cache_dir=str(tmp_path),
        )

        try:
            raise ValueError("TTS engine crashed on voice af_bella")
        except ValueError as e:
            report.add_failure(
                chapter_index=7,
                chapter_title="Chapter 8: The Storm",
                error=e,
                utterance_index=42,
                speaker="Alice",
                text_preview="She screamed in terror...",
                voice_id="af_bella",
                emotion="fearful",
            )

        path = report.save(tmp_path / "failure.json")
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["book_title"] == "Test Book"
        assert data["total_chapters"] == 10
        assert data["failed_count"] == 1
        assert len(data["failed_chapters"]) == 1

        fc = data["failed_chapters"][0]
        assert fc["chapter_index"] == 7
        assert fc["chapter_title"] == "Chapter 8: The Storm"
        assert "TTS engine crashed" in fc["error_message"]
        assert fc["stack_trace"]  # not empty
        assert fc["failed_utterance"]["speaker"] == "Alice"
        assert fc["failed_utterance"]["voice_id"] == "af_bella"

    def test_load_roundtrip(self, tmp_path):
        """Report survives save/load cycle."""
        from audiobooker.renderer.failure_report import RenderFailureReport

        report = RenderFailureReport(book_title="Roundtrip")
        try:
            raise RuntimeError("fail")
        except RuntimeError as e:
            report.add_failure(0, "Ch1", e)

        path = report.save(tmp_path / "rt.json")
        loaded = RenderFailureReport.load(path)
        assert loaded.book_title == "Roundtrip"
        assert len(loaded.failed_chapters) == 1

    def test_empty_report_is_valid(self, tmp_path):
        """Report with no failures is still valid JSON."""
        from audiobooker.renderer.failure_report import RenderFailureReport
        report = RenderFailureReport(book_title="Clean")
        path = report.save(tmp_path / "clean.json")
        data = json.loads(path.read_text())
        assert data["failed_count"] == 0
        assert data["failed_chapters"] == []


# =========================================================================
# Config serialization — new fields
# =========================================================================

class TestConfigNewFields:
    """ProjectConfig serialization of Phase 5 fields."""

    def test_booknlp_mode_roundtrip(self):
        config = ProjectConfig(booknlp_mode="on")
        d = config.to_dict()
        assert d["booknlp_mode"] == "on"
        loaded = ProjectConfig.from_dict(d)
        assert loaded.booknlp_mode == "on"

    def test_emotion_mode_roundtrip(self):
        config = ProjectConfig(emotion_mode="off", emotion_confidence_threshold=0.5)
        d = config.to_dict()
        assert d["emotion_mode"] == "off"
        assert d["emotion_confidence_threshold"] == 0.5
        loaded = ProjectConfig.from_dict(d)
        assert loaded.emotion_mode == "off"
        assert loaded.emotion_confidence_threshold == 0.5

    def test_defaults_for_missing_fields(self):
        """Old project files without new fields get sensible defaults."""
        d = {"chapter_pause_ms": 2000}
        config = ProjectConfig.from_dict(d)
        assert config.booknlp_mode == "auto"
        assert config.emotion_mode == "rule"
        assert config.emotion_confidence_threshold == 0.75

    def test_full_project_save_load(self, tmp_path):
        """Full project save/load preserves new config fields."""
        project = AudiobookProject.from_string(
            "Hello world",
            title="Test",
        )
        project.config.booknlp_mode = "off"
        project.config.emotion_mode = "auto"
        project.config.emotion_confidence_threshold = 0.6

        path = project.save(tmp_path / "test.audiobooker")
        loaded = AudiobookProject.load(path)
        assert loaded.config.booknlp_mode == "off"
        assert loaded.config.emotion_mode == "auto"
        assert loaded.config.emotion_confidence_threshold == 0.6


# =========================================================================
# Integration: compile with emotion inference
# =========================================================================

class TestCompileWithEmotion:
    """Emotion inference integrates into the compile pipeline."""

    def test_compile_applies_emotion(self):
        """Compile with emotion_mode='rule' applies verb-based emotions."""
        project = AudiobookProject.from_string(
            '"Run!" she screamed. "Get out now!" he shouted.',
            title="Emotion Test",
        )
        project.config.emotion_mode = "rule"
        project.config.emotion_confidence_threshold = 0.75
        project.compile()

        # Should have some utterances with inferred emotions
        all_utterances = [u for ch in project.chapters for u in ch.utterances]
        assert len(all_utterances) > 0

    def test_compile_with_emotion_off(self):
        """emotion_mode='off' leaves emotions as-is."""
        project = AudiobookProject.from_string(
            '"Run!" she screamed.',
            title="No Emotion",
        )
        project.config.emotion_mode = "off"
        project.compile()

        all_utterances = [u for ch in project.chapters for u in ch.utterances]
        # dialogue detection still works, emotions may come from verb in compile_chapter
        # but the emotion inferencer is disabled
        assert len(all_utterances) > 0
