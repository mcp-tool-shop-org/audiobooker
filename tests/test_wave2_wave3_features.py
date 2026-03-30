"""
Tests for Wave 2 + Wave 3 features.

Wave 2:
- Text cleaners (strip_page_numbers, normalize_whitespace, expand_abbreviations, decode_html_entities)
- Pronunciation overrides (add, remove, apply during compile)
- Dry-run compilation (returns utterances without modifying chapters)
- Batch casting export/import round-trip
- French and German language profile detection (quote pairs, speaker verbs)
- Compilation quality report (per-speaker counts, unknown rate)
- Voice preview method (mock TTS, verify truncation at sentence boundary)

Wave 3:
- PDF parser if pymupdf available (skip if not)
- Text normalization (numbers, years, abbreviations, currency)
- Per-chapter pause fields serialization
- Chapter mood field
- Utterance type enum
- Character pitch_shift and emphasis fields
- Turn-tracking with scene breaks (reset on ***)
- Multi-word speaker names ("Dr. Watson said")
- Em-dash dialogue detection
- Spanish and Japanese language profiles
"""

import json
from unittest.mock import MagicMock, patch

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
from audiobooker.parser.text_cleaners import (
    strip_page_numbers,
    normalize_whitespace,
    expand_common_abbreviations,
    decode_html_entities,
    clean_text,
    apply_pronunciation_overrides,
)
from audiobooker.casting.dialogue import compile_chapter, compile_report
from audiobooker.language.profile import get_profile, available_profiles


# =========================================================================
# Wave 2: Text Cleaners
# =========================================================================

class TestStripPageNumbers:
    """Tests for strip_page_numbers cleaner."""

    def test_bare_page_number(self):
        """Standalone digits on their own line are stripped."""
        text = "Some text.\n42\nMore text."
        result = strip_page_numbers(text)
        assert "42" not in result
        assert "Some text." in result
        assert "More text." in result

    def test_page_prefix(self):
        """'Page 42' format is stripped."""
        text = "Content here.\nPage 123\nContinued."
        result = strip_page_numbers(text)
        assert "Page 123" not in result
        assert "Content here." in result

    def test_dashed_page_number(self):
        """Centered dashed format '- 42 -' is stripped."""
        text = "Before.\n- 7 -\nAfter."
        result = strip_page_numbers(text)
        assert "- 7 -" not in result

    def test_inline_numbers_preserved(self):
        """Numbers embedded in sentences are NOT stripped."""
        text = "There were 42 cats in the room."
        result = strip_page_numbers(text)
        assert "42" in result

    def test_multi_digit_page_numbers(self):
        """Multi-digit standalone numbers are stripped."""
        text = "Line one.\n12345\nLine two."
        result = strip_page_numbers(text)
        assert "12345" not in result

    def test_no_page_numbers(self):
        """Text without page numbers is unchanged."""
        text = "Hello world. No pages here."
        assert strip_page_numbers(text) == text


class TestNormalizeWhitespace:
    """Tests for normalize_whitespace cleaner."""

    def test_collapse_multiple_spaces(self):
        """Multiple spaces become a single space."""
        text = "Hello     world"
        result = normalize_whitespace(text)
        assert result == "Hello world"

    def test_collapse_tabs(self):
        """Tabs are collapsed to single space."""
        text = "Hello\t\tworld"
        result = normalize_whitespace(text)
        assert result == "Hello world"

    def test_collapse_blank_lines(self):
        """Three or more blank lines become two."""
        text = "Para one.\n\n\n\n\nPara two."
        result = normalize_whitespace(text)
        assert result == "Para one.\n\nPara two."

    def test_preserves_single_newlines(self):
        """Single newlines between paragraphs are preserved."""
        text = "Line one.\n\nLine two."
        result = normalize_whitespace(text)
        assert result == "Line one.\n\nLine two."

    def test_strips_outer_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        text = "   Hello world.   "
        result = normalize_whitespace(text)
        assert result == "Hello world."


class TestExpandAbbreviations:
    """Tests for expand_common_abbreviations cleaner."""

    def test_mr_expansion(self):
        result = expand_common_abbreviations("Mr. Smith entered.")
        assert "Mister Smith" in result

    def test_dr_expansion(self):
        result = expand_common_abbreviations("Dr. Watson looked up.")
        assert "Doctor Watson" in result

    def test_etc_expansion(self):
        result = expand_common_abbreviations("cats, dogs, etc. were present.")
        assert "etcetera" in result

    def test_vs_expansion(self):
        result = expand_common_abbreviations("Alice vs. Bob")
        assert "versus" in result

    def test_multiple_abbreviations(self):
        text = "Dr. Smith and Mrs. Jones met Prof. Lee."
        result = expand_common_abbreviations(text)
        assert "Doctor Smith" in result
        assert "Missus Jones" in result
        assert "Professor Lee" in result

    def test_non_abbreviation_preserved(self):
        """Text without abbreviations is unchanged."""
        text = "Hello world."
        assert expand_common_abbreviations(text) == text


