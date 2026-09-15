"""The render gate must watch the number that can see a guess.

FEAT-CAST-001 added `attribution_quality`, which counts dialogue whose
speaker was GUESSED by turn-tracking. `quality` counts only dialogue the
tool ADMITS it could not attribute — and a guess lowers that number rather
than raising it.

So the render gate, watching `quality`, was blind to exactly the failure the
new metric exists to expose: a chapter where every line got a confident
wrong speaker sails through, because nothing is `unknown`.

The measured passage behind this reads `quality: ok` and
`attribution_quality: failed` at 52% hand-scored speaker accuracy.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from audiobooker.casting import compile_report
from audiobooker.models import CastingTable, Chapter
from audiobooker.parser.text import split_into_chapters

# Two speakers named once, then six lines of bare alternation. Turn-tracking
# fills all six, so nothing is `unknown` and `quality` sees a clean chapter.
LEDGER = (
    '"Two ounces light," said Halloran.\n\n'
    '"The scale is wrong," said Ines.\n\n'
    '"Then weigh it again."\n\n'
    '"I already did."\n\n'
    '"Do it once more."\n\n'
    '"It reads the same."\n\n'
    '"Then the scale is wrong."\n\n'
    '"That is what I said."\n'
)


def _chapter(text: str = LEDGER) -> Chapter:
    """split_into_chapters yields (title, raw_text) tuples, not Chapters."""
    from audiobooker.casting import compile_chapter

    title, raw = split_into_chapters(text)[0]
    ch = Chapter(index=0, title=title, raw_text=raw)
    ch.utterances = compile_chapter(ch, CastingTable())
    return ch


class TestTheGateWatchesTheRightNumber:
    def test_the_two_verdicts_actually_diverge_here(self):
        """Premise. If they ever agree on this fixture the rest of the file
        proves nothing, so fail loudly rather than pass vacuously."""
        report = compile_report([_chapter()], CastingTable())
        assert report["quality"] == "ok"
        assert report["attribution_quality"] == "failed", (
            f"fixture no longer diverges: {report['attribution_quality']} "
            f"at unverified {report['dialogue_unverified_rate']:.2f}"
        )

    def test_render_refuses_a_chapter_that_is_mostly_guesswork(self):
        from audiobooker.cli import _check_dialogue_attribution_quality

        args = SimpleNamespace(force=False, silent=False, debug=False,
                               json_output=False)
        rc = _check_dialogue_attribution_quality(
            args, [_chapter()], CastingTable()
        )
        assert rc == 1, (
            "render proceeded on a chapter where 6 of 8 dialogue lines are "
            "alternation guesses — the gate is still reading `quality`, "
            "which a guess makes look BETTER"
        )

    def test_render_refuses_guesswork_as_json(self, capsys):
        """F-f9e7314c: gate refusals through _report_error so --json is parseable.

        json_output=False cannot see a machine-readable refusal. Drive the
        helper with json_output=True: stderr is one JSON object with
        code/message/hint, stdout empty, rc==1.
        """
        from audiobooker.cli import _check_dialogue_attribution_quality

        args = SimpleNamespace(force=False, silent=False, debug=False,
                               json_output=True)
        rc = _check_dialogue_attribution_quality(
            args, [_chapter()], CastingTable()
        )
        assert rc == 1
        captured = capsys.readouterr()
        assert captured.out.strip() == "", captured.out
        payload = json.loads(captured.err)
        assert payload["code"]
        assert payload["message"]
        assert "hint" in payload

    def test_cli_render_json_refuses_ledger_without_force(
        self, tmp_path, capsys, monkeypatch
    ):
        """F-f9e7314c: ``render --json`` without --force on LEDGER is JSON.

        --force belongs only on the bypass test. render_project / Project.render
        must stay uncalled.
        """
        from audiobooker import AudiobookProject
        from audiobooker.cli import main

        project = AudiobookProject.from_string(
            "Chapter 1: The Scale\n\n" + LEDGER,
            title="Ledger",
            author="Author",
        )
        project.compile()
        for speaker in list(project.get_uncast_speakers()):
            project.cast(speaker, "af_bella")
        project.config.validate_voices_on_render = False
        path = tmp_path / "ledger.audiobooker"
        project.save(path)

        calls: list = []

        def _must_not_render(*a, **k):
            calls.append((a, k))
            raise AssertionError("render must be refused before synthesis")

        monkeypatch.setattr(AudiobookProject, "render", _must_not_render)
        monkeypatch.setattr(
            "audiobooker.renderer.engine.render_project", _must_not_render
        )

        code = main(["render", "-p", str(path), "--json"])
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out.strip() == "", captured.out
        payload = json.loads(captured.err)
        assert payload["code"]
        assert payload["message"]
        assert "hint" in payload
        assert not calls, (
            "render --json without --force spent TTS on the LEDGER book "
            f"(F-f9e7314c); calls={calls!r}"
        )

    def test_force_still_overrides(self):
        from audiobooker.cli import _check_dialogue_attribution_quality

        args = SimpleNamespace(force=True, silent=False, debug=False,
                               json_output=False)
        assert _check_dialogue_attribution_quality(
            args, [_chapter()], CastingTable()
        ) is None

    def test_a_well_attributed_chapter_still_renders(self):
        """The gate must not become unpassable — every line tagged."""
        from types import SimpleNamespace

        from audiobooker.cli import _check_dialogue_attribution_quality

        ch = _chapter(
            '"The council will decide," said Aldric.\n\n'
            '"The shadow advances," said Morgaine.\n\n'
            '"I have seen it," said Theron.\n'
        )

        report = compile_report([ch], CastingTable())
        assert report["attribution_quality"] == "ok", report[
            "attribution_source_distribution"
        ]

        args = SimpleNamespace(force=False, silent=False, debug=False,
                               json_output=False)
        assert _check_dialogue_attribution_quality(
            args, [ch], CastingTable()
        ) is None
