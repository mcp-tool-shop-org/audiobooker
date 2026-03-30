"""Tests for text parsers."""

import pytest

from audiobooker.parser.text import (
    parse_text,
    split_into_chapters,
    detect_chapter_pattern,
    extract_frontmatter,
)
from audiobooker.parser.epub import html_to_text, extract_title_from_html


class TestHtmlToText:
    """Tests for HTML to text conversion."""

    def test_simple_paragraph(self):
        """Test converting simple HTML."""
        html = "<p>Hello world.</p>"
        text = html_to_text(html)
        assert "Hello world." in text

    def test_multiple_paragraphs(self):
        """Test converting multiple paragraphs."""
        html = "<p>First paragraph.</p><p>Second paragraph.</p>"
        text = html_to_text(html)
        assert "First paragraph." in text
        assert "Second paragraph." in text

    def test_strips_scripts(self):
        """Test that scripts are stripped."""
        html = "<p>Text</p><script>alert('bad')</script><p>More text</p>"
        text = html_to_text(html)
        assert "alert" not in text
        assert "Text" in text
        assert "More text" in text

    def test_strips_styles(self):
        """Test that style tags are stripped."""
        html = "<p>Text</p><style>body { color: red; }</style>"
        text = html_to_text(html)
        assert "color" not in text
        assert "Text" in text


class TestExtractTitle:
    """Tests for title extraction from HTML."""

    def test_h1_title(self):
        """Test extracting H1 title."""
        html = "<h1>Chapter One: The Beginning</h1><p>Content...</p>"
        title = extract_title_from_html(html)
        assert title == "Chapter One: The Beginning"

    def test_h2_title(self):
        """Test extracting H2 title."""
        html = "<h2>Part Two</h2><p>Content...</p>"
        title = extract_title_from_html(html)
        assert title == "Part Two"

    def test_no_title(self):
        """Test when no title found."""
        html = "<p>Just some content without heading.</p>"
        title = extract_title_from_html(html)
        assert title is None


class TestExtractFrontmatter:
    """Tests for YAML frontmatter extraction."""

    def test_with_frontmatter(self):
        """Test extracting YAML frontmatter."""
        text = """---
title: My Book
author: John Doe
---

Chapter 1

The story begins..."""

        metadata, remaining = extract_frontmatter(text)

        assert metadata["title"] == "My Book"
        assert metadata["author"] == "John Doe"
        assert "Chapter 1" in remaining
        assert "---" not in remaining

    def test_without_frontmatter(self):
        """Test text without frontmatter."""
        text = "Just regular text without metadata."
        metadata, remaining = extract_frontmatter(text)

        assert metadata == {}
        assert remaining == text


class TestDetectChapterPattern:
    """Tests for chapter pattern detection."""

    def test_chapter_number_pattern(self):
        """Test detecting 'Chapter N' pattern."""
        text = """
Chapter 1

Some content.

Chapter 2

More content.

Chapter 3
"""
        pattern = detect_chapter_pattern(text)
        assert pattern is not None
        # Pattern should match "Chapter N" format
        assert pattern.search("Chapter 1") is not None
        assert pattern.search("Chapter 2") is not None

    def test_markdown_h1_pattern(self):
        """Test detecting markdown H1 pattern."""
        text = """
# Introduction

Content here.

# Chapter One

More content.

# Chapter Two
"""
        pattern = detect_chapter_pattern(text)
        assert pattern is not None
        # Pattern should match markdown H1 headings
        assert pattern.search("# Introduction") is not None

    def test_no_pattern(self):
        """Test when no chapter pattern found."""
        text = "Just a simple paragraph without any chapters."
        pattern = detect_chapter_pattern(text)
        assert pattern is None


class TestSplitIntoChapters:
    """Tests for chapter splitting."""

    def test_chapter_split(self):
        """Test splitting by Chapter N pattern."""
        text = """Chapter 1

First chapter content.

Chapter 2

Second chapter content."""

        chapters = split_into_chapters(text)

        assert len(chapters) == 2
        assert "First chapter content" in chapters[0][1]
        assert "Second chapter content" in chapters[1][1]

    def test_no_chapters(self):
        """Test text without chapters becomes single chapter."""
        text = "Just some text without chapter markers."
        chapters = split_into_chapters(text)

        assert len(chapters) == 1
        assert chapters[0][0] == "Chapter 1"
        assert "Just some text" in chapters[0][1]


class TestParseText:
    """Tests for full text parsing."""

    def test_parse_simple_text(self, tmp_path):
        """Test parsing a simple text file."""
        content = """---
title: Test Book
author: Test Author
---

Chapter 1

This is the first chapter.

Chapter 2

This is the second chapter."""

        temp_path = tmp_path / "book.txt"
        temp_path.write_text(content, encoding="utf-8")

        metadata, chapters = parse_text(temp_path)

        assert metadata["title"] == "Test Book"
        assert metadata["author"] == "Test Author"
        assert len(chapters) == 2
        assert "first chapter" in chapters[0].raw_text
        assert "second chapter" in chapters[1].raw_text

    def test_parse_markdown(self, tmp_path):
        """Test parsing markdown file."""
        content = """# My Story

Once upon a time...

# Chapter One

The adventure begins."""

        temp_path = tmp_path / "story.md"
        temp_path.write_text(content, encoding="utf-8")

        metadata, chapters = parse_text(temp_path)

        assert len(chapters) == 2
        assert chapters[0].title == "My Story"
        assert chapters[1].title == "Chapter One"


# ---------------------------------------------------------------------------
# FT-TEST-006: Encoding error tests
# ---------------------------------------------------------------------------

class TestEncodingErrors:
    """Tests that non-UTF-8 files produce a helpful error."""

    def test_latin1_file_raises_with_utf8_hint(self, tmp_path):
        """parse_text() raises ValueError mentioning UTF-8 for Latin-1 files."""
        latin1_file = tmp_path / "latin1.txt"
        # Write bytes that are valid Latin-1 but invalid UTF-8
        # 0xe9 = 'é' in Latin-1, but invalid as a standalone UTF-8 byte
        latin1_file.write_bytes(b"Caf\xe9 au lait\n")
        with pytest.raises(ValueError, match="UTF-8"):
            parse_text(latin1_file)

    def test_utf8_file_accepted(self, tmp_path):
        """parse_text() accepts valid UTF-8 files with Unicode."""
        utf8_file = tmp_path / "utf8.txt"
        utf8_file.write_text("Caf\u00e9 au lait\n", encoding="utf-8")
        metadata, chapters = parse_text(utf8_file)
        assert len(chapters) >= 1
