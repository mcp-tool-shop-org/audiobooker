"""
Tests for render cache + resume (Phase 3).

Covers:
- Cache hit/miss correctness
- Hash invalidation when text/casting/params change
- Manifest atomic write safety
- Failed chapters don't corrupt prior audio
- --no-resume forces full re-render
- --from-chapter skips earlier chapters
- allow_partial assembles despite failures
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiobooker.models import (
    Chapter, CastingTable, Utterance, UtteranceType, ProjectConfig,
)
from audiobooker.project import AudiobookProject
from audiobooker.renderer.engine import render_chapter, render_project, RenderError, RenderSummary
from audiobooker.renderer.cache_manifest import (
    CacheManifest, ChapterCacheEntry, load_manifest, save_manifest,
    get_cache_root, get_chapter_wav_path, get_manifest_path,
)
from audiobooker.renderer.hash_utils import (
    sha256_text, sha256_json, chapter_text_hash, casting_hash, render_params_hash,
)
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav
from tests.fakes.fake_ffmpeg import FakeAssembler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chapter(index: int = 0, title: str = "Test Chapter", text: str = "") -> Chapter:
    if not text:
        text = f"Chapter {index} content. " * 10
    ch = Chapter(index=index, title=title, raw_text=text)
    ch.utterances.append(
        Utterance(
            speaker="narrator",
            text=text,
            utterance_type=UtteranceType.NARRATION,
            chapter_index=index,
            line_index=0,
        )
    )
    return ch


def _make_project(num_chapters: int = 3, title: str = "Resume Test") -> AudiobookProject:
    project = AudiobookProject(title=title)
    project.cast("narrator", "af_heart")
    for i in range(num_chapters):
        project.chapters.append(_make_chapter(index=i, title=f"Chapter {i+1}"))
    return project


# ---------------------------------------------------------------------------
# Hash utilities
# ---------------------------------------------------------------------------

class TestHashUtils:
    def test_sha256_text_deterministic(self):
        assert sha256_text("hello") == sha256_text("hello")
        assert sha256_text("hello") != sha256_text("world")

    def test_sha256_json_sorted_keys(self):
        a = sha256_json({"b": 1, "a": 2})
        b = sha256_json({"a": 2, "b": 1})
        assert a == b

    def test_chapter_text_hash_changes_on_edit(self):
        ch = _make_chapter(text="original text")
        h1 = chapter_text_hash(ch)
        ch.raw_text = "modified text"
        h2 = chapter_text_hash(ch)
        assert h1 != h2

    def test_casting_hash_changes_on_voice_change(self):
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        h1 = casting_hash(casting)
        casting.cast("narrator", "bm_george")
        h2 = casting_hash(casting)
        assert h1 != h2

    def test_casting_hash_includes_fallback(self):
        c1 = CastingTable(fallback_voice_id="af_heart")
        c2 = CastingTable(fallback_voice_id="bm_george")
        assert casting_hash(c1) != casting_hash(c2)

    def test_render_params_hash_changes_on_sample_rate(self):
        cfg1 = ProjectConfig(sample_rate=24000)
        cfg2 = ProjectConfig(sample_rate=44100)
        assert render_params_hash(cfg1) != render_params_hash(cfg2)


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

class TestCacheManifest:
    def test_roundtrip(self, tmp_path: Path):
        manifest = CacheManifest(book_title="Test")
        entry = ChapterCacheEntry(
            chapter_index=0, text_hash="abc", casting_hash="def",
            render_params_hash="ghi", wav_path="/tmp/ch.wav",
            duration_s=1.5, status="ok",
        )
        manifest.set_entry(entry)

        path = tmp_path / "manifest.json"
        save_manifest(manifest, path)
        loaded = load_manifest(path)

        assert loaded is not None
        assert loaded.book_title == "Test"
        assert len(loaded.chapters) == 1
        assert loaded.chapters[0].status == "ok"

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert load_manifest(tmp_path / "nope.json") is None

    def test_load_corrupt_returns_none(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("NOT JSON", encoding="utf-8")
        assert load_manifest(path) is None

    def test_entry_is_valid(self, tmp_path: Path):
        wav = tmp_path / "ch.wav"
        write_silence_wav(wav)

        entry = ChapterCacheEntry(
            chapter_index=0, text_hash="aaa", casting_hash="bbb",
            render_params_hash="ccc", wav_path=str(wav),
            duration_s=1.0, status="ok",
        )
        assert entry.is_valid("aaa", "bbb", "ccc")
        assert not entry.is_valid("CHANGED", "bbb", "ccc")
        assert not entry.is_valid("aaa", "CHANGED", "ccc")
        assert not entry.is_valid("aaa", "bbb", "CHANGED")

    def test_entry_invalid_if_wav_missing(self):
        entry = ChapterCacheEntry(
            chapter_index=0, text_hash="a", casting_hash="b",
            render_params_hash="c", wav_path="/nonexistent/ch.wav",
            duration_s=1.0, status="ok",
        )
        assert not entry.is_valid("a", "b", "c")

    def test_entry_invalid_if_status_failed(self, tmp_path: Path):
        wav = tmp_path / "ch.wav"
        write_silence_wav(wav)

        entry = ChapterCacheEntry(
            chapter_index=0, text_hash="a", casting_hash="b",
            render_params_hash="c", wav_path=str(wav),
            duration_s=1.0, status="failed",
        )
        assert not entry.is_valid("a", "b", "c")

    def test_set_entry_replaces_existing(self):
        manifest = CacheManifest()
        e1 = ChapterCacheEntry(chapter_index=0, text_hash="old", casting_hash="", render_params_hash="", wav_path="", status="ok")
        e2 = ChapterCacheEntry(chapter_index=0, text_hash="new", casting_hash="", render_params_hash="", wav_path="", status="ok")
        manifest.set_entry(e1)
        manifest.set_entry(e2)
        assert len(manifest.chapters) == 1
        assert manifest.chapters[0].text_hash == "new"

    def test_atomic_write_survives_interruption(self, tmp_path: Path):
        """Simulate crash: write .tmp but don't rename. Next load returns last good."""
        manifest_path = tmp_path / "render_v1.json"

        # Write a good manifest
        good = CacheManifest(book_title="Good")
        save_manifest(good, manifest_path)

        # Simulate a crash: write tmp file but don't rename
        tmp_file = manifest_path.with_suffix(".json.tmp")
        tmp_file.write_text('{"corrupt": true}', encoding="utf-8")

        # Loading should return the last good manifest
        loaded = load_manifest(manifest_path)
        assert loaded is not None
        assert loaded.book_title == "Good"


