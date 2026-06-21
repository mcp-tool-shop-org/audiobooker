"""OUTPUT-F1: Tests for v2.1 output/ACX CLI wiring.

Covers:
- ProjectConfig.output_profile / aac_bitrate / mp3_bitrate (validation + round-trip)
- render flags: --acx, --bitrate, --split, --narrator/--genre/--series
- new subcommands: sample, master-check, export-chapters

All renderer/output entry points (render_project, render_sample, master_check,
export_chapter_metadata) are mocked — these tests never touch real audio,
ffmpeg, or voice-soundboard.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from audiobooker.cli import create_parser, main
from audiobooker.models import ProjectConfig


# ---------------------------------------------------------------------------
# models.ProjectConfig — new fields
# ---------------------------------------------------------------------------


class TestProjectConfigOutputProfile:
    def test_defaults_preserve_current_behavior(self):
        cfg = ProjectConfig()
        assert cfg.output_profile == "podcast"
        assert cfg.aac_bitrate is None
        assert cfg.mp3_bitrate is None

    def test_acx_profile_accepted(self):
        cfg = ProjectConfig(output_profile="acx", aac_bitrate="192k", mp3_bitrate="192k")
        assert cfg.output_profile == "acx"
        assert cfg.aac_bitrate == "192k"
        assert cfg.mp3_bitrate == "192k"

    def test_invalid_profile_rejected(self):
        with pytest.raises(ValueError, match="output_profile"):
            ProjectConfig(output_profile="loud")

    def test_round_trip_serialization(self):
        cfg = ProjectConfig(output_profile="acx", aac_bitrate="256k", mp3_bitrate="192k")
        data = cfg.to_dict()
        assert data["output_profile"] == "acx"
        assert data["aac_bitrate"] == "256k"
        assert data["mp3_bitrate"] == "192k"
        restored = ProjectConfig.from_dict(data)
        assert restored.output_profile == "acx"
        assert restored.aac_bitrate == "256k"
        assert restored.mp3_bitrate == "192k"

    def test_from_dict_legacy_missing_keys_defaults(self):
        # An older project file with none of the new keys still loads.
        cfg = ProjectConfig.from_dict({"output_format": "m4b"})
        assert cfg.output_profile == "podcast"
        assert cfg.aac_bitrate is None
        assert cfg.mp3_bitrate is None


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestRenderFlagParsing:
    def test_render_acx_split_bitrate(self):
        parser = create_parser()
        args = parser.parse_args(
            ["render", "--acx", "--split", "--bitrate", "192k"]
        )
        assert args.acx is True
        assert args.split is True
        assert args.bitrate == "192k"

    def test_render_metadata_overrides(self):
        parser = create_parser()
        args = parser.parse_args(
            ["render", "--narrator", "Jane Doe", "--genre", "Sci-Fi", "--series", "Foundation"]
        )
        assert args.narrator == "Jane Doe"
        assert args.genre == "Sci-Fi"
        assert args.series == "Foundation"

    def test_render_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["render"])
        assert args.acx is False
        assert args.split is False
        assert args.bitrate is None
        assert args.narrator is None


class TestSampleFlagParsing:
    def test_sample_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            ["sample", "--from-chapter", "2", "--start-seconds", "10", "--duration", "120", "--acx"]
        )
        assert args.command == "sample"
        assert args.from_chapter == 2
        assert args.start_seconds == 10.0
        assert args.duration == 120.0
        assert args.acx is True

    def test_sample_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["sample"])
        assert args.from_chapter == 0
        assert args.start_seconds == 0.0
        assert args.duration == 180.0


class TestMasterCheckExportParsing:
    def test_master_check_args(self):
        parser = create_parser()
        args = parser.parse_args(["master-check", "book.m4b", "--json"])
        assert args.command == "master-check"
        assert args.file == "book.m4b"
        assert args.json_output is True

    def test_export_chapters_format_choices(self):
        parser = create_parser()
        for fmt in ("ffmetadata", "cue", "json"):
            args = parser.parse_args(["export-chapters", "--format", fmt])
            assert args.chapter_format == fmt

    def test_export_chapters_default_format(self):
        parser = create_parser()
        args = parser.parse_args(["export-chapters"])
        assert args.chapter_format == "ffmetadata"


# ---------------------------------------------------------------------------
# render command — routing of new kwargs into render_project / project.render
# ---------------------------------------------------------------------------


def _write_project(tmp_path: Path) -> Path:
    """Create a tiny compiled project file on disk and return its path."""
    from audiobooker.project import AudiobookProject

    project = AudiobookProject.from_string(
        "Chapter 1\n\nHello world. This is a test sentence for narration.",
        title="Routing Test",
        author="Tester",
    )
    project.cast("narrator", "af_heart")
    project.compile()
    path = tmp_path / "routing.audiobooker"
    project.save(path)
    return path


class TestRenderRouting:
    def test_acx_routes_through_render_project_with_profile(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")

        with patch("audiobooker.renderer.engine.render_project", return_value=fake_out) as mock_rp:
            code = main(["render", "-p", str(proj_path), "--acx", "-o", str(fake_out)])

        assert code == 0
        assert mock_rp.called
        kwargs = mock_rp.call_args.kwargs
        assert kwargs.get("output_profile") == "acx"

    def test_split_and_bitrate_passed_through(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")

        with patch("audiobooker.renderer.engine.render_project", return_value=fake_out) as mock_rp:
            code = main(
                ["render", "-p", str(proj_path), "--split", "--bitrate", "192k", "-o", str(fake_out)]
            )

        assert code == 0
        kwargs = mock_rp.call_args.kwargs
        assert kwargs.get("split") is True
        assert kwargs.get("bitrate") == "192k"

    def test_metadata_overrides_applied_before_render(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")

        captured = {}

        def _capture(project, output_path, **kwargs):
            captured["narrator"] = project.metadata.narrator_name
            captured["genre"] = project.metadata.genre
            captured["series"] = project.metadata.series
            return fake_out

        with patch("audiobooker.renderer.engine.render_project", side_effect=_capture):
            code = main(
                [
                    "render", "-p", str(proj_path),
                    "--narrator", "Jane Doe",
                    "--genre", "Fantasy",
                    "--series", "Realm",
                    "--acx",  # force the direct render_project path
                    "-o", str(fake_out),
                ]
            )

        assert code == 0
        assert captured["narrator"] == "Jane Doe"
        assert captured["genre"] == "Fantasy"
        assert captured["series"] == "Realm"

    def test_plain_render_still_works(self, tmp_path, monkeypatch):
        """No advanced flags -> goes through project.render(), preserving behavior."""
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")

        with patch(
            "audiobooker.project.AudiobookProject.render", return_value=fake_out
        ) as mock_render:
            code = main(["render", "-p", str(proj_path), "-o", str(fake_out)])

        assert code == 0
        assert mock_render.called
        kwargs = mock_render.call_args.kwargs
        # project.render forwards profile/bitrate/split with podcast defaults.
        assert kwargs.get("output_profile") == "podcast"
        assert kwargs.get("split") is False


# ---------------------------------------------------------------------------
# sample command
# ---------------------------------------------------------------------------


class TestSampleCommand:
    def test_sample_invokes_render_sample(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "sample.m4b"

        # render_sample is added concurrently by the renderer agent; create=True
        # lets these tests pass whether or not it exists yet in the engine module.
        with patch(
            "audiobooker.renderer.engine.render_sample", return_value=out, create=True
        ) as mock_rs:
            code = main(
                [
                    "sample", "-p", str(proj_path),
                    "--from-chapter", "0",
                    "--start-seconds", "5",
                    "--duration", "60",
                    "--acx",
                    "-o", str(out),
                ]
            )

        assert code == 0
        assert mock_rs.called
        kwargs = mock_rs.call_args.kwargs
        assert kwargs.get("from_chapter") == 0
        assert kwargs.get("start_seconds") == 5.0
        assert kwargs.get("duration") == 60.0
        assert kwargs.get("output_profile") == "acx"

    def test_sample_chapter_out_of_range(self, tmp_path, monkeypatch, capsys):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.renderer.engine.render_sample", create=True
        ) as mock_rs:
            code = main(["sample", "-p", str(proj_path), "--from-chapter", "99"])

        assert code == 1
        assert not mock_rs.called
        captured = capsys.readouterr()
        assert "not found" in captured.out


# ---------------------------------------------------------------------------
# master-check command
# ---------------------------------------------------------------------------


def _master_result(passes: bool) -> dict:
    return {
        "profile": "acx",
        "measured_rms_db": -20.5,
        "measured_peak_db": -3.5,
        "measured_noise_floor_db": -65.0,
        "passes": passes,
        "failures": [] if passes else ["RMS -12.0 dB outside ACX range [-23, -18]"],
    }


class TestMasterCheckCommand:
    def test_pass_returns_zero(self, tmp_path, capsys):
        audio = tmp_path / "book.m4b"
        audio.write_bytes(b"fake")

        with patch("audiobooker.renderer.output.master_check", return_value=_master_result(True)):
            code = main(["master-check", str(audio)])

        assert code == 0
        out = capsys.readouterr().out
        assert "PASS" in out

    def test_fail_returns_one(self, tmp_path, capsys):
        audio = tmp_path / "book.m4b"
        audio.write_bytes(b"fake")

        with patch("audiobooker.renderer.output.master_check", return_value=_master_result(False)):
            code = main(["master-check", str(audio)])

        assert code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out

    def test_json_output(self, tmp_path, capsys):
        audio = tmp_path / "book.m4b"
        audio.write_bytes(b"fake")

        with patch("audiobooker.renderer.output.master_check", return_value=_master_result(True)):
            code = main(["master-check", str(audio), "--json"])

        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["passes"] is True
        assert payload["profile"] == "acx"

    def test_missing_file_returns_one(self, tmp_path, capsys):
        missing = tmp_path / "nope.m4b"
        code = main(["master-check", str(missing)])
        assert code == 1
        assert "not found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# export-chapters command
# ---------------------------------------------------------------------------


class TestExportChaptersCommand:
    def test_export_to_stdout(self, tmp_path, monkeypatch, capsys):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.renderer.output.export_chapter_metadata",
            return_value=";FFMETADATA1\n[CHAPTER]\n",
        ) as mock_exp:
            code = main(["export-chapters", "-p", str(proj_path), "--format", "ffmetadata"])

        assert code == 0
        assert mock_exp.called
        assert mock_exp.call_args.kwargs.get("fmt") == "ffmetadata"
        assert "FFMETADATA1" in capsys.readouterr().out

    def test_export_to_file(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "chapters.cue"

        with patch(
            "audiobooker.renderer.output.export_chapter_metadata",
            return_value='FILE "x" WAVE\n',
        ):
            code = main(
                ["export-chapters", "-p", str(proj_path), "--format", "cue", "-o", str(out)]
            )

        assert code == 0
        assert out.exists()
        assert "WAVE" in out.read_text(encoding="utf-8")

    def test_export_json_passes_chapters(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.renderer.output.export_chapter_metadata",
            return_value="[]",
        ) as mock_exp:
            code = main(["export-chapters", "-p", str(proj_path), "--format", "json"])

        assert code == 0
        # First positional arg is the chapters/durations payload — a list of
        # (title, duration_seconds) tuples.
        chapters_arg = mock_exp.call_args.args[0]
        assert isinstance(chapters_arg, list)
        assert chapters_arg and len(chapters_arg[0]) == 2
        assert isinstance(chapters_arg[0][0], str)  # title
