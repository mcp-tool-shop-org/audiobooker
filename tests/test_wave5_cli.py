"""
Wave 5 (dogfood swarm) — cli-surface amend regression tests.

PH-B-002 CLI surfacing. Wave 4 (see tests/test_stageb_pipeline.py) fixed the
attribution-quality METRIC in audiobooker/casting/dialogue.py:
compile_report() now exports dialogue_unknown_rate, total_dialogue_unknown,
and a 'ok' | 'degraded' | 'failed' quality verdict via
dialogue_quality_verdict(). compile_chapter() computes and LOGS the same
verdict but deliberately does not raise on 'failed' — raising there would
have changed compile_chapter's return contract for every existing caller.

That left two gaps, both in the CLI (audiobooker/cli.py), both covered here:

1. `compile` never printed the rate. A user had no way to discover how much
   dialogue was attributed short of listening to the finished audiobook.
2. Nothing halted before `render`. A book whose casting collapsed to
   near-100%-unknown would still render a full (paid) TTS pass.

Every test in this file was written BEFORE its fix and observed RED against
the untouched wave-4 tree (cli.py at commit b084c24). See the docstring on
each class for what was seen red.

Fixture note: the text fixtures below were checked against the REAL
AudiobookProject.compile() -> compile_report() pipeline (not the low-level
compile_chapter() helper test_stageb_pipeline.py uses) to confirm they
actually produce the 'failed' / 'degraded' / 'ok' verdicts asserted on. See
FAILED_ATTRIBUTION_TEXT / DEGRADED_TEXT below for the measured numbers.
"""

from __future__ import annotations

import sys

import pytest

from audiobooker import AudiobookProject
from audiobooker.casting import compile_report
from audiobooker.cli import main


# ---------------------------------------------------------------------------
# Fixture texts — each verdict confirmed against the real compile() pipeline.
# ---------------------------------------------------------------------------

# Same shape as test_stageb_pipeline.py's DILUTED_BLANK_LINE_PROSE (narration
# paragraphs with no speech verb at all, interleaved with a short quote): every
# dialogue line is unattributed regardless of turn-tracking or preprocessing.
# Measured: quality='failed', dialogue_unknown_rate=1.0 (4/4).
FAILED_ATTRIBUTION_TEXT = "Chapter 1: Fog\n\n" + "\n\n".join(
    "\n\n".join([
        "The corridor was empty again, and the lamps guttered in their brackets.",
        "Somewhere below, a door closed with the finality of a verdict.",
        "Nobody moved for a long moment after that.",
        f'"Line number {i}."',
    ])
    for i in range(4)
)

# One named speaker (Alice) up front; turn-tracking needs a SECOND known
# speaker to alternate with, so the next three bare quotes stay unknown.
# Measured: quality='degraded', dialogue_unknown_rate=0.75 (3/4).
DEGRADED_TEXT = "Chapter 1: Talk\n\n" + (
    '"One," said Alice.\n\n'
    "The hall was cold.\n\n"
    '"Two."\n\n'
    "Nothing stirred.\n\n"
    '"Three."\n\n'
    "Nothing stirred again.\n\n"
    '"Four."'
)

# Two named speakers, both explicitly tagged throughout.
# Measured: quality='ok', dialogue_unknown_rate=0.0 (0/4).
HEALTHY_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "The morning sun peeked through the curtains. "
    '"Good morning," said Alice cheerfully. '
    '"Hello there," Bob replied with a smile.\n\n'
    "Chapter 2: The Middle\n\n"
    "Later that afternoon, the two met again. "
    '"Did you finish the report?" Alice asked. '
    '"Almost done," said Bob.'
)

# No quoted text anywhere — total_dialogue == 0.
NARRATION_ONLY_TEXT = (
    "Chapter 1: Only Prose\n\n"
    "No dialogue lives here at all. Just plain narration through and "
    "through, one paragraph after another, nothing in quotes.\n\n"
    "A second paragraph, still nothing but narration."
)


def _make_project(tmp_path, text: str, title: str = "Test Book"):
    """Create + save a project, returning its path (mirrors test_health_c_cli.py)."""
    project = AudiobookProject.from_string(text, title=title, author="Author")
    path = tmp_path / "p.audiobooker"
    project.save(path)
    return path


