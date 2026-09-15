"""`render --dry-run` still printed one numbering scheme.

FEAT-UX-007 made every printed chapter reference carry both numbers,
because this CLI has four schemes in play: `-c N` is 0-based, `--chapters`
and `--exclude-chapters` take 1-based ranges, and the `chapters` listing
is 1-based. Nothing on screen said which one you were looking at.

`_chapter_label`'s own docstring names `render --dry-run` as one of the
four — and the dry-run table is the single worst place to leave ambiguous,
because it is the command you run *in order to decide what to pass next*.
Reading `[3] The Gate` there, you cannot tell whether the next command is
`-c 3` or `-c 4`.

It was missed because the table lives in `renderer/engine.py` while the
label helper lives in `cli.py`, and `cli` imports `engine`, so the fix
could not simply import across.
"""

from __future__ import annotations

import re

import pytest

from audiobooker import AudiobookProject
from audiobooker.labels import chapter_label

BOOK = "\n\n".join(
    f"Chapter {n}: Section {n}\n\nThe hall was cold and nobody spoke. "
    f"He counted the lamps again, and there were still {n}."
    for n in range(1, 4)
)


@pytest.fixture()
def project(tmp_path):
    p = AudiobookProject.from_string(BOOK, title="Numbering", author="A")
    p.compile()
    p.save(tmp_path / "book.audiobooker")
    return p


class TestTheDryRunTableNamesBothSchemes:
    def test_every_listed_chapter_carries_both_numbers(self, project,
                                                       capsys):
        from audiobooker.renderer.engine import dry_run_render

        dry_run_render(project, resume=False)
        out = capsys.readouterr().out

        listing = out.split("Chapters to render:", 1)
        assert len(listing) == 2, f"no chapter listing printed:\n{out}"
        body = listing[1]

        for index in range(len(project.chapters)):
            assert chapter_label(index) in body, (
                f"chapter {index} is not labelled with both schemes.\n"
                f"expected {chapter_label(index)!r} in:\n{body}"
            )

    def test_the_bare_bracket_index_is_gone(self, project, capsys):
        """The old form. Asserted explicitly so a partial fix that adds the
        new label beside the old one does not pass."""
        from audiobooker.renderer.engine import dry_run_render

        dry_run_render(project, resume=False)
        body = capsys.readouterr().out.split("Chapters to render:", 1)[1]

        for index in range(len(project.chapters)):
            assert not re.search(rf"^\s*\[{index}\]\s", body, re.M), (
                f"still printing the bare 0-based '[{index}]':\n{body}"
            )

    def test_a_selection_names_the_chapters_it_actually_selected(
        self, project, capsys
    ):
        """The case that makes this more than cosmetic.

        `--chapters` hands the renderer a FILTERED list, so the enumerate
        position is the chapter's place in the subset, not in the book.
        Printing the position put "ch.3" beside a chapter titled
        "Chapter 4" — a confident wrong number, which is worse than the
        bare "[2]" it replaced.
        """
        from audiobooker.renderer.engine import (
            dry_run_render, filter_chapters_by_selection,
        )

        project.chapters = filter_chapters_by_selection(
            project.chapters, include_ranges="1,3"
        )
        assert [c.index for c in project.chapters] == [0, 2]

        dry_run_render(project, resume=False)
        body = capsys.readouterr().out.split("Chapters to render:", 1)[1]

        assert chapter_label(0) in body
        assert chapter_label(2) in body, (
            "the second selected chapter is chapter 3 (index 2); the table "
            f"renumbered it to its position in the subset:\n{body}"
        )
        assert chapter_label(1) not in body, (
            f"chapter 2 was not selected but is named:\n{body}"
        )

    def test_the_label_disambiguates_at_all(self, project):
        """Guard the premise: a label that did not contain both numbers
        would make the assertions above pass while fixing nothing."""
        assert "0" in chapter_label(0) and "1" in chapter_label(0)
        assert chapter_label(0) != chapter_label(1)

    def test_the_dry_run_table_is_console_safe(self, project, capsys):
        """This table is printed, so it lives under the same constraint as
        cli.py's output: a legacy Windows console cannot render an em-dash
        and will substitute '?'."""
        from audiobooker.renderer.engine import dry_run_render

        dry_run_render(project, resume=False)
        out = capsys.readouterr().out
        try:
            out.encode("cp437")
        except UnicodeEncodeError as e:
            pytest.fail(
                f"dry-run output does not survive a cp437 console: {e}\n"
                f"{out!r}"
            )


class TestOneLabelRuleNotTwo:
    def test_cli_and_engine_share_the_helper(self):
        from audiobooker import cli

        assert cli._chapter_label is chapter_label

    def test_labels_is_a_leaf(self):
        """engine imports models only under TYPE_CHECKING, deliberately.
        The label helper has to be importable at runtime from both cli and
        engine without dragging the package in behind it."""
        import ast
        import pathlib

        import audiobooker.labels as mod

        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("audiobooker"), (
                    f"labels imports {node.module}"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("audiobooker")
