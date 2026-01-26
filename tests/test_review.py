"""Tests for review file export/import."""

import pytest
from pathlib import Path

from audiobooker.models import Chapter, Utterance, UtteranceType, CastingTable
from audiobooker.review import (
    export_for_review,
    import_reviewed,
    preview_review_format,
    SPEAKER_PATTERN,
    CHAPTER_PATTERN,
)


class TestReviewPatterns:
    """Tests for regex patterns."""

    def test_speaker_pattern_simple(self):
        """Test simple speaker tag."""
        match = SPEAKER_PATTERN.match("@narrator")
        assert match is not None
        assert match.group(1) == "narrator"
        assert match.group(2) is None

    def test_speaker_pattern_with_emotion(self):
        """Test speaker tag with emotion."""
        match = SPEAKER_PATTERN.match("@Alice (nervous)")
        assert match is not None
        assert match.group(1) == "Alice"
        assert match.group(2) == "nervous"

    def test_speaker_pattern_complex_emotion(self):
        """Test speaker with multi-word emotion."""
        match = SPEAKER_PATTERN.match("@Bob (slightly angry)")
        assert match is not None
        assert match.group(1) == "Bob"
        assert match.group(2) == "slightly angry"

    def test_chapter_pattern(self):
        """Test chapter marker."""
        match = CHAPTER_PATTERN.match("=== Chapter 1: The Beginning ===")
        assert match is not None
        assert match.group(1) == "Chapter 1: The Beginning"

    def test_chapter_pattern_simple(self):
        """Test simple chapter marker."""
        match = CHAPTER_PATTERN.match("=== Introduction ===")
        assert match is not None
        assert match.group(1) == "Introduction"


class TestExportForReview:
    """Tests for export_for_review function."""

    def test_export_basic(self, tmp_path):
        """Test basic export."""
        from audiobooker.project import AudiobookProject

        # Create minimal project
        project = AudiobookProject(title="Test Book", author="Test Author")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="Test",
                utterances=[
                    Utterance(speaker="narrator", text="The door opened."),
                    Utterance(speaker="Alice", text="Hello?", emotion="nervous"),
                ],
            )
        ]

        output_path = tmp_path / "review.txt"
        result = export_for_review(project, output_path)

        assert result.exists()
        content = result.read_text()

        # Check header
        assert "# Audiobooker Review File" in content
        assert "# Title: Test Book" in content
        assert "# Author: Test Author" in content

        # Check chapter
        assert "=== Chapter 1 ===" in content

        # Check utterances
        assert "@narrator" in content
        assert "The door opened." in content
        assert "@Alice (nervous)" in content
        assert "Hello?" in content

    def test_export_default_path(self, tmp_path, monkeypatch):
        """Test export with default path."""
        from audiobooker.project import AudiobookProject

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        project = AudiobookProject(title="My Book", author="Author")
        project.chapters = [
            Chapter(
                index=0,
                title="Ch1",
                raw_text="Test",
                utterances=[Utterance(speaker="narrator", text="Text.")],
            )
        ]

        result = export_for_review(project)

        assert result.name == "My Book_review.txt"
        assert result.exists()

    def test_export_preserves_speaker_continuity(self, tmp_path):
        """Test that consecutive utterances from same speaker are grouped."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Test",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Line one."),
                    Utterance(speaker="narrator", text="Line two."),
                    Utterance(speaker="Alice", text="Hello"),
                    Utterance(speaker="narrator", text="She said."),
                ],
            )
        ]

        output = tmp_path / "test.txt"
        export_for_review(project, output)
        content = output.read_text()

        # Count @narrator occurrences - should be 2 (not 3)
        narrator_tags = content.count("@narrator\n")
        assert narrator_tags == 2


class TestImportReviewed:
    """Tests for import_reviewed function."""

    def test_import_basic(self, tmp_path):
        """Test basic import."""
        from audiobooker.project import AudiobookProject

        # Create project with chapter
        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(index=0, title="Chapter 1", raw_text="Original text")
        ]

        # Create review file
        review_content = """# Audiobooker Review File
# Title: Test

=== Chapter 1 ===

@narrator
The story begins.

@Alice (happy)
Hello world!
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content)

        # Import
        stats = import_reviewed(project, review_path)

        assert stats["chapters_updated"] == 1
        assert stats["utterances_imported"] == 2
        assert "narrator" in stats["speakers_found"]
        assert "Alice" in stats["speakers_found"]

        # Check chapter was updated
        chapter = project.chapters[0]
        assert len(chapter.utterances) == 2
        assert chapter.utterances[0].speaker == "narrator"
        assert chapter.utterances[0].text == "The story begins."
        assert chapter.utterances[1].speaker == "Alice"
        assert chapter.utterances[1].emotion == "happy"

    def test_import_speaker_change(self, tmp_path):
        """Test that speaker name changes are imported."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="Unknown", text="Hello"),
                ],
            )
        ]

        # Review file with corrected speaker
        review_content = """=== Chapter 1 ===