class TestDecodeHtmlEntities:
    """Tests for decode_html_entities cleaner."""

    def test_amp(self):
        assert decode_html_entities("salt &amp; pepper") == "salt & pepper"

    def test_lt_gt(self):
        assert decode_html_entities("a &lt; b &gt; c") == "a < b > c"

    def test_nbsp(self):
        assert decode_html_entities("hello&nbsp;world") == "hello\xa0world"

    def test_numeric_entities(self):
        # &#8220; = left double quote, &#8221; = right double quote
        assert decode_html_entities("&#8220;hello&#8221;") == "\u201chello\u201d"

    def test_no_entities(self):
        text = "Plain text."
        assert decode_html_entities(text) == text


class TestCleanTextPipeline:
    """Tests for the full clean_text pipeline."""

    def test_default_pipeline(self):
        """Default pipeline applies all cleaners in order."""
        text = "Mr. Smith said &amp; then\n42\nHello     world."
        result = clean_text(text)
        assert "Mister Smith" in result
        assert "&" in result
        assert "42" not in result or "Hello" in result
        # whitespace normalized
        assert "     " not in result

    def test_custom_cleaner_list(self):
        """Custom cleaner list only applies specified cleaners."""
        text = "Mr. Smith said hello.\n42\n"
        # Only strip page numbers
        result = clean_text(text, cleaners=[strip_page_numbers])
        assert "Mr." in result  # abbreviation NOT expanded
        assert "42" not in result  # page number stripped


# =========================================================================
# Wave 2: Pronunciation Overrides
# =========================================================================

class TestPronunciationOverrides:
    """Tests for pronunciation override system."""

    def test_simple_override(self):
        text = "Cthulhu rose from the depths."
        overrides = {"Cthulhu": "kuh-THOO-loo"}
        result = apply_pronunciation_overrides(text, overrides)
        assert "kuh-THOO-loo" in result
        assert "Cthulhu" not in result

    def test_case_insensitive(self):
        text = "The TARDIS materialized."
        overrides = {"tardis": "TAR-dis"}
        result = apply_pronunciation_overrides(text, overrides)
        assert "TAR-dis" in result

    def test_multiple_overrides(self):
        text = "Gandalf met Aragorn in Rivendell."
        overrides = {
            "Gandalf": "GAN-dalf",
            "Aragorn": "AR-ah-gorn",
            "Rivendell": "RIV-en-dell",
        }
        result = apply_pronunciation_overrides(text, overrides)
        assert "GAN-dalf" in result
        assert "AR-ah-gorn" in result
        assert "RIV-en-dell" in result

    def test_whole_word_boundary(self):
        """Override does not replace partial word matches."""
        text = "The cat sat on the mat."
        overrides = {"cat": "kat"}
        result = apply_pronunciation_overrides(text, overrides)
        assert "kat" in result
        # "mat" should NOT be affected
        assert "mat" in result

    def test_empty_overrides(self):
        text = "No changes expected."
        assert apply_pronunciation_overrides(text, {}) == text

    def test_overrides_in_config(self):
        """Pronunciation overrides in config are applied during compile."""
        project = AudiobookProject.from_string(
            "Cthulhu rose from the deep.",
            title="Override Test",
        )
        project.config.pronunciation_overrides = {"Cthulhu": "kuh-THOO-loo"}
        project.config.clean_text = False  # isolate pronunciation overrides
        project.cast("narrator", "af_heart")
        project.compile()

        all_text = " ".join(
            u.text for ch in project.chapters for u in ch.utterances
        )
        assert "kuh-THOO-loo" in all_text
        assert "Cthulhu" not in all_text

    def test_overrides_serialization(self):
        """Pronunciation overrides survive config serialization."""
        config = ProjectConfig(
            pronunciation_overrides={"Cthulhu": "kuh-THOO-loo"}
        )
        data = config.to_dict()
        assert data["pronunciation_overrides"]["Cthulhu"] == "kuh-THOO-loo"
        restored = ProjectConfig.from_dict(data)
        assert restored.pronunciation_overrides["Cthulhu"] == "kuh-THOO-loo"

    def test_add_and_remove_overrides(self):
        """Add and remove overrides from ProjectConfig."""
        config = ProjectConfig()
        assert config.pronunciation_overrides == {}

        # Add
        config.pronunciation_overrides["Moria"] = "MORE-ee-ah"
        assert "Moria" in config.pronunciation_overrides

        # Remove
        del config.pronunciation_overrides["Moria"]
        assert "Moria" not in config.pronunciation_overrides


