"""Tests for core data models."""

import pytest
from audiobooker.models import (
    Utterance,
    UtteranceType,
    Chapter,
    Character,
    CastingTable,
    ProjectConfig,
)


class TestUtterance:
    """Tests for Utterance dataclass."""

    def test_create_narration(self):
        """Test creating a narration utterance."""
        u = Utterance(
            speaker="narrator",
            text="The door creaked open.",
            utterance_type=UtteranceType.NARRATION,
        )
        assert u.speaker == "narrator"
        assert u.text == "The door creaked open."
        assert u.utterance_type == UtteranceType.NARRATION
        assert u.emotion is None

    def test_create_dialogue(self):
        """Test creating a dialogue utterance."""
        u = Utterance(
            speaker="Alice",
            text="Hello, is anyone there?",
            utterance_type=UtteranceType.DIALOGUE,
            emotion="nervous",
        )
        assert u.speaker == "Alice"
        assert u.utterance_type == UtteranceType.DIALOGUE
        assert u.emotion == "nervous"

    def test_to_script_line_simple(self):
        """Test conversion to script format without emotion."""
        u = Utterance(speaker="narrator", text="It was dark.")
        line = u.to_script_line()
        assert line == "[S1:narrator] It was dark."

    def test_to_script_line_with_emotion(self):
        """Test conversion to script format with emotion."""
        u = Utterance(
            speaker="Bob",
            text="Run!",
            emotion="fearful",
        )
        line = u.to_script_line()
        assert line == "[S1:Bob] (fearful) Run!"

    def test_serialization(self):
        """Test to_dict and from_dict."""
        u = Utterance(
            speaker="Alice",
            text="Hello",
            utterance_type=UtteranceType.DIALOGUE,
            emotion="happy",
            chapter_index=1,
            line_index=5,
        )
        data = u.to_dict()
        restored = Utterance.from_dict(data)

        assert restored.speaker == u.speaker
        assert restored.text == u.text
        assert restored.utterance_type == u.utterance_type
        assert restored.emotion == u.emotion
        assert restored.chapter_index == u.chapter_index
        assert restored.line_index == u.line_index


class TestChapter:
    """Tests for Chapter dataclass."""

    def test_word_count(self):
        """Test word count calculation."""
        chapter = Chapter(
            index=0,
            title="Chapter 1",
            raw_text="One two three four five.",
        )
        assert chapter.word_count == 5

    def test_estimated_duration(self):
        """Test estimated duration calculation."""
        # 150 words = 1 minute
        chapter = Chapter(
            index=0,
            title="Test",
            raw_text=" ".join(["word"] * 150),
        )
        assert chapter.estimated_duration_minutes == pytest.approx(1.0)

    def test_is_compiled(self):
        """Test compiled status."""
        chapter = Chapter(index=0, title="Test", raw_text="Hello")
        assert not chapter.is_compiled

        chapter.utterances.append(
            Utterance(speaker="narrator", text="Hello")
        )
        assert chapter.is_compiled

    def test_serialization(self):
        """Test to_dict and from_dict."""
        chapter = Chapter(
            index=2,
            title="Chapter 3: The Beginning",
            raw_text="It was a dark and stormy night.",
            source_file="book.epub",
        )
        chapter.utterances.append(
            Utterance(speaker="narrator", text="It was a dark and stormy night.")
        )

        data = chapter.to_dict()
        restored = Chapter.from_dict(data)

        assert restored.index == chapter.index
        assert restored.title == chapter.title
        assert restored.raw_text == chapter.raw_text
        assert len(restored.utterances) == 1


class TestCastingTable:
    """Tests for CastingTable."""

    def test_cast_character(self):
        """Test casting a character."""
        table = CastingTable()
        char = table.cast("Alice", "af_bella", emotion="warm")

        assert char.name == "Alice"
        assert char.voice == "af_bella"
        assert char.emotion == "warm"
        assert "alice" in table.characters

    def test_get_voice_cast(self):
        """Test getting voice for cast character."""
        table = CastingTable()
        table.cast("Bob", "bm_george", emotion="grumpy")

        voice, emotion = table.get_voice("Bob")
        assert voice == "bm_george"
        assert emotion == "grumpy"

    def test_get_voice_uncast_with_narrator(self):
        """Test fallback to narrator for uncast character."""
        table = CastingTable()
        table.cast("narrator", "af_heart", emotion="calm")

        voice, emotion = table.get_voice("UnknownCharacter")
        assert voice == "af_heart"
        assert emotion == "calm"

    def test_get_voice_mapping(self):
        """Test getting voice mapping dict."""
        table = CastingTable()
        table.cast("narrator", "bm_george")
        table.cast("Alice", "af_bella")

        mapping = table.get_voice_mapping()
        assert mapping == {
            "narrator": "bm_george",
            "alice": "af_bella",
        }

    def test_serialization(self):
        """Test to_dict and from_dict."""
        table = CastingTable()
        table.cast("narrator", "bm_george", description="Main narrator")
        table.cast("Alice", "af_bella", emotion="warm")

        data = table.to_dict()
        restored = CastingTable.from_dict(data)

        assert len(restored.characters) == 2
        assert restored.characters["narrator"].voice == "bm_george"
        assert restored.characters["alice"].emotion == "warm"


class TestProjectConfig:
    """Tests for ProjectConfig."""

    def test_defaults(self):
        """Test default values."""
        config = ProjectConfig()
        assert config.chapter_pause_ms == 2000
        assert config.sample_rate == 24000
        assert config.output_format == "m4b"

    def test_serialization(self):
        """Test to_dict and from_dict."""
        config = ProjectConfig(
            chapter_pause_ms=3000,
            output_format="mp3",
        )

        data = config.to_dict()
        restored = ProjectConfig.from_dict(data)

        assert restored.chapter_pause_ms == 3000
        assert restored.output_format == "mp3"