class TestFixturesMatchClaimedVerdict:
    """Guard the fixtures themselves against drift, independent of the CLI.

    If one of these ever fails, the CLI tests below are testing the wrong
    thing — fix the fixture, not the CLI.
    """

    def test_failed_fixture_is_failed(self):
        project = AudiobookProject.from_string(FAILED_ATTRIBUTION_TEXT, title="X")
        project.compile()
        report = compile_report(project.chapters, project.casting)
        assert report["quality"] == "failed"
        assert report["dialogue_unknown_rate"] == pytest.approx(1.0)

    def test_degraded_fixture_is_degraded(self):
        project = AudiobookProject.from_string(DEGRADED_TEXT, title="X")
        project.compile()
        report = compile_report(project.chapters, project.casting)
        assert report["quality"] == "degraded"

    def test_healthy_fixture_is_ok(self):
        project = AudiobookProject.from_string(HEALTHY_TEXT, title="X")
        project.compile()
        report = compile_report(project.chapters, project.casting)
        assert report["quality"] == "ok"
        assert report["total_dialogue"] > 0

    def test_narration_only_fixture_has_no_dialogue(self):
        project = AudiobookProject.from_string(NARRATION_ONLY_TEXT, title="X")
        project.compile()
        report = compile_report(project.chapters, project.casting)
        assert report["total_dialogue"] == 0


# ---------------------------------------------------------------------------
# PH-B-002 item 1 — `compile` must print the dialogue-unattributed rate.
#
# RED on the untouched tree: `main(["compile", "-p", str(path)])` printed the
# existing "Compiled N utterances: ... speakers resolved ..." observability
# line and nothing else — no mention of "attribution" anywhere in stdout or
# stderr, for ANY of the three dialogue-bearing fixtures below (healthy,
# degraded, failed all looked identical from the CLI's output). Confirmed by
# running this file against the tree with cli.py stashed back to commit
# b084c24 (pre-wave-5): all four tests in TestComplilePrintsAttribution
# failed on the "attribution" / "failed" / "force" substring assertions.
# ---------------------------------------------------------------------------

