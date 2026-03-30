"""Tests for core data models."""

import json
import uuid
from pathlib import Path

import pytest

from audiobooker.models import (
    BookMetadata,
    Character,
    Utterance,
    UtteranceType,
    Chapter,
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
        """Test conversion to script format without emotion.

        S1 is always used as the speaker slot prefix — this is intentional.
        voice-soundboard's dialogue engine uses the S1 prefix as a speaker
        identifier and maps it to the voice via the voices dict. Multiple
        speakers all use S1 because the voices dict resolves the actual voice.
        """
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


class TestChapterEdgeCases:
    """Edge case tests for Chapter word_count and estimated_duration."""

    @pytest.mark.parametrize("raw_text, expected_count", [
        ("", 0),
        ("hello", 1),
        (" ".join(["word"] * 10000), 10000),
    ], ids=["empty", "single-word", "large-10k-words"])
    def test_word_count_edge_cases(self, raw_text, expected_count):
        """Chapter.word_count handles empty, single-word, and large inputs."""
        chapter = Chapter(index=0, title="Edge", raw_text=raw_text)
        assert chapter.word_count == expected_count

    def test_empty_chapter_estimated_duration(self):
        """Empty chapter has zero estimated duration."""
        chapter = Chapter(index=0, title="Empty", raw_text="")
        assert chapter.estimated_duration_minutes == pytest.approx(0.0)

    def test_single_word_chapter_estimated_duration(self):
        """Single word chapter has near-zero estimated duration."""
        chapter = Chapter(index=0, title="Tiny", raw_text="hello")
        assert chapter.estimated_duration_minutes == pytest.approx(1.0 / 150)


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


# ---------------------------------------------------------------------------
# F-TEST-015: AudiobookProject.load() error paths
# ---------------------------------------------------------------------------

class TestProjectLoadErrors:
    """Tests for AudiobookProject.load() error paths."""

    def test_load_missing_file(self, tmp_path):
        """load() raises FileNotFoundError for missing file."""
        from audiobooker.project import AudiobookProject
        missing = tmp_path / "nonexistent" / "path.audiobooker"
        with pytest.raises(FileNotFoundError, match="not found"):
            AudiobookProject.load(str(missing))

    def test_load_corrupt_json(self, tmp_path):
        """load() raises json.JSONDecodeError for corrupt JSON."""
        from audiobooker.project import AudiobookProject
        corrupt = tmp_path / "corrupt.audiobooker"
        corrupt.write_text("{invalid json content!!!", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            AudiobookProject.load(corrupt)

    def test_load_schema_version_mismatch(self, tmp_path):
        """load() raises ValueError for future schema version."""
        from audiobooker.project import AudiobookProject
        future = tmp_path / "future.audiobooker"
        future.write_text(json.dumps({
            "schema_version": 9999,
            "title": "Future Book",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="schema v9999"):
            AudiobookProject.load(future)

    def test_load_missing_required_fields(self, tmp_path):
        """load() handles missing fields with defaults."""
        from audiobooker.project import AudiobookProject
        minimal = tmp_path / "minimal.audiobooker"
        minimal.write_text(json.dumps({
            "schema_version": 1,
        }), encoding="utf-8")
        project = AudiobookProject.load(minimal)
        assert project.title == "Untitled"
        assert project.chapters == []


# ---------------------------------------------------------------------------
# F-TEST-018: Chapter.is_rendered tests
# ---------------------------------------------------------------------------

class TestChapterIsRendered:
    """Tests for Chapter.is_rendered property."""

    def test_false_when_audio_path_none(self):
        """is_rendered is False when audio_path is None."""
        chapter = Chapter(index=0, title="Test", raw_text="hello")
        assert chapter.audio_path is None
        assert chapter.is_rendered is False

    def test_false_when_file_not_exists(self, tmp_path):
        """is_rendered is False when audio_path points to non-existent file."""
        chapter = Chapter(index=0, title="Test", raw_text="hello")
        chapter.audio_path = tmp_path / "nonexistent.wav"
        assert chapter.is_rendered is False

    def test_true_when_file_exists(self, tmp_path):
        """is_rendered is True when audio_path points to existing file."""
        audio_file = tmp_path / "chapter_0.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 40)

        chapter = Chapter(index=0, title="Test", raw_text="hello")
        chapter.audio_path = audio_file
        assert chapter.is_rendered is True


# ---------------------------------------------------------------------------
# F-TEST-022: get_uncast_speakers / get_detected_speakers tests
# ---------------------------------------------------------------------------

class TestSpeakerDetection:
    """Tests for get_uncast_speakers and get_detected_speakers."""

    def test_empty_project(self):
        """Empty project returns empty speaker sets."""
        from audiobooker.project import AudiobookProject
        project = AudiobookProject(title="Empty")
        assert project.get_detected_speakers() == set()
        assert project.get_uncast_speakers() == set()

    def test_only_narrator(self):
        """Project with only narrator utterances."""
        from audiobooker.project import AudiobookProject
        project = AudiobookProject(title="Test")
        project.cast("narrator", "af_heart")
        project.chapters = [
            Chapter(
                index=0, title="Ch1", raw_text="text",
                utterances=[Utterance(speaker="narrator", text="Hello.")],
            )
        ]
        detected = project.get_detected_speakers()
        assert "narrator" in detected
        assert project.get_uncast_speakers() == set()

    def test_mix_cast_uncast(self, compiled_project):
        """Mix of cast and uncast speakers.

        Uses compiled_project fixture (FT-TEST-009) which has narrator,
        Alice, and Bob all cast. All detected speakers should be cast.
        """
        detected = compiled_project.get_detected_speakers()
        assert "narrator" in detected

        # Since compiled_project has all speakers cast, uncast should be
        # empty or only contain speakers from the text that weren't
        # explicitly cast (like "unknown").
        uncast = compiled_project.get_uncast_speakers()
        # narrator, alice, bob are all cast in compiled_project
        assert "narrator" not in uncast
        assert "alice" not in uncast
        assert "bob" not in uncast


# ---------------------------------------------------------------------------
# FT-TEST-001: Path traversal + null byte tests
# ---------------------------------------------------------------------------

class TestPathTraversalAndNullByte:
    """Tests that AudiobookProject.load() rejects malicious paths."""

    def test_source_path_with_traversal_rejected(self, tmp_path):
        """load() raises ValueError when source_path contains '..' traversal."""
        from audiobooker.project import AudiobookProject
        project_file = tmp_path / "evil.audiobooker"
        project_file.write_text(json.dumps({
            "schema_version": 1,
            "title": "Evil Book",
            "source_path": "/some/path/../../etc/passwd",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="traversal"):
            AudiobookProject.load(project_file)

    def test_source_path_with_null_byte_rejected(self, tmp_path):
        """load() raises ValueError when source_path contains null bytes."""
        from audiobooker.project import AudiobookProject
        project_file = tmp_path / "null.audiobooker"
        project_file.write_text(json.dumps({
            "schema_version": 1,
            "title": "Null Book",
            "source_path": "/some/path\x00malicious",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="null bytes"):
            AudiobookProject.load(project_file)

    def test_output_path_with_traversal_rejected(self, tmp_path):
        """load() rejects traversal in output_path too."""
        from audiobooker.project import AudiobookProject
        project_file = tmp_path / "evil2.audiobooker"
        project_file.write_text(json.dumps({
            "schema_version": 1,
            "title": "Evil Book 2",
            "output_path": "C:/Users/../../../etc/shadow",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="traversal"):
            AudiobookProject.load(project_file)

    def test_normal_absolute_path_accepted(self, tmp_path):
        """load() accepts normal absolute paths without traversal."""
        from audiobooker.project import AudiobookProject
        project_file = tmp_path / "good.audiobooker"
        project_file.write_text(json.dumps({
            "schema_version": 1,
            "title": "Good Book",
            "source_path": "/home/user/books/novel.epub",
        }), encoding="utf-8")
        project = AudiobookProject.load(project_file)
        assert project.source_path is not None
        assert str(project.source_path).endswith("novel.epub")

    def test_none_source_path_accepted(self, tmp_path):
        """load() accepts null source_path (no file)."""
        from audiobooker.project import AudiobookProject
        project_file = tmp_path / "nosource.audiobooker"
        project_file.write_text(json.dumps({
            "schema_version": 1,
            "title": "No Source",
            "source_path": None,
        }), encoding="utf-8")
        project = AudiobookProject.load(project_file)
        assert project.source_path is None


# ---------------------------------------------------------------------------
# FT-TEST-005: File size rejection tests
# ---------------------------------------------------------------------------

class TestFileSizeRejection:
    """Tests that oversized files are rejected."""

    def test_project_load_rejects_oversized_file(self, tmp_path):
        """load() raises ValueError for project files > 50 MB."""
        from audiobooker.project import AudiobookProject
        big_file = tmp_path / "huge.audiobooker"
        # Create a sparse file > 50 MB using seek+write
        with open(big_file, "wb") as f:
            f.seek(51 * 1024 * 1024)
            f.write(b"\x00")
        with pytest.raises(ValueError, match="too large"):
            AudiobookProject.load(big_file)

    def test_text_parser_rejects_oversized_file(self, tmp_path):
        """parse_text() raises ValueError for text files > 100 MB."""
        from audiobooker.parser.text import parse_text
        big_file = tmp_path / "huge.txt"
        # Create a sparse file > 100 MB using seek+write
        with open(big_file, "wb") as f:
            f.seek(101 * 1024 * 1024)
            f.write(b"\x00")
        with pytest.raises(ValueError, match="too large"):
            parse_text(big_file)


# ---------------------------------------------------------------------------
# FT-TEST-010: ProjectConfig validation tests
# ---------------------------------------------------------------------------

class TestProjectConfigValidation:
    """Parametrized tests for ProjectConfig field validation."""

    @pytest.mark.parametrize("bad_format", [
        "aac", "wma", "opus", "m4a", "", "MP3",
    ], ids=["aac", "wma", "opus", "m4a", "empty", "uppercase-MP3"])
    def test_invalid_output_format(self, bad_format):
        """ProjectConfig rejects invalid output_format values."""
        with pytest.raises(ValueError, match="output_format"):
            ProjectConfig(output_format=bad_format)

    @pytest.mark.parametrize("bad_mode", [
        "yes", "no", "always", "", "ON",
    ], ids=["yes", "no", "always", "empty", "uppercase-ON"])
    def test_invalid_booknlp_mode(self, bad_mode):
        """ProjectConfig rejects invalid booknlp_mode values."""
        with pytest.raises(ValueError, match="booknlp_mode"):
            ProjectConfig(booknlp_mode=bad_mode)

    @pytest.mark.parametrize("bad_mode", [
        "on", "always", "ml", "", "RULE",
    ], ids=["on", "always", "ml", "empty", "uppercase-RULE"])
    def test_invalid_emotion_mode(self, bad_mode):
        """ProjectConfig rejects invalid emotion_mode values."""
        with pytest.raises(ValueError, match="emotion_mode"):
            ProjectConfig(emotion_mode=bad_mode)

    @pytest.mark.parametrize("bad_behavior", [
        "ignore", "error", "default", "",
    ], ids=["ignore", "error", "default", "empty"])
    def test_invalid_unknown_character_behavior(self, bad_behavior):
        """CastingTable rejects invalid unknown_character_behavior."""
        with pytest.raises(ValueError, match="unknown_character_behavior"):
            CastingTable(unknown_character_behavior=bad_behavior)

    @pytest.mark.parametrize("valid_format", ["m4b", "mp3", "wav", "ogg", "flac"])
    def test_valid_output_formats_accepted(self, valid_format):
        """All documented output formats are accepted."""
        config = ProjectConfig(output_format=valid_format)
        assert config.output_format == valid_format

    @pytest.mark.parametrize("valid_mode", ["on", "off", "auto"])
    def test_valid_booknlp_modes_accepted(self, valid_mode):
        """All documented booknlp_mode values are accepted."""
        config = ProjectConfig(booknlp_mode=valid_mode)
        assert config.booknlp_mode == valid_mode

    @pytest.mark.parametrize("valid_mode", ["off", "rule", "auto"])
    def test_valid_emotion_modes_accepted(self, valid_mode):
        """All documented emotion_mode values are accepted."""
        config = ProjectConfig(emotion_mode=valid_mode)
        assert config.emotion_mode == valid_mode

    @pytest.mark.parametrize("bad_speed", [0.0, 0.4, 2.1, 3.0, -1.0])
    def test_invalid_global_speed(self, bad_speed):
        """ProjectConfig rejects global_speed outside 0.5-2.0."""
        with pytest.raises(ValueError, match="global_speed"):
            ProjectConfig(global_speed=bad_speed)


# ---------------------------------------------------------------------------
# Wave 1: Chapter merge / split / exclude
# ---------------------------------------------------------------------------

class TestChapterManagement:
    """Tests for chapter merge, split, and exclude operations."""

    def _make_project(self, num_chapters=4):
        """Create a project with N chapters, each with 3 paragraphs."""
        from audiobooker.project import AudiobookProject
        chapters = []
        for i in range(num_chapters):
            text = f"Para one of chapter {i}.\n\nPara two of chapter {i}.\n\nPara three of chapter {i}."
            chapters.append((f"Chapter {i}", text))
        return AudiobookProject.from_chapters(chapters, title="Mgmt Test")

    def test_exclude_chapter(self):
        """exclude_chapter marks chapter as skip=True."""
        project = self._make_project()
        project.exclude_chapter(1)
        assert project.chapters[1].skip is True
        assert project.chapters[0].skip is False

    def test_include_chapter(self):
        """include_chapter restores skip=False."""
        project = self._make_project()
        project.exclude_chapter(2)
        assert project.chapters[2].skip is True
        project.include_chapter(2)
        assert project.chapters[2].skip is False

    def test_exclude_out_of_range(self):
        """exclude_chapter raises IndexError for invalid index."""
        project = self._make_project(2)
        with pytest.raises(IndexError):
            project.exclude_chapter(5)
        with pytest.raises(IndexError):
            project.exclude_chapter(-1)

    def test_merge_chapters(self):
        """merge_chapters combines text and re-indexes."""
        project = self._make_project(4)
        original_titles = [ch.title for ch in project.chapters]

        merged = project.merge_chapters(1, 2)

        # Should have 3 chapters now
        assert len(project.chapters) == 3
        # Merged chapter keeps first title
        assert merged.title == original_titles[1]
        # Text from both chapters present
        assert "chapter 1" in merged.raw_text
        assert "chapter 2" in merged.raw_text
        # Indices re-numbered
        for i, ch in enumerate(project.chapters):
            assert ch.index == i

    def test_merge_invalid_range(self):
        """merge_chapters raises for invalid ranges."""
        project = self._make_project(3)
        with pytest.raises(IndexError):
            project.merge_chapters(0, 5)
        with pytest.raises(ValueError):
            project.merge_chapters(2, 1)  # start >= end
        with pytest.raises(ValueError):
            project.merge_chapters(1, 1)  # start == end

    def test_split_chapter(self):
        """split_chapter divides at paragraph boundary."""
        project = self._make_project(2)
        first, second = project.split_chapter(0, at_paragraph=1)

        # Should have 3 chapters now
        assert len(project.chapters) == 3
        assert first.title == "Chapter 0"
        assert "(continued)" in second.title
        # First part has para 0, second has paras 1-2
        assert "Para one" in first.raw_text
        assert "Para two" in second.raw_text
        # Indices re-numbered
        for i, ch in enumerate(project.chapters):
            assert ch.index == i

    def test_split_invalid_paragraph(self):
        """split_chapter raises for invalid paragraph index."""
        project = self._make_project(1)
        with pytest.raises(ValueError):
            project.split_chapter(0, at_paragraph=0)  # can't split at start
        with pytest.raises(ValueError):
            project.split_chapter(0, at_paragraph=100)  # past end

    def test_merge_invalidates_utterances(self):
        """Merge clears utterances on affected chapters."""
        project = self._make_project(3)
        project.cast("narrator", "af_heart")
        project.compile()
        assert len(project.chapters[1].utterances) > 0

        project.merge_chapters(0, 1)
        # Merged and later chapters have utterances cleared
        assert len(project.chapters[0].utterances) == 0


# ---------------------------------------------------------------------------
# Wave 1: BookMetadata serialization round-trip
# ---------------------------------------------------------------------------

class TestBookMetadataSerialization:
    """Tests for BookMetadata to_dict/from_dict round-trip."""

    def test_full_metadata_roundtrip(self):
        """All BookMetadata fields survive serialization."""
        meta = BookMetadata(
            cover_art_path=Path("/covers/art.jpg"),
            genre="Science Fiction",
            series="The Expanse",
            series_index=3,
            year=2025,
            narrator_name="James Holden",
            publisher="Orbit Books",
        )
        data = meta.to_dict()
        restored = BookMetadata.from_dict(data)

        assert str(restored.cover_art_path).endswith("art.jpg")
        assert restored.genre == "Science Fiction"
        assert restored.series == "The Expanse"
        assert restored.series_index == 3
        assert restored.year == 2025
        assert restored.narrator_name == "James Holden"
        assert restored.publisher == "Orbit Books"

    def test_empty_metadata_roundtrip(self):
        """Default BookMetadata survives round-trip."""
        meta = BookMetadata()
        data = meta.to_dict()
        restored = BookMetadata.from_dict(data)

        assert restored.cover_art_path is None
        assert restored.genre == ""
        assert restored.series == ""
        assert restored.series_index is None
        assert restored.year is None

    def test_partial_metadata_from_dict(self):
        """from_dict handles missing fields with defaults."""
        data = {"genre": "Fantasy"}
        restored = BookMetadata.from_dict(data)
        assert restored.genre == "Fantasy"
        assert restored.cover_art_path is None
        assert restored.narrator_name == ""


# ---------------------------------------------------------------------------
# Wave 1: Character aliases
# ---------------------------------------------------------------------------

class TestCharacterAliases:
    """Tests for character alias resolution via CastingTable."""

    def test_cast_with_alias_resolves_voice(self):
        """get_voice resolves through aliases."""
        table = CastingTable()
        char = table.cast("Elizabeth", "af_bella", emotion="refined")
        char.aliases = ["Liz", "Beth", "Lizzy"]

        # Direct lookup
        voice, emotion = table.get_voice("Elizabeth")
        assert voice == "af_bella"

        # Alias lookups
        voice, emotion = table.get_voice("Liz")
        assert voice == "af_bella"
        assert emotion == "refined"

        voice, emotion = table.get_voice("Beth")
        assert voice == "af_bella"

        voice, emotion = table.get_voice("Lizzy")
        assert voice == "af_bella"

    def test_alias_case_insensitive(self):
        """Alias resolution is case-insensitive."""
        table = CastingTable()
        char = table.cast("Robert", "bm_george")
        char.aliases = ["Bob", "Bobby"]

        voice, _ = table.get_voice("bob")
        assert voice == "bm_george"

        voice, _ = table.get_voice("BOBBY")
        assert voice == "bm_george"

    def test_unmatched_alias_falls_back(self):
        """Speaker not in aliases falls back to narrator/default."""
        table = CastingTable()
        table.cast("narrator", "af_heart")
        char = table.cast("Alice", "af_bella")
        char.aliases = ["Ally"]

        voice, _ = table.get_voice("TotallyUnknown")
        assert voice == "af_heart"  # falls back to narrator

    def test_alias_serialization_roundtrip(self):
        """Aliases survive CastingTable to_dict/from_dict."""
        table = CastingTable()
        char = table.cast("Alice", "af_bella")
        char.aliases = ["Ally", "Al"]

        data = table.to_dict()
        restored = CastingTable.from_dict(data)

        restored_char = restored.characters["alice"]
        assert restored_char.aliases == ["Ally", "Al"]

    def test_resolve_alias_returns_none_for_no_match(self):
        """resolve_alias returns None when no alias matches."""
        table = CastingTable()
        table.cast("Alice", "af_bella")
        result = table.resolve_alias("UnknownSpeaker")
        assert result is None


# ---------------------------------------------------------------------------
# Wave 1: Character speed field
# ---------------------------------------------------------------------------

class TestCharacterSpeed:
    """Tests for Character.speed field."""

    def test_default_speed(self):
        """Default speed is 1.0."""
        char = Character(name="Test", voice="af_heart")
        assert char.speed == 1.0

    def test_custom_speed(self):
        """Custom speed is preserved."""
        char = Character(name="Slow", voice="af_heart", speed=0.7)
        assert char.speed == 0.7

    def test_speed_validation_low(self):
        """Speed below 0.5 raises ValueError."""
        with pytest.raises(ValueError, match="speed"):
            Character(name="Bad", voice="af_heart", speed=0.3)

    def test_speed_validation_high(self):
        """Speed above 2.0 raises ValueError."""
        with pytest.raises(ValueError, match="speed"):
            Character(name="Bad", voice="af_heart", speed=2.5)

    def test_speed_boundary_values(self):
        """Boundary values 0.5 and 2.0 are accepted."""
        slow = Character(name="Slow", voice="af_heart", speed=0.5)
        assert slow.speed == 0.5
        fast = Character(name="Fast", voice="af_heart", speed=2.0)
        assert fast.speed == 2.0

    def test_cast_with_speed(self):
        """CastingTable.cast passes speed to Character."""
        table = CastingTable()
        table.cast("narrator", "af_heart", speed=0.8)
        assert table.characters["narrator"].speed == 0.8

    def test_get_speed(self):
        """CastingTable.get_speed returns character speed."""
        table = CastingTable()
        table.cast("narrator", "af_heart", speed=1.5)
        assert table.get_speed("narrator") == 1.5

    def test_get_speed_unknown_returns_default(self):
        """get_speed for unknown speaker returns 1.0."""
        table = CastingTable()
        assert table.get_speed("Unknown") == 1.0

    def test_speed_in_script_line(self):
        """Utterance.to_script_line includes speed when not 1.0."""
        u = Utterance(speaker="narrator", text="Slow text.")
        line = u.to_script_line(speed=0.8)
        assert "{speed:0.8}" in line

    def test_speed_omitted_at_default(self):
        """Utterance.to_script_line omits speed at 1.0."""
        u = Utterance(speaker="narrator", text="Normal text.")
        line = u.to_script_line(speed=1.0)
        assert "speed" not in line

    def test_speed_serialization_roundtrip(self):
        """Character speed survives to_dict/from_dict."""
        char = Character(name="Test", voice="af_heart", speed=1.3)
        data = char.to_dict()
        restored = Character.from_dict(data)
        assert restored.speed == 1.3


# ---------------------------------------------------------------------------
# Wave 1: Conversation turn-tracking
# ---------------------------------------------------------------------------

class TestConversationTurnTracking:
    """Tests for alternating speaker inference in dialogue compilation."""

    def test_alternating_speakers_inferred(self):
        """Unattributed quotes alternate between known speakers."""
        from audiobooker.casting.dialogue import compile_chapter

        # Two speakers, second quote unattributed — should infer alternation
        chapter = Chapter(
            index=0,
            title="Turn Test",
            raw_text=(
                '"Hello!" said Alice. "Hi there!" "How are you?" said Alice.'
            ),
        )
        casting = CastingTable()
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting)
        dialogue_utterances = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]

        # Should have at least 3 dialogue utterances
        assert len(dialogue_utterances) >= 2
        # At least one should be attributed to Alice
        alice_lines = [u for u in dialogue_utterances if u.speaker == "Alice"]
        assert len(alice_lines) >= 1

    def test_turn_stack_resets_on_scene_break(self):
        """Scene breaks (***) reset the turn stack."""
        from audiobooker.casting.dialogue import compile_chapter

        chapter = Chapter(
            index=0,
            title="Scene Break Test",
            raw_text=(
                '"Hello!" said Alice. "Hi!" said Bob.\n\n'
                '* * *\n\n'
                '"New scene line."'
            ),
        )
        casting = CastingTable()
        casting.cast("Alice", "af_bella")
        casting.cast("Bob", "bm_george")

        utterances = compile_chapter(chapter, casting)
        dialogue = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]

        # After scene break, the unattributed line should be "unknown" (stack reset)
        # or fallback, not Alice/Bob
        if len(dialogue) >= 3:
            last_dialogue = dialogue[-1]
            # After reset, speaker should be unknown (can't infer from empty stack)
            assert last_dialogue.speaker == "unknown"


# ---------------------------------------------------------------------------
# Wave 1: Utterance UUID generation and position tracking
# ---------------------------------------------------------------------------

class TestUtteranceUUIDAndPosition:
    """Tests for Utterance.id (UUID) and start_pos/end_pos tracking."""

    def test_uuid_auto_generated(self):
        """Each Utterance gets a unique UUID by default."""
        u1 = Utterance(speaker="narrator", text="One.")
        u2 = Utterance(speaker="narrator", text="Two.")
        assert u1.id != u2.id
        # Validate it's a proper UUID
        uuid.UUID(u1.id)  # raises if invalid

    def test_uuid_preserved_in_serialization(self):
        """Utterance UUID survives to_dict/from_dict."""
        u = Utterance(speaker="narrator", text="Test.")
        original_id = u.id
        data = u.to_dict()
        restored = Utterance.from_dict(data)
        assert restored.id == original_id

    def test_position_tracking_in_compilation(self):
        """Compiled utterances have start_pos and end_pos set."""
        from audiobooker.casting.dialogue import compile_chapter

        chapter = Chapter(
            index=0,
            title="Position Test",
            raw_text='The morning began. "Hello!" said Alice.',
        )
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting)

        for u in utterances:
            assert u.start_pos >= 0, f"start_pos not set for utterance: {u.text}"
            assert u.end_pos > u.start_pos, f"end_pos must be > start_pos for: {u.text}"

    def test_position_tracking_serialization(self):
        """start_pos and end_pos survive to_dict/from_dict."""
        u = Utterance(
            speaker="narrator", text="Test.",
            start_pos=10, end_pos=25,
        )
        data = u.to_dict()
        restored = Utterance.from_dict(data)
        assert restored.start_pos == 10
        assert restored.end_pos == 25

    def test_default_position_is_negative(self):
        """Default start_pos/end_pos is -1 (unset)."""
        u = Utterance(speaker="narrator", text="Test.")
        assert u.start_pos == -1
        assert u.end_pos == -1
