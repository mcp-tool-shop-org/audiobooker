"""Tests for dialogue detection and compilation."""

import pytest
from audiobooker.casting.dialogue import (
    detect_dialogue,
    parse_inline_override,
    compile_chapter,
    extract_speaker_from_context,
    utterances_to_script,
)
from audiobooker.models import Chapter, CastingTable, UtteranceType


class TestParseInlineOverride:
    """Tests for inline override parsing."""

    def test_no_override(self):
        """Test text without override."""
        char, emotion, text = parse_inline_override("Just regular text.")
        assert char is None
        assert emotion is None
        assert text == "Just regular text."

    def test_character_only(self):
        """Test override with just character name."""
        char, emotion, text = parse_inline_override('[Alice] "Hello!"')
        assert char == "Alice"
        assert emotion is None
        assert text == '"Hello!"'

    def test_character_and_emotion(self):
        """Test override with character and emotion."""
        char, emotion, text = parse_inline_override('[Bob|angry] "Get out!"')
        assert char == "Bob"
        assert emotion == "angry"
        assert text == '"Get out!"'


class TestDetectDialogue:
    """Tests for dialogue detection."""

    def test_simple_dialogue(self):
        """Test detecting simple quoted dialogue."""
        text = 'He said "Hello there" and walked away.'
        segments = detect_dialogue(text)

        # Should have 3 segments: narration, dialogue, narration
        assert len(segments) == 3
        # Check content and type, not exact positions
        assert "He said" in segments[0][0]
        assert segments[0][1] is False  # narration
        assert segments[1][0] == "Hello there"
        assert segments[1][1] is True  # dialogue
        assert "walked away" in segments[2][0]
        assert segments[2][1] is False  # narration

    def test_multiple_quotes(self):
        """Test detecting multiple dialogue segments."""
        text = '"Hi" she said. "How are you?"'
        segments = detect_dialogue(text)

        dialogue_segments = [s for s in segments if s[1]]
        assert len(dialogue_segments) == 2
        assert dialogue_segments[0][0] == "Hi"
        assert dialogue_segments[1][0] == "How are you?"

    def test_no_dialogue(self):
        """Test text without dialogue."""
        text = "The sun was setting over the mountains."
        segments = detect_dialogue(text)

        assert len(segments) == 1
        assert segments[0][1] is False  # not dialogue

    def test_smart_quotes(self):
        """Test detecting curly/smart quotes."""
        text = 'She whispered "Be careful" softly.'
        segments = detect_dialogue(text)

        dialogue_segments = [s for s in segments if s[1]]
        assert len(dialogue_segments) == 1
        assert dialogue_segments[0][0] == "Be careful"


class TestExtractSpeaker:
    """Tests for speaker extraction from context."""

    def test_said_name_pattern(self):
        """Test 'said Alice' pattern."""
        text = '"Hello!" said Alice cheerfully.'
        # Quote is at positions 0-8, context window looks around it
        speaker, emotion = extract_speaker_from_context(text, 0, 9)
        assert speaker == "Alice"

    def test_name_said_pattern(self):
        """Test 'Alice said' pattern."""
        text = 'Alice said "Hello!" with a smile.'
        speaker, emotion = extract_speaker_from_context(text, 12, 20)
        assert speaker == "Alice"

    def test_emotion_from_verb(self):
        """Test emotion extraction from speech verb."""
        text = '"Watch out!" whispered Bob urgently.'
        # Quote is at positions 0-12, context looks around
        speaker, emotion = extract_speaker_from_context(text, 0, 13)
        assert speaker == "Bob"
        assert emotion == "whisper"

    def test_no_speaker_found(self):
        """Test when no speaker can be found."""
        text = '"Hello there."'
        speaker, emotion = extract_speaker_from_context(text, 0, 14)
        assert speaker is None


class TestCompileChapter:
    """Tests for chapter compilation."""

    def test_simple_chapter(self):
        """Test compiling a simple chapter."""
        chapter = Chapter(
            index=0,
            title="Test Chapter",
            raw_text='The door opened. "Hello?" said Alice.',
        )
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting)

        assert len(utterances) >= 2
        # Should have narration and dialogue
        narration = [u for u in utterances if u.utterance_type == UtteranceType.NARRATION]
        dialogue = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]
        assert len(narration) >= 1
        assert len(dialogue) >= 1

    def test_inline_override(self):
        """Test chapter with inline override."""
        chapter = Chapter(
            index=0,
            title="Test",
            raw_text='[Bob|angry] "Get out of here!"',
        )
        casting = CastingTable()

        utterances = compile_chapter(chapter, casting)

        assert len(utterances) == 1
        assert utterances[0].speaker == "Bob"
        assert utterances[0].emotion == "angry"

    def test_updates_line_counts(self):
        """Test that compilation updates character line counts."""
        chapter = Chapter(
            index=0,
            title="Test",
            raw_text='"Hi" said Alice. "Hello" said Alice.',
        )
        casting = CastingTable()
        casting.cast("Alice", "af_bella")

        compile_chapter(chapter, casting)

        # Alice should have line count updated
        assert casting.characters["alice"].line_count == 2


class TestUtterancesToScript:
    """Tests for script conversion."""

    def test_simple_script(self):
        """Test converting utterances to script."""
        from audiobooker.models import Utterance

        utterances = [
            Utterance(speaker="narrator", text="The room was quiet."),
            Utterance(speaker="Alice", text="Hello?", emotion="nervous"),
        ]
        casting = CastingTable()

        script = utterances_to_script(utterances, casting)

        assert "[S1:narrator] The room was quiet." in script
        assert "[S2:alice] (nervous) Hello?" in script
