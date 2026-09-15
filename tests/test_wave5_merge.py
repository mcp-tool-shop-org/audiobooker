"""Wave 5 integration fixes — the items that spanned two agents' file grants.

Each of these was deliberately held back from the parallel wave because no
single agent could own it, and doing them here is the coordinator's job at
the merge. They still need tests.
"""

from __future__ import annotations

import logging

from audiobooker.cli import USER_ERROR_TYPES
from audiobooker.errors import AudiobookerError, CompilationFailedError
from audiobooker.models import Chapter, ProjectConfig


class TestCompileWorkersIsClampedToTheMachine:
    """CH-B-013.

    `compile_workers` is validated as "a positive integer" in BOTH models.py
    and config_file.py. The two agree — and what they agree on is a floor
    with no ceiling. A config copied from another project, or an honest
    "more workers = faster" guess, passed validation and spawned that many
    ProcessPoolExecutor workers, each of which may load BookNLP/spaCy.

    The existing `min(compile_workers, len(active_chapters))` bound does not
    help on the books that matter: a long novel has 40-80+ chapters, so the
    chapter count IS the large number.
    """

    def test_a_huge_worker_count_still_passes_validation(self):
        """Not a bug to fix in the validator — establishing the premise.

        A ceiling here would have to be an arbitrary constant and would
        wrongly refuse a legitimate value on a 128-core machine. The clamp
        is what adapts.
        """
        assert ProjectConfig(compile_workers=500).compile_workers == 500

    def test_workers_never_exceed_cpu_count(self, monkeypatch, caplog):
        """Measures the number actually handed to the pool.

        NOTE the patch target. `_compile_parallel` does
        `from concurrent.futures import ProcessPoolExecutor` INSIDE the
        function, so patching `audiobooker.project.ProcessPoolExecutor` binds
        a name nothing reads and the probe records nothing — a test that
        passes because it measured nothing. Patch the source module, and
        assert unconditionally so a mis-aimed patch fails loudly instead.
        """
        import concurrent.futures as cf

        import audiobooker.project as project_mod

        monkeypatch.setattr(project_mod.os, "cpu_count", lambda: 4)
        captured: dict = {}

        class FakePool:
            def __init__(self, max_workers=None, **kw):
                captured["max_workers"] = max_workers
                raise RuntimeError("stop here — the count is what we measure")

        monkeypatch.setattr(cf, "ProcessPoolExecutor", FakePool)

        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="T", author="A")
        project.chapters = [
            Chapter(index=i, title=f"C{i}", raw_text=f"Line {i}.")
            for i in range(40)
        ]
        project.config.compile_workers = 500
        project.config.parallel_compile = True  # the gate for this path

        with caplog.at_level(logging.WARNING):
            try:
                project.compile()
            except Exception:
                pass  # the sequential fallback is not what this measures

        # 500 requested, 4 CPUs, 40 chapters -> 4. Unconditional: if the
        # pool was never constructed, this test proved nothing and must say so.
        assert "max_workers" in captured, (
            "the executor was never constructed — this test measured nothing"
        )
        assert captured["max_workers"] == 4

    def test_the_clamp_says_so_rather_than_silently_ignoring_you(
        self, monkeypatch, caplog
    ):
        """A setting that is not honoured must be visible, or the user just
        wonders why it did not get faster."""
        import audiobooker.project as project_mod

        monkeypatch.setattr(project_mod.os, "cpu_count", lambda: 2)

        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="T", author="A")
        project.chapters = [
            Chapter(index=i, title=f"C{i}", raw_text=f"Line {i}.")
            for i in range(8)
        ]
        project.config.compile_workers = 64
        project.config.parallel_compile = True  # the gate for this path

        with caplog.at_level(logging.WARNING):
            try:
                project.compile()
            except Exception:
                pass

        assert "compile_workers=64" in caplog.text, caplog.text
        assert "2 CPU" in caplog.text, caplog.text


class TestAFailedCompileIsAUserError:
    """CH-B-002 handoff item 1.

    `CompilationFailedError` subclasses `RuntimeError` so that every existing
    `except Exception` site keeps working — but that also meant main()'s
    catch-all owned it and exited 2, "audiobooker hit an unexpected error".
    A book that did not compile is the user's book not compiling.
    """

    def test_it_is_a_user_error_type(self):
        assert CompilationFailedError in USER_ERROR_TYPES

    def test_it_still_satisfies_the_broad_handlers(self):
        """The reason it subclasses RuntimeError in the first place."""
        assert issubclass(CompilationFailedError, RuntimeError)
        assert issubclass(CompilationFailedError, AudiobookerError)

    def test_it_carries_the_shipcheck_error_shape(self):
        err = CompilationFailedError("chapter 0: boom", chapter_count=3)
        assert err.code == "COMPILE_ALL_CHAPTERS_FAILED"
        assert "3 chapter(s)" in err.detail.message
        assert "3 chapter(s)" in str(err)
        assert err.hint
        assert err.retryable is False

    def test_it_lives_in_errors_and_project_re_exports_it(self):
        """Moved out of project.py, but the old import path still works —
        it was public the moment it could be raised at a caller."""
        from audiobooker.project import CompilationFailedError as ViaProject

        assert ViaProject is CompilationFailedError


class TestRequiredChecksCanActuallyRun:
    """A docs-only PR could never merge: branch protection required five
    checks that ci.yml's paths filter guaranteed would never fire."""

    def test_pull_request_is_not_paths_filtered(self):
        import pathlib
        import re

        ci = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
        text = ci.read_text(encoding="utf-8")
        m = re.search(r"\n  pull_request:\n(.*?)(?=\n  [a-z_]+:|\njobs:)",
                      text, re.S)
        assert m, "no pull_request trigger found"
        assert "paths:" not in m.group(1), (
            "pull_request is paths-filtered again — a docs-only PR will block "
            "forever on required checks that never run"
        )

    def test_push_is_still_paths_filtered(self):
        """The cost control stays where cost actually lives."""
        import pathlib
        import re

        ci = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
        text = ci.read_text(encoding="utf-8")
        m = re.search(r"\n  push:\n(.*?)(?=\n  [a-z#]+)", text, re.S)
        assert m and "paths:" in m.group(1)
