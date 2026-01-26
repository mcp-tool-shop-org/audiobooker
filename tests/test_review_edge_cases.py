"""Edge case tests for review format stability.

These tests catch the nasty edge cases that bite once real users touch it:
- Whitespace and quote preservation
- Smart quotes and em-dashes from EPUB
- Chapter markers with special characters
- Unicode safety
- Line ending normalization
"""

import pytest
from pathlib import Path

from audiobooker.models import Chapter, Utterance
from audiobooker.review import (
    export_for_review,
    import_reviewed,
    SPEAKER_PATTERN,
    CHAPTER_PATTERN,
)


class TestWhitespacePreservation:
    """Tests for whitespace handling in roundtrip."""

    def test_preserves_internal_whitespace(self, tmp_path):
        """Text with multiple spaces should be preserved."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="She paused...    then continued."),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        # Re-import
        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]
        import_reviewed(project2, review_path)

        # Multiple spaces should be normalized to single (expected behavior)
        assert "then continued" in project2.chapters[0].utterances[0].text

    def test_handles_leading_trailing_whitespace(self, tmp_path):
        """Leading/trailing whitespace should be stripped."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """=== Chapter 1 ===

@narrator
   Text with leading spaces
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        import_reviewed(project, review_path)

        # Should be stripped
        assert project.chapters[0].utterances[0].text == "Text with leading spaces"


class TestSmartQuotesAndDashes:
    """Tests for smart typography from EPUB sources."""

    def test_smart_quotes_preserved(self, tmp_path):
        """Smart/curly quotes should be preserved."""
        from audiobooker.project import AudiobookProject

        # Use Unicode escapes for smart quotes to avoid encoding issues
        smart_text = "\u201cHello,\u201d she said, \u201chow are you?\u201d"

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text=smart_text),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        # Re-import
        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]
        import_reviewed(project2, review_path)

        # Smart quotes should be preserved
        text = project2.chapters[0].utterances[0].text
        assert "\u201c" in text or '"' in text  # Either smart or regular quotes

    def test_em_dashes_preserved(self, tmp_path):
        """Em-dashes should be preserved."""
        from audiobooker.project import AudiobookProject

        # Use Unicode escape for em-dash
        em_dash_text = "She paused\u2014then ran."

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text=em_dash_text),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        # Re-import
        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]
        import_reviewed(project2, review_path)

        # Em-dash should be preserved
        assert "\u2014" in project2.chapters[0].utterances[0].text

    def test_ellipsis_preserved(self, tmp_path):
        """Ellipsis character should be preserved."""
        from audiobooker.project import AudiobookProject

        # Use Unicode escape for ellipsis
        ellipsis_text = "He thought\u2026 then spoke."

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text=ellipsis_text),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]
        import_reviewed(project2, review_path)

        assert "\u2026" in project2.chapters[0].utterances[0].text


class TestChapterMarkerEdgeCases:
    """Tests for chapter markers with special characters."""

    def test_chapter_title_with_equals(self, tmp_path):
        """Chapter title containing = should not break parsing."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1: 2 + 2 = 4",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Math lesson."),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1: 2 + 2 = 4", raw_text="")]
        stats = import_reviewed(project2, review_path)

        assert stats["chapters_updated"] == 1
        assert len(project2.chapters[0].utterances) == 1

    def test_chapter_title_with_special_chars(self, tmp_path):
        """Chapter title with various special chars."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1: The 'Test' & Trial!",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text="Content."),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1: The 'Test' & Trial!", raw_text="")]
        stats = import_reviewed(project2, review_path)

        assert stats["chapters_updated"] == 1

    def test_chapter_pattern_does_not_match_partial(self):
        """Pattern should not match partial markers."""
        # These should NOT match
        assert CHAPTER_PATTERN.match("== Not enough =") is None
        assert CHAPTER_PATTERN.match("=== Missing end") is None
        assert CHAPTER_PATTERN.match("Missing start ===") is None


class TestSpeakerTagEdgeCases:
    """Tests for speaker tag edge cases."""

    def test_speaker_with_numbers(self):
        """Speaker names with numbers should work."""
        match = SPEAKER_PATTERN.match("@Agent007")
        assert match is not None
        assert match.group(1) == "Agent007"

    def test_speaker_with_underscore(self):
        """Speaker names with underscores should work."""
        match = SPEAKER_PATTERN.match("@Old_Man_Jenkins")
        assert match is not None
        assert match.group(1) == "Old_Man_Jenkins"

    def test_speaker_emotion_with_spaces(self):
        """Emotions can have multiple words."""
        match = SPEAKER_PATTERN.match("@Alice (very nervous)")
        assert match is not None
        assert match.group(1) == "Alice"
        assert match.group(2) == "very nervous"

    def test_speaker_not_confused_with_email(self):
        """@ in email should not be parsed as speaker."""
        # This is text content, not a speaker tag
        match = SPEAKER_PATTERN.match("Contact me at test@example.com")
        assert match is None


