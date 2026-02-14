"""
EPUB Parser for Audiobooker.

Extracts chapters and metadata from EPUB files using ebooklib.
Converts HTML content to plain text suitable for TTS.
"""

import logging
import re
from pathlib import Path
from typing import Optional
from html.parser import HTMLParser
from io import StringIO

from audiobooker.models import Chapter

logger = logging.getLogger("audiobooker.parser")


class HTMLTextExtractor(HTMLParser):
    """
    Extract plain text from HTML, preserving paragraph structure.

    Handles:
    - Block elements (p, div, h1-h6) -> newlines
    - Inline elements -> preserved
    - Whitespace normalization
    """

    # Block-level elements that should have newlines
    BLOCK_TAGS = {
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "blockquote", "pre", "br", "hr",
    }

    # Tags to skip entirely
    SKIP_TAGS = {"script", "style", "head", "meta", "link", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self.output = StringIO()
        self.skip_depth = 0
        self._pending_newline = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self._pending_newline = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in self.BLOCK_TAGS:
            self._pending_newline = True

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return

        # Normalize whitespace
        text = " ".join(data.split())
        if not text:
            return

        if self._pending_newline:
            self.output.write("\n\n")
            self._pending_newline = False

        self.output.write(text + " ")

    def get_text(self) -> str:
        """Get extracted text with normalized whitespace."""
        text = self.output.getvalue()
        # Normalize multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Clean up extra spaces
        text = re.sub(r" +", " ", text)
        return text.strip()


def html_to_text(html_content: str) -> str:
    """
    Convert HTML to plain text.

    Args:
        html_content: HTML string

    Returns:
        Plain text with paragraph structure preserved
    """
    extractor = HTMLTextExtractor()
    try:
        extractor.feed(html_content)
    except Exception:
        # Fallback: strip all tags
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = " ".join(text.split())
        return text
    return extractor.get_text()


def extract_title_from_html(html_content: str) -> Optional[str]:
    """
    Try to extract chapter title from HTML content.

    Looks for h1, h2, h3 tags at the start of content.
    """
    # Look for heading at start
    patterns = [
        r"<h[1-3][^>]*>([^<]+)</h[1-3]>",
        r"<title>([^<]+)</title>",
    ]

    for pattern in patterns:
        match = re.search(pattern, html_content[:2000], re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Clean up the title
            title = re.sub(r"\s+", " ", title)
            if title and len(title) < 200:
                return title

    return None


def parse_epub(
    path: Path,
    min_chapter_words: int = 50,
    keep_titled_short_chapters: bool = True,
) -> tuple[dict, list[Chapter]]:
    """
    Parse an EPUB file into chapters.

    Args:
        path: Path to EPUB file
        min_chapter_words: Minimum word count for a section to be kept.
        keep_titled_short_chapters: Keep short sections that have a heading/title.

    Returns:
        Tuple of (metadata dict, list of Chapters)

    Raises:
        ImportError: If ebooklib is not installed
        FileNotFoundError: If file doesn't exist
    """
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        raise ImportError(
            "ebooklib is required for EPUB parsing. "
            "Install with: pip install ebooklib"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EPUB not found: {path}")

    # Read EPUB
    book = epub.read_epub(str(path))

    # Extract metadata
    metadata = {}

    # Title
    title_list = book.get_metadata("DC", "title")
    if title_list:
        metadata["title"] = title_list[0][0]

    # Author
    creator_list = book.get_metadata("DC", "creator")
    if creator_list:
        metadata["author"] = creator_list[0][0]

    # Language
    lang_list = book.get_metadata("DC", "language")
    if lang_list:
        metadata["language"] = lang_list[0][0]

    # Extract chapters from spine (reading order)
    chapters = []
    chapter_index = 0

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        # Get HTML content
        content = item.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")

        # Convert to plain text
        text = html_to_text(content)
        word_count = len(text.split())

        # Try to extract title
        title = extract_title_from_html(item.get_content().decode("utf-8", errors="replace"))

        # Skip short sections (unless titled and keep_titled_short_chapters)
        if word_count < min_chapter_words:
            if title and keep_titled_short_chapters:
                logger.info(
                    f"Keeping short titled section: {title!r} "
                    f"({word_count} words < {min_chapter_words} threshold)"
                )
            else:
                logger.info(
                    f"Skipping short section: {title or item.get_name()!r} "
                    f"({word_count} words < {min_chapter_words} threshold)"
                )
                continue

        if not title:
            title = f"Chapter {chapter_index + 1}"

        chapter = Chapter(
            index=chapter_index,
            title=title,
            raw_text=text,
            source_file=item.get_name(),
        )
        chapters.append(chapter)
        chapter_index += 1

    # If no chapters found, try spine order
    if not chapters:
        for spine_item in book.spine:
            item_id = spine_item[0] if isinstance(spine_item, tuple) else spine_item
            item = book.get_item_with_id(item_id)

            if item is None:
                continue

            content = item.get_content()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")

            text = html_to_text(content)
            word_count = len(text.split())
            title = extract_title_from_html(content)

            if word_count < min_chapter_words:
                if title and keep_titled_short_chapters:
                    logger.info(
                        f"Keeping short titled section: {title!r} "
                        f"({word_count} words < {min_chapter_words} threshold)"
                    )
                else:
                    logger.info(
                        f"Skipping short section: {title or item.get_name()!r} "
                        f"({word_count} words < {min_chapter_words} threshold)"
                    )
                    continue

            if not title:
                title = f"Chapter {chapter_index + 1}"

            chapter = Chapter(
                index=chapter_index,
                title=title,
                raw_text=text,
                source_file=item.get_name(),
            )
            chapters.append(chapter)
            chapter_index += 1

    return metadata, chapters
