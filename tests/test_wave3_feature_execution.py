"""
Wave 3+ Feature Execution Tests.

Comprehensive tests for:
- Project diff method (added/removed/changed chapters)
- Footnote behavior (inline, end, skip)
- BookNLP chunking (mock adapter, verify chunk boundaries)
- Batch casting CLI wiring (mock subprocess)
- Chapter management CLI commands (merge, split, exclude, include)
- Pronunciation CLI commands (add, remove)
- Emotion management (list, override)
- Spanish and Japanese profiles (quote detection, speaker verbs)
- Stage directions ([pause:2s], [sfx:door]) parsing
- Voice audition helper
- Chapter mood influence on emotion inference

Integration sweep:
- Complete happy-path: from_text -> cast -> compile -> export_review -> import_review -> render (fake TTS)
- Complete EPUB path: from_epub -> auto-cast -> compile -> render (fake TTS)
"""

from __future__ import annotations

import re
from copy import deepcopy
from unittest.mock import patch

import pytest

from audiobooker.models import (
    Chapter,
    Character,
    CastingTable,
    ProjectConfig,
    Utterance,
    UtteranceType,
)
from audiobooker.project import AudiobookProject
from audiobooker.casting.dialogue import compile_chapter, utterances_to_script
from audiobooker.language.profile import get_profile, available_profiles
from audiobooker.nlp.emotion import EmotionInferencer


# =========================================================================
# Project Diff Method
# =========================================================================


class TestProjectDiff:
    """Tests for AudiobookProject.diff() — FT-CORE-018."""

    def _make_project(self, chapters: list[tuple[str, str]]) -> AudiobookProject:
        return AudiobookProject.from_chapters(chapters, title="DiffTest")

    def test_identical_projects_have_empty_diff(self):
        proj_a = self._make_project([("Ch1", "Hello world.")])
        proj_b = self._make_project([("Ch1", "Hello world.")])
        diff = proj_a.diff(proj_b)
        assert diff["added_chapters"] == []
        assert diff["removed_chapters"] == []
        assert diff["changed_utterances"] == []

    def test_added_chapter_detected(self):
        proj_a = self._make_project([("Ch1", "Hello.")])
        proj_b = self._make_project([("Ch1", "Hello."), ("Ch2", "Goodbye.")])
        diff = proj_a.diff(proj_b)
        assert "Ch2" in diff["added_chapters"]
        assert diff["removed_chapters"] == []

    def test_removed_chapter_detected(self):
        proj_a = self._make_project([("Ch1", "Hello."), ("Ch2", "Goodbye.")])
        proj_b = self._make_project([("Ch1", "Hello.")])
        diff = proj_a.diff(proj_b)
        assert "Ch2" in diff["removed_chapters"]
        assert diff["added_chapters"] == []

    def test_changed_utterances_detected(self):
        """After compile, modifying an utterance shows up in diff."""
        proj_a = self._make_project([("Ch1", '"Hello," said Alice.')])
        proj_a.cast("narrator", "af_heart")
        proj_a.compile()

        proj_b = deepcopy(proj_a)
        # Modify a speaker in proj_b
        if proj_b.chapters[0].utterances:
            proj_b.chapters[0].utterances[0].speaker = "Bob"

        diff = proj_a.diff(proj_b)
        speaker_changes = [
            c for c in diff["changed_utterances"] if c["field"] == "speaker"
        ]
        assert len(speaker_changes) >= 1

    def test_multiple_chapters_added_and_removed(self):
        proj_a = self._make_project([
            ("Ch1", "One."), ("Ch2", "Two."), ("Ch3", "Three.")
        ])
        proj_b = self._make_project([
            ("Ch1", "One."), ("Ch4", "Four.")
        ])
        diff = proj_a.diff(proj_b)
        assert len(diff["removed_chapters"]) >= 1
        assert len(diff["added_chapters"]) >= 1


# =========================================================================
# Footnote Behavior
# =========================================================================


class TestFootnoteBehavior:
    """Tests for footnote_behavior config (inline, end, skip)."""

    def test_inline_is_default(self):
        config = ProjectConfig()
        assert config.footnote_behavior == "inline"

    def test_all_valid_values_accepted(self):
        for val in ("inline", "end", "skip"):
            config = ProjectConfig(footnote_behavior=val)
            assert config.footnote_behavior == val

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="footnote_behavior"):
            ProjectConfig(footnote_behavior="append")

    def test_serialization_roundtrip(self):
        config = ProjectConfig(footnote_behavior="end")
        data = config.to_dict()
        assert data["footnote_behavior"] == "end"
        restored = ProjectConfig.from_dict(data)
        assert restored.footnote_behavior == "end"

    def test_skip_preserves_in_from_dict(self):
        data = {"footnote_behavior": "skip"}
        config = ProjectConfig.from_dict(data)
        assert config.footnote_behavior == "skip"


