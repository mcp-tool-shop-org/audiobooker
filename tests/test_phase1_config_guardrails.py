"""Tests for Phase 1: Correctness + Config Guardrails."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from audiobooker.models import (
    CastingTable,
    ProjectConfig,
    Chapter,
    Utterance,
)


# ---------------------------------------------------------------------------
# 1.2 + 1.7 ProjectConfig new fields
# ---------------------------------------------------------------------------

class TestProjectConfigNewFields:
    """New config fields serialize/deserialize cleanly."""

    def test_defaults(self):
        cfg = ProjectConfig()
        assert cfg.fallback_voice_id == "af_heart"
        assert cfg.validate_voices_on_render is True
        assert cfg.estimated_wpm == 150
        assert cfg.min_chapter_words == 50
        assert cfg.keep_titled_short_chapters is True

    def test_custom_values(self):
        cfg = ProjectConfig(
            fallback_voice_id="bm_george",
            validate_voices_on_render=False,
            estimated_wpm=120,
            min_chapter_words=30,
            keep_titled_short_chapters=False,
        )
        assert cfg.fallback_voice_id == "bm_george"
        assert cfg.validate_voices_on_render is False
        assert cfg.estimated_wpm == 120
        assert cfg.min_chapter_words == 30
        assert cfg.keep_titled_short_chapters is False

    def test_roundtrip(self):
        cfg = ProjectConfig(
            fallback_voice_id="am_liam",
            validate_voices_on_render=False,
            estimated_wpm=180,
            min_chapter_words=25,
            keep_titled_short_chapters=False,
        )
        data = cfg.to_dict()
        restored = ProjectConfig.from_dict(data)
        assert restored.fallback_voice_id == "am_liam"
        assert restored.validate_voices_on_render is False
        assert restored.estimated_wpm == 180
        assert restored.min_chapter_words == 25
        assert restored.keep_titled_short_chapters is False

    def test_from_dict_missing_new_fields_uses_defaults(self):
        """Old project files without new fields load safely."""
        old_data = {
            "chapter_pause_ms": 2000,
            "sample_rate": 24000,
        }
        cfg = ProjectConfig.from_dict(old_data)
        assert cfg.fallback_voice_id == "af_heart"
        assert cfg.validate_voices_on_render is True
        assert cfg.estimated_wpm == 150
        assert cfg.min_chapter_words == 50
        assert cfg.keep_titled_short_chapters is True

    def test_estimated_wpm_used_by_project(self):
        """Project.estimated_duration_minutes uses config WPM."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(
            config=ProjectConfig(estimated_wpm=100),
        )
        # 300 words at 100 wpm = 3 minutes
        project.chapters = [
            Chapter(index=0, title="Ch1", raw_text=" ".join(["word"] * 300))
        ]
        assert project.estimated_duration_minutes == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 1.4 CastingTable fallback_voice_id
# ---------------------------------------------------------------------------