class TestCompilePrintsAttribution:
    def test_healthy_book_shows_the_rate(self, tmp_path, capsys):
        path = _make_project(tmp_path, HEALTHY_TEXT)
        code = main(["compile", "-p", str(path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "attribution" in out.lower()
        assert "0%" in out or "0/4" in out

    def test_degraded_book_warns_but_still_succeeds(self, tmp_path, capsys):
        path = _make_project(tmp_path, DEGRADED_TEXT)
        code = main(["compile", "-p", str(path)])
        # compile itself still succeeds — only `render` refuses.
        assert code == 0
        captured = capsys.readouterr()
        assert "attribution" in captured.out.lower()
        assert "degraded" in captured.err.lower()

    def test_failed_book_warns_loudly_and_mentions_force(self, tmp_path, capsys):
        path = _make_project(tmp_path, FAILED_ATTRIBUTION_TEXT)
        code = main(["compile", "-p", str(path)])
        assert code == 0
        captured = capsys.readouterr()
        assert "attribution" in captured.out.lower()
        err_lower = captured.err.lower()
        assert "failed" in err_lower
        # The user needs to be told render will refuse and how to get past it.
        assert "force" in err_lower

    def test_pure_narration_book_is_not_noisy(self, tmp_path, capsys):
        """A book with zero dialogue has nothing to attribute — no line at all."""
        path = _make_project(tmp_path, NARRATION_ONLY_TEXT)
        code = main(["compile", "-p", str(path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "attribution" not in out.lower()


# ---------------------------------------------------------------------------
# PH-B-002 item 2 — `render` must refuse on a 'failed' verdict, unless
# --force. Both the full-book and single-chapter render paths are covered,
# since the finding named both ("does render currently have any access to
# the compile report for the project it is about to render?").
#
# RED on the untouched tree: every "must refuse" test below FAILED because
# the render proceeded anyway — the mocked AudiobookProject.render /
# render_chapter was called (code == 0), with nothing printed about
# attribution quality on stderr. Confirmed the same way as above (cli.py
# stashed back to b084c24).
# ---------------------------------------------------------------------------

class TestRenderRefusesOnFailedAttribution:
    def test_full_book_render_refuses(self, tmp_path, monkeypatch, capsys):
        path = _make_project(tmp_path, FAILED_ATTRIBUTION_TEXT)

        calls = []

        def fake_render(self, *a, **k):
            calls.append((a, k))
            return tmp_path / "out.m4b"

        monkeypatch.setattr(AudiobookProject, "render", fake_render)

        code = main(["render", "-p", str(path)])

        assert code == 1
        assert not calls, "render must refuse BEFORE any TTS pass is attempted"
        err = capsys.readouterr().err
        assert "unattributed" in err.lower() or "attribution" in err.lower()
        assert "force" in err.lower()

    def test_single_chapter_render_refuses(self, tmp_path, monkeypatch, capsys):
        path = _make_project(tmp_path, FAILED_ATTRIBUTION_TEXT)

        calls = []

        def fake_render_chapter(self, *a, **k):
            calls.append((a, k))
            return tmp_path / "chapter_000.wav"

        monkeypatch.setattr(AudiobookProject, "render_chapter", fake_render_chapter)

        code = main(["render", "-p", str(path), "-c", "0"])

        assert code == 1
        assert not calls, "render -c must refuse BEFORE any TTS pass is attempted"
        err = capsys.readouterr().err
        assert "unattributed" in err.lower() or "attribution" in err.lower()

    def test_force_bypasses_the_gate(self, tmp_path, monkeypatch):
        path = _make_project(tmp_path, FAILED_ATTRIBUTION_TEXT)

        calls = []

        def fake_render(self, *a, **k):
            calls.append((a, k))
            return tmp_path / "out.m4b"

        monkeypatch.setattr(AudiobookProject, "render", fake_render)

        code = main(["render", "-p", str(path), "--force"])

        assert code == 0
        assert calls, "--force must let a render proceed even on 'failed' quality"

    def test_degraded_attribution_does_not_block_render(self, tmp_path, monkeypatch):
        """Only 'failed' halts render — 'degraded' is a warning, not a wall."""
        path = _make_project(tmp_path, DEGRADED_TEXT)

        calls = []

        def fake_render(self, *a, **k):
            calls.append((a, k))
            return tmp_path / "out.m4b"

        monkeypatch.setattr(AudiobookProject, "render", fake_render)

        code = main(["render", "-p", str(path)])

        assert code == 0
        assert calls, "a merely 'degraded' book must still be allowed to render"

    def test_healthy_attribution_renders_normally(self, tmp_path, monkeypatch):
        path = _make_project(tmp_path, HEALTHY_TEXT)

        calls = []

        def fake_render(self, *a, **k):
            calls.append((a, k))
            return tmp_path / "out.m4b"

        monkeypatch.setattr(AudiobookProject, "render", fake_render)

        code = main(["render", "-p", str(path)])

        assert code == 0
        assert calls


class TestProgressBarCannotKillARender:
    """A cosmetic progress indicator must never abort the render it reports on.

    Found while smoke-testing PH-B-002 through the real CLI: rich's default
    spinner is "dots", drawn with braille (U+28xx), and cp1252 -- the DEFAULT
    Windows console codepage -- cannot encode it. Every render on a stock
    Windows console raised UnicodeEncodeError, on a healthy book, AFTER the
    user had already paid for the TTS pass. The original guard caught only
    ImportError, so the failure escaped.
    """

    def test_spinner_is_ascii_when_the_console_cannot_encode_braille(
        self, monkeypatch
    ):
        import io

        from audiobooker.cli import _encodable_spinner

        monkeypatch.setattr(
            sys, "stdout",
            io.TextIOWrapper(io.BytesIO(), encoding="cp1252"),
        )
        assert _encodable_spinner() == "line"

    def test_spinner_stays_pretty_when_the_console_can(self, monkeypatch):
        import io

        from audiobooker.cli import _encodable_spinner

        monkeypatch.setattr(
            sys, "stdout",
            io.TextIOWrapper(io.BytesIO(), encoding="utf-8"),
        )
        assert _encodable_spinner() == "dots"

    def test_unknown_encoding_degrades_instead_of_raising(self, monkeypatch):
        """`LookupError`, not just UnicodeEncodeError -- a stream can report an
        encoding name Python does not know."""
        from audiobooker.cli import _encodable_spinner

        class Weird:
            encoding = "not-a-real-codec"

        monkeypatch.setattr(sys, "stdout", Weird())
        assert _encodable_spinner() == "line"

    def test_the_chosen_spinner_actually_encodes(self):
        """The real assertion: whatever we pick, this console can print it."""
        from rich.spinner import Spinner

        from audiobooker.cli import _encodable_spinner

        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        for frame in Spinner(_encodable_spinner()).frames:
            frame.encode(encoding)
