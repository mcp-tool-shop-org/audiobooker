"""
Regression tests for dogfood-swarm Stage C HUMANIZATION fixes (v2.0.1).

Each test fails against the pre-fix behavior and passes against the fix.
Hermetic: no network, no real ffmpeg, no voice-soundboard (mocked as needed).

Covered fixes:
- ENGINE-C-001   ffmpeg preflight at top of render_project() (fail fast)
- ENGINE-C-001   assembly failure on missing ffmpeg wraps into RenderError
- ENGINE-C-002   voice-soundboard import error uses the canonical install string
- ENGINE-C-003   dry-run labels words/wpm as "Audiobook length", not render time
- ENGINE-C-004   parallel progress callback advances monotonically
- REVIEW-C-005    unmatched review block is counted/named, not silently dropped
- REVIEW-C-005    export header warns not to edit the '=== Title === [id:...]' line
- FAILREPORT-C-006 save() with no cache_dir returns None sentinel (no phantom path)
"""

from __future__ import annotations

import logging

import pytest

from audiobooker import AudiobookProject
from audiobooker.models import Chapter, Utterance, UtteranceType
from audiobooker.renderer.engine import (
    RenderError,
    VOICE_SOUNDBOARD_INSTALL_HINT,
    dry_run_render,
    render_project,
)
from tests.fakes.fake_tts import FakeTTSEngine
from tests.fakes.fake_ffmpeg import FakeAssembler
from tests.conftest import GOLDEN_BOOK_PATH


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project() -> AudiobookProject:
    """Parse and compile the golden book (cast + compiled)."""
    p = AudiobookProject.from_text(GOLDEN_BOOK_PATH)
    p.cast("narrator", "af_heart", emotion="calm")
    p.cast("Sarah", "af_bella", emotion="curious")
    p.cast("Marcus", "am_michael", emotion="serious")
    p.compile()
    return p


# ---------------------------------------------------------------------------
# ENGINE-C-001 — ffmpeg preflight fails fast before the render loop
# ---------------------------------------------------------------------------

def test_render_project_preflights_missing_ffmpeg(project, tmp_path, monkeypatch):
    """ENGINE-C-001: when the default m4b assembler needs ffmpeg and it is
    missing, render_project raises DEP_FFMPEG_MISSING *before* rendering any
    chapter — not after burning through the whole book."""
    import audiobooker.renderer.output as output_mod

    monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: False)

    engine = FakeTTSEngine()

    with pytest.raises(RenderError) as exc_info:
        render_project(
            project,
            tmp_path / "book.m4b",
            engine=engine,
            cache_root=tmp_path / "cache",
            # assembler=None -> real m4b assembler -> preflight applies
        )

    err = exc_info.value
    assert err.code == "DEP_FFMPEG_MISSING"
    assert err.retryable is True
    assert "ffmpeg.org/download.html" in err.hint
    assert "cached" in err.hint
    # Fail-fast: not a single chapter was synthesized.
    assert engine.calls == []


def test_render_project_skips_preflight_for_injected_assembler(project, tmp_path, monkeypatch):
    """ENGINE-C-001: an injected (test/non-ffmpeg) assembler must NOT trip the
    ffmpeg preflight even if check_ffmpeg() reports unavailable."""
    import audiobooker.renderer.output as output_mod

    monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: False)

    engine = FakeTTSEngine()
    assembler = FakeAssembler()

    result = render_project(
        project,
        tmp_path / "book.m4b",
        engine=engine,
        assembler=assembler,
        cache_root=tmp_path / "cache",
    )
    assert result.exists()
    assert len(engine.calls) == len(project.chapters)