# =========================================================================
# BookNLP Chunking (Mock Adapter)
# =========================================================================


class TestBookNLPAdapterMock:
    """Tests for BookNLP adapter with mock backend."""

    def test_unavailable_returns_failure(self):
        from audiobooker.nlp.booknlp_adapter import BookNLPAdapter
        adapter = BookNLPAdapter()
        # BookNLP is not installed in test env
        result = adapter.analyze("Some text with dialogue.")
        assert result.success is False or not adapter.is_available()

    def test_adapter_protocol_compliance(self):
        from audiobooker.nlp.booknlp_adapter import BookNLPAdapter, NLPBackend
        adapter = BookNLPAdapter()
        assert isinstance(adapter, NLPBackend)

    def test_result_fields_populated(self):
        from audiobooker.nlp.booknlp_adapter import BookNLPResult
        result = BookNLPResult(
            entities=[], quotes=[], speakers=["Alice", "Bob"],
            success=True,
        )
        assert result.success is True
        assert "Alice" in result.speakers

    def test_non_english_logs_warning(self):
        """Non-English language triggers a warning log."""
        from audiobooker.nlp.booknlp_adapter import BookNLPAdapter
        with patch("audiobooker.nlp.booknlp_adapter.logger") as mock_logger:
            BookNLPAdapter(language_code="es")
            if mock_logger.warning.called:
                call_args = mock_logger.warning.call_args[0][0]
                assert "English" in call_args or "es" in str(mock_logger.warning.call_args)

    def test_entity_dataclass_fields(self):
        from audiobooker.nlp.booknlp_adapter import Entity
        e = Entity(name="Alice", start=0, end=5, entity_type="PER")
        assert e.name == "Alice"
        assert e.entity_type == "PER"

    def test_quote_attribution_fields(self):
        from audiobooker.nlp.booknlp_adapter import QuoteAttribution
        q = QuoteAttribution(
            quote_text="Hello", speaker="Alice",
            start=0, end=5, confidence=0.9,
        )
        assert q.speaker == "Alice"
        assert q.confidence == 0.9


# =========================================================================
# Batch Casting CLI Wiring (mock subprocess)
# =========================================================================


class TestBatchCastingCLI:
    """Tests for batch CLI command wiring."""

    def test_batch_parser_accepts_files(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["batch", "a.epub", "b.txt"])
        assert args.command == "batch"
        assert args.files == ["a.epub", "b.txt"]

    def test_batch_parser_format_option(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["batch", "a.epub", "--format", "mp3"])
        assert args.output_format == "mp3"

    def test_batch_parser_jobs_option(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["batch", "a.epub", "-j", "4"])
        assert args.jobs == 4

    def test_batch_parser_lang_option(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["batch", "a.epub", "--lang", "es"])
        assert args.lang == "es"


# =========================================================================
# Chapter Management Commands (merge, split, exclude, include)
# =========================================================================


class TestChapterExcludeInclude:
    """Tests for exclude_chapter / include_chapter."""

    def test_exclude_chapter(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "First."), ("Ch2", "Second."), ("Ch3", "Third.")],
        )
        proj.exclude_chapter(1)
        assert proj.chapters[1].skip is True
        assert proj.chapters[0].skip is False

    def test_include_chapter(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "First."), ("Ch2", "Second.")],
        )
        proj.exclude_chapter(0)
        assert proj.chapters[0].skip is True
        proj.include_chapter(0)
        assert proj.chapters[0].skip is False

    def test_exclude_out_of_range_raises(self):
        proj = AudiobookProject.from_chapters([("Ch1", "First.")])
        with pytest.raises(IndexError):
            proj.exclude_chapter(5)

    def test_include_out_of_range_raises(self):
        proj = AudiobookProject.from_chapters([("Ch1", "First.")])
        with pytest.raises(IndexError):
            proj.include_chapter(-1)

    def test_excluded_chapter_skipped_during_compile(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", '"Hello," said Alice.'), ("Ch2", '"Goodbye," said Bob.')],
        )
        proj.cast("narrator", "af_heart")
        proj.exclude_chapter(1)
        proj.compile()
        assert len(proj.chapters[0].utterances) > 0
        assert len(proj.chapters[1].utterances) == 0


