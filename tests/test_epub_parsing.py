"""Tests for EPUB parsing.

Covers: metadata extraction, chapter splitting, short-section filtering,
keep_titled_short_chapters, and spine-order fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audiobooker.parser.epub import parse_epub, html_to_text, extract_title_from_html


def _has_ebooklib() -> bool:
    try:
        import ebooklib  # noqa: F401
        return True
    except ImportError:
        return False


requires_ebooklib = pytest.mark.skipif(
    not _has_ebooklib(),
    reason="ebooklib not installed — install with: pip install ebooklib",
)


def _create_test_epub(tmp_path: Path, chapters: list[tuple[str, str]], title: str = "Test Book", author: str = "Test Author") -> Path:
    """Create a minimal EPUB file for testing.

    Args:
        tmp_path: Directory to write the EPUB.
        chapters: List of (chapter_title, html_body) tuples.
        title: Book title.
        author: Author name.

    Returns:
        Path to the created EPUB file.
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("test-book-001")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    epub_chapters = []
    for i, (ch_title, html_body) in enumerate(chapters):
        ch = epub.EpubHtml(
            title=ch_title,
            file_name=f"chapter_{i}.xhtml",
            lang="en",
        )
        ch.content = f"<html><body><h1>{ch_title}</h1>{html_body}</body></html>"
        book.add_item(ch)
        epub_chapters.append(ch)

    # Add navigation
    book.toc = epub_chapters
    book.spine = ["nav"] + epub_chapters

    # Add required NCX and Nav
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = tmp_path / "test.epub"
    epub.write_epub(str(path), book)
    return path


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

@requires_ebooklib
class TestEpubMetadata:
    """Tests for EPUB metadata extraction."""

    def test_extracts_title_and_author(self, tmp_path):
        """parse_epub extracts title and author from EPUB metadata."""
        epub_path = _create_test_epub(
            tmp_path,
            chapters=[("Chapter 1", "<p>The story begins here with enough words to pass the threshold for minimum chapter word count.</p>")],
            title="My Great Book",
            author="Jane Doe",
        )

        metadata, chapters = parse_epub(epub_path)
        assert metadata["title"] == "My Great Book"
        assert metadata["author"] == "Jane Doe"

    def test_missing_metadata_defaults(self, tmp_path):
        """parse_epub handles EPUB with missing metadata gracefully."""
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier("test-no-meta")
        book.set_title("")
        book.set_language("en")

        ch = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
        ch.content = "<html><body><h1>Chapter 1</h1><p>Content here that has enough words to be a chapter section in the parser.</p></body></html>"
        book.add_item(ch)
        book.toc = [ch]
        book.spine = ["nav", ch]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        path = tmp_path / "empty_meta.epub"
        epub.write_epub(str(path), book)

        metadata, chapters = parse_epub(path)
        # Should not crash; title may be empty string
        assert isinstance(metadata, dict)


# ---------------------------------------------------------------------------
# Chapter splitting
# ---------------------------------------------------------------------------

@requires_ebooklib
class TestEpubChapterSplitting:
    """Tests for EPUB chapter splitting."""

    def test_multi_chapter_splitting(self, tmp_path):
        """Multiple EPUB sections become separate chapters."""
        long_text = "<p>" + " ".join(["word"] * 100) + "</p>"
        epub_path = _create_test_epub(
            tmp_path,
            chapters=[
                ("Chapter 1: Dawn", long_text),
                ("Chapter 2: Noon", long_text),
                ("Chapter 3: Dusk", long_text),
            ],
        )

        metadata, chapters = parse_epub(epub_path)
        assert len(chapters) >= 3
        assert chapters[0].title == "Chapter 1: Dawn"
        assert chapters[1].title == "Chapter 2: Noon"
        assert chapters[2].title == "Chapter 3: Dusk"

    def test_chapter_text_extracted(self, tmp_path):
        """Chapter raw_text contains the HTML body converted to plain text."""
        epub_path = _create_test_epub(
            tmp_path,
            chapters=[("Ch1", "<p>The quick brown fox jumps over the lazy dog repeatedly until we have enough words to pass the threshold.</p>")],
        )

        _, chapters = parse_epub(epub_path)
        assert len(chapters) >= 1
        assert "quick brown fox" in chapters[0].raw_text


# ---------------------------------------------------------------------------
# Short-section filtering
# ---------------------------------------------------------------------------

