"""INPUT-F2: Tests for v2.1 input-source CLI/project/models wiring.

Covers (integration side only — parser internals are owned by another agent
and are mocked here):

- ProjectConfig.use_toc / phoneme_overrides (validation + round-trip)
- new-command routing: .docx -> from_docx, directory -> from_folder
- --chapter-delimiter threaded into from_text / from_string split
- --force-text threaded into from_pdf -> parse_pdf(force_text=True)
- pronunciation import / export subcommands -> import_lexicon / export_lexicon
- batch: .docx + directory entries
- from_epub threads config.use_toc into parse_epub

Every parser entry point (parse_docx, read_folder_chapters, parse_pdf,
parse_epub, load_lexicon, save_lexicon, split_into_chapters, parse_text) is
mocked — these tests never read a real .docx/.pdf/.epub or touch ffmpeg.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from audiobooker.cli import create_parser, main
from audiobooker.models import Chapter, ProjectConfig
from audiobooker.project import AudiobookProject


# ---------------------------------------------------------------------------
# models.ProjectConfig — new INPUT fields
# ---------------------------------------------------------------------------


class TestProjectConfigInputFields:
    def test_defaults_preserve_current_behavior(self):
        cfg = ProjectConfig()
        assert cfg.use_toc == "auto"
        assert cfg.phoneme_overrides == {}

    def test_use_toc_accepted_values(self):
        for val in ("auto", "on", "off"):
            assert ProjectConfig(use_toc=val).use_toc == val

    def test_invalid_use_toc_rejected(self):
        with pytest.raises(ValueError, match="use_toc"):
            ProjectConfig(use_toc="maybe")

    def test_phoneme_overrides_independent_instances(self):
        a = ProjectConfig()
        b = ProjectConfig()
        a.phoneme_overrides["x"] = "y"
        assert b.phoneme_overrides == {}  # default_factory, not shared

    def test_round_trip_serialization(self):
        cfg = ProjectConfig(use_toc="on", phoneme_overrides={"nginx": "EN-jin-eks"})
        data = cfg.to_dict()
        assert data["use_toc"] == "on"
        assert data["phoneme_overrides"] == {"nginx": "EN-jin-eks"}
        restored = ProjectConfig.from_dict(data)
        assert restored.use_toc == "on"
        assert restored.phoneme_overrides == {"nginx": "EN-jin-eks"}

    def test_from_dict_legacy_missing_keys_defaults(self):
        cfg = ProjectConfig.from_dict({"output_format": "m4b"})
        assert cfg.use_toc == "auto"
        assert cfg.phoneme_overrides == {}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestNewFlagParsing:
    def test_new_chapter_delimiter_and_force_text(self):
        parser = create_parser()
        args = parser.parse_args(
            ["new", "book.txt", "--chapter-delimiter", r"^Scene \d+", "--force-text"]
        )
        assert args.chapter_delimiter == r"^Scene \d+"
        assert args.force_text is True

    def test_new_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["new", "book.epub"])
        assert args.chapter_delimiter is None
        assert args.force_text is False

    def test_from_stdin_chapter_delimiter(self):
        parser = create_parser()
        args = parser.parse_args(["from-stdin", "--chapter-delimiter", "###"])
        assert args.chapter_delimiter == "###"

    def test_pronunciation_import_export_parse(self):
        parser = create_parser()
        imp = parser.parse_args(["pronunciation", "import", "lex.csv"])
        assert imp.pronunciation_command == "import"
        assert imp.file == "lex.csv"
        exp = parser.parse_args(["pronunciation", "export", "out.json"])
        assert exp.pronunciation_command == "export"
        assert exp.file == "out.json"


# ---------------------------------------------------------------------------
# project factories — from_docx / from_folder (parsers mocked)
# ---------------------------------------------------------------------------


def _fake_chapters() -> list[Chapter]:
    return [
        Chapter(index=0, title="Chapter 1", raw_text="Hello world. A test."),
        Chapter(index=1, title="Chapter 2", raw_text="More narration here."),
    ]


class TestFromDocx:
    def test_from_docx_mirrors_from_epub(self, tmp_path):
        doc = tmp_path / "book.docx"
        doc.write_bytes(b"PK\x03\x04fake-docx")  # existence only; parser mocked

        meta = {"title": "Doc Title", "author": "Doc Author", "publisher": "ACME"}
        with patch(
            "audiobooker.parser.docx.parse_docx",
            return_value=(meta, _fake_chapters()),
            create=True,
        ) as mock_parse:
            project = AudiobookProject.from_docx(doc)

        assert mock_parse.called
        assert project.title == "Doc Title"
        assert project.author == "Doc Author"
        assert project.metadata.publisher == "ACME"
        assert len(project.chapters) == 2
        # narrator auto-cast like the other factories
        assert "narrator" in project.casting.characters

    def test_from_docx_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            AudiobookProject.from_docx(tmp_path / "missing.docx")

    def test_from_docx_threads_profile_or_falls_back(self, tmp_path):
        """If parse_docx lacks profile=, from_docx retries without it."""
        doc = tmp_path / "book.docx"
        doc.write_bytes(b"fake")

        calls = {"n": 0}

        def _picky(path, *, min_chapter_words=50, **kwargs):
            calls["n"] += 1
            if "profile" in kwargs:
                raise TypeError("parse_docx() got an unexpected keyword 'profile'")
            return ({"title": "T"}, _fake_chapters())

        with patch("audiobooker.parser.docx.parse_docx", side_effect=_picky, create=True):
            project = AudiobookProject.from_docx(doc)

        assert calls["n"] == 2  # first with profile (TypeError), then without
        assert project.title == "T"


class TestFromFolder:
    def test_from_folder_builds_chapters(self, tmp_path):
        folder = tmp_path / "mybook"
        folder.mkdir()

        pairs = [("Intro", "First chapter text."), ("Rising", "Second chapter text.")]
        with patch(
            "audiobooker.parser.text.read_folder_chapters",
            return_value=pairs,
            create=True,
        ) as mock_read:
            project = AudiobookProject.from_folder(folder)

        assert mock_read.called
        assert [c.title for c in project.chapters] == ["Intro", "Rising"]
        assert project.chapters[0].index == 0
        assert project.chapters[1].index == 1
        assert project.title == "mybook"
        assert "narrator" in project.casting.characters

    def test_from_folder_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            AudiobookProject.from_folder(tmp_path / "nope")

    def test_from_folder_empty_raises(self, tmp_path):
        folder = tmp_path / "empty"
        folder.mkdir()
        with patch(
            "audiobooker.parser.text.read_folder_chapters",
            return_value=[],
            create=True,
        ):
            with pytest.raises(ValueError, match="No chapter files"):
                AudiobookProject.from_folder(folder)


# ---------------------------------------------------------------------------
# delimiter / force-text threading into the parser layer
# ---------------------------------------------------------------------------


class TestDelimiterThreading:
    def test_from_string_passes_delimiter_pattern(self):
        with patch(
            "audiobooker.parser.text.split_into_chapters",
            return_value=[("A", "x"), ("B", "y")],
        ) as mock_split, patch(
            "audiobooker.parser.text.extract_frontmatter",
            return_value=({}, "body text"),
        ):
            AudiobookProject.from_string("body text", chapter_delimiter=r"^Scene")

        assert mock_split.called
        assert mock_split.call_args.kwargs.get("delimiter_pattern") == r"^Scene"

    def test_from_text_passes_chapter_delimiter(self, tmp_path):
        f = tmp_path / "book.txt"
        f.write_text("Chapter 1\n\nText.", encoding="utf-8")

        with patch(
            "audiobooker.parser.text.parse_text",
            return_value=({"title": "X"}, _fake_chapters()),
        ) as mock_parse:
            AudiobookProject.from_text(f, chapter_delimiter="###")

        assert mock_parse.call_args.kwargs.get("chapter_delimiter") == "###"

    def test_chapter_delimiter_not_a_project_field(self, tmp_path):
        """chapter_delimiter must be consumed, never reach _validate_kwargs."""
        f = tmp_path / "book.txt"
        f.write_text("Chapter 1\n\nText.", encoding="utf-8")
        with patch(
            "audiobooker.parser.text.parse_text",
            return_value=({}, _fake_chapters()),
        ):
            # Should NOT raise TypeError about an unknown field.
            AudiobookProject.from_text(f, chapter_delimiter="###")


class TestForceTextThreading:
    def test_from_pdf_passes_force_text(self, tmp_path):
        f = tmp_path / "book.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        captured = {}

        def _parse(path, *, min_chapter_words=50, **kwargs):
            captured.update(kwargs)
            return ({"title": "P"}, _fake_chapters())

        with patch("audiobooker.parser.pdf.parse_pdf", side_effect=_parse):
            AudiobookProject.from_pdf(f, force_text=True)

        assert captured.get("force_text") is True

    def test_from_pdf_force_text_survives_profile_fallback(self, tmp_path):
        """If parse_pdf rejects profile= but accepts force_text=, keep force_text."""
        f = tmp_path / "book.pdf"
        f.write_bytes(b"fake")

        seen = []

        def _parse(path, *, min_chapter_words=50, **kwargs):
            seen.append(dict(kwargs))
            if "profile" in kwargs:
                raise TypeError("unexpected keyword 'profile'")
            return ({"title": "P"}, _fake_chapters())

        with patch("audiobooker.parser.pdf.parse_pdf", side_effect=_parse):
            AudiobookProject.from_pdf(f, force_text=True)

        # second (fallback) call still carried force_text
        assert seen[-1].get("force_text") is True


# ---------------------------------------------------------------------------
# from_epub threads use_toc
# ---------------------------------------------------------------------------


class TestUseTocThreading:
    def test_from_epub_passes_use_toc(self, tmp_path):
        f = tmp_path / "book.epub"
        f.write_bytes(b"PK\x03\x04fake-epub")

        captured = {}

        def _parse(path, *, min_chapter_words=50, keep_titled_short_chapters=True, **kwargs):
            captured.update(kwargs)
            return ({"title": "E"}, _fake_chapters())

        cfg = ProjectConfig(use_toc="on")
        with patch("audiobooker.parser.epub.parse_epub", side_effect=_parse):
            AudiobookProject.from_epub(f, config=cfg)

        assert captured.get("use_toc") == "on"


# ---------------------------------------------------------------------------
# cmd_new routing (parsers mocked) — exit codes through main()
# ---------------------------------------------------------------------------


class TestCmdNewRouting:
    def test_new_routes_docx(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        doc = tmp_path / "book.docx"
        doc.write_bytes(b"fake")

        with patch(
            "audiobooker.parser.docx.parse_docx",
            return_value=({"title": "D"}, _fake_chapters()),
            create=True,
        ) as mock_parse:
            code = main(["new", str(doc)])

        assert code == 0
        assert mock_parse.called
        assert (tmp_path / "book.audiobooker").exists()

    def test_new_routes_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        folder = tmp_path / "chaps"
        folder.mkdir()

        with patch(
            "audiobooker.parser.text.read_folder_chapters",
            return_value=[("One", "text a"), ("Two", "text b")],
            create=True,
        ) as mock_read:
            code = main(["new", str(folder)])

        assert code == 0
        assert mock_read.called
        assert (tmp_path / "chaps.audiobooker").exists()

    def test_new_force_text_threaded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pdf = tmp_path / "book.pdf"
        pdf.write_bytes(b"%PDF fake")

        captured = {}

        def _parse(path, *, min_chapter_words=50, **kwargs):
            captured.update(kwargs)
            return ({"title": "P"}, _fake_chapters())

        with patch("audiobooker.parser.pdf.parse_pdf", side_effect=_parse):
            code = main(["new", str(pdf), "--force-text"])

        assert code == 0
        assert captured.get("force_text") is True

    def test_new_delimiter_threaded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        txt = tmp_path / "book.txt"
        txt.write_text("Chapter 1\n\nText.", encoding="utf-8")

        with patch(
            "audiobooker.parser.text.parse_text",
            return_value=({"title": "T"}, _fake_chapters()),
        ) as mock_parse:
            code = main(["new", str(txt), "--chapter-delimiter", "###"])

        assert code == 0
        assert mock_parse.call_args.kwargs.get("chapter_delimiter") == "###"


# ---------------------------------------------------------------------------
# pronunciation import / export commands
# ---------------------------------------------------------------------------


def _seed_project(tmp_path: Path) -> Path:
    project = AudiobookProject.from_string(
        "Chapter 1\n\nHello world.", title="LexBook", author="Me"
    )
    path = tmp_path / "lexbook.audiobooker"
    project.save(path)
    return path


class TestPronunciationLexicon:
    def test_import_merges_spelling_and_phoneme(self, tmp_path, monkeypatch):
        proj_path = _seed_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        lex = tmp_path / "lex.csv"
        lex.write_text("word,replacement,type\n", encoding="utf-8")

        entries = {
            "Hermione": "Her-MY-oh-nee",
            "nginx": {"replacement": "EN-jin-eks", "type": "phoneme"},
        }
        with patch(
            "audiobooker.parser.text_cleaners.load_lexicon",
            return_value=entries,
            create=True,
        ) as mock_load:
            code = main(["pronunciation", "import", str(lex), "-p", str(proj_path)])

        assert code == 0
        assert mock_load.called
        reloaded = AudiobookProject.load(proj_path)
        assert reloaded.config.pronunciation_overrides.get("Hermione") == "Her-MY-oh-nee"
        assert reloaded.config.phoneme_overrides.get("nginx") == "EN-jin-eks"

    def test_export_calls_save_lexicon(self, tmp_path, monkeypatch):
        proj_path = _seed_project(tmp_path)
        # seed an override so there's something to export
        project = AudiobookProject.load(proj_path)
        project.add_pronunciation("Hermione", "Her-MY-oh-nee")
        project.config.phoneme_overrides["nginx"] = "EN-jin-eks"
        project.save(proj_path)
        monkeypatch.chdir(tmp_path)

        out = tmp_path / "out.csv"
        with patch(
            "audiobooker.parser.text_cleaners.save_lexicon",
            create=True,
        ) as mock_save:
            code = main(["pronunciation", "export", str(out), "-p", str(proj_path)])

        assert code == 0
        assert mock_save.called

    def test_import_missing_file_returns_one(self, tmp_path, monkeypatch, capsys):
        proj_path = _seed_project(tmp_path)
        monkeypatch.chdir(tmp_path)
        # load_lexicon never reached: import_lexicon raises FileNotFoundError first
        code = main(["pronunciation", "import", str(tmp_path / "nope.csv"), "-p", str(proj_path)])
        assert code == 1
        assert "Error" in capsys.readouterr().out


class TestProjectLexiconMethods:
    def test_import_lexicon_handles_flat_string_values(self, tmp_path):
        project = AudiobookProject.from_string("Hi.", title="T")
        lex = tmp_path / "lex.json"
        lex.write_text("{}", encoding="utf-8")
        with patch(
            "audiobooker.parser.text_cleaners.load_lexicon",
            return_value={"Smaug": "SMOWG"},
            create=True,
        ):
            project.import_lexicon(lex)
        assert project.config.pronunciation_overrides["Smaug"] == "SMOWG"
        assert "Smaug" not in project.config.phoneme_overrides

    def test_export_lexicon_falls_back_to_flat_map(self, tmp_path):
        project = AudiobookProject.from_string("Hi.", title="T")
        project.add_pronunciation("Smaug", "SMOWG")
        out = tmp_path / "lex.csv"

        calls = []

        def _save(path, overrides):
            calls.append(overrides)
            # First (rich dict-of-dicts) shape rejected; flat accepted.
            if calls and any(isinstance(v, dict) for v in overrides.values()):
                raise TypeError("save_lexicon expected flat str map")

        with patch(
            "audiobooker.parser.text_cleaners.save_lexicon",
            side_effect=_save,
            create=True,
        ):
            project.export_lexicon(out)

        # Called twice: rich shape then flat fallback.
        assert len(calls) == 2
        assert calls[-1] == {"Smaug": "SMOWG"}


# ---------------------------------------------------------------------------
# batch: .docx + directory entries
# ---------------------------------------------------------------------------


class TestBatchInputSources:
    def test_batch_dry_run_includes_docx_and_dir(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        doc = tmp_path / "a.docx"
        doc.write_bytes(b"fake")
        folder = tmp_path / "chaps"
        folder.mkdir()

        code = main(["batch", str(doc), str(folder), "--dry-run"])
        assert code == 0
        out = capsys.readouterr().out
        assert "a.docx" in out
        assert "chaps" in out

    def test_batch_routes_docx_and_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        doc = tmp_path / "a.docx"
        doc.write_bytes(b"fake")
        folder = tmp_path / "chaps"
        folder.mkdir()

        out_file = tmp_path / "out.m4b"
        out_file.write_bytes(b"fake")

        with patch(
            "audiobooker.parser.docx.parse_docx",
            return_value=({"title": "A"}, _fake_chapters()),
            create=True,
        ) as mock_docx, patch(
            "audiobooker.parser.text.read_folder_chapters",
            return_value=[("One", "x"), ("Two", "y")],
            create=True,
        ) as mock_folder, patch(
            "audiobooker.renderer.engine.render_project",
            return_value=out_file,
        ):
            code = main(["batch", str(doc), str(folder)])

        # 0 = all succeeded, 3 = partial — either way both sources were routed.
        assert code in (0, 3)
        assert mock_docx.called
        assert mock_folder.called
