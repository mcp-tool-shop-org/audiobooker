"""
Regression tests for dogfood-swarm Stage A renderer + review fixes (v2.0.1).

Each test fails against the pre-fix behavior and passes against the fix.

Covered defects:
- REVIEW-A-001  utterance_type preserved on review round-trip
- REVIEW-A-002  body text starting with #/@/=== survives round-trip
- CACHE-A-003   load_manifest recovers from .bak when live manifest is missing
- ENGINE-A-004  preprocess_ssml escapes XML metacharacters
- ENGINE-A-005  failure counter increment is lock-guarded
- ENGINE-A-007  disk-full branch unlinks the partial .wav.tmp
- OUTPUT-A-006  missing cover art logs a warning instead of silent no-op
"""

from __future__ import annotations

import logging
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from audiobooker.models import Chapter, Utterance, UtteranceType


# ---------------------------------------------------------------------------
# REVIEW-A-001 — utterance_type round-trips losslessly
# ---------------------------------------------------------------------------

def _project_with_chapter(utterances):
    from audiobooker.project import AudiobookProject

    project = AudiobookProject(title="Round Trip", author="Tester")
    project.chapters = [
        Chapter(index=0, title="Chapter 1", raw_text="x", utterances=utterances)
    ]
    return project


def test_review_roundtrip_preserves_utterance_type(tmp_path):
    """REVIEW-A-001: NARRATION/DIALOGUE/DIRECTION/PAUSE must survive export→import.

    Pre-fix, import re-derived the type from a quote heuristic, collapsing
    DIRECTION and PAUSE to NARRATION.
    """
    from audiobooker.review import export_for_review, import_reviewed

    original = [
        Utterance(speaker="narrator", text="The hall fell silent.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker="Alice", text='"Who is there?"',
                  utterance_type=UtteranceType.DIALOGUE, emotion="nervous"),
        Utterance(speaker="director", text="She pauses by the window.",
                  utterance_type=UtteranceType.DIRECTION),
        Utterance(speaker="pause-marker", text="A long stillness.",
                  utterance_type=UtteranceType.PAUSE),
    ]
    project = _project_with_chapter(original)

    review_path = tmp_path / "review.txt"
    export_for_review(project, review_path)

    # Re-import unchanged.
    import_reviewed(project, review_path)

    types = [u.utterance_type for u in project.chapters[0].utterances]
    assert types == [
        UtteranceType.NARRATION,
        UtteranceType.DIALOGUE,
        UtteranceType.DIRECTION,
        UtteranceType.PAUSE,
    ]


# ---------------------------------------------------------------------------
# REVIEW-A-002 — body text starting with control chars survives round-trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", ["#1 bestseller", "@home tonight", "=== results ==="])
def test_review_roundtrip_preserves_control_char_body(tmp_path, body):
    """REVIEW-A-002: utterance bodies starting with #/@/=== must not be dropped.

    Pre-fix, '#...' was treated as a comment (skipped), '@...' as a speaker,
    and '=== ... ===' as a chapter marker — so the body text vanished.
    """
    from audiobooker.review import export_for_review, import_reviewed

    original = [
        Utterance(speaker="narrator", text="Lead-in line.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker="Alice", text=body,
                  utterance_type=UtteranceType.DIALOGUE),
        Utterance(speaker="narrator", text="Trailing line.",
                  utterance_type=UtteranceType.NARRATION),
    ]
    project = _project_with_chapter(original)

    review_path = tmp_path / "review.txt"
    export_for_review(project, review_path)
    import_reviewed(project, review_path)

    texts = [u.text for u in project.chapters[0].utterances]
    assert body in texts, f"body {body!r} was lost on round-trip; got {texts!r}"


# ---------------------------------------------------------------------------
# CACHE-A-003 — load_manifest recovers from .bak
# ---------------------------------------------------------------------------