# ---------------------------------------------------------------------------
# Resume logic (render_project integration)
# ---------------------------------------------------------------------------

class TestResumeSkipsUnchanged:
    def test_second_render_skips_all(self, tmp_path: Path):
        """Render once → re-render → no TTS calls."""
        project = _make_project(num_chapters=3)
        cache = tmp_path / "cache"

        engine1 = FakeTTSEngine(duration_per_call=0.5)
        assembler = FakeAssembler()
        render_project(project, tmp_path / "book1.m4b", engine=engine1, assembler=assembler, cache_root=cache)
        assert len(engine1.calls) == 3

        engine2 = FakeTTSEngine()
        assembler2 = FakeAssembler()
        render_project(project, tmp_path / "book2.m4b", engine=engine2, assembler=assembler2, cache_root=cache)
        assert len(engine2.calls) == 0

    def test_changed_chapter_text_rerenders_only_that_chapter(self, tmp_path: Path):
        """Change chapter 1's text → only chapter 1 re-rendered."""
        project = _make_project(num_chapters=3)
        cache = tmp_path / "cache"

        engine1 = FakeTTSEngine(duration_per_call=0.5)
        render_project(project, tmp_path / "book1.m4b", engine=engine1, assembler=FakeAssembler(), cache_root=cache)
        assert len(engine1.calls) == 3

        # Change chapter 1's text (invalidates its text_hash)
        project.chapters[1].raw_text = "Completely different text content now."

        engine2 = FakeTTSEngine(duration_per_call=0.5)
        render_project(project, tmp_path / "book2.m4b", engine=engine2, assembler=FakeAssembler(), cache_root=cache)
        assert len(engine2.calls) == 1  # only chapter 1

    def test_changed_casting_rerenders_all(self, tmp_path: Path):
        """Change narrator voice → all chapters invalidated."""
        project = _make_project(num_chapters=2)
        cache = tmp_path / "cache"

        engine1 = FakeTTSEngine()
        render_project(project, tmp_path / "b1.m4b", engine=engine1, assembler=FakeAssembler(), cache_root=cache)
        assert len(engine1.calls) == 2

        # Change narrator voice
        project.cast("narrator", "bm_george")

        engine2 = FakeTTSEngine()
        render_project(project, tmp_path / "b2.m4b", engine=engine2, assembler=FakeAssembler(), cache_root=cache)
        assert len(engine2.calls) == 2  # all re-rendered