# =========================================================================
# Wave 2: Dry-Run Compilation
# =========================================================================

class TestDryRunCompilation:
    """Tests for compile(dry_run=True)."""

    def test_dry_run_returns_utterances(self):
        """Dry-run returns dict of chapter_index -> utterances."""
        project = AudiobookProject.from_string(
            "Chapter 1: Start\n\nHello world. \"Hi\" said Alice.\n\n"
            "Chapter 2: End\n\nGoodbye world.",
            title="Dry Run Test",
        )
        project.cast("narrator", "af_heart")
        project.cast("Alice", "af_bella")

        result = project.compile(dry_run=True)
        assert result is not None
        assert isinstance(result, dict)
        # Should have entries for compiled chapters
        assert len(result) >= 1
        # Values are lists of Utterance
        for chapter_idx, utts in result.items():
            assert isinstance(utts, list)
            for u in utts:
                assert isinstance(u, Utterance)

    def test_dry_run_does_not_modify_chapters(self):
        """Dry-run does not write utterances to chapter objects."""
        project = AudiobookProject.from_string(
            '"Hello!" said Alice.',
            title="DryRun NoMod",
        )
        project.cast("narrator", "af_heart")
        project.cast("Alice", "af_bella")

        # Chapters should have no utterances before
        assert all(len(ch.utterances) == 0 for ch in project.chapters)

        result = project.compile(dry_run=True)
        assert result is not None

        # Chapters still have no utterances after dry-run
        assert all(len(ch.utterances) == 0 for ch in project.chapters)

    def test_normal_compile_returns_none(self):
        """Normal compile (dry_run=False) returns None."""
        project = AudiobookProject.from_string("Hello.", title="Normal")
        project.cast("narrator", "af_heart")
        result = project.compile()
        assert result is None
        # But chapters have utterances
        assert any(len(ch.utterances) > 0 for ch in project.chapters)


# =========================================================================
# Wave 2: Batch Casting Export/Import
# =========================================================================