class TestCastingTableFallback:
    """CastingTable uses configurable fallback, not a literal."""

    def test_default_fallback(self):
        table = CastingTable()
        voice, emotion = table.get_voice("nobody")
        assert voice == "af_heart"
        assert emotion is None

    def test_custom_fallback(self):
        table = CastingTable(fallback_voice_id="bm_george")
        voice, emotion = table.get_voice("nobody")
        assert voice == "bm_george"
        assert emotion is None

    def test_mapped_speaker_ignores_fallback(self):
        table = CastingTable(fallback_voice_id="bm_george")
        table.cast("Alice", "af_bella", emotion="warm")
        voice, emotion = table.get_voice("Alice")
        assert voice == "af_bella"
        assert emotion == "warm"

    def test_narrator_fallback_before_ultimate(self):
        table = CastingTable(fallback_voice_id="bm_george")
        table.cast("narrator", "af_sky")
        voice, _ = table.get_voice("unknown")
        assert voice == "af_sky"  # narrator, not ultimate fallback

    def test_case_insensitive_lookup(self):
        table = CastingTable()
        table.cast("Alice", "af_bella")
        voice, _ = table.get_voice("alice")
        assert voice == "af_bella"
        voice2, _ = table.get_voice("ALICE")
        assert voice2 == "af_bella"

    def test_fallback_roundtrip(self):
        table = CastingTable(fallback_voice_id="am_onyx")
        data = table.to_dict()
        restored = CastingTable.from_dict(data)
        assert restored.fallback_voice_id == "am_onyx"

    def test_from_dict_missing_fallback_uses_default(self):
        old_data = {"characters": {}, "default_narrator": "narrator"}
        table = CastingTable.from_dict(old_data)
        assert table.fallback_voice_id == "af_heart"

    def test_project_syncs_config_to_casting(self):
        """ProjectConfig.fallback_voice_id propagates to CastingTable."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(
            config=ProjectConfig(fallback_voice_id="am_fenrir"),
        )
        assert project.casting.fallback_voice_id == "am_fenrir"


# ---------------------------------------------------------------------------
# 1.3 Voice validation
# ---------------------------------------------------------------------------

class TestVoiceValidation:
    """Voice registry + VoiceNotFoundError."""

    def test_validate_voices_all_present(self):
        from audiobooker.casting.voice_registry import validate_voices

        available = {"af_heart", "bm_george", "af_bella"}
        missing = validate_voices({"af_heart", "bm_george"}, available)
        assert missing == []

    def test_validate_voices_some_missing(self):
        from audiobooker.casting.voice_registry import validate_voices

        available = {"af_heart", "bm_george"}
        missing = validate_voices({"af_heart", "fake_voice"}, available)
        assert missing == ["fake_voice"]

    def test_voice_not_found_error_message(self):
        from audiobooker.casting.voice_registry import VoiceNotFoundError

        err = VoiceNotFoundError(missing=["fake_voice"], available_count=20)
        assert "fake_voice" in str(err)
        assert "20 voices available" in str(err)
        assert "audiobooker voices" in str(err)

    def test_project_validate_voices_raises(self):
        """render() raises VoiceNotFoundError when voices are missing."""
        from audiobooker.project import AudiobookProject
        from audiobooker.casting.voice_registry import VoiceNotFoundError

        project = AudiobookProject(
            config=ProjectConfig(validate_voices_on_render=True),
        )
        project.cast("narrator", "nonexistent_voice")
        project.chapters = [
            Chapter(
                index=0,
                title="Test",
                raw_text="Hello world " * 20,
                utterances=[Utterance(speaker="narrator", text="Hello world")],
            )
        ]

        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart", "bm_george"},
        ):
            with pytest.raises(VoiceNotFoundError) as exc_info:
                project.render()
            assert "nonexistent_voice" in str(exc_info.value)

    def test_project_skip_validation_when_disabled(self):
        """render() skips validation when validate_voices_on_render=False."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(
            config=ProjectConfig(validate_voices_on_render=False),
        )
        project.cast("narrator", "nonexistent_voice")
        project.chapters = [
            Chapter(
                index=0,
                title="Test",
                raw_text="Hello world " * 20,
                utterances=[Utterance(speaker="narrator", text="Hello")],
            )
        ]

        # Should NOT call get_available_voices at all
        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
        ) as mock_get:
            # Will fail at render_project (no voice-soundboard), but
            # validation should be skipped — we only care that
            # get_available_voices was never called
            with pytest.raises(Exception):
                project.render()
            mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 1.5 FFmpeg chapter embedding: no silent fallback
# ---------------------------------------------------------------------------

class TestAssemblyResult:
    """AssemblyResult tracks chapter embedding status."""

    def test_success_result(self):
        from audiobooker.renderer.output import AssemblyResult

        result = AssemblyResult(
            output_path=Path("test.m4b"),
            chapters_embedded=True,
        )
        assert result.chapters_embedded is True
        assert result.chapter_error == ""

    def test_fallback_result(self):
        from audiobooker.renderer.output import AssemblyResult

        result = AssemblyResult(
            output_path=Path("test.m4a"),
            chapters_embedded=False,
            chapter_error="Conversion failed: unknown codec",
        )
        assert result.chapters_embedded is False
        assert "unknown codec" in result.chapter_error


# ---------------------------------------------------------------------------
# 1.6 EPUB short-section dropping
# ---------------------------------------------------------------------------

class TestEpubShortSections:
    """EPUB parser respects min_chapter_words and keep_titled_short_chapters."""

    def test_parse_epub_signature_accepts_thresholds(self):
        """parse_epub accepts min_chapter_words and keep_titled_short_chapters."""
        import inspect
        from audiobooker.parser.epub import parse_epub

        sig = inspect.signature(parse_epub)
        assert "min_chapter_words" in sig.parameters
        assert "keep_titled_short_chapters" in sig.parameters

    def test_project_config_round_trip_with_epub_fields(self):
        """min_chapter_words and keep_titled_short_chapters survive save/load."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(
            config=ProjectConfig(
                min_chapter_words=25,
                keep_titled_short_chapters=False,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.audiobooker"
            project.save(path)
            loaded = AudiobookProject.load(path)

            assert loaded.config.min_chapter_words == 25
            assert loaded.config.keep_titled_short_chapters is False


# ---------------------------------------------------------------------------
# Full project roundtrip with all new fields
# ---------------------------------------------------------------------------

class TestFullProjectRoundtrip:
    """All new config fields survive save/load cycle."""

    def test_save_load_roundtrip(self):
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(
            title="Test Book",
            config=ProjectConfig(
                fallback_voice_id="am_fenrir",
                validate_voices_on_render=False,
                estimated_wpm=120,
                min_chapter_words=30,
                keep_titled_short_chapters=False,
            ),
        )
        project.cast("narrator", "bm_george")
        project.casting.fallback_voice_id = "am_fenrir"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.audiobooker"
            project.save(path)

            loaded = AudiobookProject.load(path)
            assert loaded.config.fallback_voice_id == "am_fenrir"
            assert loaded.config.validate_voices_on_render is False
            assert loaded.config.estimated_wpm == 120
            assert loaded.config.min_chapter_words == 30
            assert loaded.config.keep_titled_short_chapters is False
            assert loaded.casting.fallback_voice_id == "am_fenrir"