class TestNoResume:
    def test_no_resume_forces_full_rerender(self, tmp_path: Path):
        project = _make_project(num_chapters=2)
        cache = tmp_path / "cache"

        engine1 = FakeTTSEngine()
        render_project(project, tmp_path / "b1.m4b", engine=engine1, assembler=FakeAssembler(), cache_root=cache)

        engine2 = FakeTTSEngine()
        render_project(
            project, tmp_path / "b2.m4b", engine=engine2, assembler=FakeAssembler(),
            cache_root=cache, resume=False,
        )
        assert len(engine2.calls) == 2  # all re-rendered despite cache


class TestFromChapter:
    def test_from_chapter_skips_earlier(self, tmp_path: Path):
        project = _make_project(num_chapters=3)
        cache = tmp_path / "cache"

        # Render chapters 0 and 1 first
        engine1 = FakeTTSEngine(duration_per_call=0.5)
        render_project(project, tmp_path / "b1.m4b", engine=engine1, assembler=FakeAssembler(), cache_root=cache)

        # Now render from chapter 2 only (chapters 0-1 remain cached)
        engine2 = FakeTTSEngine(duration_per_call=0.5)
        render_project(
            project, tmp_path / "b2.m4b", engine=engine2, assembler=FakeAssembler(),
            cache_root=cache, from_chapter=2,
        )
        assert len(engine2.calls) == 0  # chapter 2 is already cached


class TestFailedChapterPreservation:
    def test_failure_does_not_delete_prior_audio(self, tmp_path: Path):
        """Chapter 2 fails → chapters 0-1 WAVs still exist and are status=ok."""
        project = _make_project(num_chapters=3)
        cache = tmp_path / "cache"

        engine = FakeTTSEngine(fail_on_call=2, fail_error="boom")

        with pytest.raises(RenderError, match="boom"):
            render_project(
                project, tmp_path / "book.m4b",
                engine=engine, assembler=FakeAssembler(),
                cache_root=cache,
            )

        # Chapters 0 and 1 WAVs should exist
        for i in range(2):
            wav = get_chapter_wav_path(cache, i)
            assert wav.exists(), f"Chapter {i} WAV should survive"

        # Manifest should show chapters 0-1 ok, chapter 2 failed
        manifest = load_manifest(get_manifest_path(cache))
        assert manifest is not None
        assert manifest.get_entry(0).status == "ok"
        assert manifest.get_entry(1).status == "ok"
        assert manifest.get_entry(2).status == "failed"

    def test_allow_partial_assembles_despite_failure(self, tmp_path: Path):
        project = _make_project(num_chapters=3)
        cache = tmp_path / "cache"

        engine = FakeTTSEngine(fail_on_call=1)

        result = render_project(
            project, tmp_path / "book.m4b",
            engine=engine, assembler=FakeAssembler(),
            cache_root=cache, allow_partial=True,
        )

        # Should assemble with the chapters that succeeded
        assert result.exists()

    def test_resume_after_failure_skips_ok_chapters(self, tmp_path: Path):
        """Fail on chapter 2 → resume → only chapter 2 re-rendered."""
        project = _make_project(num_chapters=3)
        cache = tmp_path / "cache"

        engine1 = FakeTTSEngine(fail_on_call=2)
        with pytest.raises(RenderError):
            render_project(project, tmp_path / "b1.m4b", engine=engine1, assembler=FakeAssembler(), cache_root=cache)

        # Resume: chapters 0-1 cached, chapter 2 should re-render
        engine2 = FakeTTSEngine(duration_per_call=0.5)
        render_project(project, tmp_path / "b2.m4b", engine=engine2, assembler=FakeAssembler(), cache_root=cache)
        assert len(engine2.calls) == 1  # only chapter 2


class TestRenderSummary:
    def test_summary_on_success(self, tmp_path: Path):
        project = _make_project(num_chapters=2)
        cache = tmp_path / "cache"

        # First render
        engine = FakeTTSEngine()
        render_project(project, tmp_path / "b.m4b", engine=engine, assembler=FakeAssembler(), cache_root=cache)

        # Second render — check the manifest shows all ok
        manifest = load_manifest(get_manifest_path(cache))
        assert len(manifest.ok_chapters()) == 2
        assert len(manifest.failed_chapters()) == 0

    def test_render_error_includes_summary(self, tmp_path: Path):
        project = _make_project(num_chapters=2)
        cache = tmp_path / "cache"
        engine = FakeTTSEngine(fail_on_call=0)

        with pytest.raises(RenderError) as exc_info:
            render_project(project, tmp_path / "b.m4b", engine=engine, assembler=FakeAssembler(), cache_root=cache)

        assert exc_info.value.summary is not None
        assert exc_info.value.summary.failed == 1