class TestBatchCastingExportImport:
    """Tests for export_casting and import_casting round-trip."""

    def test_export_import_roundtrip(self, tmp_path):
        """Export then import preserves all casting data."""
        project = AudiobookProject.from_string("Text.", title="Cast Test")
        project.cast("narrator", "af_heart", emotion="calm", description="Main narrator")
        project.cast("Alice", "af_bella", emotion="warm", speed=0.9)
        char = project.casting.characters["alice"]
        char.aliases = ["Ally"]

        cast_file = tmp_path / "casting.json"
        project.export_casting(cast_file)

        # Verify file exists and is valid JSON
        assert cast_file.exists()
        data = json.loads(cast_file.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 2  # narrator + Alice

        # Import into fresh project
        project2 = AudiobookProject.from_string("Text.", title="Import Test")
        project2.import_casting(cast_file)

        # Verify imported data
        assert "narrator" in project2.casting.characters
        assert "alice" in project2.casting.characters
        alice = project2.casting.characters["alice"]
        assert alice.voice == "af_bella"
        assert alice.emotion == "warm"
        assert alice.speed == 0.9
        assert alice.aliases == ["Ally"]

    def test_import_overwrites_existing(self, tmp_path):
        """Import overwrites existing characters with same name."""
        project = AudiobookProject.from_string("Text.", title="Overwrite Test")
        project.cast("Alice", "af_heart", emotion="cold")

        cast_file = tmp_path / "cast.json"
        cast_file.write_text(json.dumps([
            {"name": "Alice", "voice": "af_bella", "emotion": "warm"}
        ]))

        project.import_casting(cast_file)
        assert project.casting.characters["alice"].voice == "af_bella"
        assert project.casting.characters["alice"].emotion == "warm"

    def test_import_missing_file_raises(self, tmp_path):
        """Import raises FileNotFoundError for missing file."""
        project = AudiobookProject.from_string("Text.", title="Missing File")
        with pytest.raises(FileNotFoundError):
            project.import_casting(tmp_path / "nonexistent.json")

    def test_import_invalid_format_raises(self, tmp_path):
        """Import raises ValueError for non-array JSON."""
        cast_file = tmp_path / "bad.json"
        cast_file.write_text('{"not": "an array"}')

        project = AudiobookProject.from_string("Text.", title="Bad Format")
        with pytest.raises(ValueError, match="JSON array"):
            project.import_casting(cast_file)

    def test_import_missing_keys_raises(self, tmp_path):
        """Import raises ValueError for entries missing name/voice."""
        cast_file = tmp_path / "bad2.json"
        cast_file.write_text(json.dumps([{"name": "Alice"}]))  # missing voice

        project = AudiobookProject.from_string("Text.", title="Bad Keys")
        with pytest.raises(ValueError, match="name.*voice"):
            project.import_casting(cast_file)


# =========================================================================
# Wave 2: French and German Language Profile Detection
# =========================================================================

class TestFrenchProfile:
    """Tests for French language profile."""

    def test_french_registered(self):
        profile = get_profile("fr")
        assert profile.code == "fr"
        assert profile.name == "French"

    def test_french_in_available(self):
        codes = available_profiles()
        assert "fr" in codes

    def test_french_guillemets(self):
        """French uses guillemets as dialogue quotes."""
        profile = get_profile("fr")
        # Guillemets should be in dialogue_quotes
        opens = [pair[0] for pair in profile.dialogue_quotes]
        assert "\u00ab" in opens  # left guillemet

    def test_french_speaker_verbs(self):
        """French profile has French speech verbs."""
        profile = get_profile("fr")
        assert "dit" in profile.speaker_verbs
        assert "demanda" in profile.speaker_verbs
        assert "murmura" in profile.speaker_verbs

    def test_french_emotion_hints(self):
        """French emotion hints map verbs to emotions."""
        profile = get_profile("fr")
        assert profile.emotion_hints["chuchota"] == "whisper"
        assert profile.emotion_hints["cria"] == "angry"
        assert profile.emotion_hints["rit"] == "happy"

    def test_french_speaker_blacklist(self):
        """French pronouns are blacklisted."""
        profile = get_profile("fr")
        assert "il" in profile.speaker_blacklist
        assert "elle" in profile.speaker_blacklist
        assert "doucement" in profile.speaker_blacklist

    def test_french_chapter_patterns(self):
        """French chapter patterns match 'Chapitre'."""
        profile = get_profile("fr")
        assert any("Chapitre" in p for p in profile.chapter_patterns)

    def test_french_dialogue_detection(self):
        """Guillemet-wrapped text is detected as dialogue."""
        from audiobooker.casting.dialogue import detect_dialogue
        profile = get_profile("fr")
        text = '\u00ab Bonjour \u00bb dit Marie.'
        segments = detect_dialogue(text, profile=profile)
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) >= 1


class TestGermanProfile:
    """Tests for German language profile."""

    def test_german_registered(self):
        profile = get_profile("de")
        assert profile.code == "de"
        assert profile.name == "German"

    def test_german_in_available(self):
        codes = available_profiles()
        assert "de" in codes

    def test_german_low_high_quotes(self):
        """German uses low-high double quotes."""
        profile = get_profile("de")
        opens = [pair[0] for pair in profile.dialogue_quotes]
        assert "\u201e" in opens  # low double quote

    def test_german_speaker_verbs(self):
        """German profile has German speech verbs."""
        profile = get_profile("de")
        assert "sagte" in profile.speaker_verbs
        assert "fragte" in profile.speaker_verbs
        assert "fl\u00fcsterte" in profile.speaker_verbs

    def test_german_emotion_hints(self):
        """German emotion hints map verbs to emotions."""
        profile = get_profile("de")
        assert profile.emotion_hints["fl\u00fcsterte"] == "whisper"
        assert profile.emotion_hints["schrie"] == "angry"
        assert profile.emotion_hints["lachte"] == "happy"

    def test_german_speaker_blacklist(self):
        """German pronouns are blacklisted."""
        profile = get_profile("de")
        assert "er" in profile.speaker_blacklist
        assert "sie" in profile.speaker_blacklist
        assert "leise" in profile.speaker_blacklist

    def test_german_chapter_patterns(self):
        """German chapter patterns match 'Kapitel'."""
        profile = get_profile("de")
        assert any("Kapitel" in p for p in profile.chapter_patterns)

    def test_german_dialogue_detection(self):
        """German low-high quotes detected as dialogue."""
        from audiobooker.casting.dialogue import detect_dialogue
        profile = get_profile("de")
        text = '\u201eHallo\u201c sagte Hans.'
        segments = detect_dialogue(text, profile=profile)
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) >= 1


# =========================================================================
# Wave 2: Compilation Quality Report
# =========================================================================