def test_assembly_ffmpeg_failure_wraps_into_render_error(project, tmp_path):
    """ENGINE-C-001: if assembly fails on missing ffmpeg AFTER a successful
    render, the RuntimeError is wrapped in a RenderError so the recoverable,
    cached-chapter path is surfaced instead of a raw stack."""

    def ffmpeg_missing_assembler(**kwargs):
        raise RuntimeError(
            "FFmpeg is required for M4B assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )

    engine = FakeTTSEngine()

    with pytest.raises(RenderError) as exc_info:
        render_project(
            project,
            tmp_path / "book.m4b",
            engine=engine,
            assembler=ffmpeg_missing_assembler,
            cache_root=tmp_path / "cache",
        )

    err = exc_info.value
    assert err.code == "DEP_FFMPEG_MISSING"
    assert err.retryable is True
    assert "cached" in err.hint
    # Chapters DID render before assembly failed — re-run will skip them.
    assert len(engine.calls) == len(project.chapters)


# ---------------------------------------------------------------------------
# ENGINE-C-002 — voice-soundboard install hint is canonical
# ---------------------------------------------------------------------------

def test_voice_soundboard_install_hint_is_canonical():
    """ENGINE-C-002: the install string must be the PyPI form, never a
    'pip install -e F:/AI/...' editable path."""
    assert "pip install voice-soundboard" in VOICE_SOUNDBOARD_INSTALL_HINT
    assert "audiobooker-ai[render]" in VOICE_SOUNDBOARD_INSTALL_HINT
    assert "F:/AI" not in VOICE_SOUNDBOARD_INSTALL_HINT
    assert "-e " not in VOICE_SOUNDBOARD_INSTALL_HINT
    assert "git clone" not in VOICE_SOUNDBOARD_INSTALL_HINT


def test_missing_voice_soundboard_raises_canonical_hint(monkeypatch):
    """ENGINE-C-002: instantiating the real engine without voice-soundboard
    surfaces the canonical install string (no editable filesystem path)."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("voice_soundboard"):
            raise ImportError("No module named 'voice_soundboard'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from audiobooker.renderer.engine import _VoiceSoundboardEngine

    with pytest.raises(ImportError) as exc_info:
        _VoiceSoundboardEngine()

    msg = str(exc_info.value)
    assert "pip install voice-soundboard" in msg
    assert "F:/AI" not in msg


# ---------------------------------------------------------------------------
# ENGINE-C-003 — dry-run labels playback length, not render time
# ---------------------------------------------------------------------------

def test_dry_run_labels_audiobook_length(project, tmp_path, capsys):
    """ENGINE-C-003: words/wpm is playback length, not render wall-time.
    The dry-run output must say 'Audiobook length', not 'Estimated render time'."""
    # Give the project a stable on-disk home so cache resolution is quiet.
    project.save(tmp_path / "book.audiobooker")

    dry_run_render(project, resume=False)

    out = capsys.readouterr().out
    assert "Audiobook length:" in out
    assert "Estimated render time:" not in out


# ---------------------------------------------------------------------------
# ENGINE-C-004 — parallel progress advances monotonically
# ---------------------------------------------------------------------------

def test_parallel_progress_is_monotonic(project, tmp_path):
    """ENGINE-C-004: under jobs>1 the progress callback's 'current' value must
    never decrease, even though as_completed() finishes chapters out of order."""
    # Need at least a few chapters to exercise parallel ordering.
    assert len(project.chapters) >= 2

    engine = FakeTTSEngine()
    assembler = FakeAssembler()
    seen: list[int] = []

    def on_progress(current, total, status):
        seen.append(current)
        assert 0 <= current <= total

    render_project(
        project,
        tmp_path / "book.m4b",
        progress_callback=on_progress,
        engine=engine,
        assembler=assembler,
        cache_root=tmp_path / "cache",
        jobs=4,
    )

    # The 'current' sequence must be non-decreasing.
    assert seen == sorted(seen), f"progress went backwards: {seen}"


# ---------------------------------------------------------------------------
# REVIEW-C-005 — unmatched review block is counted + named, not dropped
# ---------------------------------------------------------------------------

def _project_with_chapter(title: str, chapter_id: str, utterances) -> AudiobookProject:
    p = AudiobookProject(title="Review Skip", author="Tester")
    p.chapters = [
        Chapter(index=0, id=chapter_id, title=title, raw_text="x", utterances=utterances)
    ]
    return p


def test_import_counts_unmatched_blocks(tmp_path, caplog):
    """REVIEW-C-005: a review block whose title/id matches no chapter must be
    counted in chapters_skipped and named in skipped_titles, with a warning."""
    from audiobooker.review import import_reviewed

    project = _project_with_chapter(
        "Real Chapter", "ch-real",
        [Utterance(speaker="narrator", text="Hello.",
                   utterance_type=UtteranceType.NARRATION)],
    )

    # A review file with one matching block and one orphan block.
    review = tmp_path / "review.txt"
    review.write_text(
        "=== Real Chapter === [id:ch-real]\n"
        "\n"
        "@narrator\n"
        "Hello there.\n"
        "\n"
        "=== Ghost Chapter === [id:does-not-exist]\n"
        "\n"
        "@narrator\n"
        "Nobody will hear this.\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="audiobooker.review"):
        stats = import_reviewed(project, review)

    assert stats["chapters_updated"] == 1
    assert stats["chapters_skipped"] == 1
    assert "Ghost Chapter" in stats["skipped_titles"]
    assert any("Ghost Chapter" in r.message for r in caplog.records), (
        f"expected a warning naming the skipped block; got "
        f"{[r.message for r in caplog.records]}"
    )


def test_import_no_skips_reports_zero(tmp_path):
    """REVIEW-C-005: a clean import reports chapters_skipped=0 and an empty
    skipped_titles list (keys always present so the CLI can read them)."""
    from audiobooker.review import import_reviewed

    project = _project_with_chapter(
        "Solo", "ch-solo",
        [Utterance(speaker="narrator", text="One.",
                   utterance_type=UtteranceType.NARRATION)],
    )
    review = tmp_path / "review.txt"
    review.write_text(
        "=== Solo === [id:ch-solo]\n\n@narrator\nOne edited.\n",
        encoding="utf-8",
    )

    stats = import_reviewed(project, review)
    assert stats["chapters_skipped"] == 0
    assert stats["skipped_titles"] == []


def test_export_header_warns_against_editing_id_line(tmp_path):
    """REVIEW-C-005: the exported review file must instruct users not to edit
    the '=== Title === [id:...]' line that import uses for matching."""
    from audiobooker.review import export_for_review

    project = _project_with_chapter(
        "Note", "ch-note",
        [Utterance(speaker="narrator", text="Body.",
                   utterance_type=UtteranceType.NARRATION)],
    )
    out = export_for_review(project, tmp_path / "review.txt")
    header = out.read_text(encoding="utf-8")

    assert "[id:" in header
    # The note explicitly calls out the id line as off-limits.
    lower = header.lower()
    assert "do not edit" in lower or "do not change" in lower
    assert "id" in lower


# ---------------------------------------------------------------------------
# FAILREPORT-C-006 — save() with no cache_dir returns None sentinel
# ---------------------------------------------------------------------------

def test_failure_report_save_no_cache_dir_returns_none(caplog):
    """FAILREPORT-C-006: save() with no cache_dir (and no explicit path) must
    return None — never a path to a file that was never written."""
    from audiobooker.renderer.failure_report import RenderFailureReport

    report = RenderFailureReport(book_title="No Cache")
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        report.add_failure(0, "Ch1", e)

    with caplog.at_level(logging.WARNING, logger="audiobooker.failure_report"):
        result = report.save()  # no cache_dir, no path

    assert result is None
    assert any("no report file was written" in r.message.lower()
               for r in caplog.records)


def test_failure_report_save_with_path_still_returns_path(tmp_path):
    """FAILREPORT-C-006: an explicit path still returns the real written path
    (the sentinel only applies to the no-target case)."""
    from audiobooker.renderer.failure_report import RenderFailureReport

    report = RenderFailureReport(book_title="Has Path")
    out = report.save(tmp_path / "report.json")
    assert out is not None
    assert out.exists()
