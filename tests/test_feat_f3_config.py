"""Tests for v2.1 WORKFLOW feature F-FEAT-F3.

Covers:
- config_file.load_config: project-local > user precedence, friendly-key
  mapping, .audiobookerrc vs [tool.audiobooker] discovery, unknown-key
  warnings, graceful no-file / malformed-file behavior.
- config_file.find_config_files: diagnostics helper.
- AudiobookProject.rename_chapter / reorder_chapters: validation, re-indexing,
  and cache invalidation (matching merge_chapters/split_chapter).

These tests build temp config files and temp projects; they never touch the
user's real ~/.audiobookerrc (Path.home is monkeypatched to a tmp dir).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audiobooker import config_file
from audiobooker.config_file import (
    find_config_files,
    have_toml_support,
    load_config,
)
from audiobooker.models import Chapter
from audiobooker.project import AudiobookProject


requires_toml = pytest.mark.skipif(
    not have_toml_support(),
    reason="no TOML parser available (tomllib/tomli)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point Path.home() at an empty tmp dir so no real ~/.audiobookerrc leaks."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _make_project(n_chapters: int = 3) -> AudiobookProject:
    chapters = [
        Chapter(index=i, title=f"Chapter {i + 1}", raw_text=f"Para A {i}.\n\nPara B {i}.")
        for i in range(n_chapters)
    ]
    return AudiobookProject(title="Test Book", chapters=chapters)


# ===========================================================================
# load_config — no file
# ===========================================================================


class TestLoadConfigNoFile:
    def test_returns_empty_when_no_config(self, tmp_path, isolated_home):
        """No project-local file and no user file -> {} (never crash)."""
        src = tmp_path / "book.txt"
        src.write_text("hello", encoding="utf-8")
        # No pyproject in tmp_path, no .audiobookerrc, empty home.
        assert load_config(src) == {}

    def test_returns_empty_when_source_is_none(self, tmp_path, isolated_home, monkeypatch):
        """source_path=None anchors at cwd; empty cwd -> {}."""
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)
        assert load_config(None) == {}


# ===========================================================================
# load_config — project-local .audiobookerrc
# ===========================================================================


@requires_toml
class TestProjectRc:
    def test_audiobookerrc_friendly_keys_mapped(self, tmp_path, isolated_home):
        """Friendly keys (lang, format, wpm, ...) map to ProjectConfig fields."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / ".audiobookerrc",
            'lang = "fr"\n'
            'format = "mp3"\n'
            "wpm = 175\n"
            "normalize = false\n"
            'profile = "acx"\n'
            "chapter_pause_ms = 3000\n",
        )

        cfg = load_config(src)
        assert cfg["language_code"] == "fr"
        assert cfg["output_format"] == "mp3"
        assert cfg["estimated_wpm"] == 175
        assert cfg["normalize_text"] is False
        assert cfg["output_profile"] == "acx"
        assert cfg["chapter_pause_ms"] == 3000

    def test_mapped_dict_feeds_projectconfig(self, tmp_path, isolated_home):
        """The mapped dict (minus sections) is valid for ProjectConfig(**mapped)."""
        from audiobooker.models import ProjectConfig

        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / ".audiobookerrc",
            'lang = "es"\nformat = "wav"\njobs = 2\n',  # 'jobs' is unknown -> dropped
        )
        cfg = load_config(src)
        cfg.pop("book", None)
        cfg.pop("casting", None)
        cfg.pop("lexicon", None)
        pc = ProjectConfig(**cfg)
        assert pc.language_code == "es"
        assert pc.output_format == "wav"

    def test_book_section_passed_through(self, tmp_path, isolated_home):
        """A [book] table is returned untouched under the 'book' key."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / ".audiobookerrc",
            'lang = "en"\n\n[book]\ntitle = "My Title"\nauthor = "Me"\nseries = "Saga"\n',
        )
        cfg = load_config(src)
        assert cfg["book"] == {"title": "My Title", "author": "Me", "series": "Saga"}
        assert "book" not in {"language_code"}  # book is not a ProjectConfig field

    def test_casting_and_lexicon_refs(self, tmp_path, isolated_home):
        """casting/lexicon file refs pass through as strings."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / ".audiobookerrc",
            'casting = "cast.json"\nlexicon = "lex.csv"\n',
        )
        cfg = load_config(src)
        assert cfg["casting"] == "cast.json"
        assert cfg["lexicon"] == "lex.csv"

    def test_unknown_key_warns_and_dropped(self, tmp_path, isolated_home, caplog):
        """Unknown keys are dropped with a warning, not crashed on."""
        import logging

        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / ".audiobookerrc",
            'lang = "en"\nbogus_setting = 42\n',
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.config_file"):
            cfg = load_config(src)
        assert "bogus_setting" not in cfg
        assert cfg["language_code"] == "en"
        assert any("bogus_setting" in r.message for r in caplog.records)

    def test_malformed_toml_warns_and_returns_empty(self, tmp_path, isolated_home, caplog):
        """A malformed .audiobookerrc warns and is skipped (no crash)."""
        import logging

        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(tmp_path / ".audiobookerrc", "this is = = not valid toml [[[")
        with caplog.at_level(logging.WARNING, logger="audiobooker.config_file"):
            cfg = load_config(src)
        assert cfg == {}
        assert any("Could not parse" in r.message for r in caplog.records)


