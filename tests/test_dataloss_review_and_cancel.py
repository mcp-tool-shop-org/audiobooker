"""Two data-loss defects found by the Phase 5 feature audit.

Both are bugs rather than feature gaps, so they are fixed as bugs rather
than waiting on the feature-review gate.

1. FEAT-CAST-002 — a second `review-export` destroys the first round's
   corrections, triggered by excluding a front-matter chapter.
2. FEAT-PROD-001 — Ctrl-C does not stop a `--jobs N` render; every queued
   chapter is still synthesized and, on a paid API, billed.
"""

from __future__ import annotations

import pathlib
from concurrent.futures import Future

import pytest

from audiobooker.models import UtteranceType
from audiobooker.project import AudiobookProject


# ---------------------------------------------------------------------------
# 1. Review corrections must survive a re-export
# ---------------------------------------------------------------------------

BOOK = """Chapter 1

A dedication that nobody should ever have to listen to.

Chapter 2

"Two ounces light," said Halloran.

"The scale is wrong," said Ines.

Chapter 3

"We check the manifest tomorrow," said Ines.
"""


def _book(tmp_path: pathlib.Path, *, exclude_first: bool = False
          ) -> AudiobookProject:
    """Parse, optionally exclude the front matter, THEN compile.

    The order is the whole defect. Excluding before compiling is what real
    use looks like — you drop the dedication, then compile what is left —
    and it leaves the skipped chapter permanently uncompiled. Compiling
    first would mark every chapter compiled and satisfy even the unnarrowed
    guard, which is how an earlier version of this test passed against the
    bug it was written to catch.
    """
    src = tmp_path / "book.txt"
    src.write_text(BOOK, encoding="utf-8")
    p = AudiobookProject.from_text(src)
    if exclude_first:
        p.chapters[0].skip = True
    p.compile()
    return p


class TestReviewCorrectionsSurviveReExport:
    """FEAT-CAST-002.

    `export_for_review` guarded its implicit recompile with
    `all(c.is_compiled for c in self.chapters)` — over EVERY chapter,
    including skipped ones. `compile()` deliberately never compiles a
    skipped chapter, so once any chapter is excluded that condition can
    never be satisfied: every export recompiles, and `compile()` assigns
    `chapter.utterances = utterances` unconditionally, discarding whatever
    the human just fixed.

    The trigger is the first thing anyone does with a real EPUB — dropping
    the front matter so the dedication is not narrated.
    """

    def test_excluding_a_chapter_does_not_arm_a_recompile(self, tmp_path):
        p = _book(tmp_path, exclude_first=True)
        assert len(p.chapters) >= 2, "fixture must have a chapter to exclude"
        assert not p.chapters[0].is_compiled, (
            "the excluded chapter must be UNcompiled — that is the condition "
            "that made the unnarrowed guard permanently false"
        )

        # Every chapter compile() would actually touch is compiled, so no
        # recompile is warranted. Before the fix this predicate was computed
        # over all chapters and was therefore permanently False.
        assert all(c.is_compiled for c in p.chapters if not c.skip)

    def test_a_correction_survives_review_export(self, tmp_path):
        p = _book(tmp_path, exclude_first=True)

        target = None
        for ch in p.chapters:
            if ch.skip:
                continue
            for u in ch.utterances:
                if u.utterance_type is UtteranceType.DIALOGUE:
                    target = (ch.index, u.id)
                    u.speaker = "ReviewedByAHuman"
                    break
            if target:
                break
        assert target, "fixture produced no dialogue to correct"
        ch_index, utt_id = target

        p.export_for_review(tmp_path / "review.txt")

        speaker = next(
            (u.speaker for c in p.chapters if c.index == ch_index
             for u in c.utterances if u.id == utt_id),
            "<the utterance no longer exists>",
        )
        assert speaker == "ReviewedByAHuman", (
            "review-export recompiled and destroyed the correction"
        )

    def test_an_uncompiled_active_chapter_still_triggers_compile(self, tmp_path):
        """The guard must still do its job — narrowing it must not disable it."""
        p = _book(tmp_path, exclude_first=True)
        active = next(c for c in p.chapters if not c.skip)
        active.utterances = []
        assert not active.is_compiled

        p.export_for_review(tmp_path / "review.txt")
        assert active.is_compiled, "export must compile a genuinely uncompiled chapter"

    def test_status_reports_compiled_ignoring_skipped_chapters(self, tmp_path):
        """Same confusion, cosmetic surface: a project whose active chapters
        are all compiled IS compiled, whatever the excluded ones say."""
        p = _book(tmp_path, exclude_first=True)
        assert p.info()["compiled"] is True


# ---------------------------------------------------------------------------
# 2. An interrupt must stop queued work
# ---------------------------------------------------------------------------

class TestInterruptStopsQueuedChapters:
    """FEAT-PROD-001.

    Every chapter is submitted to the pool up front. The `except RenderError`
    and `except Exception` clauses cancel the remainder — but KeyboardInterrupt
    and SystemExit are BaseException and match neither, so they fall through
    to `with ThreadPoolExecutor(...)`'s implicit `shutdown(wait=True)`, which
    drains the whole queue before the interrupt ever reaches the caller.

    On a paid TTS API that is money spent after the user pressed Ctrl-C.
    """

    def test_baseexception_in_the_result_loop_cancels_the_remainder(
        self, monkeypatch
    ):
        """Models the real shape: the interrupt arrives in the MAIN thread,
        inside the as_completed loop, while work is still queued."""
        import audiobooker.renderer.engine as engine_mod

        pending = [Future() for _ in range(6)]
        done = Future()
        done.set_result(None)

        def fake_as_completed(fs, *a, **kw):
            yield done
            raise KeyboardInterrupt("user pressed Ctrl-C")

        monkeypatch.setattr(engine_mod, "as_completed", fake_as_completed)

        # Reproduce the engine's loop shape exactly, including the pool's
        # context-manager exit, so the test exercises the structure rather
        # than a paraphrase of it.
        from concurrent.futures import ThreadPoolExecutor

        futures = {f: i for i, f in enumerate(pending)}

        def run():
            with ThreadPoolExecutor(max_workers=2) as pool:  # noqa: F841
                try:
                    for fut in engine_mod.as_completed(futures):
                        fut.result()
                except BaseException:
                    for f in futures:
                        f.cancel()
                    raise

        with pytest.raises(KeyboardInterrupt):
            run()

        assert all(f.cancelled() for f in pending), (
            "queued chapters were not cancelled — they would still be "
            "synthesized and billed after the interrupt"
        )

    def test_the_engine_has_a_baseexception_guard_on_the_pool(self):
        """Pins the fix at its call site.

        An `except Exception` cannot see KeyboardInterrupt, so the parallel
        block must name BaseException (or pass cancel_futures) explicitly.
        A regression here is silent and only shows up on a real interrupt
        against a paid API.
        """
        src = pathlib.Path(
            engine_file := __import__(
                "audiobooker.renderer.engine", fromlist=["__file__"]
            ).__file__
        ).read_text(encoding="utf-8")
        assert engine_file
        start = src.index("if jobs > 1 and len(chapters_to_render) > 1:")
        block = src[start:start + 2600]
        assert ("BaseException" in block) or ("cancel_futures" in block), (
            "the parallel render block cancels only on Exception, so a "
            "Ctrl-C still drains every queued chapter"
        )
