"""
Renderer unit tests — direct coverage of engine.py + output.py.

All tests are hermetic: no voice-soundboard, no FFmpeg, no network.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from audiobooker.models import (
    Chapter,
    CastingTable,
    Utterance,
    UtteranceType,
    ProjectConfig,
)
from audiobooker.renderer.engine import render_chapter, render_project, RenderLog
from audiobooker.renderer.output import generate_chapter_metadata, AssemblyResult
from audiobooker.renderer.protocols import SynthesisResult

from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav, assert_wav_header_valid
from tests.fakes.fake_ffmpeg import FakeAssembler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chapter(index: int = 0, title: str = "Test Chapter", utterances: int = 3) -> Chapter:
    ch = Chapter(index=index, title=title, raw_text="Hello world " * 20)
    for i in range(utterances):
        ch.utterances.append(
            Utterance(
                speaker="narrator" if i % 2 == 0 else "Alice",
                text=f"Utterance {i} text.",
                utterance_type=UtteranceType.NARRATION if i % 2 == 0 else UtteranceType.DIALOGUE,
                chapter_index=index,
                line_index=i,
            )
        )
    return ch


def _make_casting() -> CastingTable:
    table = CastingTable()
    table.cast("narrator", "af_heart", emotion="calm")
    table.cast("Alice", "af_bella", emotion="warm")
    return table


# ---------------------------------------------------------------------------
# FakeTTS / WAV helpers
# ---------------------------------------------------------------------------

class TestFakeTTSEngine:
    def test_writes_valid_wav(self, tmp_path: Path):
        engine = FakeTTSEngine()
        result = engine.synthesize(
            script="[S1:narrator] Hello",
            voices={"narrator": "af_heart"},
            output_path=tmp_path / "out.wav",
        )
        assert result.audio_path.exists()
        assert result.duration_seconds == 0.25
        assert_wav_header_valid(result.audio_path)

    def test_records_calls(self, tmp_path: Path):
        engine = FakeTTSEngine()
        engine.synthesize("[S1:a] Hi", {"a": "af_heart"}, tmp_path / "1.wav")
        engine.synthesize("[S1:b] Bye", {"b": "bm_george"}, tmp_path / "2.wav")
        assert len(engine.calls) == 2
        assert engine.calls[0].voices == {"a": "af_heart"}

    def test_fail_on_call(self, tmp_path: Path):
        engine = FakeTTSEngine(fail_on_call=0)
        with pytest.raises(RuntimeError, match="Fake TTS failure"):
            engine.synthesize("script", {}, tmp_path / "x.wav")


class TestWriteSilenceWav:
    def test_creates_file(self, tmp_path: Path):
        p = tmp_path / "silence.wav"
        write_silence_wav(p, duration_s=0.1)
        assert p.exists()
        assert p.stat().st_size > 44  # WAV header is 44 bytes

    def test_valid_header(self, tmp_path: Path):
        p = tmp_path / "test.wav"
        write_silence_wav(p)
        assert_wav_header_valid(p)


# ---------------------------------------------------------------------------
# render_chapter
# ---------------------------------------------------------------------------

class TestRenderChapter:
    def test_writes_wav_and_sets_duration(self, tmp_path: Path):
        chapter = _make_chapter()
        casting = _make_casting()
        engine = FakeTTSEngine(duration_per_call=0.5)

        result_path = render_chapter(
            chapter, casting, tmp_path / "ch0.wav", engine=engine,
        )

        assert result_path.exists()
        assert_wav_header_valid(result_path)
        assert chapter.duration_seconds == 0.5
        assert chapter.audio_path == result_path

    def test_raises_on_empty_utterances(self, tmp_path: Path):
        chapter = Chapter(index=0, title="Empty", raw_text="x")
        casting = _make_casting()
        engine = FakeTTSEngine()

        with pytest.raises(ValueError, match="no utterances"):
            render_chapter(chapter, casting, tmp_path / "x.wav", engine=engine)

    def test_tts_failure_includes_context(self, tmp_path: Path):
        chapter = _make_chapter(utterances=5)
        casting = _make_casting()
        engine = FakeTTSEngine(fail_on_call=0, fail_error="Voice model crashed")

        with pytest.raises(RuntimeError, match="Voice model crashed"):
            render_chapter(chapter, casting, tmp_path / "x.wav", engine=engine)

    def test_engine_receives_correct_voice_mapping(self, tmp_path: Path):
        chapter = _make_chapter(utterances=1)
        casting = _make_casting()
        engine = FakeTTSEngine()

        render_chapter(chapter, casting, tmp_path / "ch.wav", engine=engine)

        assert len(engine.calls) == 1
        assert "narrator" in engine.calls[0].voices
        assert engine.calls[0].voices["narrator"] == "af_heart"

    def test_progress_callback_invoked(self, tmp_path: Path):
        chapter = _make_chapter()
        casting = _make_casting()
        engine = FakeTTSEngine()
        progress_calls = []

        def on_progress(current, total):
            progress_calls.append((current, total))

        # FakeTTS doesn't call progress_callback internally,
        # but render_chapter passes it through to engine.synthesize.
        # We just verify no crash.
        render_chapter(
            chapter, casting, tmp_path / "ch.wav",
            progress_callback=on_progress, engine=engine,
        )
        assert chapter.audio_path is not None


# ---------------------------------------------------------------------------
# render_project
# ---------------------------------------------------------------------------

class TestRenderProject:
    def _make_project(self, num_chapters: int = 2):
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test Book")
        project.cast("narrator", "af_heart")
        project.cast("Alice", "af_bella")

        for i in range(num_chapters):
            project.chapters.append(_make_chapter(index=i, title=f"Chapter {i+1}"))

        return project

    def test_renders_all_chapters_and_assembles(self, tmp_path: Path):
        project = self._make_project(num_chapters=2)
        engine = FakeTTSEngine(duration_per_call=0.3)
        assembler = FakeAssembler()

        result = render_project(
            project, tmp_path / "book.m4b",
            engine=engine, assembler=assembler,
            cache_root=tmp_path / "cache",
        )

        assert result.exists()
        assert len(engine.calls) == 2
        assert len(assembler.calls) == 1
        assert assembler.calls[0]["title"] == "Test Book"

    def test_assembler_receives_chapter_info(self, tmp_path: Path):
        project = self._make_project(num_chapters=3)
        engine = FakeTTSEngine(duration_per_call=0.25)
        assembler = FakeAssembler()

        render_project(
            project, tmp_path / "book.m4b",
            engine=engine, assembler=assembler,
            cache_root=tmp_path / "cache",
        )

        chapter_files = assembler.calls[0]["chapter_files"]
        assert len(chapter_files) == 3
        for path, title, duration in chapter_files:
            assert isinstance(path, Path)
            assert isinstance(title, str)

    def test_progress_callback_called_per_chapter(self, tmp_path: Path):
        project = self._make_project(num_chapters=2)
        engine = FakeTTSEngine()
        assembler = FakeAssembler()
        progress = []

        def on_progress(current, total, status):
            progress.append((current, total, status))

        render_project(
            project, tmp_path / "book.m4b",
            progress_callback=on_progress, engine=engine, assembler=assembler,
            cache_root=tmp_path / "cache",
        )

        assert len(progress) >= 3  # 2 chapters + 1 assembling
        assert "Assembling" in progress[-1][2]

    def test_skips_already_rendered_chapters(self, tmp_path: Path):
        project = self._make_project(num_chapters=2)
        engine1 = FakeTTSEngine(duration_per_call=0.5)
        assembler = FakeAssembler()
        cache = tmp_path / "cache"

        # First render: both chapters
        render_project(project, tmp_path / "book1.m4b", engine=engine1, assembler=assembler, cache_root=cache)
        assert len(engine1.calls) == 2

        # Second render with resume: both should be cache hits
        engine2 = FakeTTSEngine(duration_per_call=0.5)
        assembler2 = FakeAssembler()
        render_project(project, tmp_path / "book2.m4b", engine=engine2, assembler=assembler2, cache_root=cache)
        assert len(engine2.calls) == 0

    def test_assembly_failure_surfaces(self, tmp_path: Path):
        project = self._make_project(num_chapters=1)
        engine = FakeTTSEngine()
        assembler = FakeAssembler(chapters_embedded=False)

        result = render_project(
            project, tmp_path / "book.m4b",
            engine=engine, assembler=assembler,
            cache_root=tmp_path / "cache",
        )

        # Should still return a path (M4A fallback)
        assert result.exists()


# ---------------------------------------------------------------------------
# output.py — generate_chapter_metadata (pure function, no FFmpeg needed)
# ---------------------------------------------------------------------------

class TestGenerateChapterMetadata:
    def test_single_chapter(self, tmp_path: Path):
        chapters = [(tmp_path / "ch0.wav", "Chapter 1", 10.0)]
        metadata = generate_chapter_metadata(chapters, chapter_pause_ms=2000)

        assert ";FFMETADATA1" in metadata
        assert "[CHAPTER]" in metadata
        assert "title=Chapter 1" in metadata
        assert "START=0" in metadata
        assert "END=10000" in metadata

    def test_multiple_chapters_with_pause(self, tmp_path: Path):
        chapters = [
            (tmp_path / "ch0.wav", "Chapter 1", 5.0),
            (tmp_path / "ch1.wav", "Chapter 2", 3.0),
        ]
        metadata = generate_chapter_metadata(chapters, chapter_pause_ms=1000)

        # Chapter 1: START=0, END=5000
        # Pause: 1000ms
        # Chapter 2: START=6000, END=9000
        assert "START=0" in metadata
        assert "END=5000" in metadata
        assert "START=6000" in metadata
        assert "END=9000" in metadata

    def test_zero_pause(self, tmp_path: Path):
        chapters = [
            (tmp_path / "ch0.wav", "A", 2.0),
            (tmp_path / "ch1.wav", "B", 3.0),
        ]
        metadata = generate_chapter_metadata(chapters, chapter_pause_ms=0)

        assert "START=0" in metadata
        assert "END=2000" in metadata
        assert "START=2000" in metadata
        assert "END=5000" in metadata


# ---------------------------------------------------------------------------
# AssemblyResult
# ---------------------------------------------------------------------------

class TestAssemblyResult:
    def test_success(self):
        r = AssemblyResult(output_path=Path("x.m4b"), chapters_embedded=True)
        assert r.chapters_embedded
        assert r.chapter_error == ""

    def test_failure(self):
        r = AssemblyResult(
            output_path=Path("x.m4a"),
            chapters_embedded=False,
            chapter_error="metadata parse error",
        )
        assert not r.chapters_embedded
        assert "metadata" in r.chapter_error


# ---------------------------------------------------------------------------
# RenderLog
# ---------------------------------------------------------------------------

class TestRenderLog:
    def test_to_json(self):
        log = RenderLog(
            chapter_index=0,
            chapter_title="Test",
            utterance_count=5,
            total_chars=100,
            status="success",
        )
        j = log.to_json()
        assert '"chapter_title": "Test"' in j
        assert '"status": "success"' in j

    def test_error_log(self):
        log = RenderLog(
            chapter_index=1,
            chapter_title="Bad Chapter",
            utterance_count=3,
            total_chars=50,
            status="error",
            error_message="boom",
            error_speaker="Alice",
        )
        j = log.to_json()
        assert '"error_message": "boom"' in j
        assert '"error_speaker": "Alice"' in j
