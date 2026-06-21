"""F-FEAT-F3 (WORKFLOW v2.1): Tests for the CLI workflow features.

Covers the cli.py side of the v2.1 WORKFLOW slice (the other agent owns
config_file.py / project.py / models.py and is exercised only via mocks here):

- FT-CLI-001  make: one command new -> compile -> auto-cast -> render
- FT-CLI-002  config-file merge (CLI flag > config-file value > default)
- FT-CAST-019 audition <character> table + --render
- FT-CLI-003  interactive casting (cast --interactive / cast-interactive)
- FT-CLI-004  shell completion subcommand + argcomplete marker
- FT-CLI-008  watch mode (mtime polling, resume, Ctrl-C clean)
- FT-CLI-006  manifest batch (--manifest .toml/.json)
- FT-PARSE-006 chapters rename / reorder (CLI side; project methods mocked)

Render/engine and the voice suggester are mocked: these tests never touch real
audio, ffmpeg, or voice-soundboard.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from audiobooker.cli import (
    _apply_book_overrides,
    _build_config_from,
    _load_manifest,
    create_parser,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_project(tmp_path: Path, title: str = "Workflow Test") -> Path:
    """Create a tiny compiled project file on disk and return its path."""
    from audiobooker.project import AudiobookProject

    project = AudiobookProject.from_string(
        "Chapter 1\n\nHello world. This is a test sentence for narration.\n\n"
        '"I am Alice," she said.',
        title=title,
        author="Tester",
    )
    project.compile()
    path = tmp_path / "wf.audiobooker"
    project.save(path)
    return path


# ===========================================================================
# FT-CLI-002: config-file merge
# ===========================================================================


class TestConfigMerge:
    def test_cli_flag_beats_config_beats_default(self):
        file_cfg = {"output_format": "mp3", "estimated_wpm": 200}
        cfg = _build_config_from(
            file_cfg,
            cli_overrides={"output_format": "wav"},
            base_kwargs={"language_code": "fr"},
        )
        assert cfg.output_format == "wav"        # CLI flag wins
        assert cfg.estimated_wpm == 200          # config-file value
        assert cfg.language_code == "fr"         # base kwarg
        assert cfg.chapter_pause_ms == 2000      # built-in default

    def test_none_cli_override_does_not_clobber_config(self):
        file_cfg = {"output_format": "mp3"}
        cfg = _build_config_from(file_cfg, cli_overrides={"output_format": None})
        assert cfg.output_format == "mp3"

    def test_section_keys_stripped_before_construction(self):
        # book/casting/lexicon must never reach ProjectConfig(**mapped).
        file_cfg = {
            "output_format": "m4b",
            "book": {"title": "X"},
            "casting": "cast.json",
            "lexicon": "lex.csv",
        }
        cfg = _build_config_from(file_cfg, cli_overrides={})
        assert cfg.output_format == "m4b"

    def test_invalid_config_value_raises_structured_error(self):
        # ProjectConfig.__post_init__ validates; bad enum -> ValueError.
        with pytest.raises(ValueError, match="output_format"):
            _build_config_from({"output_format": "flacc"}, cli_overrides={})

    def test_new_seeds_config_from_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello world narration here.", encoding="utf-8")

        captured = {}

        def _fake_load_config(source_path=None):
            return {"output_format": "mp3", "estimated_wpm": 222}

        real_from_text = None
        from audiobooker.project import AudiobookProject

        def _capture_from_text(path, *, config=None, **kw):
            captured["config"] = config
            return real_from_text(path, config=config, **kw)

        real_from_text = AudiobookProject.from_text
        with patch("audiobooker.cli._load_config_file", side_effect=_fake_load_config), \
             patch.object(AudiobookProject, "from_text", staticmethod(_capture_from_text)):
            code = main(["new", str(src)])

        assert code == 0
        assert captured["config"].output_format == "mp3"
        assert captured["config"].estimated_wpm == 222

    def test_new_cli_lang_beats_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText.", encoding="utf-8")

        with patch(
            "audiobooker.cli._load_config_file",
            return_value={"language_code": "es"},
        ):
            code = main(["new", str(src), "--lang", "en"])
        assert code == 0
        # Loaded project should carry the CLI lang, not the config one.
        proj = next(tmp_path.glob("*.audiobooker"))
        from audiobooker.project import AudiobookProject
        loaded = AudiobookProject.load(proj)
        assert loaded.config.language_code == "en"


# ===========================================================================
# FT-CLI-002: config sections (book / casting / lexicon)
# ===========================================================================


class TestConfigSections:
    def test_book_section_applied(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText body here.", encoding="utf-8")

        cfg = {
            "book": {
                "title": "Configured Title",
                "author": "Cfg Author",
                "series": "My Series",
                "series_index": 3,
            }
        }
        with patch("audiobooker.cli._load_config_file", return_value=cfg):
            code = main(["new", str(src)])
        assert code == 0
        from audiobooker.project import AudiobookProject
        loaded = AudiobookProject.load(next(tmp_path.glob("*.audiobooker")))
        assert loaded.title == "Configured Title"
        assert loaded.author == "Cfg Author"
        assert loaded.metadata.series == "My Series"
        assert loaded.metadata.series_index == 3

    def test_casting_section_imported(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText.", encoding="utf-8")

        with patch("audiobooker.cli._load_config_file", return_value={"casting": "cast.json"}), \
             patch(
                 "audiobooker.project.AudiobookProject.import_casting"
             ) as mock_import:
            code = main(["new", str(src)])
        assert code == 0
        assert mock_import.called

    def test_missing_casting_file_warns_not_fatal(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText.", encoding="utf-8")

        with patch(
            "audiobooker.cli._load_config_file",
            return_value={"casting": "does-not-exist.json"},
        ):
            code = main(["new", str(src)])
        assert code == 0  # missing aux file is a warning, not a failure
        out = capsys.readouterr().out
        assert "WARNING" in out


# ===========================================================================
# FT-CLI-001: make
# ===========================================================================


class TestMake:
    def test_make_runs_full_sequence(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text(
            "Chapter 1\n\nHello world narration.\n\n\"Hi,\" said Bob.",
            encoding="utf-8",
        )
        fake_out = tmp_path / "Book.m4b"

        with patch(
            "audiobooker.renderer.engine.render_project", return_value=fake_out
        ) as mock_rp:
            code = main(["make", str(src), "-j", "2"])

        assert code == 0
        assert mock_rp.called
        # auto-cast + force are part of the shared per-book sequence.
        assert mock_rp.call_args.kwargs.get("force") is True
        assert mock_rp.call_args.kwargs.get("jobs") == 2

    def test_make_threads_acx_and_cover(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText.", encoding="utf-8")
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8\xff fake-jpeg")
        fake_out = tmp_path / "out.m4b"

        with patch(
            "audiobooker.renderer.engine.render_project", return_value=fake_out
        ) as mock_rp:
            code = main(["make", str(src), "--acx", "--cover", str(cover), "--normalize"])

        assert code == 0
        kwargs = mock_rp.call_args.kwargs
        assert kwargs.get("output_profile") == "acx"
        assert kwargs.get("cover_art") == str(cover)
        assert kwargs.get("normalize") is True

    def test_make_missing_source(self, tmp_path, capsys):
        code = main(["make", str(tmp_path / "nope.txt")])
        assert code == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_make_uses_explicit_output_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText.", encoding="utf-8")
        out = tmp_path / "custom" / "name.mp3"

        captured = {}

        def _capture(project, output_path, **kw):
            captured["output"] = output_path
            return output_path

        with patch(
            "audiobooker.renderer.engine.render_project", side_effect=_capture
        ):
            code = main(["make", str(src), "-o", str(out), "--format", "mp3"])

        assert code == 0
        assert Path(captured["output"]) == out


# ===========================================================================
# FT-CAST-019: audition
# ===========================================================================


class TestAudition:
    def _fake_candidates(self):
        return [
            {"voice_id": "af_heart", "gender": "female", "style": "calm",
             "sample_text": "hi", "score": 0.91, "low_confidence": False},
            {"voice_id": "bm_george", "gender": "male", "style": "calm",
             "sample_text": "hi", "score": 0.80, "low_confidence": False},
            {"voice_id": "am_eric", "gender": "male", "style": "neutral",
             "sample_text": "hi", "score": 0.70, "low_confidence": True},
        ]

    def test_audition_prints_table(self, tmp_path, monkeypatch, capsys):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.casting.voice_suggester.audition_voices",
            return_value=self._fake_candidates(),
        ):
            code = main(["audition", "narrator", "-p", str(proj), "-n", "2"])

        assert code == 0
        out = capsys.readouterr().out
        assert "af_heart" in out
        assert "bm_george" in out
        # capped at top 2 -> the third voice should not appear
        assert "am_eric" not in out

    def test_audition_json(self, tmp_path, monkeypatch, capsys):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.casting.voice_suggester.audition_voices",
            return_value=self._fake_candidates(),
        ):
            code = main(["audition", "narrator", "-p", str(proj), "--json"])

        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["speaker"] == "narrator"
        assert len(payload["candidates"]) == 3

    def test_audition_render_writes_one_wav_per_voice(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "aud"

        rendered = []

        def _fake_render(chapter, casting, output_path, **kw):
            Path(output_path).write_bytes(b"wav")
            rendered.append(Path(output_path).name)
            return Path(output_path)

        with patch(
            "audiobooker.casting.voice_suggester.audition_voices",
            return_value=self._fake_candidates(),
        ), patch(
            "audiobooker.renderer.engine.render_chapter", side_effect=_fake_render
        ):
            code = main([
                "audition", "narrator", "-p", str(proj), "-n", "2",
                "--render", "--line", "Sample line.", "-o", str(out_dir),
            ])

        assert code == 0
        assert sorted(rendered) == ["af_heart.wav", "bm_george.wav"]
        assert (out_dir / "af_heart.wav").exists()


# ===========================================================================
# FT-CLI-003: interactive casting
# ===========================================================================


class TestInteractiveCast:
    def _suggestions(self):
        from audiobooker.casting.voice_suggester import (
            SpeakerSuggestions, VoiceSuggestion,
        )
        return [
            SpeakerSuggestions(
                speaker="Alice",
                suggestions=[
                    VoiceSuggestion("af_heart", 0.9, "good narrator match"),
                    VoiceSuggestion("bf_emma", 0.7, "warm dialogue"),
                ],
            )
        ]

    def test_non_tty_falls_back_to_printing(self, tmp_path, monkeypatch, capsys):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.cli.sys.stdin"
        ) as fake_stdin, patch(
            "audiobooker.project.AudiobookProject.get_uncast_speakers",
            return_value={"alice"},
        ), patch(
            "audiobooker.casting.voice_suggester.VoiceSuggester.suggest_all",
            return_value=self._suggestions(),
        ):
            fake_stdin.isatty.return_value = False
            code = main(["cast", "--interactive", "-p", str(proj)])

        assert code == 0
        out = capsys.readouterr().out
        assert "Non-interactive" in out
        assert "af_heart" in out

    def test_interactive_casts_by_number(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.cli.sys.stdin"
        ) as fake_stdin, patch(
            "audiobooker.project.AudiobookProject.get_uncast_speakers",
            return_value={"alice"},
        ), patch(
            "audiobooker.casting.voice_suggester.VoiceSuggester.suggest_all",
            return_value=self._suggestions(),
        ), patch(
            "builtins.input", return_value="2"
        ), patch(
            "audiobooker.project.AudiobookProject.cast"
        ) as mock_cast:
            fake_stdin.isatty.return_value = True
            code = main(["cast", "--interactive", "-p", str(proj)])

        assert code == 0
        # choice "2" -> the second suggestion bf_emma
        mock_cast.assert_called_with("Alice", "bf_emma")

    def test_interactive_skip(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.cli.sys.stdin"
        ) as fake_stdin, patch(
            "audiobooker.project.AudiobookProject.get_uncast_speakers",
            return_value={"alice"},
        ), patch(
            "audiobooker.casting.voice_suggester.VoiceSuggester.suggest_all",
            return_value=self._suggestions(),
        ), patch(
            "builtins.input", return_value="s"
        ), patch(
            "audiobooker.project.AudiobookProject.cast"
        ) as mock_cast:
            fake_stdin.isatty.return_value = True
            code = main(["cast", "--interactive", "-p", str(proj)])

        assert code == 0
        assert not mock_cast.called

    def test_cast_interactive_alias(self, tmp_path, monkeypatch, capsys):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        with patch(
            "audiobooker.project.AudiobookProject.get_uncast_speakers",
            return_value=set(),
        ):
            code = main(["cast-interactive", "-p", str(proj)])
        assert code == 0
        assert "already cast" in capsys.readouterr().out.lower()

    def test_plain_cast_still_requires_args(self, capsys):
        # `cast` with no character/voice and no --interactive is an error.
        code = main(["cast"])
        assert code == 1
        assert "requires" in capsys.readouterr().out.lower()


# ===========================================================================
# FT-CLI-004: shell completion
# ===========================================================================


class TestCompletion:
    def test_completion_bash(self, capsys):
        code = main(["completion", "bash"])
        assert code == 0
        out = capsys.readouterr().out
        assert "register-python-argcomplete audiobooker" in out

    def test_completion_zsh(self, capsys):
        code = main(["completion", "zsh"])
        assert code == 0
        out = capsys.readouterr().out
        assert "bashcompinit" in out
        assert "register-python-argcomplete audiobooker" in out

    def test_completion_fish(self, capsys):
        code = main(["completion", "fish"])
        assert code == 0
        out = capsys.readouterr().out
        assert "fish" in out
        assert "register-python-argcomplete" in out

    def test_completion_rejects_unknown_shell(self):
        # argparse choices reject an unknown shell -> SystemExit.
        with pytest.raises(SystemExit):
            main(["completion", "powershell"])

    def test_argcomplete_marker_present(self):
        # FT-CLI-004: the magic activation marker must be in the source.
        import audiobooker.cli as cli_mod
        src = Path(cli_mod.__file__).read_text(encoding="utf-8")
        assert "PYTHON_ARGCOMPLETE_OK" in src

    def test_file_completer_suggests_audiobooker_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "one.audiobooker").write_text("{}", encoding="utf-8")
        (tmp_path / "two.audiobooker").write_text("{}", encoding="utf-8")
        (tmp_path / "skip.txt").write_text("x", encoding="utf-8")
        from audiobooker.cli import _audiobooker_file_completer
        out = _audiobooker_file_completer("")
        assert any("one.audiobooker" in c for c in out)
        assert all("skip.txt" not in c for c in out)


# ===========================================================================
# FT-CLI-008: watch mode
# ===========================================================================


class TestWatch:
    def test_watch_loop_runs_once_then_ctrl_c(self, tmp_path):
        from audiobooker.cli import _watch_loop

        src = tmp_path / "book.txt"
        src.write_text("v1", encoding="utf-8")
        calls = {"n": 0}

        def _run():
            calls["n"] += 1
            return 0

        # First _run() happens before the loop; the loop's sleep raises
        # KeyboardInterrupt so we exit cleanly without polling forever.
        with patch("audiobooker.cli.time.sleep", side_effect=KeyboardInterrupt):
            code = _watch_loop(src, _run)

        assert code == 0
        assert calls["n"] == 1  # ran once, then Ctrl-C

    def test_watch_reruns_on_mtime_change(self, tmp_path):
        from audiobooker.cli import _watch_loop

        src = tmp_path / "book.txt"
        src.write_text("v1", encoding="utf-8")
        calls = {"n": 0}

        def _run():
            calls["n"] += 1
            return 0

        # stat() call order in _watch_loop:
        #   1. initial last_mtime        -> 10
        #   2. loop current (changed)    -> 20
        #   3. debounce settled (stable) -> 20
        #   4. last_mtime after re-run   -> 20
        mtimes = iter([10.0, 20.0, 20.0, 20.0, 20.0])

        class _Stat:
            def __init__(self, m):
                self.st_mtime = m

        def _fake_stat():
            return _Stat(next(mtimes))

        sleeps = {"n": 0}

        def _fake_sleep(_):
            # sleeps: #1 poll, #2 debounce, #3 next poll -> stop
            sleeps["n"] += 1
            if sleeps["n"] >= 3:
                raise KeyboardInterrupt

        with patch.object(Path, "stat", lambda self: _fake_stat()), \
             patch("audiobooker.cli.time.sleep", side_effect=_fake_sleep):
            code = _watch_loop(src, _run)

        assert code == 0
        # initial run + one re-run after the mtime changed
        assert calls["n"] == 2

    def test_render_watch_wires_loop(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch("audiobooker.cli._watch_loop", return_value=0) as mock_loop:
            code = main(["render", "-p", str(proj), "--watch"])

        assert code == 0
        assert mock_loop.called


# ===========================================================================
# FT-CLI-006: manifest batch
# ===========================================================================


class TestManifestBatch:
    def test_load_manifest_json_list(self, tmp_path):
        mf = tmp_path / "books.json"
        mf.write_text(
            json.dumps([
                {"source": "a.epub", "title": "A"},
                {"source": "b.epub", "title": "B"},
            ]),
            encoding="utf-8",
        )
        entries = _load_manifest(mf)
        assert len(entries) == 2
        assert entries[0]["title"] == "A"

    def test_load_manifest_json_books_table(self, tmp_path):
        mf = tmp_path / "books.json"
        mf.write_text(
            json.dumps({"books": [{"source": "a.epub"}]}), encoding="utf-8"
        )
        entries = _load_manifest(mf)
        assert len(entries) == 1

    def test_load_manifest_missing_source_raises(self, tmp_path):
        mf = tmp_path / "books.json"
        mf.write_text(json.dumps([{"title": "no source"}]), encoding="utf-8")
        with pytest.raises(ValueError, match="source"):
            _load_manifest(mf)

    def test_load_manifest_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _load_manifest(tmp_path / "nope.json")

    def test_load_manifest_bad_format(self, tmp_path):
        mf = tmp_path / "books.yaml"
        mf.write_text("nope", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported"):
            _load_manifest(mf)

    @pytest.mark.skipif(
        not __import__("audiobooker.config_file", fromlist=["have_toml_support"]).have_toml_support(),
        reason="no TOML parser available",
    )
    def test_load_manifest_toml(self, tmp_path):
        mf = tmp_path / "books.toml"
        mf.write_text(
            '[[books]]\nsource = "a.epub"\ntitle = "A"\n', encoding="utf-8"
        )
        entries = _load_manifest(mf)
        assert entries[0]["source"] == "a.epub"

    def test_batch_manifest_processes_each_entry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        a = tmp_path / "a.txt"
        a.write_text("Chapter 1\n\nText A.", encoding="utf-8")
        b = tmp_path / "b.txt"
        b.write_text("Chapter 1\n\nText B.", encoding="utf-8")
        mf = tmp_path / "m.json"
        mf.write_text(
            json.dumps([
                {"source": str(a), "title": "Book A", "author": "AA"},
                {"source": str(b), "title": "Book B"},
            ]),
            encoding="utf-8",
        )

        seen_titles = []

        def _fake_render(project, output_path, **kw):
            seen_titles.append(project.title)
            Path(output_path).write_bytes(b"x")
            return Path(output_path)

        with patch(
            "audiobooker.renderer.engine.render_project", side_effect=_fake_render
        ):
            code = main(["batch", "--manifest", str(mf)])

        assert code == 0
        assert "Book A" in seen_titles
        assert "Book B" in seen_titles

    def test_apply_book_overrides_sets_metadata(self, tmp_path):
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string("Chapter 1\n\nText.", title="orig")
        _apply_book_overrides(
            project,
            {
                "title": "New Title",
                "author": "New Author",
                "series": "S",
                "series_index": 2,
            },
            base_dir=tmp_path,
        )
        assert project.title == "New Title"
        assert project.author == "New Author"
        assert project.metadata.series == "S"
        assert project.metadata.series_index == 2

    def test_apply_book_overrides_imports_cast(self, tmp_path):
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string("Chapter 1\n\nText.")
        with patch.object(project, "import_casting") as mock_import:
            _apply_book_overrides(
                project, {"cast": "cast.json"}, base_dir=tmp_path
            )
        assert mock_import.called

    def test_batch_manifest_empty_returns_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        mf = tmp_path / "m.json"
        mf.write_text(json.dumps([]), encoding="utf-8")
        code = main(["batch", "--manifest", str(mf)])
        assert code == 1


# ===========================================================================
# FT-PARSE-006: chapters rename / reorder (CLI side; project methods mocked)
# ===========================================================================


class TestChapterRenameReorder:
    def test_rename_calls_project_method(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.project.AudiobookProject.rename_chapter", create=True
        ) as mock_rename:
            code = main(["chapters", "rename", "0", "Prologue", "-p", str(proj)])

        assert code == 0
        mock_rename.assert_called_once_with(0, "Prologue")

    def test_reorder_parses_permutation(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.project.AudiobookProject.reorder_chapters", create=True
        ) as mock_reorder:
            code = main(["chapters", "reorder", "1,0", "-p", str(proj)])

        assert code == 0
        mock_reorder.assert_called_once_with([1, 0])

    def test_reorder_with_spaces(self, tmp_path, monkeypatch):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.project.AudiobookProject.reorder_chapters", create=True
        ) as mock_reorder:
            code = main(["chapters", "reorder", "1, 0", "-p", str(proj)])

        assert code == 0
        mock_reorder.assert_called_once_with([1, 0])

    def test_reorder_non_integer_rejected(self, tmp_path, monkeypatch, capsys):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        code = main(["chapters", "reorder", "a,b", "-p", str(proj)])
        assert code == 1
        assert "integers" in capsys.readouterr().out.lower()

    def test_reorder_propagates_validation_error(self, tmp_path, monkeypatch, capsys):
        proj = _write_project(tmp_path)
        monkeypatch.chdir(tmp_path)

        with patch(
            "audiobooker.project.AudiobookProject.reorder_chapters",
            create=True,
            side_effect=ValueError("new_order must be a permutation"),
        ):
            code = main(["chapters", "reorder", "5,6,7", "-p", str(proj)])

        assert code == 1
        assert "permutation" in capsys.readouterr().out.lower()


# ===========================================================================
# Parser smoke (new flags wired)
# ===========================================================================


class TestParserSmoke:
    def test_make_flags(self):
        args = create_parser().parse_args(
            ["make", "book.epub", "--acx", "-j", "3", "--cover", "c.jpg", "--watch"]
        )
        assert args.command == "make"
        assert args.acx is True
        assert args.jobs == 3
        assert args.cover == "c.jpg"
        assert args.watch is True

    def test_audition_flags(self):
        args = create_parser().parse_args(
            ["audition", "Bob", "-n", "4", "--render", "-o", "aud"]
        )
        assert args.character == "Bob"
        assert args.top == 4
        assert args.render is True
        assert args.output_dir == "aud"

    def test_cast_interactive_flag(self):
        args = create_parser().parse_args(["cast", "-i"])
        assert args.interactive is True
        assert args.character is None

    def test_batch_manifest_flag(self):
        args = create_parser().parse_args(["batch", "--manifest", "m.toml"])
        assert args.manifest == "m.toml"
        assert args.files == []

    def test_render_watch_flag(self):
        args = create_parser().parse_args(["render", "--watch"])
        assert args.watch is True

    def test_chapters_rename_reorder(self):
        a = create_parser().parse_args(["chapters", "rename", "3", "Title"])
        assert a.chapters_command == "rename"
        assert a.index == 3
        assert a.title == "Title"
        b = create_parser().parse_args(["chapters", "reorder", "2,0,1"])
        assert b.chapters_command == "reorder"
        assert b.order == "2,0,1"
