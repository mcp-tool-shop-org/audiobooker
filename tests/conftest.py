"""Shared fixtures and constants for audiobooker tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from audiobooker.project import AudiobookProject


# ---------------------------------------------------------------------------
# Golden book path — single source of truth
# ---------------------------------------------------------------------------

GOLDEN_BOOK_PATH = Path(__file__).parent.parent / "examples" / "golden_book.txt"


# ---------------------------------------------------------------------------
# Test isolation: cli._QUIET is process-global
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cli_quiet_flag():
    """Reset ``audiobooker.cli._QUIET`` before (and after) every test.

    ``--silent`` sets a module-level flag that only ``main()`` ever writes.
    A real CLI process calls ``main()`` once, so nothing leaks there — but in
    the suite a test that runs ``main([..., "--silent"])`` leaves the flag True
    for every later test that invokes a ``cmd_*`` handler DIRECTLY (those never
    go through ``main()``, so nothing resets it). Those tests then see empty
    stdout and fail for a reason that has nothing to do with what they assert.

    It is order-dependent, so it stayed invisible: the only ``--silent`` runs
    lived in test_health_c_cli.py, which sorts after test_cli_commands.py.
    Adding one ``--silent`` test to an alphabetically earlier file broke five
    unrelated tests. This fixture makes the global's default the starting
    state of every test instead of leaving it to filename ordering.
    """
    import audiobooker.cli as _cli

    _cli._QUIET = False
    yield
    _cli._QUIET = False


@pytest.fixture
def golden_book_path() -> Path:
    """Return the path to the golden book fixture, asserting it exists."""
    assert GOLDEN_BOOK_PATH.exists(), (
        f"Golden book fixture not found at {GOLDEN_BOOK_PATH}. "
        f"Ensure examples/golden_book.txt exists in the project root."
    )
    return GOLDEN_BOOK_PATH


# ---------------------------------------------------------------------------
# FT-TEST-009: Shared project fixtures
# ---------------------------------------------------------------------------

SIMPLE_PROJECT_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "The morning sun peeked through the curtains. "
    '"Good morning," said Alice cheerfully. '
    '"Hello there," Bob replied with a smile.\n\n'
    "Chapter 2: The Middle\n\n"
    "Later that afternoon, the two met again. "
    '"Did you finish the report?" Alice asked. '
    '"Almost done," said Bob.'
)


@pytest.fixture
def simple_project() -> AudiobookProject:
    """A 2-chapter project that has NOT been compiled.

    Contains narrator prose + Alice/Bob dialogue in each chapter.
    """
    project = AudiobookProject.from_string(
        SIMPLE_PROJECT_TEXT,
        title="Simple Test Book",
        author="Test Author",
    )
    # Ensure we have 2 chapters (parser splits on headings)
    assert len(project.chapters) >= 2, (
        f"Expected >=2 chapters from simple_project fixture, got {len(project.chapters)}"
    )
    return project


@pytest.fixture
def compiled_project() -> AudiobookProject:
    """A pre-compiled project with narrator + Alice + Bob cast.

    All chapters are compiled to utterances, ready for rendering
    or review export.
    """
    project = AudiobookProject.from_string(
        SIMPLE_PROJECT_TEXT,
        title="Compiled Test Book",
        author="Test Author",
    )
    project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")
    project.cast("Alice", "af_bella", emotion="warm")
    project.cast("Bob", "bm_george", emotion="friendly")
    project.compile()

    # Verify compilation produced utterances
    total = sum(len(ch.utterances) for ch in project.chapters)
    assert total > 0, "compiled_project fixture must have utterances after compile()"
    return project
