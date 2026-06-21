"""ECOSYSTEM (v2.1): Tests for the integration layer (cli / models / pyproject).

This agent owns audiobooker/cli.py, audiobooker/models.py, audiobooker/project.py,
and pyproject.toml. The renderer/casting-owned shared contract points
(engine.get_default_engine, voice_registry.get_available_voices,
output.export_podcast_rss) evolve in parallel and are exercised ONLY through
mocks here — they are validated by the renderer/casting agents' own tests.

Covers:
- models: ProjectConfig.tts_engine + ProjectConfig.utterance_cache — defaults
  preserve current behavior, serialization round-trips, legacy configs default
  cleanly.
- pyproject: the audiobooker.tts_engines entry-point registers voice-soundboard
  to the built-in engine class.
- cli FT-ENGINE-001: --engine threads the resolved engine into render/preview/
  sample/audition/make/batch; the None default preserves current behavior
  byte-for-byte. voices --engine lists that engine's voices via
  get_available_voices(engine=...).
- cli FT-RENDER-M-008: the `podcast` subcommand renders per-chapter (split) and
  writes podcast.xml from output.export_podcast_rss(project, items, base_url=).

No real audio, ffmpeg, voice-soundboard, or TTS engine is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audiobooker.cli import create_parser, main
from audiobooker.models import ProjectConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_project(tmp_path: Path, title: str = "Ecosystem Test") -> Path:
    """A tiny compiled project file on disk; returns its path."""
    from audiobooker.project import AudiobookProject

    project = AudiobookProject.from_string(
        "Chapter 1\n\nHello world. This is narration for the engine test.\n\n"
        '"I am Alice," she said.',
        title=title,
        author="Tester",
    )
    project.cast("narrator", "af_heart")
    project.compile()
    path = tmp_path / "ecosystem.audiobooker"
    project.save(path)
    return path


# ===========================================================================
# models: ProjectConfig.tts_engine + ProjectConfig.utterance_cache
# ===========================================================================


class TestProjectConfigEngineFields:
    def test_defaults_preserve_current_behavior(self):
        cfg = ProjectConfig()
        assert cfg.tts_engine == "voice-soundboard"
        assert cfg.utterance_cache is False

    def test_serialization_round_trip(self):
        cfg = ProjectConfig(tts_engine="my-tts", utterance_cache=True)
        data = cfg.to_dict()
        assert data["tts_engine"] == "my-tts"
        assert data["utterance_cache"] is True
        restored = ProjectConfig.from_dict(data)
        assert restored.tts_engine == "my-tts"
        assert restored.utterance_cache is True

    def test_legacy_config_defaults(self):
        # A pre-v2.1 config dict has neither key.
        cfg = ProjectConfig.from_dict({"output_format": "m4b"})
        assert cfg.tts_engine == "voice-soundboard"
        assert cfg.utterance_cache is False

    def test_default_dict_omits_no_new_keys(self):
        # Both new keys are always serialized (round-trip stability).
        data = ProjectConfig().to_dict()
        assert "tts_engine" in data
        assert "utterance_cache" in data


# ===========================================================================
# pyproject: entry-point registration
# ===========================================================================


class TestEntryPointRegistration:
    def test_pyproject_registers_builtin_engine(self):
        root = Path(__file__).resolve().parent.parent
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        assert '[project.entry-points."audiobooker.tts_engines"]' in text
        # voice-soundboard registered to the built-in engine class.
        assert (
            'voice-soundboard = "audiobooker.renderer.engine:_VoiceSoundboardEngine"'
            in text
        )

    def test_entry_point_target_resolves(self):
        # The string in pyproject must point at an importable class.
        import importlib

        modname, _, qual = (
            "audiobooker.renderer.engine:_VoiceSoundboardEngine"
        ).partition(":")
        obj = importlib.import_module(modname)
        for part in qual.split("."):
            obj = getattr(obj, part)
        assert obj.__name__ == "_VoiceSoundboardEngine"


# ===========================================================================
# cli: argument parsing for --engine + podcast
# ===========================================================================


class TestEngineFlagParsing:
    @pytest.mark.parametrize(
        "argv",
        [
            ["render", "--engine", "my-tts"],
            ["batch", "--engine", "my-tts"],
            ["preview", "--engine", "my-tts"],
            ["make", "book.epub", "--engine", "my-tts"],
            ["voices", "--engine", "my-tts"],
            ["sample", "--engine", "my-tts"],
            ["audition", "Alice", "--engine", "my-tts"],
            ["podcast", "--engine", "my-tts"],
        ],
    )
    def test_engine_flag_parses(self, argv):
        parser = create_parser()
        args = parser.parse_args(argv)
        assert args.engine == "my-tts"

    def test_engine_default_is_none(self):
        parser = create_parser()
        args = parser.parse_args(["render"])
        assert args.engine is None

    def test_voices_json_flag(self):
        parser = create_parser()
        args = parser.parse_args(["voices", "--json"])
        assert args.json_output is True


class TestPodcastFlagParsing:
    def test_podcast_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            ["podcast", "--base-url", "https://cdn/", "-o", "feed.xml",
             "--format", "mp3", "-j", "3", "--no-render"]
        )
        assert args.command == "podcast"
        assert args.base_url == "https://cdn/"
        assert args.output == "feed.xml"
        assert args.output_format == "mp3"
        assert args.jobs == 3
        assert args.no_render is True

    def test_podcast_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["podcast"])
        assert args.base_url == ""
        assert args.output is None
        assert args.no_render is False
        assert args.jobs == 1


# ===========================================================================
# cli FT-ENGINE-001: --engine threads the resolved engine into render
# ===========================================================================


class TestRenderEngineRouting:
    def test_no_engine_keeps_current_behavior(self, tmp_path, monkeypatch):
        """Without --engine and with a default project config, project.render is
        called WITHOUT an engine kwarg (current behavior preserved)."""
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
        # The plain path goes through project.render and must NOT inject engine.
        assert "engine" not in mock_render.call_args.kwargs

    def test_engine_routes_through_render_project_with_instance(
        self, tmp_path, monkeypatch
    ):
        """With --engine, the resolved instance is threaded into render_project."""
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")
        fake_engine = MagicMock(name="engine_instance")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ) as mock_get, patch(
            "audiobooker.renderer.engine.render_project", return_value=fake_out
        ) as mock_rp:
            code = main(
                ["render", "-p", str(proj_path), "--engine", "my-tts",
                 "-o", str(fake_out)]
            )

        assert code == 0
        mock_get.assert_called_once_with("my-tts")
        assert mock_rp.called
        assert mock_rp.call_args.kwargs.get("engine") is fake_engine

    def test_config_tts_engine_resolved_when_no_flag(self, tmp_path, monkeypatch):
        """A non-default project config tts_engine is resolved even without the
        --engine flag (explicit config choice)."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string(
            "Chapter 1\n\nHello world.", title="Cfg Engine", author="T"
        )
        project.cast("narrator", "af_heart")
        project.config.tts_engine = "configured-tts"
        project.compile()
        proj_path = tmp_path / "cfg.audiobooker"
        project.save(proj_path)
        monkeypatch.chdir(tmp_path)

        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")
        fake_engine = MagicMock(name="engine_instance")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ) as mock_get, patch(
            "audiobooker.renderer.engine.render_project", return_value=fake_out
        ) as mock_rp:
            code = main(["render", "-p", str(proj_path), "-o", str(fake_out)])

        assert code == 0
        mock_get.assert_called_once_with("configured-tts")
        assert mock_rp.call_args.kwargs.get("engine") is fake_engine

    def test_flag_overrides_config_engine(self, tmp_path, monkeypatch):
        """--engine wins over a project config tts_engine."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string(
            "Chapter 1\n\nHello world.", title="Override", author="T"
        )
        project.cast("narrator", "af_heart")
        project.config.tts_engine = "configured-tts"
        project.compile()
        proj_path = tmp_path / "ov.audiobooker"
        project.save(proj_path)
        monkeypatch.chdir(tmp_path)

        fake_out = tmp_path / "out.m4b"
        fake_out.write_bytes(b"fake")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=MagicMock(),
        ) as mock_get, patch(
            "audiobooker.renderer.engine.render_project", return_value=fake_out
        ):
            code = main(
                ["render", "-p", str(proj_path), "--engine", "cli-tts",
                 "-o", str(fake_out)]
            )

        assert code == 0
        # The CLI flag wins over the config value.
        mock_get.assert_called_once_with("cli-tts")


class TestPreviewSampleAuditionEngine:
    def test_preview_threads_engine(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_engine = MagicMock(name="engine")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.renderer.engine.render_chapter",
            return_value=tmp_path / "preview.wav",
        ) as mock_rc:
            code = main(
                ["preview", "-p", str(proj_path), "--engine", "my-tts"]
            )

        assert code == 0
        assert mock_rc.call_args.kwargs.get("engine") is fake_engine

    def test_preview_no_engine_omits_kwarg(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.renderer.engine.render_chapter",
            return_value=tmp_path / "preview.wav",
        ) as mock_rc:
            code = main(["preview", "-p", str(proj_path)])

        assert code == 0
        assert "engine" not in mock_rc.call_args.kwargs

    def test_sample_threads_engine(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_engine = MagicMock(name="engine")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.renderer.engine.render_sample",
            return_value=tmp_path / "sample.m4a",
        ) as mock_rs:
            code = main(
                ["sample", "-p", str(proj_path), "--engine", "my-tts"]
            )

        assert code == 0
        assert mock_rs.call_args.kwargs.get("engine") is fake_engine

    def test_audition_render_threads_engine(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_engine = MagicMock(name="engine")

        candidates = [{"voice_id": "af_sky", "gender": "female",
                       "style": "warm", "score": 0.9}]

        with patch(
            "audiobooker.casting.voice_suggester.audition_voices",
            return_value=candidates,
        ), patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.renderer.engine.render_chapter",
            return_value=tmp_path / "af_sky.wav",
        ) as mock_rc:
            code = main(
                ["audition", "narrator", "-p", str(proj_path),
                 "--render", "--engine", "my-tts"]
            )

        assert code == 0
        assert mock_rc.called
        assert mock_rc.call_args.kwargs.get("engine") is fake_engine


class TestMakeBatchEngine:
    def test_make_threads_engine_into_process_book(self, tmp_path, monkeypatch):
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello world from make.", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        fake_engine = MagicMock(name="engine")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.renderer.engine.render_project",
            return_value=tmp_path / "out.m4b",
        ) as mock_rp:
            code = main(["make", str(src), "--engine", "my-tts"])

        assert code == 0
        assert mock_rp.called
        assert mock_rp.call_args.kwargs.get("engine") is fake_engine

    def test_batch_threads_engine(self, tmp_path, monkeypatch):
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello world for batch.", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        fake_engine = MagicMock(name="engine")

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.renderer.engine.render_project",
            return_value=tmp_path / "out.m4b",
        ) as mock_rp:
            code = main(["batch", str(src), "--engine", "my-tts"])

        assert code in (0, 3)
        assert mock_rp.called
        assert mock_rp.call_args.kwargs.get("engine") is fake_engine


# ===========================================================================
# cli FT-ENGINE-001: voices --engine
# ===========================================================================


class TestVoicesEngine:
    def test_voices_default_uses_registry(self, capsys):
        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart", "am_liam"},
        ) as mock_gv:
            code = main(["voices"])

        assert code == 0
        # Default path resolves no engine -> get_available_voices(engine=None).
        assert mock_gv.called
        out = capsys.readouterr().out
        assert "af_heart" in out
        assert "am_liam" in out

    def test_voices_engine_resolves_and_lists(self, capsys):
        fake_engine = MagicMock(name="engine")
        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ) as mock_get, patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"xx_one", "xx_two"},
        ) as mock_gv:
            code = main(["voices", "--engine", "my-tts"])

        assert code == 0
        mock_get.assert_called_once_with("my-tts")
        # The resolved engine instance is passed through to the registry.
        assert mock_gv.call_args.kwargs.get("engine") is fake_engine
        out = capsys.readouterr().out
        assert "xx_one" in out and "xx_two" in out
        assert "my-tts" in out  # header names the engine

    def test_voices_json_output(self, capsys):
        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart"},
        ):
            code = main(["voices", "--json"])

        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["engine"] == "voice-soundboard"
        assert {"voice_id": "af_heart"} in payload["voices"]

    def test_voices_rich_descriptor_shape(self, capsys):
        """get_available_voices may return richer descriptors (id+description)."""
        fake_engine = MagicMock(name="engine")
        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value=[
                {"voice_id": "nv_1", "description": "Narrator One"},
                ("nv_2", "Narrator Two"),
            ],
        ):
            code = main(["voices", "--engine", "my-tts"])

        assert code == 0
        out = capsys.readouterr().out
        assert "nv_1" in out and "Narrator One" in out
        assert "nv_2" in out and "Narrator Two" in out

    def test_voices_search_filter(self, capsys):
        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart", "am_liam"},
        ):
            code = main(["voices", "--search", "liam"])

        assert code == 0
        out = capsys.readouterr().out
        assert "am_liam" in out
        assert "af_heart" not in out


# ===========================================================================
# cli FT-RENDER-M-008: podcast subcommand
# ===========================================================================


class TestPodcastCommand:
    def test_podcast_renders_split_and_writes_feed(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        # render() is mocked; mark chapters as rendered so items have filenames.
        def _fake_render(self, **kwargs):
            for ch in self.chapters:
                ch.audio_path = tmp_path / f"chapter_{ch.index:03d}.m4a"
                ch.duration_seconds = 12.5
            return tmp_path

        with patch(
            "audiobooker.project.AudiobookProject.render",
            autospec=True, side_effect=_fake_render,
        ) as mock_render, patch(
            "audiobooker.renderer.output.export_podcast_rss",
            create=True, return_value="<rss>FEED</rss>",
        ) as mock_rss:
            code = main(
                ["podcast", "-p", str(proj_path),
                 "--base-url", "https://cdn/", "-o", str(tmp_path / "feed.xml")]
            )

        assert code == 0
        # split=True render requested.
        assert mock_render.called
        assert mock_render.call_args.kwargs.get("split") is True
        # export_podcast_rss called with base_url and a per-chapter items list.
        assert mock_rss.called
        assert mock_rss.call_args.kwargs.get("base_url") == "https://cdn/"
        items = mock_rss.call_args.args[1]
        assert items and all("filename" in it for it in items)
        # Feed XML written to the requested path.
        assert (tmp_path / "feed.xml").read_text(encoding="utf-8") == "<rss>FEED</rss>"

    def test_podcast_default_output_path(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        def _fake_render(self, **kwargs):
            for ch in self.chapters:
                ch.audio_path = tmp_path / f"chapter_{ch.index:03d}.m4a"
                ch.duration_seconds = 1.0
            return tmp_path

        with patch(
            "audiobooker.project.AudiobookProject.render",
            autospec=True, side_effect=_fake_render,
        ), patch(
            "audiobooker.renderer.output.export_podcast_rss",
            create=True, return_value="<rss/>",
        ):
            code = main(["podcast", "-p", str(proj_path)])

        assert code == 0
        assert (tmp_path / "podcast.xml").exists()

    def test_podcast_no_render_uses_existing_audio(self, tmp_path, monkeypatch):
        """--no-render skips rendering and builds the feed from existing audio."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string(
            "Chapter 1\n\nHello.\n\nChapter 2\n\nWorld.",
            title="Prerendered", author="T",
        )
        project.cast("narrator", "af_heart")
        project.compile()
        for ch in project.chapters:
            ch.audio_path = tmp_path / f"ch_{ch.index}.m4a"
            ch.duration_seconds = 3.0
        proj_path = tmp_path / "pre.audiobooker"
        project.save(proj_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.project.AudiobookProject.render"
        ) as mock_render, patch(
            "audiobooker.renderer.output.export_podcast_rss",
            create=True, return_value="<rss/>",
        ) as mock_rss:
            code = main(["podcast", "-p", str(proj_path), "--no-render"])

        assert code == 0
        # --no-render must NOT trigger a render.
        assert not mock_render.called
        assert mock_rss.called

    def test_podcast_threads_engine(self, tmp_path, monkeypatch):
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        fake_engine = MagicMock(name="engine")

        def _fake_render(self, **kwargs):
            for ch in self.chapters:
                ch.audio_path = tmp_path / f"chapter_{ch.index:03d}.m4a"
                ch.duration_seconds = 5.0
            return tmp_path

        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=fake_engine,
        ), patch(
            "audiobooker.project.AudiobookProject.render",
            autospec=True, side_effect=_fake_render,
        ) as mock_render, patch(
            "audiobooker.renderer.output.export_podcast_rss",
            create=True, return_value="<rss/>",
        ):
            code = main(
                ["podcast", "-p", str(proj_path), "--engine", "my-tts"]
            )

        assert code == 0
        assert mock_render.call_args.kwargs.get("engine") is fake_engine

    def test_podcast_no_audio_errors_cleanly(self, tmp_path, monkeypatch, capsys):
        """--no-render with no rendered audio is a clean user error (exit 1)."""
        proj_path = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.renderer.output.export_podcast_rss",
            create=True, return_value="<rss/>",
        ) as mock_rss:
            code = main(["podcast", "-p", str(proj_path), "--no-render"])

        assert code == 1
        # No feed built when there's nothing to enclose.
        assert not mock_rss.called
        assert "no rendered chapter audio" in capsys.readouterr().out.lower()
