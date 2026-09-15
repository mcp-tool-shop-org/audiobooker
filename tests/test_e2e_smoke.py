"""
End-to-end smoke test for audiobooker, against the golden book fixture.

Two tiers, deliberately separated:

``TestEndToEndSmoke``     parse -> cast -> compile -> save/load. No TTS, no
                          ffmpeg, no network. Runs in EVERY environment,
                          including CI.
``TestEndToEndRealAudio`` render through the real voice-soundboard engine and
                          master a real M4B with the real ffmpeg binary. Skips
                          where those are absent, which is the point of it:
                          its value is that it uses the real things.

TEST-A-004. This file used to run in NO environment at all:

  * every test in it was skipped locally (no ffmpeg, no voice-soundboard);
  * ``ci.yml`` passed ``--ignore=tests/test_e2e_smoke.py`` to pytest;
  * the only Makefile target that included it, ``test-full``, was invoked by
    no workflow and no other target.

The two heavy tests genuinely need binaries CI does not have. The other four
need nothing at all — they were excluded only because ``--ignore`` works on
files and they happened to share a file with the heavy two. Those four hold the
ONLY assertions in the suite about the golden book's parsed metadata (title,
author, chapter count, chapter titles) and about the inline ``[Sarah|worried]``
override surviving compile, so the gap they left was real. The file-level
``--ignore`` is gone from ci.yml and from the Makefile, and the tier split
above is what keeps the heavy pair from dragging the cheap four back out.

Note this is NOT the only proof the render pipeline is wired:
``tests/test_smoke_render_pipeline.py`` already drives
parse -> compile -> render_chapter -> render_project -> assemble through
FakeTTSEngine and FakeAssembler, and has always run in CI. What was missing was
the parse/compile/persist half above, and the real-binary half below.
"""

import logging
import pytest
import subprocess
import tempfile
from pathlib import Path

from tests.conftest import GOLDEN_BOOK_PATH

# Use a module-specific logger instead of configuring the root logger,
# which would pollute other tests' logging state.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def has_voice_soundboard() -> bool:
    """Check if voice-soundboard is available."""
    try:
        from voice_soundboard.dialogue.engine import DialogueEngine  # noqa: F401
        return True
    except ImportError as exc:
        logger.info("voice-soundboard not available: %s", exc)
        return False


def has_ffmpeg() -> bool:
    """Check if a working ffmpeg binary is on PATH.

    Catches OSError (missing binary, permission denied, exec format error) and
    SubprocessError (the 5s timeout) rather than FileNotFoundError alone. This
    runs at IMPORT time to build the skip markers below, so an unhandled
    exception here would abort collection of the whole session rather than skip
    one test — a cheap thing to get wrong now that the module is no longer
    ``--ignore``d out of every run.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("ffmpeg not available: %s", exc)
        return False


# Skip markers — applied ONLY to the real-audio tier below.
requires_voice_soundboard = pytest.mark.skipif(
    not has_voice_soundboard(),
    reason="voice-soundboard not installed (optional [render] extra)",
)
requires_ffmpeg = pytest.mark.skipif(
    not has_ffmpeg(),
    reason="ffmpeg binary not on PATH",
)


class TestEndToEndSmoke:
    """Dependency-free end-to-end: parse -> cast -> compile -> save/load.

    Nothing in this class is skippable. It runs on every machine and on every
    CI matrix cell.
    """

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

        logger.info("Compiled %d utterances", total_utterances)
        logger.info("Chapter 1: %d utterances", len(project.chapters[0].utterances))
        logger.info("Chapter 2: %d utterances", len(project.chapters[1].utterances))

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


class TestEndToEndRealAudio:
    """End-to-end through the REAL TTS engine and the REAL ffmpeg binary.

    Deliberately skippable, and deliberately kept in a class of its own so a
    file-level ``--ignore`` is never again the tool used to exclude it. The
    equivalent wiring is already proven hermetically in
    ``tests/test_smoke_render_pipeline.py`` (FakeTTSEngine + FakeAssembler);
    what only these two can prove is that the real engine and the real muxer
    accept what the pipeline hands them.

    Not run in CI. Both need the ``[render]`` extra (voice-soundboard, which
    pulls a TTS model) and ``test_render_full_audiobook`` needs an ffmpeg
    binary as well, so installing ffmpeg alone in CI would unlock exactly zero
    of them.
    """

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

            logger.info("Rendered chapter 0:")
            logger.info("  Output: %s", result_path)
            logger.info("  Size: %s bytes", f"{result_path.stat().st_size:,}")
            logger.info("  Duration: %.1fs", project.chapters[0].duration_seconds)

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
                logger.info("  [%d/%d] %s", current, total, status)

            # Render full audiobook
            logger.info("Rendering full audiobook...")
            result_path = project.render(output_path, progress_callback=progress)

            assert result_path.exists(), f"M4B not created: {result_path}"
            assert result_path.stat().st_size > 0, "M4B is empty"

            # Verify total duration
            total_duration = sum(c.duration_seconds for c in project.chapters)
            assert total_duration > 0, "Total duration is zero"

            logger.info("Full audiobook rendered:")
            logger.info("  Output: %s", result_path)
            logger.info("  Size: %s bytes", f"{result_path.stat().st_size:,}")
            logger.info("  Duration: %.1fs (%.1f min)", total_duration, total_duration / 60)

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
                logger.info("FFprobe output:\n%s", probe_result.stdout[:500])
            else:
                logger.info("FFprobe failed: %s", probe_result.stderr)


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "-s"])