# ===========================================================================
# load_config — pyproject [tool.audiobooker]
# ===========================================================================


@requires_toml
class TestPyprojectTable:
    def test_pyproject_tool_table_used(self, tmp_path, isolated_home):
        """[tool.audiobooker] in a nearby pyproject.toml is read."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / "pyproject.toml",
            "[tool.audiobooker]\n"
            'lang = "it"\n'
            'format = "flac"\n'
            "estimated_wpm = 160\n",
        )
        cfg = load_config(src)
        assert cfg["language_code"] == "it"
        assert cfg["output_format"] == "flac"
        assert cfg["estimated_wpm"] == 160

    def test_pyproject_found_by_walking_up(self, tmp_path, isolated_home):
        """A pyproject one or more directories up is found."""
        _write(
            tmp_path / "pyproject.toml",
            '[tool.audiobooker]\nlang = "pt"\n',
        )
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        src = nested / "book.txt"
        src.write_text("body", encoding="utf-8")
        cfg = load_config(src)
        assert cfg["language_code"] == "pt"

    def test_pyproject_without_table_ignored(self, tmp_path, isolated_home):
        """A pyproject with no [tool.audiobooker] yields no project config."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / "pyproject.toml",
            '[tool.other]\nfoo = "bar"\n',
        )
        assert load_config(src) == {}

    def test_audiobookerrc_preferred_over_pyproject(self, tmp_path, isolated_home):
        """When both exist next to source, .audiobookerrc wins (more specific)."""
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(tmp_path / ".audiobookerrc", 'lang = "de"\n')
        _write(
            tmp_path / "pyproject.toml",
            '[tool.audiobooker]\nlang = "ja"\n',
        )
        cfg = load_config(src)
        assert cfg["language_code"] == "de"


# ===========================================================================
# load_config — precedence (project-local > user)
# ===========================================================================


