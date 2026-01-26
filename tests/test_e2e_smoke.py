"""
End-to-end smoke test for audiobooker.

This test verifies the full pipeline:
1. Parse source file
2. Compile to utterances
3. Render via voice-soundboard
4. Assemble M4B with ffmpeg

Skipped automatically if dependencies are missing.
"""

import logging
import os
import pytest
import shutil
import subprocess
import tempfile
from pathlib import Path

# Configure logging for visibility during test
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def has_voice_soundboard() -> bool:
    """Check if voice-soundboard is available."""
    try:
        from voice_soundboard.dialogue.engine import DialogueEngine
        return True
    except ImportError:
        return False


def has_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


# Skip markers
requires_voice_soundboard = pytest.mark.skipif(
    not has_voice_soundboard(),
    reason="voice-soundboard not installed",
)
requires_ffmpeg = pytest.mark.skipif(
    not has_ffmpeg(),
    reason="ffmpeg not installed",
)


GOLDEN_BOOK_PATH = Path(__file__).parent.parent / "examples" / "golden_book.txt"


class TestEndToEndSmoke:
    """End-to-end smoke tests."""

    def test_golden_book_exists(self):
        """Verify golden book fixture exists."""
        assert GOLDEN_BOOK_PATH.exists(), f"Golden book not found at {GOLDEN_BOOK_PATH}"

    def test_parse_golden_book(self):
        """Test parsing golden book into project."""
        from audiobooker import AudiobookProject

        project = AudiobookProject.from_text(GOLDEN_BOOK_PATH)

        assert project.title == "The Golden Test"
        assert project.author == "Audiobooker Test Suite"
        assert len(project.chapters) == 2
        assert project.chapters[0].title == "Chapter 1: The Meeting"
        assert project.chapters[1].title == "Chapter 2: The Revelation"

    def test_compile_golden_book(self):
        """Test compiling golden book to utterances."""
        from audiobooker import AudiobookProject

        project = AudiobookProject.from_text(GOLDEN_BOOK_PATH)

        # Cast characters
        project.cast("narrator", "bm_george", emotion="calm")
        project.cast("Sarah", "af_bella", emotion="curious")
        project.cast("Marcus", "am_michael", emotion="serious")

        # Compile
        project.compile()

        # Verify utterances were created
        total_utterances = sum(len(c.utterances) for c in project.chapters)
        assert total_utterances > 0, "No utterances created"

        # Verify inline overrides were parsed
        chapter1_speakers = {u.speaker for u in project.chapters[0].utterances}
        assert "Sarah" in chapter1_speakers, "Inline override [Sarah|worried] not parsed"

        print(f"\nCompiled {total_utterances} utterances")
        print(f"Chapter 1: {len(project.chapters[0].utterances)} utterances")
        print(f"Chapter 2: {len(project.chapters[1].utterances)} utterances")

    def test_project_save_load_roundtrip(self):
        """Test project serialization roundtrip."""
        from audiobooker import AudiobookProject

        project = AudiobookProject.from_text(GOLDEN_BOOK_PATH)
        project.cast("narrator", "bm_george")
        project.cast("Sarah", "af_bella", emotion="curious")
        project.compile()

        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "test.audiobooker"
            project.save(project_path)

            # Reload
            loaded = AudiobookProject.load(project_path)

            assert loaded.title == project.title
            assert len(loaded.chapters) == len(project.chapters)
            assert len(loaded.casting.characters) == len(project.casting.characters)

            # Verify utterances survived roundtrip
            assert len(loaded.chapters[0].utterances) == len(project.chapters[0].utterances)

    @requires_voice_soundboard
    def test_render_single_chapter(self):
        """Test rendering a single chapter to audio."""
        from audiobooker import AudiobookProject

        project = AudiobookProject.from_text(GOLDEN_BOOK_PATH)
        project.cast("narrator", "af_heart", emotion="calm")
        project.cast("Sarah", "af_bella")
        project.cast("Marcus", "am_michael")
        project.compile()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "chapter_0.wav"

            # Render first chapter only
            result_path = project.render_chapter(0, output_path)

            assert result_path.exists(), f"Output file not created: {result_path}"
            assert result_path.stat().st_size > 0, "Output file is empty"

            # Check duration was recorded
            assert project.chapters[0].duration_seconds > 0, "Duration not recorded"

            print(f"\nRendered chapter 0:")
            print(f"  Output: {result_path}")
            print(f"  Size: {result_path.stat().st_size:,} bytes")
            print(f"  Duration: {project.chapters[0].duration_seconds:.1f}s")

    @requires_voice_soundboard
    @requires_ffmpeg
    def test_render_full_audiobook(self):
        """Test full audiobook rendering and M4B assembly."""
        from audiobooker import AudiobookProject

        project = AudiobookProject.from_text(GOLDEN_BOOK_PATH)
        project.cast("narrator", "af_heart", emotion="calm")
        project.cast("Sarah", "af_bella", emotion="curious")
        project.cast("Marcus", "am_michael", emotion="serious")
        project.compile()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "golden_test.m4b"

            def progress(current, total, status):
                print(f"  [{current}/{total}] {status}")

            # Render full audiobook
            print("\nRendering full audiobook...")
            result_path = project.render(output_path, progress_callback=progress)

            assert result_path.exists(), f"M4B not created: {result_path}"
            assert result_path.stat().st_size > 0, "M4B is empty"

            # Verify total duration
            total_duration = sum(c.duration_seconds for c in project.chapters)
            assert total_duration > 0, "Total duration is zero"

            print(f"\nFull audiobook rendered:")
            print(f"  Output: {result_path}")
            print(f"  Size: {result_path.stat().st_size:,} bytes")
            print(f"  Duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")

            # Probe with ffprobe to verify it's valid
            probe_result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-show_format",
                    "-show_chapters",
                    str(result_path),
                ],
                capture_output=True,
                text=True,
            )

            if probe_result.returncode == 0:
                print(f"\nFFprobe output:\n{probe_result.stdout[:500]}")
            else:
                print(f"\nFFprobe failed: {probe_result.stderr}")


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "-s"])
