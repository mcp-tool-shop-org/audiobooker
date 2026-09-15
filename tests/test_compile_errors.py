"""
FT-TEST-008: Compile error handling test.

Verifies that compilation handles per-chapter failures gracefully:
- Other chapters still compile successfully
- Progress status is set to 'error'
- Project remains usable after partial compilation failure
"""

from unittest.mock import patch

import pytest

from audiobooker.project import AudiobookProject


class TestCompileErrorHandling:
    """Tests for graceful compilation failure handling."""

    def test_partial_failure_compiles_good_chapters(self):
        """Good chapters compile even when one chapter fails."""
        project = AudiobookProject.from_string(
            "Chapter 1: Good\n\nThe sun was shining brightly.\n\n"
            "Chapter 2: Also Good\n\n\"Hello!\" said Alice.\n\n"
            "Chapter 3: Fine\n\nEverything was peaceful.",
            title="Partial Failure Test",
        )
        project.cast("narrator", "af_heart")

        # Monkey-patch compile_chapter to fail on chapter index 1
        original_compile = None
        import audiobooker.casting.dialogue as dialogue_mod
        original_compile = dialogue_mod.compile_chapter

        def failing_compile(chapter, casting, **kwargs):
            if chapter.index == 1:
                raise RuntimeError("Simulated NLP crash on chapter 1")
            return original_compile(chapter, casting, **kwargs)

        with patch.object(dialogue_mod, "compile_chapter", side_effect=failing_compile):
            project.compile()

        # Chapter 0 and 2 should have utterances
        assert len(project.chapters[0].utterances) > 0, "Chapter 0 should be compiled"
        assert len(project.chapters[2].utterances) > 0, "Chapter 2 should be compiled"

        # Chapter 1 should have no utterances (compilation failed)
        assert len(project.chapters[1].utterances) == 0, "Chapter 1 should have failed"

    def test_error_message_set_on_failure(self):
        """Error message is set when any chapter fails compilation.

        Note: The compile method sets status to 'error' during failure
        handling but then resets to 'idle' after post-processing (NLP,
        emotion inference). The error_message persists as the record
        of what went wrong.
        """
        project = AudiobookProject.from_string(
            "Chapter 1: Good\n\nSome text here.\n\n"
            "Chapter 2: Bad\n\nMore text here.",
            title="Status Error Test",
        )
        project.cast("narrator", "af_heart")

        import audiobooker.casting.dialogue as dialogue_mod
        original_compile = dialogue_mod.compile_chapter

        def failing_compile(chapter, casting, **kwargs):
            if chapter.index == 1:
                raise ValueError("Bad chapter data")
            return original_compile(chapter, casting, **kwargs)

        with patch.object(dialogue_mod, "compile_chapter", side_effect=failing_compile):
            project.compile()

        assert project.progress.error_message is not None
        assert "failed to compile" in project.progress.error_message.lower()

    def test_error_message_contains_chapter_info(self):
        """Error message includes which chapter(s) failed."""
        project = AudiobookProject.from_string(
            "Chapter 1: First\n\nFirst content.\n\n"
            "Chapter 2: Second\n\nSecond content.",
            title="Error Info Test",
        )
        project.cast("narrator", "af_heart")

        import audiobooker.casting.dialogue as dialogue_mod
        original_compile = dialogue_mod.compile_chapter

        def failing_compile(chapter, casting, **kwargs):
            if chapter.index == 0:
                raise RuntimeError("specific error for chapter 0")
            return original_compile(chapter, casting, **kwargs)

        with patch.object(dialogue_mod, "compile_chapter", side_effect=failing_compile):
            project.compile()

        assert "specific error for chapter 0" in project.progress.error_message

    def test_project_usable_after_partial_failure(self, tmp_path):
        """Project can be saved/loaded after partial compilation failure."""
        project = AudiobookProject.from_string(
            "Chapter 1: Good\n\nNarrator speaks here.\n\n"
            "Chapter 2: Bad\n\nMore text.",
            title="Usable After Failure",
        )
        project.cast("narrator", "af_heart")

        import audiobooker.casting.dialogue as dialogue_mod
        original_compile = dialogue_mod.compile_chapter

        def failing_compile(chapter, casting, **kwargs):
            if chapter.index == 1:
                raise RuntimeError("boom")
            return original_compile(chapter, casting, **kwargs)

        with patch.object(dialogue_mod, "compile_chapter", side_effect=failing_compile):
            project.compile()

        # Save and reload
        save_path = tmp_path / "partial.audiobooker"
        project.save(save_path)
        loaded = AudiobookProject.load(save_path)

        # Loaded project should preserve the successfully compiled chapter
        assert len(loaded.chapters[0].utterances) > 0
        assert loaded.title == "Usable After Failure"

    def test_all_chapters_fail(self):
        """When ALL chapters fail, compile() raises (CH-B-002).

        Amended in wave 5. This test used to call ``project.compile()`` bare
        and assert only that ``progress.error_message`` had been populated —
        i.e. it pinned the defect: a book that produced zero utterances
        returned from compile() exactly as a clean book does, and no caller
        checked error_message (cmd_compile still doesn't), so the run printed
        "Compiled 0 utterances" and exited 0. Every other assertion the test
        made is kept below; the call is now wrapped in pytest.raises.
        """
        project = AudiobookProject.from_string(
            "Chapter 1: Bad\n\nSome text.\n\n"
            "Chapter 2: Also Bad\n\nMore text.",
            title="All Fail Test",
        )
        project.cast("narrator", "af_heart")

        import audiobooker.casting.dialogue as dialogue_mod
        from audiobooker.project import CompilationFailedError

        def always_failing(chapter, casting, **kwargs):
            raise RuntimeError(f"Crash on chapter {chapter.index}")

        with patch.object(dialogue_mod, "compile_chapter", side_effect=always_failing):
            with pytest.raises(CompilationFailedError) as exc:
                project.compile()

        assert exc.value.code == "COMPILE_ALL_CHAPTERS_FAILED"
        assert project.progress.error_message is not None
        assert "2 chapter(s) failed" in project.progress.error_message
        for ch in project.chapters:
            assert len(ch.utterances) == 0

    def test_excluded_chapters_not_compiled(self):
        """Excluded (skip=True) chapters are skipped during compilation."""
        project = AudiobookProject.from_string(
            "Chapter 1: Keep\n\nGood content here.\n\n"
            "Chapter 2: Skip\n\nThis should be skipped.\n\n"
            "Chapter 3: Keep\n\nMore good content.",
            title="Exclude Test",
        )
        project.cast("narrator", "af_heart")

        # Exclude chapter 1 (index 1)
        project.exclude_chapter(1)
        project.compile()

        assert len(project.chapters[0].utterances) > 0
        assert len(project.chapters[1].utterances) == 0  # excluded
        assert len(project.chapters[2].utterances) > 0

    def test_progress_callback_called(self):
        """Progress callback is invoked for each chapter."""
        project = AudiobookProject.from_string(
            "Chapter 1: First\n\nContent one.\n\n"
            "Chapter 2: Second\n\nContent two.",
            title="Callback Test",
        )
        project.cast("narrator", "af_heart")

        calls = []

        def callback(current, total, title):
            calls.append((current, total, title))

        project.compile(progress_callback=callback)

        assert len(calls) == len(project.chapters)
        # First call should be (1, N, title)
        assert calls[0][0] == 1
        assert calls[0][1] == len(project.chapters)