@requires_toml
class TestPrecedence:
    def test_project_overrides_user_key_by_key(self, tmp_path, isolated_home):
        """Project-local value wins; non-overlapping user keys still survive."""
        # User config: sets lang=en and wpm=150.
        _write(
            isolated_home / ".audiobookerrc",
            'lang = "en"\nestimated_wpm = 150\n',
        )
        # Project config: overrides lang, adds format. Leaves wpm to user.
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(
            tmp_path / ".audiobookerrc",
            'lang = "fr"\nformat = "mp3"\n',
        )
        cfg = load_config(src)
        assert cfg["language_code"] == "fr"  # project wins
        assert cfg["output_format"] == "mp3"  # project-only
        assert cfg["estimated_wpm"] == 150  # user-only, preserved

    def test_user_only_when_no_project(self, tmp_path, isolated_home):
        """With only a user config present, its values are returned."""
        _write(
            isolated_home / ".audiobookerrc",
            'lang = "zh"\nformat = "m4b"\n',
        )
        empty = tmp_path / "empty"
        empty.mkdir()
        src = empty / "book.txt"
        src.write_text("body", encoding="utf-8")
        cfg = load_config(src)
        assert cfg["language_code"] == "zh"
        assert cfg["output_format"] == "m4b"

    def test_pyproject_overrides_user(self, tmp_path, isolated_home):
        """A pyproject [tool.audiobooker] table also outranks the user config."""
        _write(isolated_home / ".audiobookerrc", 'lang = "en"\nestimated_wpm = 150\n')
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(tmp_path / "pyproject.toml", '[tool.audiobooker]\nlang = "fr"\n')
        cfg = load_config(src)
        assert cfg["language_code"] == "fr"
        assert cfg["estimated_wpm"] == 150


# ===========================================================================
# find_config_files — diagnostics
# ===========================================================================


@requires_toml
class TestFindConfigFiles:
    def test_reports_all_three(self, tmp_path, isolated_home):
        _write(isolated_home / ".audiobookerrc", 'lang = "en"\n')
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        rc = _write(tmp_path / ".audiobookerrc", 'lang = "fr"\n')
        found = find_config_files(src)
        assert found["project_rc"] == str(rc)
        assert found["user_rc"] == str(isolated_home / ".audiobookerrc")
        # pyproject not present here
        assert found["pyproject"] is None

    def test_reports_pyproject_only_with_table(self, tmp_path, isolated_home):
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(tmp_path / "pyproject.toml", '[tool.audiobooker]\nlang = "en"\n')
        found = find_config_files(src)
        assert found["pyproject"] == str(tmp_path / "pyproject.toml")
        assert found["project_rc"] is None

    def test_pyproject_without_table_not_reported(self, tmp_path, isolated_home):
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(tmp_path / "pyproject.toml", '[tool.black]\nline-length = 88\n')
        found = find_config_files(src)
        assert found["pyproject"] is None


# ===========================================================================
# no-TOML-lib fallback
# ===========================================================================


class TestNoTomlLib:
    def test_no_lib_no_file_returns_empty(self, tmp_path, isolated_home, monkeypatch):
        """No TOML lib + no file -> {} (the contract's safe default)."""
        monkeypatch.setattr(config_file, "_toml_load", None)
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        assert load_config(src) == {}

    def test_no_lib_with_file_warns_and_skips(self, tmp_path, isolated_home, monkeypatch, caplog):
        """No TOML lib but a config file exists -> warn, skip, return {}."""
        import logging

        monkeypatch.setattr(config_file, "_toml_load", None)
        src = tmp_path / "book.txt"
        src.write_text("body", encoding="utf-8")
        _write(tmp_path / ".audiobookerrc", 'lang = "en"\n')
        with caplog.at_level(logging.WARNING, logger="audiobooker.config_file"):
            cfg = load_config(src)
        assert cfg == {}
        assert any("no TOML parser" in r.message for r in caplog.records)


# ===========================================================================
# rename_chapter
# ===========================================================================


