"""
Hermetic render pipeline smoke test.

Exercises the full pipeline:
  parse → compile → render_chapter → render_project → assemble

Uses FakeTTS + FakeAssembler — no voice-soundboard, no FFmpeg, no network.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from audiobooker import AudiobookProject
from audiobooker.renderer.engine import render_chapter, render_project
from tests.fakes.fake_tts import FakeTTSEngine, assert_wav_header_valid
from tests.fakes.fake_ffmpeg import FakeAssembler


GOLDEN_BOOK = Path(__file__).parent.parent / "examples" / "golden_book.txt"


@pytest.fixture
def project() -> AudiobookProject:
    """Parse and compile the golden book."""
    p = AudiobookProject.from_text(GOLDEN_BOOK)
    p.cast("narrator", "af_heart", emotion="calm")
    p.cast("Sarah", "af_bella", emotion="curious")
    p.cast("Marcus", "am_michael", emotion="serious")
    p.compile()
    return p


class TestHermeticRenderPipeline:
    """Full pipeline with no external dependencies."""

    def test_parse_compile_render_single_chapter(self, project: AudiobookProject, tmp_path: Path):
        engine = FakeTTSEngine(duration_per_call=1.5)

        chapter = project.chapters[0]
        out = tmp_path / "ch0.wav"

        result = render_chapter(chapter, project.casting, out, engine=engine)

        assert result.exists()
        assert_wav_header_valid(result)
        assert chapter.duration_seconds == 1.5
        assert chapter.audio_path == result
        assert len(engine.calls) == 1

    def test_render_all_chapters_and_assemble(self, project: AudiobookProject, tmp_path: Path):
        engine = FakeTTSEngine(duration_per_call=2.0)
        assembler = FakeAssembler()

        out = tmp_path / "book.m4b"
        result = render_project(project, out, engine=engine, assembler=assembler)

        assert result.exists()
        assert len(engine.calls) == len(project.chapters)
        assert len(assembler.calls) == 1

        # Assembler got correct metadata
        call = assembler.calls[0]
        assert call["title"] == project.title
        assert len(call["chapter_files"]) == len(project.chapters)

    def test_progress_reports_all_chapters_plus_assembly(self, project: AudiobookProject, tmp_path: Path):
        engine = FakeTTSEngine()
        assembler = FakeAssembler()
        events = []

        def on_progress(current, total, status):
            events.append((current, total, status))

        render_project(
            project, tmp_path / "book.m4b",
            progress_callback=on_progress,
            engine=engine, assembler=assembler,
        )

        # At least one event per chapter + assembly
        assert len(events) >= len(project.chapters) + 1
        assert "Assembling" in events[-1][2]

    def test_chapter_durations_recorded(self, project: AudiobookProject, tmp_path: Path):
        engine = FakeTTSEngine(duration_per_call=0.75)
        assembler = FakeAssembler()

        render_project(project, tmp_path / "book.m4b", engine=engine, assembler=assembler)

        for ch in project.chapters:
            assert ch.duration_seconds == 0.75
            assert ch.audio_path is not None

    def test_skip_already_rendered(self, project: AudiobookProject, tmp_path: Path):
        engine = FakeTTSEngine(duration_per_call=1.0)
        assembler = FakeAssembler()

        # Pre-render chapter 0
        pre = tmp_path / "pre.wav"
        render_chapter(project.chapters[0], project.casting, pre, engine=engine)

        engine2 = FakeTTSEngine(duration_per_call=2.0)
        render_project(project, tmp_path / "book.m4b", engine=engine2, assembler=assembler)

        # engine2 should only have rendered the remaining chapters
        assert len(engine2.calls) == len(project.chapters) - 1

    def test_voice_mapping_flows_through(self, project: AudiobookProject, tmp_path: Path):
        engine = FakeTTSEngine()
        assembler = FakeAssembler()

        render_project(project, tmp_path / "book.m4b", engine=engine, assembler=assembler)

        # Every TTS call should have received voice mappings
        for call in engine.calls:
            assert "narrator" in call.voices
            assert call.voices["narrator"] == "af_heart"
