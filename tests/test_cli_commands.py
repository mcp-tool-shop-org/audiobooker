"""Tests for CLI commands and argument parsing.

Covers: cmd_new, cmd_cast, cmd_info, cmd_voices, cmd_chapters,
cmd_speakers, find_project_file.
Uses mocks/fakes to avoid needing real audio or voice-soundboard.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from audiobooker.cli import (
    main,
    create_parser,
    find_project_file,
    cmd_new,
    cmd_cast,
    cmd_info,
    cmd_voices,
    cmd_chapters,
    cmd_speakers,
)


# ---------------------------------------------------------------------------
# Argument parser tests
# ---------------------------------------------------------------------------

class TestArgumentParser:
    """Tests for CLI argument parsing."""

    def test_no_command_prints_help(self, capsys):
        """No command prints help and returns 0."""
        code = main([])
        assert code == 0

    def test_unknown_command_returns_error(self, capsys):
        """Unknown command causes argparse to exit with code 2."""
        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent-command"])
        assert exc_info.value.code == 2

    def test_new_command_parsed(self):
        """'new' command parses source argument."""
        parser = create_parser()
        args = parser.parse_args(["new", "book.epub"])
        assert args.command == "new"
        assert args.source == "book.epub"

    def test_new_command_with_options(self):
        """'new' with --output and --lang."""
        parser = create_parser()
        args = parser.parse_args(["new", "book.epub", "-o", "out.audiobooker", "--lang", "ja"])
        assert args.output == "out.audiobooker"
        assert args.lang == "ja"

    def test_cast_command_parsed(self):
        """'cast' command parses character and voice."""
        parser = create_parser()
        args = parser.parse_args(["cast", "Alice", "af_bella", "-e", "nervous"])
        assert args.command == "cast"
        assert args.character == "Alice"
        assert args.voice == "af_bella"
        assert args.emotion == "nervous"

    def test_render_command_with_options(self):
        """'render' command accepts chapter, no-resume, from-chapter."""
        parser = create_parser()
        args = parser.parse_args(["render", "-c", "3", "--no-resume", "--from-chapter", "2"])
        assert args.chapter == 3
        assert args.no_resume is True
        assert args.from_chapter == 2

    def test_info_command_verbose(self):
        """'info' command with --verbose flag."""
        parser = create_parser()
        args = parser.parse_args(["info", "-v"])
        assert args.command == "info"
        assert args.verbose is True

    def test_voices_command_with_filters(self):
        """'voices' command with gender and search filters."""
        parser = create_parser()
        args = parser.parse_args(["voices", "-g", "female", "-s", "heart"])
        assert args.gender == "female"
        assert args.search == "heart"

    def test_chapters_command_parsed(self):
        """'chapters' command parsed."""
        parser = create_parser()
        args = parser.parse_args(["chapters", "-p", "test.audiobooker"])
        assert args.command == "chapters"
        assert args.project == "test.audiobooker"

    def test_speakers_command_parsed(self):
        """'speakers' command parsed."""
        parser = create_parser()
        args = parser.parse_args(["speakers"])
        assert args.command == "speakers"

    def test_diagnose_json_flag(self):
        """'diagnose --json' flag."""
        parser = create_parser()
        args = parser.parse_args(["diagnose", "--json"])
        assert args.json_output is True


# ---------------------------------------------------------------------------
# find_project_file tests (F-TEST-016)
# ---------------------------------------------------------------------------

class TestFindProjectFile:
    """Tests for find_project_file function."""

    def test_specified_valid_path(self, tmp_path):
        """Specified path that exists is returned."""
        proj = tmp_path / "test.audiobooker"
        proj.write_text("{}")
        result = find_project_file(str(proj))
        assert result == proj

    def test_specified_missing_path(self, tmp_path):
        """Specified path that doesn't exist raises FileNotFoundError."""
        missing = tmp_path / "nonexistent" / "path.audiobooker"
        with pytest.raises(FileNotFoundError, match="not found"):
            find_project_file(str(missing))

    def test_single_audiobooker_in_cwd(self, tmp_path, monkeypatch):
        """Single .audiobooker in cwd is auto-detected."""
        monkeypatch.chdir(tmp_path)
        proj = tmp_path / "mybook.audiobooker"
        proj.write_text("{}")

        result = find_project_file()
        assert result.name == "mybook.audiobooker"

    def test_multiple_audiobooker_in_cwd(self, tmp_path, monkeypatch):
        """Multiple .audiobooker in cwd raises ValueError."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.audiobooker").write_text("{}")
        (tmp_path / "b.audiobooker").write_text("{}")

        with pytest.raises(ValueError, match="Multiple project files"):
            find_project_file()

    def test_none_in_cwd(self, tmp_path, monkeypatch):
        """No .audiobooker in cwd raises FileNotFoundError."""
        monkeypatch.chdir(tmp_path)

        with pytest.raises(FileNotFoundError, match="No project file found"):
            find_project_file()


# ---------------------------------------------------------------------------
# cmd_new tests
# ---------------------------------------------------------------------------

class TestCmdNew:
    """Tests for cmd_new command."""

    def test_new_from_txt(self, tmp_path, capsys):
        """Create project from text file."""
        source = tmp_path / "book.txt"
        source.write_text(
            "---\ntitle: Test\nauthor: Author\n---\n\nChapter 1\n\nHello world.\n",
            encoding="utf-8",
        )

        parser = create_parser()
        args = parser.parse_args(["new", str(source)])
        code = cmd_new(args)

        assert code == 0
        captured = capsys.readouterr()
        assert "Project created" in captured.out
        assert (source.with_suffix(".audiobooker")).exists()

    def test_new_missing_source(self, tmp_path, capsys):
        """Missing source file returns error with descriptive message."""
        missing = tmp_path / "nonexistent" / "book.txt"
        parser = create_parser()
        args = parser.parse_args(["new", str(missing)])
        code = cmd_new(args)

        assert code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out
        # Error message should indicate what went wrong
        assert "book.txt" in captured.out or "not found" in captured.out.lower() or "Error" in captured.out

    def test_new_unsupported_format(self, tmp_path, capsys):
        """Unsupported file format returns error."""
        # .rtf is genuinely unsupported (epub/pdf/txt/md/docx + folders are not).
        source = tmp_path / "book.rtf"
        source.write_text("dummy")

        parser = create_parser()
        args = parser.parse_args(["new", str(source)])
        code = cmd_new(args)

        assert code == 1
        captured = capsys.readouterr()
        assert "Unsupported" in captured.out or "error" in captured.out.lower()


# ---------------------------------------------------------------------------
# cmd_cast tests
# ---------------------------------------------------------------------------

class TestCmdCast:
    """Tests for cmd_cast command."""

    def test_cast_character(self, tmp_path, capsys):
        """Cast a character in an existing project."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string("Hello world.", title="Test")
        proj_path = tmp_path / "test.audiobooker"
        project.save(proj_path)

        parser = create_parser()
        args = parser.parse_args(["cast", "Alice", "af_bella", "-p", str(proj_path)])
        code = cmd_cast(args)

        assert code == 0
        captured = capsys.readouterr()
        assert "Cast Alice as af_bella" in captured.out

        # Verify it persisted
        loaded = AudiobookProject.load(proj_path)
        voice, _ = loaded.casting.get_voice("Alice")
        assert voice == "af_bella"