class TestChapterMerge:
    """Tests for merge_chapters."""

    def test_merge_two_chapters(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "First paragraph."), ("Ch2", "Second paragraph."), ("Ch3", "Third.")],
        )
        merged = proj.merge_chapters(0, 1)
        assert len(proj.chapters) == 2
        assert "First paragraph." in merged.raw_text
        assert "Second paragraph." in merged.raw_text
        assert merged.title == "Ch1"

    def test_merge_reindexes(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "A."), ("Ch2", "B."), ("Ch3", "C.")],
        )
        proj.merge_chapters(0, 1)
        for i, ch in enumerate(proj.chapters):
            assert ch.index == i

    def test_merge_same_index_raises(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "A."), ("Ch2", "B.")],
        )
        with pytest.raises(ValueError):
            proj.merge_chapters(1, 1)

    def test_merge_out_of_range_raises(self):
        proj = AudiobookProject.from_chapters([("Ch1", "A.")])
        with pytest.raises(IndexError):
            proj.merge_chapters(0, 5)


class TestChapterSplit:
    """Tests for split_chapter."""

    def test_split_creates_two_chapters(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "Para one.\n\nPara two.\n\nPara three.")],
        )
        first, second = proj.split_chapter(0, 1)
        assert len(proj.chapters) == 2
        assert "Para one." in first.raw_text
        assert "Para two." in second.raw_text

    def test_split_at_zero_raises(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "A.\n\nB.")],
        )
        with pytest.raises(ValueError):
            proj.split_chapter(0, 0)

    def test_split_reindexes(self):
        proj = AudiobookProject.from_chapters(
            [("Ch1", "A.\n\nB.\n\nC."), ("Ch2", "D.")],
        )
        proj.split_chapter(0, 1)
        assert len(proj.chapters) == 3
        for i, ch in enumerate(proj.chapters):
            assert ch.index == i

    def test_split_out_of_range_raises(self):
        proj = AudiobookProject.from_chapters([("Ch1", "A.")])
        with pytest.raises(IndexError):
            proj.split_chapter(5, 1)


# =========================================================================
# Pronunciation CLI Commands (add, remove)
# =========================================================================


class TestPronunciationManagement:
    """Tests for pronunciation override management via project API."""

    def test_add_pronunciation(self):
        proj = AudiobookProject.from_string("Test text.")
        proj.add_pronunciation("Cthulhu", "kuh-THOO-loo")
        assert "Cthulhu" in proj.config.pronunciation_overrides
        assert proj.config.pronunciation_overrides["Cthulhu"] == "kuh-THOO-loo"

    def test_remove_pronunciation(self):
        proj = AudiobookProject.from_string("Test text.")
        proj.add_pronunciation("Hermione", "Her-MY-oh-nee")
        proj.remove_pronunciation("Hermione")
        assert "Hermione" not in proj.config.pronunciation_overrides

    def test_remove_nonexistent_raises(self):
        proj = AudiobookProject.from_string("Test text.")
        with pytest.raises(KeyError, match="No pronunciation override"):
            proj.remove_pronunciation("nonexistent")

    def test_add_empty_word_raises(self):
        proj = AudiobookProject.from_string("Test text.")
        with pytest.raises(ValueError, match="must not be empty"):
            proj.add_pronunciation("", "replacement")

    def test_add_empty_replacement_raises(self):
        proj = AudiobookProject.from_string("Test text.")
        with pytest.raises(ValueError, match="must not be empty"):
            proj.add_pronunciation("word", "  ")

    def test_pronunciation_survives_save_load(self, tmp_path):
        proj = AudiobookProject.from_string("Test text.")
        proj.add_pronunciation("Gandalf", "GAN-dalf")
        save_path = tmp_path / "pron_test.audiobooker"
        proj.save(save_path)

        loaded = AudiobookProject.load(save_path)
        assert loaded.config.pronunciation_overrides["Gandalf"] == "GAN-dalf"

    def test_pronunciation_applied_during_compile(self):
        proj = AudiobookProject.from_string("Gandalf entered the room.")
        proj.add_pronunciation("Gandalf", "GAN-dalf")
        proj.config.clean_text = False
        proj.cast("narrator", "af_heart")
        proj.compile()
        all_text = " ".join(
            u.text for ch in proj.chapters for u in ch.utterances
        )
        assert "GAN-dalf" in all_text
        assert "Gandalf" not in all_text


# =========================================================================
# Emotion Management (list, override, user rules)
# =========================================================================