@Marcus
Hello
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content)

        import_reviewed(project, review_path)

        # Speaker should be changed
        assert project.chapters[0].utterances[0].speaker == "Marcus"

    def test_import_emotion_added(self, tmp_path):
        """Test that added emotions are imported."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Text", emotion=None),
                ],
            )
        ]

        # Review file with emotion added
        review_content = """=== Chapter 1 ===

@narrator (somber)
Text
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content)

        import_reviewed(project, review_path)

        # Emotion should be added
        assert project.chapters[0].utterances[0].emotion == "somber"

    def test_import_utterance_deleted(self, tmp_path):
        """Test that deleted utterances are removed."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Keep this."),
                    Utterance(speaker="narrator", text="Delete this."),
                    Utterance(speaker="narrator", text="Also keep."),
                ],
            )
        ]

        # Review file with middle utterance removed
        review_content = """=== Chapter 1 ===

@narrator
Keep this.
Also keep.
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content)

        import_reviewed(project, review_path)

        # Should have 1 utterance with merged text
        assert len(project.chapters[0].utterances) == 1
        assert "Keep this." in project.chapters[0].utterances[0].text
        assert "Also keep." in project.chapters[0].utterances[0].text

    def test_import_skips_comments(self, tmp_path):
        """Test that comment lines are ignored."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """# This is a comment
=== Chapter 1 ===

# Another comment
@narrator
Text here.
# Inline comment - this will be ignored
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content)

        stats = import_reviewed(project, review_path)

        assert stats["utterances_imported"] == 1
        assert project.chapters[0].utterances[0].text == "Text here."


class TestRoundtrip:
    """Tests for full export -> edit -> import cycle."""

    def test_roundtrip_preserves_content(self, tmp_path):
        """Test that export -> import preserves content."""
        from audiobooker.project import AudiobookProject

        # Create project
        project = AudiobookProject(title="Test Book", author="Author")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="The sun rose."),
                    Utterance(speaker="Alice", text="Good morning!", emotion="cheerful"),
                    Utterance(speaker="Bob", text="Hello there."),
                ],
            ),
            Chapter(
                index=1,
                title="Chapter 2",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Later that day."),
                ],
            ),
        ]

        # Export
        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        # Create new project and import
        project2 = AudiobookProject(title="Test Book", author="Author")
        project2.chapters = [
            Chapter(index=0, title="Chapter 1", raw_text=""),
            Chapter(index=1, title="Chapter 2", raw_text=""),
        ]

        stats = import_reviewed(project2, review_path)

        # Verify
        assert stats["chapters_updated"] == 2
        assert len(project2.chapters[0].utterances) == 3
        assert len(project2.chapters[1].utterances) == 1

        # Check content preserved
        assert project2.chapters[0].utterances[0].speaker == "narrator"
        assert project2.chapters[0].utterances[1].speaker == "Alice"
        assert project2.chapters[0].utterances[1].emotion == "cheerful"
        assert project2.chapters[0].utterances[2].speaker == "Bob"

    def test_roundtrip_with_edits(self, tmp_path):
        """Test roundtrip with modifications."""
        from audiobooker.project import AudiobookProject

        # Create and export
        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Scene 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Opening."),
                    Utterance(speaker="Unknown", text="Who am I?"),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        # Edit the review file
        content = review_path.read_text()
        content = content.replace("@Unknown", "@Marcus (confused)")
        review_path.write_text(content)

        # Import
        import_reviewed(project, review_path)

        # Verify edit was applied
        assert project.chapters[0].utterances[1].speaker == "Marcus"
        assert project.chapters[0].utterances[1].emotion == "confused"


class TestPreviewReviewFormat:
    """Tests for preview_review_format function."""

    def test_preview_chapter(self):
        """Test previewing a chapter."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Preview Chapter",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Line 1."),
                    Utterance(speaker="Alice", text="Line 2.", emotion="sad"),
                ],
            )
        ]

        preview = preview_review_format(project, 0)

        assert "=== Preview Chapter ===" in preview
        assert "@narrator" in preview
        assert "Line 1." in preview
        assert "@Alice (sad)" in preview
        assert "Line 2." in preview

    def test_preview_uncompiled_chapter(self):
        """Test previewing uncompiled chapter."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(index=0, title="Empty", raw_text="Some text")
        ]

        preview = preview_review_format(project, 0)

        assert "=== Empty ===" in preview
        assert "# (Not compiled)" in preview

    def test_preview_out_of_range(self):
        """Test previewing non-existent chapter."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = []

        preview = preview_review_format(project, 5)

        assert "# Chapter not found" in preview