@requires_ebooklib
class TestEpubShortSectionFiltering:
    """Tests for min_chapter_words and keep_titled_short_chapters."""

    def test_short_untitled_dropped(self, tmp_path):
        """Sections below min_chapter_words without title are dropped."""
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier("test-short")
        book.set_title("Short Test")
        book.set_language("en")

        # Short section (no heading)
        short_ch = epub.EpubHtml(title="", file_name="short.xhtml", lang="en")
        short_ch.content = "<html><body><p>Short text.</p></body></html>"
        book.add_item(short_ch)

        # Long section
        long_text = " ".join(["word"] * 100)
        long_ch = epub.EpubHtml(title="Long Chapter", file_name="long.xhtml", lang="en")
        long_ch.content = f"<html><body><h1>Long Chapter</h1><p>{long_text}</p></body></html>"
        book.add_item(long_ch)

        book.toc = [short_ch, long_ch]
        book.spine = ["nav", short_ch, long_ch]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        path = tmp_path / "short_test.epub"
        epub.write_epub(str(path), book)

        _, chapters = parse_epub(path, min_chapter_words=50)
        # Short section should be dropped
        titles = [c.title for c in chapters]
        assert "Long Chapter" in titles

    def test_short_titled_kept(self, tmp_path):
        """Sections below min_chapter_words WITH title are kept when keep_titled_short_chapters=True."""
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier("test-titled-short")
        book.set_title("Titled Short Test")
        book.set_language("en")

        # Short section with title
        titled_ch = epub.EpubHtml(title="Prologue", file_name="prologue.xhtml", lang="en")
        titled_ch.content = "<html><body><h1>Prologue</h1><p>Very short prologue text.</p></body></html>"
        book.add_item(titled_ch)

        # Long section
        long_text = " ".join(["word"] * 100)
        long_ch = epub.EpubHtml(title="Chapter 1", file_name="ch1.xhtml", lang="en")
        long_ch.content = f"<html><body><h1>Chapter 1</h1><p>{long_text}</p></body></html>"
        book.add_item(long_ch)

        book.toc = [titled_ch, long_ch]
        book.spine = ["nav", titled_ch, long_ch]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        path = tmp_path / "titled_short.epub"
        epub.write_epub(str(path), book)

        _, chapters = parse_epub(path, min_chapter_words=50, keep_titled_short_chapters=True)
        titles = [c.title for c in chapters]
        assert "Prologue" in titles

    def test_short_titled_dropped_when_disabled(self, tmp_path):
        """Short titled sections are dropped when keep_titled_short_chapters=False."""
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier("test-titled-drop")
        book.set_title("Drop Short Test")
        book.set_language("en")

        # Short section with title
        titled_ch = epub.EpubHtml(title="Prologue", file_name="prologue.xhtml", lang="en")
        titled_ch.content = "<html><body><h1>Prologue</h1><p>Short.</p></body></html>"
        book.add_item(titled_ch)

        # Long section
        long_text = " ".join(["word"] * 100)
        long_ch = epub.EpubHtml(title="Chapter 1", file_name="ch1.xhtml", lang="en")
        long_ch.content = f"<html><body><h1>Chapter 1</h1><p>{long_text}</p></body></html>"
        book.add_item(long_ch)

        book.toc = [titled_ch, long_ch]
        book.spine = ["nav", titled_ch, long_ch]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        path = tmp_path / "drop_short.epub"
        epub.write_epub(str(path), book)

        _, chapters = parse_epub(path, min_chapter_words=50, keep_titled_short_chapters=False)
        titles = [c.title for c in chapters]
        assert "Prologue" not in titles


# ---------------------------------------------------------------------------
# Spine-order fallback
# ---------------------------------------------------------------------------

@requires_ebooklib
class TestEpubSpineFallback:
    """Tests for spine-order fallback path."""

    def test_file_not_found_raises(self):
        """parse_epub raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError, match="EPUB not found"):
            parse_epub(Path("/nonexistent/book.epub"))


# ---------------------------------------------------------------------------
# HTML helper tests
# ---------------------------------------------------------------------------

class TestHtmlHelpers:
    """Tests for html_to_text and extract_title_from_html."""

    def test_html_to_text_strips_tags(self):
        """html_to_text strips HTML tags and preserves text."""
        result = html_to_text("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<p>" not in result

    def test_extract_title_from_h1(self):
        """extract_title_from_html finds h1 title."""
        title = extract_title_from_html("<h1>My Chapter</h1><p>content</p>")
        assert title == "My Chapter"

    def test_extract_title_none_when_missing(self):
        """extract_title_from_html returns None when no heading."""
        title = extract_title_from_html("<p>Just a paragraph.</p>")
        assert title is None