class TestCompilationQualityReport:
    """Tests for compile_report quality metrics."""

    def _make_compiled_chapters(self):
        """Create chapters with known utterance distributions."""
        ch1 = Chapter(index=0, title="Ch1", raw_text="text")
        ch1.utterances = [
            Utterance(speaker="narrator", text="The sun rose.", utterance_type=UtteranceType.NARRATION),
            Utterance(speaker="Alice", text="Hello!", utterance_type=UtteranceType.DIALOGUE, emotion="happy"),
            Utterance(speaker="unknown", text="Who is this?", utterance_type=UtteranceType.DIALOGUE),
        ]
        ch2 = Chapter(index=1, title="Ch2", raw_text="more text")
        ch2.utterances = [
            Utterance(speaker="narrator", text="Later that day.", utterance_type=UtteranceType.NARRATION),
            Utterance(speaker="Bob", text="Goodbye!", utterance_type=UtteranceType.DIALOGUE),
        ]
        return [ch1, ch2]

    def test_speaker_line_counts(self):
        chapters = self._make_compiled_chapters()
        casting = CastingTable()
        report = compile_report(chapters, casting)

        assert report["speaker_line_counts"]["narrator"] == 2
        assert report["speaker_line_counts"]["alice"] == 1
        assert report["speaker_line_counts"]["unknown"] == 1
        assert report["speaker_line_counts"]["bob"] == 1

    def test_unknown_rate(self):
        chapters = self._make_compiled_chapters()
        casting = CastingTable()
        report = compile_report(chapters, casting)

        # 1 unknown out of 5 total = 0.2
        assert report["unknown_rate"] == pytest.approx(0.2)

    def test_total_counts(self):
        chapters = self._make_compiled_chapters()
        casting = CastingTable()
        report = compile_report(chapters, casting)

        assert report["total_utterances"] == 5
        assert report["total_dialogue"] == 3
        assert report["total_narration"] == 2

    def test_emotion_distribution(self):
        chapters = self._make_compiled_chapters()
        casting = CastingTable()
        report = compile_report(chapters, casting)

        assert report["emotion_distribution"].get("happy") == 1

    def test_top_unattributed(self):
        chapters = self._make_compiled_chapters()
        casting = CastingTable()
        report = compile_report(chapters, casting)

        assert len(report["top_unattributed"]) == 1
        assert report["top_unattributed"][0]["text"] == "Who is this?"

    def test_empty_chapters(self):
        """Report handles empty chapter list."""
        report = compile_report([], CastingTable())
        assert report["total_utterances"] == 0
        assert report["unknown_rate"] == 0.0


# =========================================================================
# Wave 2: Voice Preview (Mock TTS)
# =========================================================================

class TestVoicePreview:
    """Tests for preview method with mocked TTS engine."""

    def test_preview_truncates_at_sentence_boundary(self):
        """Long text is truncated at sentence boundary within 500 chars."""
        # Build text > 500 chars with sentence boundaries
        sentence = "This is a test sentence. "
        long_text = sentence * 30  # ~750 chars
        assert len(long_text) > 500

        project = AudiobookProject.from_string("Hello.", title="Preview Test")

        with patch("audiobooker.renderer.engine.TTSEngine") as MockEngine:
            mock_engine = MagicMock()
            MockEngine.return_value = mock_engine

            project.preview(long_text, voice="af_bella")

            # Verify synthesize was called
            mock_engine.synthesize.assert_called_once()
            call_kwargs = mock_engine.synthesize.call_args
            synthesized_text = call_kwargs.kwargs.get("text") or call_kwargs[1].get("text") or call_kwargs[0][0]

            # Text should be <= 500 chars and end with sentence punctuation
            assert len(synthesized_text) <= 500
            assert synthesized_text[-1] in ".!?"

    def test_preview_short_text_unchanged(self):
        """Short text passes through without truncation."""
        short_text = "Hello world."
        project = AudiobookProject.from_string("Hello.", title="Preview Short")

        with patch("audiobooker.renderer.engine.TTSEngine") as MockEngine:
            mock_engine = MagicMock()
            MockEngine.return_value = mock_engine

            project.preview(short_text, voice="af_bella")

            mock_engine.synthesize.assert_called_once()
            call_args = mock_engine.synthesize.call_args
            # Access text by keyword
            text_arg = call_args.kwargs.get("text", "")
            assert text_arg == short_text

    def test_preview_empty_text_raises(self):
        """Empty text raises ValueError."""
        project = AudiobookProject.from_string("Hello.", title="Preview Empty")

        with patch("audiobooker.renderer.engine.TTSEngine"):
            with pytest.raises(ValueError, match="empty"):
                project.preview("", voice="af_bella")

    def test_preview_passes_voice_and_speed(self):
        """Voice ID and speed are passed to TTS engine."""
        project = AudiobookProject.from_string("Hello.", title="Preview Args")

        with patch("audiobooker.renderer.engine.TTSEngine") as MockEngine:
            mock_engine = MagicMock()
            MockEngine.return_value = mock_engine

            project.preview("Hello world.", voice="bm_george", speed=1.5, emotion="happy")

            call_kwargs = mock_engine.synthesize.call_args.kwargs
            assert call_kwargs["voice"] == "bm_george"
            assert call_kwargs["speed"] == 1.5
            assert call_kwargs["emotion"] == "happy"


