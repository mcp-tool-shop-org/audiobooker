"""The review file tells you how to import it. That command has to run.

`review-export` names the file from the book TITLE, so "The Midnight
Garden" produces `The Midnight Garden_review.txt`. The CLI already learned
this — it prints the follow-up command through `_quote_arg`, after an
unquoted name with a space made argparse reject it and dump all 34
subcommands at a user who had done nothing wrong.

The review file's OWN header was missed. It carries the same instruction,
built the same way, unquoted — and it is the copy the user actually has in
front of them, because it is sitting at the top of the file they just
opened to edit.

Fixing it in place would mean a second copy of the quoting rule in a
second module. This release removed six drifting allowlists in favour of
one table; the same argument applies to a Windows-vs-POSIX quoting rule.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from audiobooker import AudiobookProject
from audiobooker.shell_quote import quote_arg

BOOK = (
    "Chapter 1: The Gate\n\n"
    '"We should go," said Alice.\n\n'
    '"Not yet," said Bob.\n'
)

SPACED_TITLE = "The Midnight Garden"


def _header_command(tmp_path, title: str) -> str:
    project = AudiobookProject.from_string(title + "\n\n" + BOOK,
                                           title=title, author="Author")
    project.compile()
    out = tmp_path / f"{title}_review.txt"
    project.export_for_review(out)
    text = out.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "review-import" in line:
            return line
    raise AssertionError(f"no import instruction in the header:\n{text[:400]}")


class TestTheHeaderCommandSurvivesPasting:
    def test_a_spaced_filename_is_quoted(self, tmp_path):
        line = _header_command(tmp_path, SPACED_TITLE)
        assert f"{SPACED_TITLE}_review.txt" in line, line
        # The bare, unquoted form is what argparse chokes on.
        assert f"review-import {SPACED_TITLE}_review.txt" not in line, (
            "the review file's own header still prints an unquoted "
            f"filename with spaces:\n  {line}"
        )

    def test_the_quoted_command_parses_back_to_one_argument(self, tmp_path):
        """The real contract is not 'has quotes' — it is 'the shell hands
        argparse exactly one filename'. Assert that, not the spelling."""
        line = _header_command(tmp_path, SPACED_TITLE)
        command = line.split("import with:", 1)[1].strip()

        if os.name == "nt":
            # cmd.exe's own parser is the authority on Windows; shlex is
            # POSIX and disagrees about backslashes.
            argv = subprocess.list2cmdline  # noqa: F841 - documents intent
            assert command.count('"') == 2, command
            inner = command.split('"')[1]
            assert inner == f"{SPACED_TITLE}_review.txt", inner
        else:
            import shlex

            parts = shlex.split(command)
            assert parts[:2] == ["audiobooker", "review-import"], parts
            assert parts[2] == f"{SPACED_TITLE}_review.txt", parts
            assert len(parts) == 3, parts

    def test_an_ordinary_filename_is_left_alone(self, tmp_path):
        """Quoting everything would be safe and ugly. A plain name should
        read as a plain name."""
        line = _header_command(tmp_path, "PlainBook")
        assert "review-import PlainBook_review.txt" in line, line
        assert '"' not in line, line


class TestOneQuotingRuleNotTwo:
    def test_cli_and_review_share_the_helper(self):
        """If these ever diverge, one of the two printed commands starts
        failing on a platform nobody tested."""
        from audiobooker import cli, review

        assert cli._quote_arg is quote_arg
        assert review.quote_arg is quote_arg

    @pytest.mark.skipif(os.name == "nt", reason="POSIX quoting")
    def test_posix_quoting_is_shlex(self):
        assert quote_arg("a b.txt") == "'a b.txt'"

    @pytest.mark.skipif(os.name != "nt", reason="Windows quoting")
    def test_windows_uses_double_quotes_not_shlex(self):
        """shlex.quote wraps Windows paths in SINGLE quotes, which cmd.exe
        does not treat as quoting at all — the bug the helper exists to
        avoid."""
        assert quote_arg("a b.txt") == '"a b.txt"'
        assert quote_arg(r"C:\Books\My Book_review.txt").startswith('"')
        assert quote_arg("plain.txt") == "plain.txt"


def test_module_is_a_leaf(self=None):
    """shell_quote must not import the package back, or the lazy
    cli -> review import turns into a cycle."""
    import ast
    import pathlib

    src = pathlib.Path(
        sys.modules["audiobooker.shell_quote"].__file__
    ).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("audiobooker"), (
                f"shell_quote imports {node.module}"
            )
        elif isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.startswith("audiobooker"), a.name