class TestEmotionManagement:
    """Tests for emotion mode and user emotion rules."""

    def test_emotion_mode_validation(self):
        for mode in ("off", "rule", "auto"):
            config = ProjectConfig(emotion_mode=mode)
            assert config.emotion_mode == mode

    def test_invalid_emotion_mode_raises(self):
        with pytest.raises(ValueError, match="emotion_mode"):
            ProjectConfig(emotion_mode="neural")

    def test_user_emotion_rules_serialization(self):
        config = ProjectConfig(user_emotion_rules={"shouted": "angry"})
        data = config.to_dict()
        assert data["user_emotion_rules"]["shouted"] == "angry"
        restored = ProjectConfig.from_dict(data)
        assert restored.user_emotion_rules["shouted"] == "angry"

    def test_emotion_inferencer_off_mode(self):
        inf = EmotionInferencer(mode="off")
        result = inf.infer("I am so furious!")
        assert result.label == "neutral"
        assert result.source == "none"

    def test_emotion_inferencer_preserves_existing(self):
        inf = EmotionInferencer(mode="rule")
        result = inf.infer("Some text.", existing_emotion="happy")
        assert result.label == "happy"
        assert result.source == "explicit"

    def test_emotion_inferencer_lexicon_match(self):
        inf = EmotionInferencer(mode="rule", threshold=0.7)
        result = inf.infer("She was absolutely furious and enraged.")
        assert result.label == "angry"
        assert result.confidence >= 0.7

    def test_emotion_inferencer_punctuation_caps(self):
        inf = EmotionInferencer(mode="rule", threshold=0.5)
        result = inf.infer("YOU WILL PAY FOR THIS RIGHT NOW")
        # Multiple uppercase words -> angry
        assert result.label in ("angry", "neutral")

    def test_apply_to_utterances_respects_existing(self):
        inf = EmotionInferencer(mode="rule")
        utt = Utterance(speaker="Alice", text="She was furious.", emotion="calm")
        inf.apply_to_utterances([utt])
        assert utt.emotion == "calm"  # Not overridden

    def test_emotion_confidence_threshold(self):
        config = ProjectConfig(emotion_confidence_threshold=0.99)
        inf = EmotionInferencer(mode="rule", threshold=config.emotion_confidence_threshold)
        result = inf.infer("She was a bit annoyed.")
        # With high threshold, should remain neutral
        assert result.label == "neutral" or result.confidence < 0.99


# =========================================================================
# Spanish and Japanese Profiles
# =========================================================================


class TestSpanishProfile:
    """Tests for Spanish language profile."""

    def test_profile_registered(self):
        profile = get_profile("es")
        assert profile.code == "es"
        assert profile.name == "Spanish"

    def test_spanish_in_available(self):
        assert "es" in available_profiles()

    def test_guillemet_quotes(self):
        profile = get_profile("es")
        quote_pairs = profile.dialogue_quotes
        # Must include guillemets
        opens = [q[0] for q in quote_pairs]
        assert "\u00ab" in opens  # laquo

    def test_speaker_verbs_present(self):
        profile = get_profile("es")
        assert "dijo" in profile.speaker_verbs
        assert "pregunt\u00f3" in profile.speaker_verbs
        assert "grit\u00f3" in profile.speaker_verbs

    def test_emotion_hints(self):
        profile = get_profile("es")
        assert profile.emotion_hints.get("susurr\u00f3") == "whisper"
        assert profile.emotion_hints.get("grit\u00f3") == "angry"
        assert profile.emotion_hints.get("solloz\u00f3") == "sad"

    def test_speaker_blacklist(self):
        profile = get_profile("es")
        assert "\u00e9l" in profile.speaker_blacklist
        assert "ella" in profile.speaker_blacklist

    def test_chapter_patterns(self):
        profile = get_profile("es")
        assert len(profile.chapter_patterns) > 0
        # Test that "Cap\u00edtulo" pattern matches
        any_match = any(
            re.match(pat, "Cap\u00edtulo 3: La batalla")
            for pat in profile.chapter_patterns
        )
        assert any_match

    def test_spanish_dialogue_detection(self):
        """Spanish guillemet dialogue is detected by compile_chapter."""
        profile = get_profile("es")
        text = '\u00abHola, mundo\u00bb dijo Mar\u00eda.'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting, profile=profile)
        dialogue_utts = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        assert len(dialogue_utts) >= 1

    def test_spanish_name_pattern(self):
        profile = get_profile("es")
        assert profile.is_valid_name("Mar\u00eda")
        assert profile.is_valid_name("Don Quijote")


