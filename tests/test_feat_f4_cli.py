"""CASTING-DEPTH (v2.1): Tests for the integration layer (cli/models/project).

This agent owns audiobooker/cli.py, audiobooker/models.py, and
audiobooker/project.py. The casting-owned modules (casting.presets,
casting.alias_discovery, the voice_suggester bulk helper, the dialogue scene
tags, and the emotion preset packs) are exercised ONLY through mocks here —
they evolve in parallel and are validated by the casting agent's own tests.

Covers:
- models: Utterance.intensity, Character.default_intensity,
  ProjectConfig.emotion_preset — defaults preserve current behavior,
  serialization round-trips, legacy files default cleanly, validation.
- project: export_casting / import_casting CSV branch; set_mood_span scene-tag
  injection; default_intensity gap-fill at compile.
- cli: cast-preset (save/list/apply/delete + --from-project), cast-fill,
  cast-export/cast-import --format csv, emotions mood-span, emotions presets,
  speakers --suggest-aliases (+ --apply), --emotion-preset on compile/make.

No real audio, ffmpeg, or voice-soundboard is touched.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audiobooker.cli import create_parser, main
from audiobooker.models import Character, ProjectConfig, Utterance
from audiobooker.nlp.speaker_resolver import AliasProposal
from audiobooker.project import (
    AudiobookProject,
    _csv_aliases,
    _csv_float,
    _csv_int,
    _gender_from_voice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(title: str = "Depth Test") -> AudiobookProject:
    """A tiny compiled project with a narrator + two dialogue speakers."""
    project = AudiobookProject.from_string(
        "Chapter 1\n\n"
        "Hello world. This is narration for the test.\n\n"
        '"I am Alice," she said.\n\n'
        '"And I am Bob," he replied.',
        title=title,
        author="Tester",
    )
    project.compile()
    return project


def _write_project(tmp_path: Path, title: str = "Depth Test") -> Path:
    project = _make_project(title)
    path = tmp_path / "depth.audiobooker"
    project.save(path)
    return path


@pytest.fixture
def stub_presets(monkeypatch):
    """Patch the real audiobooker.casting.presets functions with mocks.

    The module exists (casting-owned); patching its attributes in place lets the
    cli wiring (`from audiobooker.casting import presets`) be tested in isolation.
    """
    import audiobooker.casting.presets as presets_mod
    ns = types.SimpleNamespace(
        save_preset=MagicMock(name="save_preset"),
        list_presets=MagicMock(name="list_presets", return_value=[]),
        load_preset=MagicMock(name="load_preset", return_value=[]),
        delete_preset=MagicMock(name="delete_preset"),
        preset_dir=MagicMock(name="preset_dir", return_value=Path("/tmp/audiobooker/presets")),
    )
    for fn in ("save_preset", "list_presets", "load_preset", "delete_preset", "preset_dir"):
        monkeypatch.setattr(presets_mod, fn, getattr(ns, fn))
    return ns


@pytest.fixture
def stub_alias_discovery(monkeypatch):
    """Patch the real speaker_resolver.suggest_aliases (returns list[AliasProposal])."""
    import audiobooker.nlp.speaker_resolver as sr
    m = MagicMock(name="suggest_aliases", return_value=[])
    monkeypatch.setattr(sr, "suggest_aliases", m)
    return m


# ===========================================================================
# models: Utterance.intensity
# ===========================================================================


class TestUtteranceIntensity:
    def test_default_none_preserves_behavior(self):
        u = Utterance(speaker="Alice", text="Hi")
        assert u.intensity is None
        # Not serialized when None -> existing project files round-trip unchanged.
        assert "intensity" not in u.to_dict()

    def test_set_intensity_round_trips(self):
        u = Utterance(speaker="Bob", text="Hi", emotion="angry", intensity=0.7)
        data = u.to_dict()
        assert data["intensity"] == 0.7
        restored = Utterance.from_dict(data)
        assert restored.intensity == 0.7

    def test_legacy_dict_without_intensity_defaults_none(self):
        # A project file written before v2.1 has no "intensity" key.
        legacy = {"speaker": "Alice", "text": "Hi", "emotion": "happy"}
        u = Utterance.from_dict(legacy)
        assert u.intensity is None

    @pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0])
    def test_out_of_range_rejected(self, bad):
        with pytest.raises(ValueError, match="intensity"):
            Utterance(speaker="x", text="y", intensity=bad)

    def test_bool_rejected(self):
        # bool is an int subclass — must not be accepted as 0/1 intensity.
        with pytest.raises(ValueError, match="intensity"):
            Utterance(speaker="x", text="y", intensity=True)

    def test_boundaries_allowed(self):
        assert Utterance(speaker="x", text="y", intensity=0.0).intensity == 0.0
        assert Utterance(speaker="x", text="y", intensity=1.0).intensity == 1.0


# ===========================================================================
# models: Character.default_intensity
# ===========================================================================


class TestCharacterDefaultIntensity:
    def test_default_none_not_serialized(self):
        c = Character(name="Alice", voice="af_sky")
        assert c.default_intensity is None
        assert "default_intensity" not in c.to_dict()

    def test_set_round_trips(self):
        c = Character(name="Bob", voice="am_liam", default_intensity=0.3)
        assert c.to_dict()["default_intensity"] == 0.3
        assert Character.from_dict(c.to_dict()).default_intensity == 0.3

    def test_legacy_dict_defaults_none(self):
        legacy = {"name": "Alice", "voice": "af_sky"}
        assert Character.from_dict(legacy).default_intensity is None

    @pytest.mark.parametrize("bad", [-0.5, 1.01, 5.0])
    def test_out_of_range_rejected(self, bad):
        with pytest.raises(ValueError, match="default_intensity"):
            Character(name="x", voice="af_sky", default_intensity=bad)


# ===========================================================================
# models: ProjectConfig.emotion_preset
# ===========================================================================


class TestEmotionPresetConfig:
    def test_default_is_neutral(self):
        assert ProjectConfig().emotion_preset == "neutral"

    def test_serialization_round_trip(self):
        cfg = ProjectConfig(emotion_preset="dramatic")
        assert cfg.to_dict()["emotion_preset"] == "dramatic"
        assert ProjectConfig.from_dict(cfg.to_dict()).emotion_preset == "dramatic"

    def test_legacy_config_defaults_neutral(self):
        # Pre-v2.1 config dict has no emotion_preset key.
        assert ProjectConfig.from_dict({}).emotion_preset == "neutral"

    @pytest.mark.parametrize(
        "preset", ["neutral", "literary", "dramatic", "children"]
    )
    def test_valid_presets_accepted(self, preset):
        assert ProjectConfig(emotion_preset=preset).emotion_preset == preset

    def test_invalid_preset_rejected(self):
        with pytest.raises(ValueError, match="emotion_preset"):
            ProjectConfig(emotion_preset="bogus")


# ===========================================================================
# project: CSV cast sheets
# ===========================================================================


class TestCastingCSV:
    def test_csv_helpers(self):
        assert _gender_from_voice("af_sky") == "female"
        assert _gender_from_voice("bf_emma") == "female"
        assert _gender_from_voice("am_liam") == "male"
        assert _gender_from_voice("bm_george") == "male"
        assert _gender_from_voice("weird") == "unknown"
        assert _csv_aliases("a; b ;c ") == ["a", "b", "c"]
        assert _csv_aliases("") == []
        assert _csv_float("", 1.0) == 1.0
        assert _csv_float("1.5", 1.0) == 1.5
        assert _csv_float("bad", 0.9) == 0.9
        assert _csv_int("", 0) == 0
        assert _csv_int("4", 0) == 4

    def test_export_csv_columns_and_aliases(self, tmp_path):
        project = AudiobookProject.from_string("x", title="T")
        project.cast("Alice", "af_sky", emotion="happy")
        project.casting.characters[
            project.casting.normalize_key("Alice")
        ].aliases = ["Al", "Ally"]

        out = tmp_path / "cast.csv"
        project.export_casting(out)  # infers csv from extension
        text = out.read_text(encoding="utf-8")
        header = text.splitlines()[0]
        assert header == (
            "name,voice,gender,line_count,emotion,speed,emphasis,aliases,description"
        )
        assert "Al;Ally" in text
        assert "female" in text  # derived gender column

    def test_csv_round_trip(self, tmp_path):
        project = AudiobookProject.from_string("x", title="T")
        project.cast("Alice", "af_sky", emotion="happy")
        project.casting.characters[
            project.casting.normalize_key("Alice")
        ].aliases = ["Al"]

        out = tmp_path / "cast.csv"
        project.export_casting(out)

        fresh = AudiobookProject.from_string("y", title="T2")
        fresh.import_casting(out)
        al = fresh.casting.characters[fresh.casting.normalize_key("Alice")]
        assert al.voice == "af_sky"
        assert al.emotion == "happy"
        assert al.aliases == ["Al"]

    def test_import_tolerates_missing_optional_columns(self, tmp_path):
        partial = tmp_path / "partial.csv"
        partial.write_text("name,voice\nCarol,bf_emma\n", encoding="utf-8")
        project = AudiobookProject.from_string("x", title="T")
        project.import_casting(partial, fmt="csv")
        assert (
            project.casting.characters[
                project.casting.normalize_key("Carol")
            ].voice
            == "bf_emma"
        )

    def test_import_csv_missing_required_column_errors(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("name,emotion\nAlice,happy\n", encoding="utf-8")
        project = AudiobookProject.from_string("x", title="T")
        with pytest.raises(ValueError, match="voice"):
            project.import_casting(bad, fmt="csv")

    def test_explicit_fmt_overrides_extension(self, tmp_path):
        # A .txt path with fmt="csv" still writes CSV.
        out = tmp_path / "cast.txt"
        project = AudiobookProject.from_string("x", title="T")
        project.cast("Alice", "af_sky")
        project.export_casting(out, fmt="csv")
        assert out.read_text(encoding="utf-8").startswith("name,voice,gender")


# ===========================================================================
# project: mood-span + default_intensity gap-fill
# ===========================================================================


class TestMoodSpanProject:
    def test_set_mood_span_injects_scene_tags(self):
        project = AudiobookProject.from_string(
            "Chapter 1\n\nThe storm raged on through the night.", title="M"
        )
        project.compile()
        assert project.chapters[0].utterances  # compiled before

        fragment = project.set_mood_span(0, 0, 9, "tense")
        text = project.chapters[0].raw_text
        assert "[scene:tense]" in text
        assert "[/scene]" in text
        assert fragment == project.chapters[0].raw_text[
            len("[scene:tense]"):len("[scene:tense]") + len(fragment)
        ]
        # Span invalidates compiled utterances + cached audio.
        assert project.chapters[0].utterances == []

    def test_set_mood_span_validates_offsets(self):
        project = AudiobookProject.from_string("Chapter 1\n\nShort.", title="M")
        with pytest.raises(ValueError):
            project.set_mood_span(0, 5, 2, "sad")  # start >= end

    def test_set_mood_span_bad_chapter(self):
        project = AudiobookProject.from_string("Chapter 1\n\nText.", title="M")
        with pytest.raises(IndexError):
            project.set_mood_span(9, 0, 1, "sad")

    def test_default_intensity_gap_fill(self):
        project = AudiobookProject.from_string(
            "Chapter 1\n\n"
            '"Get out!" Alice shouted, furious and enraged.',
            title="I",
        )
        project.cast("Alice", "af_sky")
        project.casting.characters[
            project.casting.normalize_key("Alice")
        ].default_intensity = 0.4
        project.compile()

        alice_key = project.casting.normalize_key("Alice")
        emo = [
            u
            for ch in project.chapters
            for u in ch.utterances
            if u.emotion and project.casting.normalize_key(u.speaker) == alice_key
        ]
        # Every emotional Alice line with no explicit intensity inherits 0.4.
        assert emo, "expected at least one emotional Alice utterance"
        assert all(u.intensity == 0.4 for u in emo)

    def test_default_intensity_never_overrides_explicit(self):
        # An utterance that already has an intensity is left untouched.
        project = AudiobookProject.from_string("Chapter 1\n\nText.", title="I")
        project.cast("Alice", "af_sky")
        project.casting.characters[
            project.casting.normalize_key("Alice")
        ].default_intensity = 0.4
        ch = project.chapters[0]
        ch.utterances = [
            Utterance(speaker="Alice", text="Hi", emotion="happy", intensity=0.9)
        ]
        project._apply_default_intensities()
        assert ch.utterances[0].intensity == 0.9


# ===========================================================================
# cli: cast-export / cast-import --format csv
# ===========================================================================


class TestCastExportImportCLI:
    def test_cast_export_csv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        out = tmp_path / "cast.csv"
        code = main(["cast-export", str(out), "-p", str(path), "--format", "csv"])
        assert code == 0
        assert out.exists()
        assert out.read_text(encoding="utf-8").startswith("name,voice,gender")

    def test_cast_import_csv_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        out = tmp_path / "cast.csv"
        assert main(["cast-export", str(out), "-p", str(path)]) == 0

        # Mutate the CSV: add a brand-new character row.
        text = out.read_text(encoding="utf-8")
        out.write_text(text + "Zara,bf_emma,female,0,,1.0,1.0,,\n", encoding="utf-8")

        assert main(["cast-import", str(out), "-p", str(path), "--format", "csv"]) == 0
        loaded = AudiobookProject.load(path)
        assert (
            loaded.casting.characters[loaded.casting.normalize_key("Zara")].voice
            == "bf_emma"
        )


# ===========================================================================
# cli: cast-preset (casting.presets mocked with create=True)
# ===========================================================================


class TestCastPresetCLI:
    def test_save_calls_save_preset(self, tmp_path, monkeypatch, stub_presets):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        code = main(["cast-preset", "save", "mycast", "-p", str(path)])
        assert code == 0
        assert stub_presets.save_preset.called
        name, casting_list = stub_presets.save_preset.call_args[0][:2]
        assert name == "mycast"
        assert isinstance(casting_list, list)
        assert any(c.get("name") for c in casting_list)

    def test_save_from_project(self, tmp_path, monkeypatch, stub_presets):
        monkeypatch.chdir(tmp_path)
        seed = _write_project(tmp_path, title="Seed")
        code = main(["cast-preset", "save", "fromseed", "--from-project", str(seed)])
        assert code == 0
        assert stub_presets.save_preset.called

    def test_list_presets(self, tmp_path, capsys, stub_presets):
        stub_presets.list_presets.return_value = ["alpha", "beta"]
        code = main(["cast-preset", "list"])
        assert code == 0
        out = capsys.readouterr().out
        assert "alpha" in out and "beta" in out

    def test_list_presets_json(self, tmp_path, capsys, stub_presets):
        stub_presets.list_presets.return_value = ["alpha"]
        code = main(["cast-preset", "list", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["presets"] == ["alpha"]

    def test_apply_reports_matched_and_unmatched(
        self, tmp_path, monkeypatch, capsys, stub_presets
    ):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        # "narrator" IS a detected speaker in the fixture; "Ghost" is not.
        stub_presets.load_preset.return_value = [
            {"name": "narrator", "voice": "af_sky", "aliases": []},
            {"name": "Ghost", "voice": "am_onyx", "aliases": []},
        ]
        code = main(["cast-preset", "apply", "mycast", "-p", str(path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "Matched detected speakers: 1" in out
        assert "Added but not detected:    1" in out
        # Both characters end up in the cast.
        loaded = AudiobookProject.load(path)
        assert loaded.casting.normalize_key("narrator") in loaded.casting.characters
        assert loaded.casting.normalize_key("Ghost") in loaded.casting.characters

    def test_delete_calls_delete_preset(self, stub_presets):
        code = main(["cast-preset", "delete", "old"])
        assert code == 0
        assert stub_presets.delete_preset.call_args[0][0] == "old"

    def test_no_subcommand_usage(self, capsys):
        code = main(["cast-preset"])
        assert code == 1
        assert "Usage" in capsys.readouterr().out


# ===========================================================================
# cli: cast-fill (voice_suggester.bulk_fill_voices mocked with create=True)
# ===========================================================================


class TestCastFillCLI:
    def test_requires_explicit_pool(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        code = main(["cast-fill", "-p", str(path)])
        assert code == 1
        assert "explicit voice pool" in capsys.readouterr().out

    def test_calls_bulk_helper_with_pool(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        with patch(
            "audiobooker.casting.voice_suggester.bulk_fill_voices",
            create=True,
            return_value={"Alice": "af_sky", "Bob": "am_liam"},
        ) as mock_fill:
            code = main([
                "cast-fill",
                "-p", str(path),
                "--voices", "af_sky,am_liam",
                "--narrator", "af_heart",
                "--minor-voice", "am_onyx",
                "--minor-threshold", "3",
                "--gender", "female",
                "--overwrite",
            ])
        assert code == 0
        assert mock_fill.called
        kwargs = mock_fill.call_args.kwargs
        assert kwargs["voices"] == ["af_sky", "am_liam"]
        assert kwargs["narrator"] == "af_heart"
        assert kwargs["minor_voice"] == "am_onyx"
        assert kwargs["minor_threshold"] == 3
        assert kwargs["gender"] == "female"
        assert kwargs["overwrite"] is True
        out = capsys.readouterr().out
        assert "Alice" in out and "Bob" in out

    def test_narrator_only_pool_is_enough(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        with patch(
            "audiobooker.casting.voice_suggester.bulk_fill_voices",
            create=True,
            return_value={},
        ) as mock_fill:
            code = main(["cast-fill", "-p", str(path), "--narrator", "af_heart"])
        assert code == 0
        assert mock_fill.called


# ===========================================================================
# cli: speakers --suggest-aliases (casting.alias_discovery mocked)
# ===========================================================================


class TestSuggestAliasesCLI:
    def test_suggest_only_reports_without_apply(
        self, tmp_path, monkeypatch, capsys, stub_alias_discovery
    ):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        stub_alias_discovery.return_value = [
            AliasProposal(candidate="Al", speaker="Alice", score=0.9, co_occurrences=3),
            AliasProposal(candidate="Ally", speaker="Alice", score=0.5, co_occurrences=2),
        ]
        code = main(["speakers", "--suggest-aliases", "-p", str(path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "Al" in out and "Ally" in out
        assert "--apply" in out  # nudges the user; nothing applied yet
        # Nothing was written to the cast.
        loaded = AudiobookProject.load(path)
        alice = loaded.casting.characters.get(loaded.casting.normalize_key("Alice"))
        if alice is not None:
            assert "Al" not in alice.aliases

    def test_apply_writes_aliases(self, tmp_path, monkeypatch, stub_alias_discovery):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        # Alice must be cast for the alias to land on a character.
        project = AudiobookProject.load(path)
        project.cast("Alice", "af_sky")
        project.save(path)

        stub_alias_discovery.return_value = [
            AliasProposal(candidate="Al", speaker="Alice", score=0.9, co_occurrences=3),
        ]
        code = main(["speakers", "--suggest-aliases", "--apply", "-p", str(path)])
        assert code == 0
        loaded = AudiobookProject.load(path)
        alice = loaded.casting.characters[loaded.casting.normalize_key("Alice")]
        assert "Al" in alice.aliases

    def test_suggest_aliases_json(
        self, tmp_path, monkeypatch, capsys, stub_alias_discovery
    ):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        stub_alias_discovery.return_value = [
            AliasProposal(candidate="Al", speaker="Alice", score=0.9, co_occurrences=3),
        ]
        code = main(["speakers", "--suggest-aliases", "--json", "-p", str(path)])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["proposals"]["Alice"][0]["alias"] == "Al"


# ===========================================================================
# cli: emotions mood-span + presets
# ===========================================================================


class TestEmotionsMoodSpanCLI:
    def test_mood_span_injects_and_saves(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        code = main(["emotions", "mood-span", "0", "0", "5", "tense", "-p", str(path)])
        assert code == 0
        loaded = AudiobookProject.load(path)
        assert "[scene:tense]" in loaded.chapters[0].raw_text
        assert "mood" in capsys.readouterr().out.lower()

    def test_mood_span_bad_offsets_reports_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        code = main(["emotions", "mood-span", "0", "9", "2", "sad", "-p", str(path)])
        assert code == 1
        assert "Error" in capsys.readouterr().out


class TestEmotionsPresetsCLI:
    def test_presets_lists_packs_and_vocab(self, capsys):
        code = main(["emotions", "presets"])
        assert code == 0
        out = capsys.readouterr().out
        for pack in ("neutral", "literary", "dramatic", "children"):
            assert pack in out
        assert "vocabulary" in out.lower()

    def test_presets_json(self, capsys):
        code = main(["emotions", "presets", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert set(payload["presets"]) >= {
            "neutral", "literary", "dramatic", "children"
        }
        assert isinstance(payload["emotions"], list)
        assert payload["emotions"]  # non-empty vocabulary


# ===========================================================================
# cli: --emotion-preset on compile / make
# ===========================================================================


class TestEmotionPresetCLI:
    def test_compile_sets_emotion_preset(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        code = main(["compile", "-p", str(path), "--emotion-preset", "dramatic"])
        assert code == 0
        loaded = AudiobookProject.load(path)
        assert loaded.config.emotion_preset == "dramatic"

    def test_compile_invalid_preset_rejected_by_argparse(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = _write_project(tmp_path)
        # argparse choices reject the bad value before any handler runs.
        with pytest.raises(SystemExit):
            main(["compile", "-p", str(path), "--emotion-preset", "bogus"])

    def test_make_threads_emotion_preset(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text(
            "Chapter 1\n\nHello narration.\n\n\"Hi,\" said Bob.", encoding="utf-8"
        )

        captured = {}
        real_build = None
        from audiobooker import cli as cli_mod

        def _capture_build(file_config, cli_overrides, **kw):
            captured["cli_overrides"] = dict(cli_overrides)
            return real_build(file_config, cli_overrides, **kw)

        real_build = cli_mod._build_config_from
        # Stub render so make doesn't touch a TTS backend.
        with patch.object(cli_mod, "_build_config_from", side_effect=_capture_build), \
             patch(
                 "audiobooker.renderer.engine.render_project",
                 return_value=Path("out.m4b"),
             ):
            main(["make", str(src), "--emotion-preset", "literary"])

        assert captured["cli_overrides"].get("emotion_preset") == "literary"


# ===========================================================================
# parser smoke: every new subcommand is registered
# ===========================================================================


class TestParserRegistration:
    @pytest.mark.parametrize(
        "argv",
        [
            ["cast-preset", "save", "n"],
            ["cast-preset", "list"],
            ["cast-preset", "apply", "n"],
            ["cast-preset", "delete", "n"],
            ["cast-fill", "--voices", "a,b"],
            ["cast-export", "x.csv", "--format", "csv"],
            ["cast-import", "x.csv", "--format", "csv"],
            ["emotions", "mood-span", "0", "0", "10", "tense"],
            ["emotions", "presets"],
            ["speakers", "--suggest-aliases", "--apply"],
            ["compile", "--emotion-preset", "dramatic"],
            ["make", "book.epub", "--emotion-preset", "children"],
        ],
    )
    def test_parses(self, argv):
        parser = create_parser()
        ns = parser.parse_args(argv)
        assert ns.command == argv[0]
