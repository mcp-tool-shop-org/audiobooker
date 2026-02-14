"""
Performance benchmarks for Audiobooker.

These measure parse, compile, and resume speed on synthetic books.
Results are printed for CI visibility; no hard-fail thresholds yet.

Run with: pytest tests/perf/ -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from audiobooker import AudiobookProject
from audiobooker.models import CastingTable, ProjectConfig, Chapter
from audiobooker.casting.dialogue import compile_chapter
from audiobooker.language.profile import get_profile
from audiobooker.nlp.emotion import EmotionInferencer

from tests.perf.conftest import generate_book, bench, BenchResult


# ---------------------------------------------------------------------------
# Parse + detect benchmark
# ---------------------------------------------------------------------------

class TestParseBenchmarks:
    """Benchmarks for text parsing and chapter splitting."""

    def test_parse_small_book(self, small_book):
        """Parse ~10k word book."""
        result = bench(
            "parse_small",
            lambda: AudiobookProject.from_string(small_book, title="Small"),
            iterations=5,
            words="~10k",
        )
        print(f"\n  {result}")
        assert result.per_iteration_ms < 5000  # generous budget

    def test_parse_large_book(self, large_book):
        """Parse ~200k word book (100+ chapters)."""
        result = bench(
            "parse_large",
            lambda: AudiobookProject.from_string(large_book, title="Large"),
            iterations=3,
            words="~200k",
            chapters="120",
        )
        print(f"\n  {result}")
        assert result.per_iteration_ms < 30000  # 30s budget


# ---------------------------------------------------------------------------
# Compile benchmark
# ---------------------------------------------------------------------------

class TestCompileBenchmarks:
    """Benchmarks for dialogue detection + compilation."""

    def test_compile_small_project(self, small_book):
        """Compile ~10k word project."""
        project = AudiobookProject.from_string(small_book, title="Small")
        result = bench(
            "compile_small",
            lambda: project.compile(),
            iterations=5,
            chapters=len(project.chapters),
        )
        print(f"\n  {result}")
        assert result.per_iteration_ms < 5000

    def test_compile_large_project(self, large_book):
        """Compile ~200k word project."""
        project = AudiobookProject.from_string(large_book, title="Large")
        result = bench(
            "compile_large",
            lambda: project.compile(),
            iterations=3,
            chapters=len(project.chapters),
        )
        print(f"\n  {result}")
        assert result.per_iteration_ms < 60000  # 60s budget

    def test_compile_single_chapter_throughput(self):
        """Measure per-chapter compile throughput."""
        profile = get_profile("en")
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        casting.cast("Alice", "af_jessica")

        # Generate one big chapter
        from tests.perf.conftest import generate_chapter
        _, body = generate_chapter(0, paragraphs=200)
        chapter = Chapter(index=0, title="Big Chapter", raw_text=body)

        result = bench(
            "single_chapter_compile",
            lambda: compile_chapter(chapter, casting, profile=profile),
            iterations=10,
            paragraphs=200,
        )
        print(f"\n  {result}")
        assert result.per_iteration_ms < 5000


# ---------------------------------------------------------------------------
# Emotion inference benchmark
# ---------------------------------------------------------------------------

class TestEmotionBenchmarks:
    """Benchmarks for emotion inference."""

    def test_emotion_inference_throughput(self, small_book):
        """Measure emotion inference on a compiled project."""
        project = AudiobookProject.from_string(small_book, title="Small")
        project.compile()

        inferencer = EmotionInferencer(mode="rule", threshold=0.75)
        all_utterances = [u for ch in project.chapters for u in ch.utterances]

        def run_inference():
            for utt in all_utterances:
                inferencer.infer(utt.text)

        result = bench(
            "emotion_inference",
            run_inference,
            iterations=5,
            utterances=len(all_utterances),
        )
        print(f"\n  {result}")
        assert result.per_iteration_ms < 5000


# ---------------------------------------------------------------------------
# Resume benchmark
# ---------------------------------------------------------------------------

class TestResumeBenchmarks:
    """Benchmarks for cache resume (second-run should be near-instant)."""

    def test_cache_lookup_speed(self):
        """Measure manifest cache lookup speed."""
        from audiobooker.renderer.cache_manifest import CacheManifest, ChapterCacheEntry

        # Build a manifest with 200 chapters
        manifest = CacheManifest(book_title="Bench")
        for i in range(200):
            manifest.set_entry(ChapterCacheEntry(
                chapter_index=i,
                text_hash=f"hash_{i}",
                casting_hash="cast_hash",
                render_params_hash="param_hash",
                wav_path=f"/tmp/chapter_{i:04d}.wav",
                status="ok",
                duration_s=120.0,
            ))

        def lookup_all():
            for i in range(200):
                entry = manifest.get_entry(i)
                assert entry is not None

        result = bench(
            "cache_lookup_200",
            lookup_all,
            iterations=100,
            chapters=200,
        )
        print(f"\n  {result}")
        # 200-chapter lookup should be < 50ms
        assert result.per_iteration_ms < 50