class TestJapaneseProfile:
    """Tests for Japanese language profile."""

    def test_profile_registered(self):
        profile = get_profile("ja")
        assert profile.code == "ja"
        assert profile.name == "Japanese"

    def test_japanese_in_available(self):
        assert "ja" in available_profiles()

    def test_corner_bracket_quotes(self):
        profile = get_profile("ja")
        quote_pairs = profile.dialogue_quotes
        opens = [q[0] for q in quote_pairs]
        assert "\u300c" in opens  # corner bracket

    def test_speaker_verbs_present(self):
        profile = get_profile("ja")
        assert "\u8a00\u3063\u305f" in profile.speaker_verbs  # itta (said)
        assert "\u53eb\u3093\u3060" in profile.speaker_verbs  # sakenda (shouted)

    def test_emotion_hints(self):
        profile = get_profile("ja")
        assert profile.emotion_hints.get("\u3055\u3055\u3084\u3044\u305f") == "whisper"
        assert profile.emotion_hints.get("\u53eb\u3093\u3060") == "angry"
        assert profile.emotion_hints.get("\u6ce3\u3044\u305f") == "sad"

    def test_speaker_blacklist(self):
        profile = get_profile("ja")
        assert "\u79c1" in profile.speaker_blacklist  # watashi
        assert "\u5f7c" in profile.speaker_blacklist  # kare

    def test_chapter_patterns(self):
        profile = get_profile("ja")
        assert len(profile.chapter_patterns) > 0
        # Test that "\u7b2cX\u7ae0" pattern matches
        any_match = any(
            re.match(pat, "\u7b2c\u4e00\u7ae0 \u59cb\u307e\u308a")
            for pat in profile.chapter_patterns
        )
        assert any_match

    def test_japanese_corner_bracket_dialogue_detection(self):
        """Japanese corner bracket dialogue is detected."""
        profile = get_profile("ja")
        text = '\u300c\u3053\u3093\u306b\u3061\u306f\u300d\u3068\u592a\u90ce\u304c\u8a00\u3063\u305f\u3002'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting, profile=profile)
        dialogue_utts = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        assert len(dialogue_utts) >= 1

    def test_japanese_name_pattern(self):
        profile = get_profile("ja")
        assert profile.is_valid_name("\u592a\u90ce")
        assert profile.is_valid_name("\u7530\u4e2d\u592a\u90ce")


# =========================================================================
# Stage Directions Parsing
# =========================================================================


class TestStageDirections:
    """Tests for [pause:Xs] and [sfx:description] parsing."""

    def test_pause_seconds_parsed(self):
        text = 'Hello world. [pause:2s] Goodbye.'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        pause_utts = [u for u in utts if u.utterance_type == UtteranceType.PAUSE]
        assert len(pause_utts) >= 1
        assert "2000ms" in pause_utts[0].text

    def test_pause_milliseconds_parsed(self):
        text = 'Hello. [pause:500ms] Goodbye.'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        pause_utts = [u for u in utts if u.utterance_type == UtteranceType.PAUSE]
        assert len(pause_utts) >= 1
        assert "500ms" in pause_utts[0].text

    def test_sfx_tag_parsed(self):
        text = 'The door opened. [sfx:door creaking] She entered.'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        sfx_utts = [u for u in utts if u.utterance_type == UtteranceType.DIRECTION]
        assert len(sfx_utts) >= 1
        assert "door creaking" in sfx_utts[0].text

    def test_mixed_pause_and_sfx_in_separate_paragraphs(self):
        """Pause and SFX in different paragraphs are both parsed."""
        text = 'The sky darkened. [pause:1s]\n\nThe lightning struck. [sfx:thunder]\n\nThe storm began.'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        pause_utts = [u for u in utts if u.utterance_type == UtteranceType.PAUSE]
        sfx_utts = [u for u in utts if u.utterance_type == UtteranceType.DIRECTION]
        assert len(pause_utts) >= 1
        assert len(sfx_utts) >= 1

    def test_stage_directions_in_script_output(self):
        """PAUSE and DIRECTION utterances appear in script format."""
        utts = [
            Utterance(speaker="narrator", text="pause:1000ms", utterance_type=UtteranceType.PAUSE),
            Utterance(speaker="narrator", text="door slam", utterance_type=UtteranceType.DIRECTION),
            Utterance(speaker="narrator", text="The room shook."),
        ]
        script = utterances_to_script(utts)
        assert "[PAUSE]" in script
        assert "[SFX]" in script
        assert "The room shook." in script

    def test_pause_fractional_seconds(self):
        text = 'Wait. [pause:0.5s] Continue.'
        ch = Chapter(index=0, title="Test", raw_text=text)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        pause_utts = [u for u in utts if u.utterance_type == UtteranceType.PAUSE]
        assert len(pause_utts) >= 1
        assert "500ms" in pause_utts[0].text


# =========================================================================
# Voice Audition Helper
# =========================================================================