class TestRenameChapter:
    def test_rename_updates_title(self):
        project = _make_project(3)
        result = project.rename_chapter(1, "Renamed Middle")
        assert project.chapters[1].title == "Renamed Middle"
        assert result is project.chapters[1]

    def test_rename_strips_whitespace(self):
        project = _make_project(2)
        project.rename_chapter(0, "  Padded  ")
        assert project.chapters[0].title == "Padded"

    def test_rename_invalidates_cached_audio_keeps_utterances(self):
        from audiobooker.models import Utterance

        project = _make_project(2)
        ch = project.chapters[0]
        ch.audio_path = Path("/tmp/ch0.wav")
        ch.duration_seconds = 42.0
        ch.utterances = [Utterance(speaker="narrator", text="hi")]

        project.rename_chapter(0, "New Title")
        assert ch.audio_path is None
        assert ch.duration_seconds == 0.0
        # Rename does not change text, so utterances are preserved.
        assert len(ch.utterances) == 1

    def test_rename_out_of_range_raises_indexerror(self):
        project = _make_project(2)
        with pytest.raises(IndexError):
            project.rename_chapter(5, "x")
        with pytest.raises(IndexError):
            project.rename_chapter(-1, "x")

    def test_rename_empty_title_raises_valueerror(self):
        project = _make_project(2)
        with pytest.raises(ValueError):
            project.rename_chapter(0, "")
        with pytest.raises(ValueError):
            project.rename_chapter(0, "   ")


# ===========================================================================
# reorder_chapters
# ===========================================================================


class TestReorderChapters:
    def test_reorder_reverses(self):
        project = _make_project(3)
        titles_before = [c.title for c in project.chapters]
        project.reorder_chapters([2, 1, 0])
        titles_after = [c.title for c in project.chapters]
        assert titles_after == list(reversed(titles_before))

    def test_reorder_reindexes(self):
        project = _make_project(4)
        project.reorder_chapters([3, 0, 1, 2])
        for i, ch in enumerate(project.chapters):
            assert ch.index == i

    def test_reorder_identity_leaves_untouched(self):
        from audiobooker.models import Utterance

        project = _make_project(3)
        for ch in project.chapters:
            ch.audio_path = Path("/tmp/a.wav")
            ch.duration_seconds = 10.0
            ch.utterances = [Utterance(speaker="narrator", text="keep")]

        project.reorder_chapters([0, 1, 2])  # identity permutation
        for ch in project.chapters:
            # Nothing moved -> nothing invalidated.
            assert ch.audio_path == Path("/tmp/a.wav")
            assert ch.duration_seconds == 10.0
            assert len(ch.utterances) == 1

    def test_reorder_invalidates_only_moved_chapters(self):
        from audiobooker.models import Utterance

        project = _make_project(3)
        for ch in project.chapters:
            ch.audio_path = Path("/tmp/a.wav")
            ch.duration_seconds = 5.0
            ch.utterances = [Utterance(speaker="narrator", text="x")]

        # Swap 0 and 2; chapter that was at index 1 stays at index 1.
        project.reorder_chapters([2, 1, 0])

        # New index 0 (was 2) moved -> invalidated.
        assert project.chapters[0].audio_path is None
        assert project.chapters[0].utterances == []
        # New index 1 (was 1) unchanged -> preserved.
        assert project.chapters[1].audio_path == Path("/tmp/a.wav")
        assert project.chapters[1].duration_seconds == 5.0
        assert len(project.chapters[1].utterances) == 1
        # New index 2 (was 0) moved -> invalidated.
        assert project.chapters[2].audio_path is None

    def test_reorder_wrong_length_raises(self):
        project = _make_project(3)
        with pytest.raises(ValueError):
            project.reorder_chapters([0, 1])

    def test_reorder_duplicate_index_raises(self):
        project = _make_project(3)
        with pytest.raises(ValueError):
            project.reorder_chapters([0, 0, 1])

    def test_reorder_out_of_range_index_raises(self):
        project = _make_project(3)
        with pytest.raises(ValueError):
            project.reorder_chapters([0, 1, 3])

    def test_reorder_non_list_raises(self):
        project = _make_project(2)
        with pytest.raises(ValueError):
            project.reorder_chapters("01")  # type: ignore[arg-type]