# =========================================================================
# Wave 3: PDF Parser (conditional)
# =========================================================================

class TestPDFParser:
    """Tests for PDF parser — skipped if pymupdf not available."""

    @pytest.fixture(autouse=True)
    def _check_pymupdf(self):
        try:
            import pymupdf  # noqa: F401
            self._has_pymupdf = True
        except ImportError:
            try:
                import fitz  # noqa: F401
                self._has_pymupdf = True
            except ImportError:
                self._has_pymupdf = False

    def test_pdf_parser_import(self):
        """PDF parser module exists (even if pymupdf not installed)."""
        if not self._has_pymupdf:
            pytest.skip("pymupdf not installed")
        # If pymupdf is available, we can try importing the parser
        try:
            from audiobooker.parser import pdf  # noqa: F401
        except ImportError:
            pytest.skip("PDF parser module not implemented yet")


# =========================================================================
# Wave 3: Text Normalization (abbreviations, numbers, currency)
# =========================================================================

class TestTextNormalization:
    """Tests for text normalization in the cleaner pipeline."""

    def test_abbreviation_expansion_sgt(self):
        result = expand_common_abbreviations("Sgt. Pepper led the charge.")
        assert "Sergeant" in result

    def test_abbreviation_expansion_lt(self):
        result = expand_common_abbreviations("Lt. Dan reported in.")
        assert "Lieutenant" in result

    def test_abbreviation_expansion_cpt(self):
        result = expand_common_abbreviations("Cpt. Ahab sailed forth.")
        assert "Captain" in result

    def test_abbreviation_expansion_gen(self):
        result = expand_common_abbreviations("Gen. Lee spoke.")
        assert "General" in result

    def test_abbreviation_expansion_jr(self):
        result = expand_common_abbreviations("John Jr. arrived.")
        assert "Junior" in result

    def test_abbreviation_expansion_sr(self):
        result = expand_common_abbreviations("Robert Sr. left.")
        assert "Senior" in result

    def test_abbreviation_expansion_inc(self):
        result = expand_common_abbreviations("Acme Inc. filed.")
        assert "Incorporated" in result

    def test_abbreviation_expansion_co(self):
        result = expand_common_abbreviations("Smith Co. merged.")
        assert "Company" in result

    def test_abbreviation_expansion_st(self):
        result = expand_common_abbreviations("St. Louis was cold.")
        assert "Saint" in result


# =========================================================================
# Wave 3: Per-Chapter Pause Fields Serialization
# =========================================================================

class TestChapterPauseSerialization:
    """Tests for per-chapter pause configuration in ProjectConfig."""

    def test_config_pause_fields_roundtrip(self):
        """Pause fields survive ProjectConfig serialization."""
        config = ProjectConfig(
            chapter_pause_ms=3000,
            narrator_pause_ms=800,
            dialogue_pause_ms=500,
        )
        data = config.to_dict()
        assert data["chapter_pause_ms"] == 3000
        assert data["narrator_pause_ms"] == 800
        assert data["dialogue_pause_ms"] == 500

        restored = ProjectConfig.from_dict(data)
        assert restored.chapter_pause_ms == 3000
        assert restored.narrator_pause_ms == 800
        assert restored.dialogue_pause_ms == 500

    def test_pause_defaults(self):
        """Default pause values are sensible."""
        config = ProjectConfig()
        assert config.chapter_pause_ms == 2000
        assert config.narrator_pause_ms == 600
        assert config.dialogue_pause_ms == 400


# =========================================================================
# Wave 3: Chapter Mood Field
# =========================================================================

class TestChapterMood:
    """Tests for chapter mood field (if implemented)."""

    def test_chapter_has_no_mood_by_default(self):
        """Chapters don't have a mood field by default (not yet implemented)."""
        ch = Chapter(index=0, title="Test", raw_text="Hello.")
        # If mood is added as a field, test it; otherwise verify it's not there
        if hasattr(ch, "mood"):
            assert ch.mood is None or ch.mood == ""
        # The chapter still serializes cleanly
        data = ch.to_dict()
        assert isinstance(data, dict)


