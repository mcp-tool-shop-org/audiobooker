"""
Tests for Phase 4 — Language Profiles + Input Flexibility.

Covers:
- LanguageProfile registry and English profile
- Profile-driven dialogue detection (same behavior as hardcoded)
- ProjectConfig.language_code serialization
- Programmatic API (from_string, from_chapters)
- Speaker casing consistency (casefold)
"""

import pytest

from audiobooker.language.profile import (
    LanguageProfile, get_profile, available_profiles, register_profile,
)
from audiobooker.language.en import ENGLISH
from audiobooker.models import (
    Chapter, CastingTable, ProjectConfig, UtteranceType,
)
from audiobooker.casting.dialogue import (
    detect_dialogue,
    extract_speaker_from_context,
    is_valid_speaker_name,
    compile_chapter,
)
from audiobooker import AudiobookProject


# ---------------------------------------------------------------------------
# LanguageProfile registry
# ---------------------------------------------------------------------------

class TestLanguageProfileRegistry:
    def test_english_registered(self):
        profile = get_profile("en")
        assert profile.code == "en"
        assert profile.name == "English"

    def test_available_profiles_includes_english(self):
        codes = available_profiles()
        assert "en" in codes

    def test_unknown_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            get_profile("xx")

    def test_english_profile_has_speaker_verbs(self):
        p = get_profile("en")
        assert "said" in p.speaker_verbs
        assert "whispered" in p.speaker_verbs

    def test_english_profile_has_emotion_hints(self):
        p = get_profile("en")
        assert p.emotion_hints["whispered"] == "whisper"
        assert p.emotion_hints["shouted"] == "angry"

    def test_english_profile_has_chapter_patterns(self):
        p = get_profile("en")
        assert len(p.chapter_patterns) >= 4

    def test_english_profile_has_scene_break_patterns(self):
        p = get_profile("en")
        assert len(p.scene_break_patterns) >= 3


# ---------------------------------------------------------------------------
# Profile-driven dialogue detection (same as hardcoded English)
# ---------------------------------------------------------------------------

class TestProfileDrivenDialogue:
    def test_detect_dialogue_with_profile(self):
        profile = get_profile("en")
        text = 'He said "Hello" and left.'
        segments = detect_dialogue(text, profile=profile)
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) == 1
        assert dialogue[0][0] == "Hello"

    def test_extract_speaker_with_profile(self):
        profile = get_profile("en")
        text = '"Hello!" said Alice cheerfully.'
        speaker, emotion = extract_speaker_from_context(
            text, 0, 9, profile=profile,
        )
        assert speaker == "Alice"

    def test_emotion_from_verb_via_profile(self):
        profile = get_profile("en")
        text = '"Run!" screamed Bob.'
        speaker, emotion = extract_speaker_from_context(
            text, 0, 6, profile=profile,
        )
        assert speaker == "Bob"
        assert emotion == "fearful"

    def test_blacklist_via_profile(self):
        profile = get_profile("en")
        casting = CastingTable()
        assert not is_valid_speaker_name("softly", casting, profile=profile)
        assert not is_valid_speaker_name("he", casting, profile=profile)

    def test_valid_name_via_profile(self):
        profile = get_profile("en")
        casting = CastingTable()
        assert is_valid_speaker_name("Alice", casting, profile=profile)

    def test_compile_chapter_with_profile(self):
        profile = get_profile("en")
        chapter = Chapter(
            index=0,
            title="Test",
            raw_text='The door opened. "Hello?" said Alice.',
        )
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting, profile=profile)
        assert len(utterances) >= 2
        dialogue = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]
        assert len(dialogue) >= 1


# ---------------------------------------------------------------------------
# ProjectConfig.language_code
# ---------------------------------------------------------------------------

class TestProjectConfigLanguage:
    def test_default_language_code(self):
        config = ProjectConfig()
        assert config.language_code == "en"

    def test_roundtrip(self):
        config = ProjectConfig(language_code="en")
        data = config.to_dict()
        assert data["language_code"] == "en"
        restored = ProjectConfig.from_dict(data)
        assert restored.language_code == "en"

    def test_from_dict_missing_language_defaults(self):
        data = {"sample_rate": 24000}
        config = ProjectConfig.from_dict(data)
        assert config.language_code == "en"


# ---------------------------------------------------------------------------
# Programmatic API
# ---------------------------------------------------------------------------

class TestProgrammaticAPI:
    def test_from_string_basic(self):
        text = "The sun rose. It was a beautiful day."
        project = AudiobookProject.from_string(text, title="Test Book")
        assert project.title == "Test Book"
        assert len(project.chapters) == 1
        assert project.config.language_code == "en"
        assert "narrator" in project.casting.characters

    def test_from_string_with_chapters(self):
        text = (
            "Chapter 1: Dawn\n\nThe sun rose.\n\n"
            "Chapter 2: Dusk\n\nThe sun set.\n\n"
            "Chapter 3: Night\n\nThe stars appeared.\n"
        )
        project = AudiobookProject.from_string(text, title="Multi")
        assert len(project.chapters) >= 2

    def test_from_string_with_frontmatter(self):
        text = "---\ntitle: My Book\nauthor: John\n---\n\nSome text."
        project = AudiobookProject.from_string(text)
        assert project.title == "My Book"
        assert project.author == "John"

    def test_from_chapters_basic(self):
        chapters = [
            ("Chapter 1", "The sun rose."),
            ("Chapter 2", "The sun set."),
        ]
        project = AudiobookProject.from_chapters(chapters, title="Split Book")
        assert project.title == "Split Book"
        assert len(project.chapters) == 2
        assert project.chapters[0].title == "Chapter 1"
        assert project.chapters[1].raw_text == "The sun set."

    def test_from_chapters_compiles(self):
        chapters = [
            ("Ch1", 'Alice said "Hello!" and smiled.'),
        ]
        project = AudiobookProject.from_chapters(chapters, title="Test")
        project.cast("Alice", "af_bella")
        project.compile()
        assert len(project.chapters[0].utterances) >= 1


# ---------------------------------------------------------------------------
# Speaker casing consistency
# ---------------------------------------------------------------------------

class TestSpeakerCasing:
    def test_normalize_key_casefold(self):
        assert CastingTable.normalize_key("Alice") == "alice"
        assert CastingTable.normalize_key("ALICE") == "alice"
        assert CastingTable.normalize_key("  Alice  ") == "alice"

    def test_cast_preserves_display_name(self):
        casting = CastingTable()
        casting.cast("Alice", "af_bella")
        assert casting.characters["alice"].name == "Alice"

    def test_alice_vs_ALICE_same_key(self):
        casting = CastingTable()
        casting.cast("Alice", "af_bella")
        casting.cast("ALICE", "af_heart")
        # Second cast should overwrite first (same key)
        assert len(casting.characters) == 1
        assert casting.characters["alice"].voice == "af_heart"
        assert casting.characters["alice"].name == "ALICE"  # display form updated

    def test_get_voice_case_insensitive(self):
        casting = CastingTable()
        casting.cast("Alice", "af_bella")
        voice, _ = casting.get_voice("alice")
        assert voice == "af_bella"
        voice2, _ = casting.get_voice("ALICE")
        assert voice2 == "af_bella"

    def test_voice_mapping_uses_casefold(self):
        casting = CastingTable()
        casting.cast("Alice", "af_bella")
        mapping = casting.get_voice_mapping()
        assert "alice" in mapping
        assert mapping["alice"] == "af_bella"