def test_load_manifest_recovers_from_bak(tmp_path):
    """CACHE-A-003: a crash between the bak→target renames leaves only the .bak.

    Pre-fix, load_manifest returned None (orphaning the entire cache).
    """
    from audiobooker.renderer.cache_manifest import (
        CacheManifest, ChapterCacheEntry, load_manifest, get_manifest_path,
        get_manifests_dir,
    )

    cache_root = tmp_path / "cache"
    get_manifests_dir(cache_root).mkdir(parents=True)
    manifest_path = get_manifest_path(cache_root)

    manifest = CacheManifest(book_title="Crash Test")
    manifest.set_entry(ChapterCacheEntry(
        chapter_index=0, text_hash="t", casting_hash="c",
        render_params_hash="p", wav_path="ch0.wav", status="ok",
    ))

    # Simulate the crash window: live manifest missing, valid .bak present.
    bak_path = manifest_path.with_suffix(".json.bak")
    bak_path.write_text(manifest.to_json(), encoding="utf-8")
    assert not manifest_path.exists()

    recovered = load_manifest(manifest_path)
    assert recovered is not None, "load_manifest failed to recover from .bak"
    assert recovered.book_title == "Crash Test"
    assert recovered.get_entry(0) is not None
    assert recovered.get_entry(0).wav_path == "ch0.wav"


# ---------------------------------------------------------------------------
# ENGINE-A-004 — SSML escaping
# ---------------------------------------------------------------------------

def test_preprocess_ssml_escapes_xml_metacharacters():
    """ENGINE-A-004: '&', '<', '>' in utterance text must produce well-formed SSML.

    Pre-fix the raw chars were interpolated, yielding unparseable XML.
    """
    from audiobooker.renderer.engine import preprocess_ssml

    utterances = [
        Utterance(speaker="narrator", text="Tom & Jerry went <down> the road > home.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker="Alice", text="5 < 6 & 6 > 5",
                  utterance_type=UtteranceType.DIALOGUE, emotion="excited"),
    ]
    ssml = preprocess_ssml(utterances)

    # Must parse without raising.
    root = ET.fromstring(ssml)
    assert root.tag == "speak"
    # The literal text is recoverable after parsing.
    flat = "".join(root.itertext())
    assert "Tom & Jerry" in flat
    assert "5 < 6 & 6 > 5" in flat


# ---------------------------------------------------------------------------
# ENGINE-A-005 — failure counter increment is lock-guarded
# ---------------------------------------------------------------------------

class _RecordingLock:
    """A lock wrapper that tracks whether it is currently held."""

    def __init__(self):
        self._lock = threading.Lock()
        self.held = False

    def __enter__(self):
        self._lock.acquire()
        self.held = True
        return self

    def __exit__(self, *exc):
        self.held = False
        self._lock.release()
        return False


class _GuardedSummary:
    """RenderSummary stand-in that asserts the lock is held when failed mutates."""

    def __init__(self, lock):
        self._lock = lock
        self.rendered = 0
        self.skipped_cached = 0
        self.failed = 0
        self.failed_chapters = []
        # Arm the guard only after construction so __init__ defaults are free.
        self._armed = True

    def __setattr__(self, name, value):
        if name == "failed" and getattr(self, "_armed", False):
            assert self._lock.held, "summary.failed mutated outside the lock"
        super().__setattr__(name, value)


def test_failure_counter_increment_is_lock_guarded(tmp_path):
    """ENGINE-A-005: summary.failed must be incremented while holding the lock.

    Pre-fix the increment happened after the `with manifest_lock` block, so the
    guarded-summary assertion (lock held) would fail.
    """
    from audiobooker.renderer.engine import _handle_chapter_failure
    from audiobooker.renderer.cache_manifest import CacheManifest, get_manifests_dir, get_manifest_path
    from audiobooker.renderer.failure_report import RenderFailureReport

    cache_root = tmp_path / "cache"
    get_manifests_dir(cache_root).mkdir(parents=True)
    manifest_path = get_manifest_path(cache_root)

    manifest = CacheManifest(book_title="Lock Test")
    failure_report = RenderFailureReport(book_title="Lock Test", total_chapters=1)

    lock = _RecordingLock()
    summary = _GuardedSummary(lock)

    chapter = Chapter(index=0, title="Ch", raw_text="x", utterances=[
        Utterance(speaker="narrator", text="boom"),
    ])

    # allow_partial=True so the helper records the failure without re-raising.
    _handle_chapter_failure(
        0, chapter, RuntimeError("synthetic failure"), "th",
        tmp_path / "ch0.wav.tmp", _NullTracker(), manifest, manifest_path,
        lock, failure_report, summary,
        "ch", "ph", allow_partial=True,
    )

    assert summary.failed == 1
    assert summary.failed_chapters and summary.failed_chapters[0]["index"] == 0