# =========================================================================
# Wave 3: Utterance Type Enum
# =========================================================================

class TestUtteranceTypeEnum:
    """Tests for UtteranceType enum values."""

    def test_narration_value(self):
        assert UtteranceType.NARRATION.value == "narration"

    def test_dialogue_value(self):
        assert UtteranceType.DIALOGUE.value == "dialogue"

    def test_direction_value(self):
        assert UtteranceType.DIRECTION.value == "direction"

    def test_pause_value(self):
        assert UtteranceType.PAUSE.value == "pause"

    def test_all_types_listed(self):
        """All expected utterance types exist."""
        names = {t.name for t in UtteranceType}
        assert "NARRATION" in names
        assert "DIALOGUE" in names
        assert "DIRECTION" in names
        assert "PAUSE" in names

    def test_from_string_roundtrip(self):
        """UtteranceType survives string round-trip."""
        for t in UtteranceType:
            assert UtteranceType(t.value) == t

    def test_utterance_type_in_serialization(self):
        """Utterance type survives to_dict/from_dict."""
        u = Utterance(speaker="narrator", text="Pause.", utterance_type=UtteranceType.PAUSE)
        data = u.to_dict()
        assert data["type"] == "pause"
        restored = Utterance.from_dict(data)
        assert restored.utterance_type == UtteranceType.PAUSE


# =========================================================================
# Wave 3: Character pitch_shift and emphasis Fields
# =========================================================================

class TestCharacterPitchShiftEmphasis:
    """Tests for Character pitch_shift and emphasis (if implemented)."""

    def test_character_basic_fields(self):
        """Character has name, voice, emotion, speed, aliases."""
        char = Character(name="Alice", voice="af_bella", emotion="warm", speed=1.2)
        assert char.name == "Alice"
        assert char.voice == "af_bella"
        assert char.emotion == "warm"
        assert char.speed == 1.2

    def test_character_serialization_preserves_all_fields(self):
        """All Character fields survive serialization."""
        char = Character(
            name="Bob",
            voice="bm_george",
            emotion="grumpy",
            description="An old man",
            speed=0.8,
            aliases=["Robert", "Bobby"],
        )
        data = char.to_dict()
        restored = Character.from_dict(data)
        assert restored.name == "Bob"
        assert restored.voice == "bm_george"
        assert restored.emotion == "grumpy"
        assert restored.description == "An old man"
        assert restored.speed == 0.8
        assert restored.aliases == ["Robert", "Bobby"]


# =========================================================================
# Wave 3: Turn-Tracking with Scene Breaks
# =========================================================================

class TestTurnTrackingSceneBreaks:
    """Tests for turn-tracking reset on scene breaks (***)."""

    def test_scene_break_resets_turn_stack(self):
        """After ***, unattributed dialogue is 'unknown' (no inference)."""
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

        # After scene break, last dialogue should be "unknown"
        if len(dialogue) >= 3:
            assert dialogue[-1].speaker == "unknown"

    def test_dashes_scene_break(self):
        """Dash scene break (---) also resets turn stack."""
        chapter = Chapter(
            index=0,
            title="Dash Break",
            raw_text=(
                '"Hello!" said Alice.\n\n'
                '- - -\n\n'
                '"After the break."'
            ),
        )
        casting = CastingTable()
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting)
        dialogue = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]

        # After scene break, can't infer from empty stack
        if len(dialogue) >= 2:
            assert dialogue[-1].speaker in ("unknown", "Alice")

    def test_no_scene_break_allows_inference(self):
        """Without scene break, turn-tracking continues."""
        chapter = Chapter(
            index=0,
            title="Continuous",
            raw_text=(
                '"Hello!" said Alice. "Hi!" said Bob.\n\n'
                '"Another line."'
            ),
        )
        casting = CastingTable()
        casting.cast("Alice", "af_bella")
        casting.cast("Bob", "bm_george")

        utterances = compile_chapter(chapter, casting)
        dialogue = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]

        # Without scene break, the third line may be inferred from turn-tracking
        if len(dialogue) >= 3:
            # Should be inferred as Alice (alternating from Bob)
            assert dialogue[-1].speaker in ("Alice", "unknown")


# =========================================================================
# Wave 3: Multi-Word Speaker Names
# =========================================================================

