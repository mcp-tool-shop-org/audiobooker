"""`report` is where a user goes to ask "how good is the attribution?"

It answered with two things it should not have.

First, `report["unknown_rate"]` — the rate the dict itself labels *secondary,
diluted by narration*, and the one this release's notes describe as the bug
that made the metric improve as attribution degraded. `compile` was moved to
the dialogue-over-dialogue rate; the command actually named `report` was
left printing the diluted one.

Second, nothing about guesses. `compile_report` has returned
`total_low_confidence`, `dialogue_unverified_rate`, `attribution_quality`,
an `attribution_source_distribution` and a ready-made `low_confidence` list
of the worst offending lines since FEAT-CAST-001 — all of it computed, none
of it printed. A book where turn-tracking invented every speaker reported
"Unattributed rate: 0.0%" and stopped talking.
"""

from __future__ import annotations

from audiobooker import AudiobookProject
from audiobooker.cli import main

# Two speakers named once, then bare alternation. Turn-tracking fills the
# rest, so nothing is `unknown` — the diluted rate and the honest one
# disagree, and the guesses are the whole story.
GUESSWORK = (
    "Chapter 1: The Ledger\n\n"
    '"Two ounces light," said Halloran.\n\n'
    '"The scale is wrong," said Ines.\n\n'
    '"Then weigh it again."\n\n'
    '"I already did."\n\n'
    '"Do it once more."\n\n'
    '"It reads the same."\n\n'
    '"Then the scale is wrong."\n\n'
    '"That is what I said."\n'
)


def _project(tmp_path, text: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = AudiobookProject.from_string(
        text, title="Test Book", author="Author"
    )
    project.compile()
    path = tmp_path / "book.audiobooker"
    project.save(path)
    return path


class TestReportShowsTheGuesses:
    def test_it_reports_the_guessed_count(self, tmp_path, capsys):
        assert main(["report", "-p", str(_project(tmp_path, GUESSWORK))]) == 0
        out = capsys.readouterr().out.lower()
        assert "guess" in out, (
            "report said nothing about the six lines whose speaker was "
            f"invented by alternation:\n{out}"
        )

    def test_it_names_the_verdict_the_render_gate_uses(self, tmp_path, capsys):
        """A user refused a render needs `report` to explain why, in the
        same vocabulary the refusal used."""
        assert main(["report", "-p", str(_project(tmp_path, GUESSWORK))]) == 0
        out = capsys.readouterr().out.lower()
        assert "failed" in out

    def test_it_lists_the_guessed_lines(self, tmp_path, capsys):
        """`low_confidence` is already built and carries the text — the
        actionable half. Printing a rate without the lines tells a user
        they have a problem and not where it is."""
        assert main(["report", "-p", str(_project(tmp_path, GUESSWORK))]) == 0
        out = capsys.readouterr().out
        assert "Do it once more" in out or "It reads the same" in out

    def test_it_shows_where_the_attributions_came_from(self, tmp_path,
                                                       capsys):
        assert main(["report", "-p", str(_project(tmp_path, GUESSWORK))]) == 0
        out = capsys.readouterr().out.lower()
        assert "turn" in out and "tag" in out

    def test_the_unattributed_rate_is_dialogue_over_dialogue(self, tmp_path,
                                                             capsys):
        """The narration-diluted `unknown_rate` is the metric this release
        replaced. `report` must print the primary one."""
        from audiobooker.casting import compile_report

        path = _project(tmp_path, GUESSWORK)
        project = AudiobookProject.load(path)
        rep = compile_report(project.chapters, project.casting)

        # Premise: on this fixture the two rates are both 0, which would
        # make the assertion below vacuous. Guard it explicitly.
        narrated = (
            "Chapter 1: Mixed\n\n"
            "The hall was cold and the lamps had not been lit.\n\n"
            '"Who is there?"\n\n'
            "Nobody answered, and the door stayed shut.\n\n"
            "He waited a while longer, counting.\n"
        )
        path2 = _project(tmp_path / "b", narrated)
        p2 = AudiobookProject.load(path2)
        rep2 = compile_report(p2.chapters, p2.casting)
        assert rep2["unknown_rate"] != rep2["dialogue_unknown_rate"], (
            "fixture no longer separates the diluted rate from the honest "
            f"one: {rep2['unknown_rate']} vs {rep2['dialogue_unknown_rate']}"
        )

        capsys.readouterr()
        assert main(["report", "-p", str(path2)]) == 0
        out = capsys.readouterr().out
        honest = f"{rep2['dialogue_unknown_rate'] * 100:.1f}%"
        diluted = f"{rep2['unknown_rate'] * 100:.1f}%"
        assert honest in out, f"expected {honest}, got:\n{out}"
        assert diluted not in out, (
            f"report is still printing the narration-diluted {diluted}"
        )

        assert rep["total_dialogue"] == 8


class TestReportStaysQuietWhenThereIsNothingToSay:
    def test_a_clean_book_does_not_grow_a_guess_section(self, tmp_path,
                                                        capsys):
        clean = (
            "Chapter 1: Clean\n\n"
            '"The council will decide," said Aldric.\n\n'
            '"The shadow advances," said Morgaine.\n\n'
            '"I have seen it," said Theron.\n'
        )
        assert main(["report", "-p", str(_project(tmp_path, clean))]) == 0
        out = capsys.readouterr().out
        assert "guessed by alternating turns" not in out.lower()

    def test_json_output_is_unchanged(self, tmp_path, capsys):
        """--json already dumps the whole report dict, guesses included.
        The text path was the only gap; don't let a fix to it reshape the
        machine-readable contract."""
        import json

        assert main(
            ["report", "-p", str(_project(tmp_path, GUESSWORK)), "--json"]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["attribution_quality"] == "failed"
        assert payload["total_low_confidence"] == 6