class _NullTracker:
    """Minimal tracker stub for _handle_chapter_failure."""

    def mark_failed(self, *a, **k):
        pass


# ---------------------------------------------------------------------------
# ENGINE-A-007 — disk-full branch unlinks the partial tmp
# ---------------------------------------------------------------------------

def test_disk_full_unlinks_partial_tmp(tmp_path):
    """ENGINE-A-007: a disk-full abort must remove the partial <target>.wav.tmp.

    We drive render_project with an engine that writes a partial tmp then raises
    an ENOSPC OSError, and assert no .wav.tmp survives in the cache.
    """
    import errno
    from audiobooker.project import AudiobookProject
    from audiobooker.renderer.engine import render_project, RenderError

    class _DiskFullEngine:
        def synthesize(self, script, voices, output_path, progress_callback=None):
            # Write a partial tmp file, then fail as if the disk filled up.
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x00" * 16)
            raise OSError(errno.ENOSPC, "No space left on device")

    project = AudiobookProject(title="DiskFull", author="Tester")
    # Cast the narrator so casting-completeness validation passes and the
    # disk-full branch (not the validation guard) is what aborts the render.
    project.casting.cast("narrator", "af_heart")
    project.chapters = [
        Chapter(index=0, title="Ch1", raw_text="word " * 3, utterances=[
            Utterance(speaker="narrator", text="hello there"),
        ]),
    ]

    cache_root = tmp_path / "cache"

    def _noop_assembler(**kwargs):
        raise AssertionError("assembler should not be reached on disk-full abort")

    with pytest.raises(RenderError):
        render_project(
            project,
            tmp_path / "out.m4b",
            engine=_DiskFullEngine(),
            assembler=_noop_assembler,
            cache_root=cache_root,
            resume=False,
        )

    leftover = list(cache_root.rglob("*.wav.tmp"))
    assert leftover == [], f"partial tmp not cleaned up: {leftover}"


# ---------------------------------------------------------------------------
# OUTPUT-A-006 — missing cover art logs a warning
# ---------------------------------------------------------------------------

def test_assemble_m4b_warns_on_missing_cover(tmp_path, caplog):
    """OUTPUT-A-006: a truthy-but-missing cover_art path must log a warning.

    Pre-fix the cover was silently skipped with no diagnostic.
    """
    from audiobooker.renderer import output as output_mod
    from audiobooker.renderer.output import assemble_m4b, AssemblyResult

    # Stub ffmpeg availability + the runner so no real subprocess runs.
    monkeypatch_ffmpeg(output_mod)

    class _OkRunner:
        def run(self, cmd):
            # Produce the output file for the final metadata pass.
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 32)
            return _RunResult(0, "")

    chap = tmp_path / "ch0.wav"
    chap.write_bytes(b"\x00" * 64)
    out_path = tmp_path / "book.m4b"

    missing_cover = tmp_path / "does_not_exist.jpg"
    assert not missing_cover.exists()

    with caplog.at_level(logging.WARNING, logger="audiobooker.output"):
        result = assemble_m4b(
            [(chap, "Chapter 1", 1.0)],
            out_path,
            title="Book",
            author="Author",
            runner=_OkRunner(),
            cover_art=str(missing_cover),
        )

    assert isinstance(result, AssemblyResult)
    assert any(
        "cover" in rec.message.lower() and "not found" in rec.message.lower()
        for rec in caplog.records
    ), f"expected a missing-cover warning; got {[r.message for r in caplog.records]}"


class _RunResult:
    def __init__(self, returncode, stderr):
        self.returncode = returncode
        self.stderr = stderr


def monkeypatch_ffmpeg(output_mod):
    """Force check_ffmpeg() to report available without spawning ffmpeg."""
    output_mod._ffmpeg_checked = True
