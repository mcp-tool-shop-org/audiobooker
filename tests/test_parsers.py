"""Tests for text parsers."""

import pytest
import tempfile
from pathlib import Path

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

    def test_parse_simple_text(self):
        """Test parsing a simple text file."""
        content = """---
title: Test Book
author: Test Author
---

Chapter 1

This is the first chapter.

Chapter 2

This is the second chapter."""

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            metadata, chapters = parse_text(temp_path)

            assert metadata["title"] == "Test Book"
            assert metadata["author"] == "Test Author"
            assert len(chapters) == 2
            assert "first chapter" in chapters[0].raw_text
            assert "second chapter" in chapters[1].raw_text

        finally:
            temp_path.unlink()

    def test_parse_markdown(self):
        """Test parsing markdown file."""
        content = """# My Story

Once upon a time...

# Chapter One

The adventure begins."""

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            metadata, chapters = parse_text(temp_path)

            assert len(chapters) >= 1

        finally:
            temp_path.unlink()