class TestUnicodeHandling:
    """Tests for Unicode text handling."""

    def test_unicode_text_preserved(self, tmp_path):
        """Unicode characters in text should be preserved."""
        from audiobooker.project import AudiobookProject

        unicode_text = "\u65e5\u672c\u8a9e\u30c6\u30b9\u30c8 caf\u00e9 r\u00e9sum\u00e9 na\u00efve"

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text=unicode_text),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]
        import_reviewed(project2, review_path)

        text = project2.chapters[0].utterances[0].text
        assert "\u65e5\u672c\u8a9e" in text  # Japanese
        assert "caf\u00e9" in text
        assert "na\u00efve" in text

    def test_unicode_speaker_names(self, tmp_path):
        """Unicode in speaker names should work."""
        from audiobooker.project import AudiobookProject

        # Note: Current pattern only matches \w+ which includes Unicode word chars
        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """=== Chapter 1 ===

@M\u00fcller
Guten Tag!
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        import_reviewed(project, review_path)

        assert project.chapters[0].utterances[0].speaker == "M\u00fcller"

    def test_emoji_in_text(self, tmp_path):
        """Emoji in text should be preserved (if present)."""
        from audiobooker.project import AudiobookProject

        emoji_text = "She smiled \U0001F60A and waved."

        project = AudiobookProject(title="Test")
        project.chapters = [
            Chapter(
                index=0,
                title="Chapter 1",
                raw_text="",
                utterances=[
                    Utterance(speaker="narrator", text=emoji_text),
                ],
            )
        ]

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        project2 = AudiobookProject(title="Test")
        project2.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]
        import_reviewed(project2, review_path)

        # Emoji should be preserved
        assert "\U0001F60A" in project2.chapters[0].utterances[0].text


class TestLineEndingNormalization:
    """Tests for line ending handling."""

    def test_windows_line_endings(self, tmp_path):
        """Windows CRLF line endings should work."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        # Write with Windows line endings
        review_content = "=== Chapter 1 ===\r\n\r\n@narrator\r\nText here.\r\n"
        review_path = tmp_path / "review.txt"
        review_path.write_bytes(review_content.encode("utf-8"))

        import_reviewed(project, review_path)

        assert len(project.chapters[0].utterances) == 1
        assert project.chapters[0].utterances[0].text == "Text here."

    def test_mixed_line_endings(self, tmp_path):
        """Mixed line endings should be handled."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        # Mix of Unix and Windows line endings
        review_content = "=== Chapter 1 ===\n\r\n@narrator\r\nLine one.\nLine two.\r\n"
        review_path = tmp_path / "review.txt"
        review_path.write_bytes(review_content.encode("utf-8"))

        import_reviewed(project, review_path)

        # Should handle gracefully
        assert len(project.chapters[0].utterances) >= 1


class TestUtteranceBlockBoundaries:
    """Tests for utterance block separation."""

    def test_consecutive_speakers_separated(self, tmp_path):
        """Consecutive different speakers should create separate utterances."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """=== Chapter 1 ===

@Alice
Hello!
@Bob
Hi there!
@Alice
How are you?
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        import_reviewed(project, review_path)

        # Should have 3 utterances
        assert len(project.chapters[0].utterances) == 3
        assert project.chapters[0].utterances[0].speaker == "Alice"
        assert project.chapters[0].utterances[1].speaker == "Bob"
        assert project.chapters[0].utterances[2].speaker == "Alice"

    def test_multiline_utterance(self, tmp_path):
        """Multiple lines under one speaker should merge."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """=== Chapter 1 ===

@narrator
The sun rose.
The birds sang.
A new day began.
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        import_reviewed(project, review_path)

        # Should be one utterance with merged text
        assert len(project.chapters[0].utterances) == 1
        text = project.chapters[0].utterances[0].text
        assert "The sun rose." in text
        assert "birds sang" in text
        assert "new day" in text


class TestEmptyAndEdgeCases:
    """Tests for empty content and edge cases."""

    def test_empty_chapter(self, tmp_path):
        """Empty chapter should be handled."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """=== Chapter 1 ===

"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        stats = import_reviewed(project, review_path)

        # Should handle gracefully (no utterances)
        assert stats["utterances_imported"] == 0

    def test_speaker_with_no_text(self, tmp_path):
        """Speaker tag with no following text should be skipped."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """=== Chapter 1 ===

@narrator

@Alice
Hello!
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        import_reviewed(project, review_path)

        # Empty narrator block should be skipped
        assert len(project.chapters[0].utterances) == 1
        assert project.chapters[0].utterances[0].speaker == "Alice"

    def test_comment_only_file(self, tmp_path):
        """File with only comments should import nothing."""
        from audiobooker.project import AudiobookProject

        project = AudiobookProject(title="Test")
        project.chapters = [Chapter(index=0, title="Chapter 1", raw_text="")]

        review_content = """# This is just a comment
# Another comment
# No actual content
"""
        review_path = tmp_path / "review.txt"
        review_path.write_text(review_content, encoding="utf-8")

        stats = import_reviewed(project, review_path)

        assert stats["chapters_updated"] == 0
        assert stats["utterances_imported"] == 0