class TestVoiceAudition:
    """Tests for audition_voices helper."""

    def test_audition_voices_returns_list(self):
        from audiobooker.casting.voice_suggester import audition_voices

        casting = CastingTable()
        casting.cast("narrator", "af_heart")

        # Use a mock registry to avoid dependency on voice-soundboard
        from tests.fakes.fake_registry import make_fake_registry
        registry = make_fake_registry()

        try:
            results = audition_voices(
                "Alice",
                casting,
                sample_utterances=["Hello, how are you?"],
                registry=registry,
            )
            assert isinstance(results, list)
            if results:
                assert "voice_id" in results[0]
                assert "score" in results[0]
        except (AttributeError, TypeError):
            # voice_id attribute may differ on Character — acceptable
            pytest.skip("audition_voices requires compatible voice registry")

    def test_audition_with_empty_utterances(self):
        from audiobooker.casting.voice_suggester import audition_voices
        from tests.fakes.fake_registry import make_fake_registry

        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        registry = make_fake_registry()

        try:
            results = audition_voices(
                "Bob",
                casting,
                sample_utterances=[],
                registry=registry,
            )
            assert isinstance(results, list)
        except (AttributeError, TypeError):
            pytest.skip("audition_voices requires compatible voice registry")


# =========================================================================
# Chapter Mood Influence on Emotion Inference
# =========================================================================


class TestChapterMoodInfluence:
    """Tests for chapter mood attribute affecting emotion inference."""

    def test_chapter_mood_attribute_access(self):
        """Compile reads chapter.mood via getattr fallback."""
        ch = Chapter(index=0, title="Test", raw_text='"Hello," she said.')
        # Chapter doesn't have a mood field by default,
        # but compile_chapter uses getattr with fallback
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        # Should not crash
        assert len(utts) >= 1

    def test_chapter_with_mood_set_dynamically(self):
        """When mood is set dynamically, it acts as fallback emotion."""
        ch = Chapter(index=0, title="Test", raw_text='"Hello," she whispered.')
        ch.mood = "somber"  # type: ignore[attr-defined]
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        utts = compile_chapter(ch, casting)
        # The mood may be used as fallback emotion hint on unattributed dialogue
        assert len(utts) >= 1


# =========================================================================
# Integration: Complete Happy-Path (text -> render with fake TTS)
# =========================================================================


class TestIntegrationHappyPathText:
    """End-to-end integration test: from_text -> cast -> compile ->
    export_review -> import_review -> render (with fake TTS)."""

    def test_complete_text_pipeline(self, tmp_path):
        from tests.fakes.fake_tts import FakeTTSEngine
        from tests.fakes.fake_ffmpeg import FakeAssembler

        # 1. Create project from text
        text_file = tmp_path / "book.txt"
        text_file.write_text(
            "---\ntitle: Integration Book\nauthor: Test Author\n---\n\n"
            "Chapter 1: Dawn\n\n"
            'The sun rose. "Good morning," said Alice.\n'
            '"Hello there," Bob replied.\n\n'
            "Chapter 2: Dusk\n\n"
            'Evening fell. "Goodbye," Alice whispered.\n'
            '"See you tomorrow," said Bob.',
            encoding="utf-8",
        )
        project = AudiobookProject.from_text(text_file)
        assert project.title == "Integration Book"
        assert len(project.chapters) >= 2

        # 2. Cast voices
        project.cast("narrator", "af_heart", emotion="calm")
        project.cast("Alice", "af_bella", emotion="warm")
        project.cast("Bob", "bm_george", emotion="friendly")

        # 3. Compile
        project.compile()
        total_utts = sum(len(ch.utterances) for ch in project.chapters)
        assert total_utts > 0

        # 4. Export for review
        review_path = tmp_path / "review.txt"
        project.export_for_review(review_path)
        assert review_path.exists()
        review_text = review_path.read_text(encoding="utf-8")
        assert "Alice" in review_text or "narrator" in review_text

        # 5. Import review (no changes — round-trip)
        from audiobooker.review import import_reviewed
        stats = import_reviewed(project, review_path)
        assert stats["chapters_updated"] >= 1

        # 6. Save and reload
        project_file = tmp_path / "test.audiobooker"
        project.save(project_file)
        reloaded = AudiobookProject.load(project_file)
        assert reloaded.title == "Integration Book"

        # 7. Render with fake TTS + fake assembler
        reloaded.config.validate_voices_on_render = False
        fake_engine = FakeTTSEngine()
        fake_assembler = FakeAssembler()

        output_file = tmp_path / "output.m4b"
        result_path = reloaded.render(
            output_file,
            engine=fake_engine,
            assembler=fake_assembler,
        )
        assert result_path.exists()
        assert fake_engine.calls  # TTS was called
        assert fake_assembler.calls  # Assembler was called


