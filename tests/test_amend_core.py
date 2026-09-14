"""
Regression tests for wave-2 (health-amend-a) core-domain fixes,
mcp-tool-shop-org/audiobooker, swarm swarm-1789421403-b984.

Each test class below corresponds to one finding from the wave-2 core
amend brief. Every scenario in this file was reproduced against the
pre-fix code first (by `git stash`-ing audiobooker/{models,project,
config_file,errors,__init__}.py back to HEAD ea50c79, running the exact
construction/round-trip below, observing the bug, then `git stash pop`-ing
the fix back) before its fix was written -- the red-then-green cycle the
wave-2 brief requires. See the wave-2 core output summary for the
per-finding before/after values that were observed.

Ownership: this file belongs to the core domain (models.py, project.py,
config_file.py, errors.py, __init__.py). It must not import anything from
casting/, renderer/, nlp/, or cli.py beyond what a couple of tests use
read-only to confirm a fix's effect reaches a downstream consumer
(casting.presets.save_preset), matching the pattern the wave-1 finding
itself used to describe the bug.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiobooker.errors import AudiobookerError, ConfigValidationError
from audiobooker.models import (
    BookMetadata,
    CastingTable,
    Chapter,
    Character,
    ProjectConfig,
)
from audiobooker.project import AudiobookProject
from audiobooker.config_file import ConfigFileError, have_toml_support, load_config

requires_toml = pytest.mark.skipif(
    not have_toml_support(),
    reason="no TOML parser available (tomllib/tomli)",
)


# ===========================================================================
# core-1-casting-roundtrip
#
# project.py:1160 _casting_as_list()/export_casting()/import_casting() --
# pitch_shift, emphasis, and default_intensity round-tripped in NEITHER
# JSON format, and pitch_shift/default_intensity round-tripped in neither
# format at all (emphasis already worked via CSV). Pre-fix reproduction
# (stash confirmed): a Character with pitch_shift=-0.2, emphasis=1.6,
# default_intensity=0.65 exported to JSON and re-imported came back as
# 0.0, 1.0, None -- with no error or warning.
# ===========================================================================


class TestCastingRoundTripJSON:
    """JSON is the complete round-trip format after this fix: every field
    Character.__post_init__ validates survives export -> import."""

    def _tuned_character(self) -> Character:
        return Character(
            name="Alice",
            voice="af_bella",
            emotion="warm",
            description="lead",
            speed=1.2,
            pitch_shift=-0.2,
            emphasis=1.6,
            aliases=["Ally", "Al"],
            default_intensity=0.65,
        )

    def test_every_tunable_field_survives_json_round_trip(self, tmp_path):
        project = AudiobookProject.from_string("Some text here.", title="T")
        project.casting.characters["alice"] = self._tuned_character()

        out = tmp_path / "cast.json"
        project.export_casting(out)

        fresh = AudiobookProject.from_string("Other text.", title="T2")
        fresh.import_casting(out)
        alice = fresh.casting.characters["alice"]

        assert alice.name == "Alice"
        assert alice.voice == "af_bella"
        assert alice.emotion == "warm"
        assert alice.description == "lead"
        assert alice.speed == 1.2
        assert alice.pitch_shift == -0.2
        assert alice.emphasis == 1.6
        assert alice.aliases == ["Ally", "Al"]
        assert alice.default_intensity == 0.65

    def test_untuned_character_export_shape_is_legacy_compatible(self, tmp_path):
        """A character with no special tuning still omits default_intensity
        (matching Character.to_dict()'s own convention), so old cast files
        stay byte-identical on export."""
        project = AudiobookProject.from_string("x", title="T")
        project.cast("Bob", "am_eric")  # all defaults

        out = tmp_path / "cast.json"
        project.export_casting(out)
        data = json.loads(out.read_text(encoding="utf-8"))
        bob_entry = next(d for d in data if d["name"] == "Bob")

        assert "default_intensity" not in bob_entry
        assert bob_entry["pitch_shift"] == 0.0
        assert bob_entry["emphasis"] == 1.0

    def test_preset_save_reuses_fixed_shape(self, tmp_path, monkeypatch):
        """casting.presets.save_preset is fed straight from
        _casting_as_list() (cli.py calls project._casting_as_list() then
        cast_presets.save_preset(...)), so the fix here also fixes cast
        presets without touching casting/presets.py."""
        from audiobooker.casting import presets as presets_mod

        monkeypatch.setattr(presets_mod, "_config_root", lambda: tmp_path)

        project = AudiobookProject.from_string("x", title="T")
        project.casting.characters["alice"] = self._tuned_character()

        cast_list = project._casting_as_list()
        presets_mod.save_preset("Tuned", cast_list)
        loaded = presets_mod.load_preset("Tuned")
        alice_entry = next(d for d in loaded if d["name"] == "Alice")

        assert alice_entry["pitch_shift"] == -0.2
        assert alice_entry["emphasis"] == 1.6
        assert alice_entry["default_intensity"] == 0.65


class TestCastingRoundTripCSV:
    """CSV already carried `emphasis` before this fix. pitch_shift and
    default_intensity are deliberately NOT added as new CSV columns: doing
    so would change the header row
    tests/test_feat_f4_cli.py::test_export_csv_columns_and_aliases asserts
    verbatim (`"name,voice,gender,line_count,emotion,speed,emphasis,`
    `aliases,description"`), and that file is outside this domain's owned
    globs this wave. This class documents the resulting, deliberate split:
    CSV carries what it always carried; JSON is the only complete format.
    See this wave's skipped[] entry (core-1-csv-columns)."""

    def test_csv_still_preserves_its_existing_columns(self, tmp_path):
        project = AudiobookProject.from_string("x", title="T")
        project.casting.characters["alice"] = Character(
            name="Alice",
            voice="af_bella",
            emotion="warm",
            speed=1.2,
            emphasis=1.6,
            aliases=["Ally"],
            description="lead",
        )
        out = tmp_path / "cast.csv"
        project.export_casting(out)

        fresh = AudiobookProject.from_string("y", title="T2")
        fresh.import_casting(out)
        alice = fresh.casting.characters["alice"]

        assert alice.voice == "af_bella"
        assert alice.emotion == "warm"
        assert alice.speed == 1.2
        assert alice.emphasis == 1.6
        assert alice.aliases == ["Ally"]
        assert alice.description == "lead"

    def test_csv_header_unchanged_pitch_shift_and_default_intensity_not_carried(
        self, tmp_path
    ):
        """Documents the known, deliberate CSV gap described in this
        class's docstring."""
        project = AudiobookProject.from_string("x", title="T")
        project.casting.characters["alice"] = Character(
            name="Alice",
            voice="af_bella",
            pitch_shift=-0.2,
            default_intensity=0.65,
        )
        out = tmp_path / "cast.csv"
        project.export_casting(out)

        header = out.read_text(encoding="utf-8").splitlines()[0]
        assert header == (
            "name,voice,gender,line_count,emotion,speed,emphasis,"
            "aliases,description"
        )

        fresh = AudiobookProject.from_string("y", title="T2")
        fresh.import_casting(out)
        alice = fresh.casting.characters["alice"]
        assert alice.pitch_shift == 0.0  # not preserved (documented gap)
        assert alice.default_intensity is None  # not preserved (documented gap)


# ===========================================================================
# core-2-config-validation
#
# config_file.py:94 / models.py:648 -- only 8 of ProjectConfig's 30 fields
# were validated. Pre-fix reproduction (stash confirmed):
# ProjectConfig(compile_workers='four', sample_rate=-1,
# emotion_confidence_threshold=5.0) constructed with NO error.
# ===========================================================================


class TestProjectConfigNumericValidation:
    def test_bad_values_from_the_finding_now_raise(self):
        with pytest.raises(ValueError, match="compile_workers"):
            ProjectConfig(compile_workers="four")
        with pytest.raises(ValueError, match="sample_rate"):
            ProjectConfig(sample_rate=-1)
        with pytest.raises(ValueError, match="emotion_confidence_threshold"):
            ProjectConfig(emotion_confidence_threshold=5.0)

    def test_errors_are_wired_to_the_structured_error_system(self):
        """core-5-errors-wiring: these new checks raise ConfigValidationError
        (AudiobookerError + ValueError), not just a plain ValueError."""
        try:
            ProjectConfig(sample_rate=0)
            pytest.fail("expected ConfigValidationError")
        except ValueError as e:
            assert isinstance(e, ConfigValidationError)
            assert isinstance(e, AudiobookerError)
            assert e.code == "CONFIG_INVALID_VALUE"
            assert e.retryable is False
            assert e.structured()["code"] == "CONFIG_INVALID_VALUE"

    @pytest.mark.parametrize(
        "field,bad",
        [
            ("chapter_pause_ms", -1),
            ("narrator_pause_ms", -1),
            ("dialogue_pause_ms", -1),
            ("min_chapter_words", -1),
            ("estimated_wpm", 0),
            ("compile_workers", 0),
            ("sample_rate", 0),
        ],
    )
    def test_negative_or_zero_rejected(self, field, bad):
        with pytest.raises(ValueError, match=field):
            ProjectConfig(**{field: bad})

    @pytest.mark.parametrize("bad", [-0.01, 1.01, -5, 10])
    def test_confidence_threshold_out_of_unit_interval_rejected(self, bad):
        with pytest.raises(ValueError, match="emotion_confidence_threshold"):
            ProjectConfig(emotion_confidence_threshold=bad)

    @pytest.mark.parametrize(
        "field",
        [
            "validate_voices_on_render",
            "keep_titled_short_chapters",
            "clean_text",
            "normalize_text",
            "parallel_compile",
            "utterance_cache",
        ],
    )
    def test_bool_fields_reject_non_bool(self, field):
        with pytest.raises(ValueError, match=field):
            ProjectConfig(**{field: 1})  # int, not bool -- easy config typo

    @pytest.mark.parametrize(
        "field", ["pronunciation_overrides", "user_emotion_rules", "phoneme_overrides"]
    )
    def test_dict_fields_reject_non_str_values(self, field):
        with pytest.raises(ValueError, match=field):
            ProjectConfig(**{field: {"a": 1}})

    @pytest.mark.parametrize(
        "field", ["language_code", "fallback_voice_id", "tts_engine"]
    )
    def test_string_fields_reject_empty(self, field):
        with pytest.raises(ValueError, match=field):
            ProjectConfig(**{field: ""})

    @pytest.mark.parametrize("field", ["aac_bitrate", "mp3_bitrate"])
    def test_optional_bitrate_fields_reject_non_string(self, field):
        with pytest.raises(ValueError, match=field):
            ProjectConfig(**{field: 192})  # int, not "192k"

    def test_valid_values_and_defaults_still_accepted(self):
        """Floor-preserving half of the fix: defaults and every value
        already exercised elsewhere in the suite must keep constructing
        cleanly."""
        cfg = ProjectConfig()
        assert cfg.sample_rate == 24000
        assert cfg.compile_workers == 4
        assert cfg.emotion_confidence_threshold == 0.75

        cfg2 = ProjectConfig(
            sample_rate=44100,
            compile_workers=8,
            estimated_wpm=180,
            chapter_pause_ms=0,
            min_chapter_words=0,
            emotion_confidence_threshold=0.0,
            aac_bitrate="192k",
            mp3_bitrate=None,
        )
        assert cfg2.sample_rate == 44100
        assert cfg2.emotion_confidence_threshold == 0.0


class TestConfigFileLoadTimeValidation:
    """config_file.py half of core-2: a bad TOML value now raises at load
    time, naming both the offending key and the file it came from, instead
    of silently reaching ProjectConfig(**mapped) unchecked."""

    @pytest.fixture
    def isolated_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        return home

    @requires_toml
    def test_bad_numeric_value_names_key_and_file(self, tmp_path, isolated_home):
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        rc = tmp_path / ".audiobookerrc"
        rc.write_text('workers = "four"\n', encoding="utf-8")

        with pytest.raises(ConfigFileError) as exc_info:
            load_config(src)
        message = str(exc_info.value)
        assert "workers" in message
        assert str(rc) in message

    @requires_toml
    def test_out_of_range_threshold_raises(self, tmp_path, isolated_home):
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        rc = tmp_path / ".audiobookerrc"
        rc.write_text("emotion_confidence_threshold = 5.0\n", encoding="utf-8")

        with pytest.raises(ConfigFileError, match="emotion_confidence_threshold"):
            load_config(src)

    @requires_toml
    def test_config_file_error_is_a_config_validation_error(self, tmp_path, isolated_home):
        """core-5-errors-wiring: config_file.ConfigFileError is a thin
        ConfigValidationError subclass, so it's catchable as
        AudiobookerError/ValueError too."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        rc = tmp_path / ".audiobookerrc"
        rc.write_text("sample_rate = -1\n", encoding="utf-8")

        with pytest.raises(AudiobookerError):
            load_config(src)

    @requires_toml
    def test_valid_config_still_loads(self, tmp_path, isolated_home):
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        rc = tmp_path / ".audiobookerrc"
        rc.write_text("workers = 2\nwpm = 175\n", encoding="utf-8")

        cfg = load_config(src)
        assert cfg["compile_workers"] == 2
        assert cfg["estimated_wpm"] == 175


# ===========================================================================
# core-3-cast-recast-wipe
#
# models.py:383 CastingTable.cast() always constructed a brand-new
# Character from its 5 parameters, overwriting self.characters[key]
# wholesale -- so re-casting to change one field (e.g. emotion) silently
# reset pitch_shift/emphasis/aliases/default_intensity/line_count. Pre-fix
# reproduction (stash confirmed): re-casting "Alice" to change only emotion
# reset pitch_shift -0.2 -> 0.0, aliases ["Ally"] -> [], line_count 42 -> 0.
# ===========================================================================


class TestRecastPreservesTuning:
    def _tune(self, table: CastingTable) -> None:
        char = table.characters["alice"]
        char.pitch_shift = -0.2
        char.emphasis = 1.6
        char.default_intensity = 0.65
        char.aliases = ["Ally"]
        char.line_count = 42

    def test_casting_table_cast_preserves_tuning_on_recast(self):
        table = CastingTable()
        table.cast("Alice", "af_bella", emotion="warm")
        self._tune(table)

        table.cast("Alice", "af_bella", emotion="furious")  # only emotion changes
        alice = table.characters["alice"]

        assert alice.emotion == "furious"
        assert alice.pitch_shift == -0.2
        assert alice.emphasis == 1.6
        assert alice.default_intensity == 0.65
        assert alice.aliases == ["Ally"]
        assert alice.line_count == 42

    def test_project_cast_preserves_tuning_on_recast(self):
        """AudiobookProject.cast() must ALSO forward the UNSET sentinel --
        it used to hardcode None/None/1.0 defaults and forward those
        concrete values every time, which would have defeated
        CastingTable.cast()'s own fix for anyone using the project-level
        API (the normal path) rather than CastingTable directly."""
        project = AudiobookProject.from_string("x", title="T")
        project.cast("Alice", "af_bella", emotion="warm")
        self._tune(project.casting)

        project.cast("Alice", "af_bella", emotion="furious")
        alice = project.casting.characters["alice"]

        assert alice.emotion == "furious"
        assert alice.pitch_shift == -0.2
        assert alice.aliases == ["Ally"]

    def test_explicit_none_still_clears_a_field(self):
        """Omitting a field preserves it; explicitly passing None still
        clears it -- the UNSET sentinel distinguishes the two cases."""
        table = CastingTable()
        table.cast("Alice", "af_bella", emotion="warm", description="lead")

        table.cast("Alice", "af_bella", emotion=None)  # explicit clear
        alice = table.characters["alice"]

        assert alice.emotion is None
        assert alice.description == "lead"  # untouched (omitted this time)

    def test_new_character_still_gets_clean_defaults(self):
        table = CastingTable()
        table.cast("Bob", "am_eric")  # first cast, everything omitted
        bob = table.characters["bob"]

        assert bob.emotion is None
        assert bob.description is None
        assert bob.speed == 1.0
        assert bob.pitch_shift == 0.0
        assert bob.emphasis == 1.0

    def test_recast_still_validates_new_values(self):
        """The fix must not weaken validation: an invalid value passed to
        an existing character on re-cast still raises."""
        table = CastingTable()
        table.cast("Alice", "af_bella")
        with pytest.raises(ValueError, match="speed"):
            table.cast("Alice", "af_bella", speed=99)


# ===========================================================================
# core-4-fallback-voice-desync
#
# project.py:168 fallback_voice_id is stored on both ProjectConfig and
# CastingTable, kept in sync by one __post_init__ line that runs only at
# construction. load() replaces both self.casting and self.config wholesale
# from the saved JSON without re-running it. Pre-fix reproduction (stash
# confirmed): setting config.fallback_voice_id='bm_george', saving, and
# reloading left casting.fallback_voice_id at 'af_heart'.
# ===========================================================================


class TestFallbackVoiceIdSync:
    def test_fallback_voice_stays_synced_through_save_and_load(self, tmp_path):
        project = AudiobookProject.from_string("x", title="T")
        project.config.fallback_voice_id = "bm_george"

        save_path = tmp_path / "proj.audiobooker"
        project.save(save_path)

        # The saved FILE itself must be internally consistent (save()-side).
        raw = json.loads(save_path.read_text(encoding="utf-8"))
        assert raw["config"]["fallback_voice_id"] == "bm_george"
        assert raw["casting"]["fallback_voice_id"] == "bm_george"

        # Re-loading it must agree too (load()-side).
        reloaded = AudiobookProject.load(save_path)
        assert reloaded.config.fallback_voice_id == "bm_george"
        assert reloaded.casting.fallback_voice_id == "bm_george"

    def test_construction_time_sync_still_works(self):
        """Baseline: the original __post_init__ sync path must still work
        for a freshly constructed project (no regression)."""
        cfg = ProjectConfig(fallback_voice_id="am_liam")
        project = AudiobookProject(title="T", config=cfg)
        assert project.casting.fallback_voice_id == "am_liam"

    def test_validate_voices_and_get_voice_agree_after_reload(self, tmp_path):
        """The concrete consequence the finding names: _validate_voices()
        (reads config.fallback_voice_id) and CastingTable.get_voice() (reads
        casting.fallback_voice_id) must check the SAME fallback voice after
        a reload. Constructed WITHOUT the narrator auto-cast from_string()
        performs, so get_voice()'s narrator-fallback tier is empty and an
        uncast speaker actually reaches the ultimate fallback_voice_id tier
        this finding is about (get_voice's default_narrator tier would
        otherwise mask the bug this test targets)."""
        project = AudiobookProject(title="T")
        project.config.fallback_voice_id = "bm_george"
        save_path = tmp_path / "proj.audiobooker"
        project.save(save_path)

        reloaded = AudiobookProject.load(save_path)
        assert reloaded.casting.characters == {}  # no narrator cast

        resolved_voice, _ = reloaded.casting.get_voice("SomeUncastSpeaker")

        assert resolved_voice == reloaded.config.fallback_voice_id == "bm_george"


# ===========================================================================
# core-6-path-trust-boundary (budget item: fixed)
#
# models.py:239 Chapter.from_dict's audio_path and BookMetadata.from_dict's
# cover_art_path were deserialized from an untrusted project file WITHOUT
# passing through the '..'/null-byte check project.py:766's load() already
# applies to source_path/output_path.
# ===========================================================================


class TestDeserializedPathTrustBoundary:
    def test_chapter_audio_path_rejects_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            Chapter.from_dict(
                {
                    "index": 0,
                    "title": "T",
                    "raw_text": "x",
                    "audio_path": "../../etc/passwd",
                }
            )

    def test_book_metadata_cover_art_path_rejects_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            BookMetadata.from_dict({"cover_art_path": "../secret.jpg"})

    def test_chapter_audio_path_rejects_null_byte(self):
        with pytest.raises(ValueError, match="null bytes"):
            Chapter.from_dict(
                {
                    "index": 0,
                    "title": "T",
                    "raw_text": "x",
                    "audio_path": "a\x00b.wav",
                }
            )

    def test_legit_paths_still_accepted_unchanged(self):
        ch = Chapter.from_dict(
            {
                "index": 0,
                "title": "T",
                "raw_text": "x",
                "audio_path": "/tmp/ch0.wav",
            }
        )
        assert ch.audio_path == Path("/tmp/ch0.wav")

        meta = BookMetadata.from_dict({"cover_art_path": "/covers/art.jpg"})
        assert str(meta.cover_art_path).endswith("art.jpg")

    def test_empty_string_still_treated_as_absent(self):
        """Byte-for-byte preserved edge case: "" continues to mean 'no
        path', not a validation error."""
        ch = Chapter.from_dict(
            {"index": 0, "title": "T", "raw_text": "x", "audio_path": ""}
        )
        assert ch.audio_path is None

        meta = BookMetadata.from_dict({"cover_art_path": ""})
        assert meta.cover_art_path is None


# ===========================================================================
# core-5-errors-wiring
#
# errors.py defined AudiobookerError/ErrorDetail as dead code -- zero
# imports, zero instantiations, zero references in tests anywhere in the
# repo, despite SHIP_GATE.md's Gate B citing it as evidence. This wave
# wires it into the new core-2 validation paths and exports it from the
# package root.
# ===========================================================================


class TestErrorsWiring:
    def test_audiobookererror_importable_from_package_root(self):
        import audiobooker

        assert audiobooker.AudiobookerError is AudiobookerError
        assert audiobooker.ConfigValidationError is ConfigValidationError

    def test_config_validation_error_catchable_as_value_and_audiobooker_error(self):
        try:
            ProjectConfig(sample_rate=-5)
            pytest.fail("expected an error")
        except AudiobookerError as e:
            assert isinstance(e, ValueError)
            assert e.structured()["code"] == "CONFIG_INVALID_VALUE"
        # And the reverse direction:
        try:
            ProjectConfig(sample_rate=-5)
            pytest.fail("expected an error")
        except ValueError as e:
            assert isinstance(e, AudiobookerError)