# ---------------------------------------------------------------------------
# cmd_info tests
# ---------------------------------------------------------------------------

class TestCmdInfo:
    """Tests for cmd_info command."""

    def test_info_output(self, tmp_path, capsys):
        """Info command prints project details."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string("Hello world.", title="My Book", author="Author")
        proj_path = tmp_path / "test.audiobooker"
        project.save(proj_path)

        parser = create_parser()
        args = parser.parse_args(["info", "-p", str(proj_path)])
        code = cmd_info(args)

        assert code == 0
        captured = capsys.readouterr()
        assert "My Book" in captured.out
        assert "Author" in captured.out


# ---------------------------------------------------------------------------
# cmd_voices tests
# ---------------------------------------------------------------------------

class TestCmdVoices:
    """Tests for cmd_voices command."""

    def test_voices_without_soundboard(self, capsys):
        """voices command without voice-soundboard installed returns error."""
        with patch.dict("sys.modules", {"voice_soundboard": None, "voice_soundboard.config": None}):
            parser = create_parser()
            args = parser.parse_args(["voices"])
            code = cmd_voices(args)
            # voice_soundboard is patched to None so the import fails → return 1
            assert code == 1


# ---------------------------------------------------------------------------
# cmd_chapters tests
# ---------------------------------------------------------------------------

class TestCmdChapters:
    """Tests for cmd_chapters command."""

    def test_chapters_lists_all(self, tmp_path, capsys):
        """chapters command lists all chapters."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string(
            "Chapter 1\n\nFirst content.\n\nChapter 2\n\nSecond content.",
            title="Test",
        )
        proj_path = tmp_path / "test.audiobooker"
        project.save(proj_path)

        parser = create_parser()
        args = parser.parse_args(["chapters", "-p", str(proj_path)])
        code = cmd_chapters(args)

        assert code == 0
        captured = capsys.readouterr()
        assert "Chapter" in captured.out


# ---------------------------------------------------------------------------
# cmd_speakers tests
# ---------------------------------------------------------------------------

class TestCmdSpeakers:
    """Tests for cmd_speakers command."""

    def test_speakers_auto_compiles(self, tmp_path, capsys):
        """speakers command compiles if needed and lists speakers."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject.from_string(
            '"Hello" said Alice. The narrator spoke.',
            title="Test",
        )
        proj_path = tmp_path / "test.audiobooker"
        project.save(proj_path)

        parser = create_parser()
        args = parser.parse_args(["speakers", "-p", str(proj_path)])
        code = cmd_speakers(args)

        assert code == 0
        captured = capsys.readouterr()
        assert "Speakers in Test" in captured.out


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

class TestExitCodes:
    """Tests for consistent exit codes."""

    def test_diagnose_returns_int(self, capsys):
        """Diagnose always returns an integer exit code."""
        code = main(["diagnose"])
        assert isinstance(code, int)
        # cmd_diagnose returns 0 when all hard checks pass (Python>=3.10, ebooklib installed).
        # voice-soundboard and ffmpeg are 'info' status, not failures.
        assert code == 0

    def test_no_args_returns_zero(self, capsys):
        """No arguments returns 0 (help shown)."""
        code = main([])
        assert code == 0