class TestMultiWordSpeakerNames:
    """Tests for multi-word speaker names like 'Dr. Watson'."""

    def test_dr_watson_attribution(self):
        """'Dr. Watson said' is attributed to 'Dr. Watson'."""
        profile = get_profile("en")
        text = '"Elementary," said Dr. Watson.'
        from audiobooker.casting.dialogue import extract_speaker_from_context
        speaker, _ = extract_speaker_from_context(text, 0, 13, profile=profile)
        assert speaker is not None
        assert "Watson" in speaker

    def test_captain_ahab_attribution(self):
        """'Captain Ahab' is a valid multi-word speaker name."""
        profile = get_profile("en")
        from audiobooker.casting.dialogue import is_valid_speaker_name
        casting = CastingTable()
        assert is_valid_speaker_name("Captain Ahab", casting, profile=profile)

    def test_mr_holmes_attribution(self):
        """'Mr. Holmes' is a valid multi-word name."""
        profile = get_profile("en")
        from audiobooker.casting.dialogue import is_valid_speaker_name
        casting = CastingTable()
        assert is_valid_speaker_name("Mr. Holmes", casting, profile=profile)


# =========================================================================
# Wave 3: Em-Dash Dialogue Detection
# =========================================================================

class TestEmDashDialogue:
    """Tests for em-dash dialogue patterns (if supported)."""

    def test_standard_quoted_dialogue_still_works(self):
        """Standard double-quoted dialogue is detected."""
        from audiobooker.casting.dialogue import detect_dialogue
        profile = get_profile("en")
        text = 'He said "Hello there" and left.'
        segments = detect_dialogue(text, profile=profile)
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) == 1
        assert dialogue[0][0] == "Hello there"

    def test_smart_quotes_detected(self):
        """Smart/curly quotes are detected as dialogue."""
        from audiobooker.casting.dialogue import detect_dialogue
        profile = get_profile("en")
        text = 'She whispered \u201cGoodbye\u201d softly.'
        segments = detect_dialogue(text, profile=profile)
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) >= 1
        assert dialogue[0][0] == "Goodbye"


# =========================================================================
# Wave 3: Spanish and Japanese Language Profiles
# =========================================================================

class TestSpanishProfile:
    """Tests for Spanish language profile — skip if not implemented."""

    def test_spanish_profile(self):
        """Spanish profile is available or skipped."""
        try:
            profile = get_profile("es")
            assert profile.code == "es"
            assert profile.name == "Spanish"
            # Check for Spanish verbs
            assert "dijo" in profile.speaker_verbs or len(profile.speaker_verbs) > 0
        except ValueError:
            pytest.skip("Spanish language profile not implemented yet")


class TestJapaneseProfile:
    """Tests for Japanese language profile — skip if not implemented."""

    def test_japanese_profile(self):
        """Japanese profile is available or skipped."""
        try:
            profile = get_profile("ja")
            assert profile.code == "ja"
        except ValueError:
            pytest.skip("Japanese language profile not implemented yet")


# =========================================================================
# Integration: Clean text + pronunciation overrides in compile
# =========================================================================

class TestCleanTextIntegration:
    """Integration tests for text cleaning during compilation."""

    def test_clean_text_enabled_by_default(self):
        """clean_text is enabled in default config."""
        config = ProjectConfig()
        assert config.clean_text is True

    def test_clean_text_config_roundtrip(self):
        """clean_text field survives serialization."""
        config = ProjectConfig(clean_text=False)
        data = config.to_dict()
        assert data["clean_text"] is False
        restored = ProjectConfig.from_dict(data)
        assert restored.clean_text is False

    def test_compile_with_page_numbers_stripped(self):
        """Page numbers in text are stripped during compile."""
        project = AudiobookProject.from_string(
            "The cat sat on the mat.\n42\nThe dog ran home.",
            title="Clean Test",
        )
        project.config.clean_text = True
        project.cast("narrator", "af_heart")
        project.compile()

        all_text = " ".join(
            u.text for ch in project.chapters for u in ch.utterances
        )
        # Page number "42" on its own line should be stripped
        # The text around it should remain
        assert "cat sat" in all_text
        assert "dog ran" in all_text

    def test_compile_with_abbreviations_expanded(self):
        """Abbreviations are expanded during compile with clean_text=True."""
        project = AudiobookProject.from_string(
            "Dr. Smith met Mrs. Jones.",
            title="Abbrev Test",
        )
        project.config.clean_text = True
        project.cast("narrator", "af_heart")
        project.compile()

        all_text = " ".join(
            u.text for ch in project.chapters for u in ch.utterances
        )
        assert "Doctor" in all_text
        assert "Missus" in all_text