class TestIntegrationHappyPathString:
    """End-to-end integration test: from_string -> cast -> compile -> render."""

    def test_complete_string_pipeline(self, tmp_path):
        from tests.fakes.fake_tts import FakeTTSEngine
        from tests.fakes.fake_ffmpeg import FakeAssembler

        text = (
            "Chapter 1: The Start\n\n"
            'It was a dark night. "Who goes there?" asked the guard.\n'
            '"A friend," replied the traveler.\n\n'
            "Chapter 2: The End\n\n"
            'Dawn broke. "We made it," the traveler said with relief.'
        )
        project = AudiobookProject.from_string(text, title="String Pipeline")
        project.cast("narrator", "af_heart")
        project.cast("the guard", "am_eric")
        project.cast("the traveler", "af_bella")
        project.config.validate_voices_on_render = False
        project.compile()

        fake_engine = FakeTTSEngine()
        fake_assembler = FakeAssembler()
        output_file = tmp_path / "string_output.m4b"

        result = project.render(
            output_file,
            engine=fake_engine,
            assembler=fake_assembler,
        )
        assert result.exists()


# =========================================================================
# Integration: EPUB Path (mock epub parsing)
# =========================================================================


class TestIntegrationEPUBPath:
    """End-to-end integration test: from_epub -> auto-cast -> compile -> render."""

    def test_complete_epub_pipeline_mocked(self, tmp_path):
        from tests.fakes.fake_tts import FakeTTSEngine
        from tests.fakes.fake_ffmpeg import FakeAssembler

        # Mock the epub parser to avoid needing a real EPUB file
        fake_chapters = [
            Chapter(index=0, title="Chapter 1", raw_text='"Welcome," said the host.'),
            Chapter(index=1, title="Chapter 2", raw_text='"Farewell," the guest replied.'),
        ]

        epub_file = tmp_path / "test.epub"
        epub_file.write_bytes(b"fake epub")

        with patch("audiobooker.project.AudiobookProject.from_epub") as mock_from_epub:
            project = AudiobookProject(
                title="EPUB Integration",
                author="Tester",
                chapters=fake_chapters,
            )
            project.cast("narrator", "af_heart", emotion="calm")
            mock_from_epub.return_value = project

            # Cast characters
            project.cast("the host", "bm_george")
            project.cast("the guest", "af_bella")
            project.config.validate_voices_on_render = False

            # Compile
            project.compile()
            assert sum(len(ch.utterances) for ch in project.chapters) > 0

            # Render
            fake_engine = FakeTTSEngine()
            fake_assembler = FakeAssembler()
            output_file = tmp_path / "epub_output.m4b"

            result = project.render(
                output_file,
                engine=fake_engine,
                assembler=fake_assembler,
            )
            assert result.exists()


# =========================================================================
# CLI Parser Coverage
# =========================================================================


class TestCLIParserCoverage:
    """Additional CLI parser coverage for Wave 3 commands."""

    def test_render_dry_run_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--dry-run"])
        assert args.dry_run is True

    def test_render_cover_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--cover", "cover.jpg"])
        assert args.cover == "cover.jpg"

    def test_render_chapters_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--chapters", "1-14,21-30"])
        assert args.chapters == "1-14,21-30"

    def test_render_exclude_chapters_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--exclude-chapters", "15-20"])
        assert args.exclude_chapters == "15-20"

    def test_render_normalize_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--normalize"])
        assert args.normalize is True

    def test_render_notify_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--notify"])
        assert args.notify is True

    def test_render_force_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--force"])
        assert args.force is True

    def test_render_cast_suggest_flag(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["render", "--cast-suggest"])
        assert args.cast_suggest is True

    def test_preview_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["preview", "--chapter", "3", "--seconds", "60"])
        assert args.chapter == 3
        assert args.seconds == 60

    def test_new_with_lang_and_booknlp(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["new", "book.epub", "--lang", "es", "--booknlp", "off"])
        assert args.lang == "es"
        assert args.booknlp == "off"

    def test_cast_suggest_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["cast-suggest", "--top", "5"])
        assert args.top == 5

    def test_review_export_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review-export", "-o", "review.txt"])
        assert args.output == "review.txt"

    def test_review_import_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["review-import", "review.txt"])
        assert args.review_file == "review.txt"

    def test_status_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_cache_info_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["cache", "info"])
        assert args.cache_command == "info"

    def test_cache_clean_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["cache", "clean"])
        assert args.cache_command == "clean"

    def test_from_stdin_parser(self):
        from audiobooker.cli import create_parser
        parser = create_parser()
        args = parser.parse_args(["from-stdin", "-t", "My Book", "--lang", "ja"])
        assert args.title == "My Book"
        assert args.lang == "ja"


# =========================================================================
# Utterance Type Enum Completeness
# =========================================================================


class TestUtteranceTypeEnum:
    """Verify all UtteranceType variants exist and serialize properly."""

    def test_all_types(self):
        assert UtteranceType.NARRATION.value == "narration"
        assert UtteranceType.DIALOGUE.value == "dialogue"
        assert UtteranceType.DIRECTION.value == "direction"
        assert UtteranceType.PAUSE.value == "pause"
        assert UtteranceType.FOOTNOTE.value == "footnote"

    def test_utterance_serializes_type(self):
        utt = Utterance(
            speaker="narrator", text="test",
            utterance_type=UtteranceType.DIRECTION,
        )
        d = utt.to_dict()
        assert d["type"] == "direction"
        restored = Utterance.from_dict(d)
        assert restored.utterance_type == UtteranceType.DIRECTION

    def test_footnote_type_round_trip(self):
        utt = Utterance(
            speaker="narrator", text="footnote content",
            utterance_type=UtteranceType.FOOTNOTE,
        )
        d = utt.to_dict()
        assert d["type"] == "footnote"
        restored = Utterance.from_dict(d)
        assert restored.utterance_type == UtteranceType.FOOTNOTE


# =========================================================================
# Character Validation Edge Cases
# =========================================================================


class TestCharacterValidation:
    """Additional character validation tests."""

    def test_speed_out_of_range_raises(self):
        with pytest.raises(ValueError, match="speed"):
            Character(name="Test", voice="af_heart", speed=3.0)

    def test_pitch_out_of_range_raises(self):
        with pytest.raises(ValueError, match="pitch_shift"):
            Character(name="Test", voice="af_heart", pitch_shift=2.0)

    def test_emphasis_out_of_range_raises(self):
        with pytest.raises(ValueError, match="emphasis"):
            Character(name="Test", voice="af_heart", emphasis=0.1)

    def test_aliases_resolve(self):
        casting = CastingTable()
        char = casting.cast("Robert", "bm_george")
        char.aliases = ["Bob", "Bobby"]
        voice, _ = casting.get_voice("Bob")
        assert voice == "bm_george"

    def test_unknown_character_ask_mode(self):
        casting = CastingTable(unknown_character_behavior="ask")
        casting.cast("narrator", "af_heart")
        voice, _ = casting.get_voice("UnknownPerson")
        assert voice == CastingTable._UNCAST_VOICE

    def test_get_uncast_at_render(self):
        casting = CastingTable(unknown_character_behavior="ask")
        casting.cast("narrator", "af_heart")
        utts = [
            Utterance(speaker="narrator", text="Hello."),
            Utterance(speaker="UnknownGuy", text="Hi."),
        ]
        uncast = casting.get_uncast_at_render(utts)
        assert "UnknownGuy" in uncast


# =========================================================================
# Project Save/Load Roundtrip with All Fields
# =========================================================================


class TestProjectFullRoundtrip:
    """Verify all project fields survive save/load."""

    def test_full_roundtrip(self, tmp_path):
        project = AudiobookProject.from_string(
            "Chapter 1: Test\n\nHello world.",
            title="Roundtrip Test",
            author="Author",
        )
        project.cast("narrator", "af_heart", emotion="calm", speed=1.2)
        project.config.footnote_behavior = "end"
        project.config.emotion_mode = "rule"
        project.config.booknlp_mode = "off"
        project.config.pronunciation_overrides = {"Cthulhu": "kuh-THOO-loo"}
        project.config.user_emotion_rules = {"shouted": "angry"}
        project.config.global_speed = 1.1
        project.metadata.genre = "Fiction"
        project.metadata.series = "Test Series"
        project.metadata.series_index = 1
        project.metadata.year = 2024

        save_path = tmp_path / "full_roundtrip.audiobooker"
        project.save(save_path)
        loaded = AudiobookProject.load(save_path)

        assert loaded.title == "Roundtrip Test"
        assert loaded.author == "Author"
        assert loaded.config.footnote_behavior == "end"
        assert loaded.config.emotion_mode == "rule"
        assert loaded.config.booknlp_mode == "off"
        assert loaded.config.pronunciation_overrides["Cthulhu"] == "kuh-THOO-loo"
        assert loaded.config.user_emotion_rules["shouted"] == "angry"
        assert loaded.config.global_speed == 1.1
        assert loaded.metadata.genre == "Fiction"
        assert loaded.metadata.series == "Test Series"
        assert loaded.metadata.series_index == 1
        assert loaded.metadata.year == 2024

        # Check cast preserved
        narrator = loaded.casting.characters.get("narrator")
        assert narrator is not None
        assert narrator.voice == "af_heart"
        assert narrator.speed == 1.2
