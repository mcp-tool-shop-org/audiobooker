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
    - Footnote elements (aside, sup, epub:type="noteref") -> tagged markers
    """

    # Sentinel markers for footnote spans (FT-CORE-019)
    FOOTNOTE_START = "\x02FOOTNOTE_START\x02"
    FOOTNOTE_END = "\x02FOOTNOTE_END\x02"

    # Block-level elements that should have newlines
    BLOCK_TAGS = {
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "blockquote", "pre", "br", "hr",
    }

    # Tags to skip entirely
    SKIP_TAGS = {"script", "style", "head", "meta", "link", "nav", "footer"}

    # Tags that indicate footnote content (FT-CORE-019)
    FOOTNOTE_TAGS = {"aside"}

    def __init__(self):
        super().__init__()
        self.output = StringIO()
        self.skip_depth = 0
        self._pending_newline = False
        self._footnote_depth = 0

    def _is_footnote_element(self, tag: str, attrs: list) -> bool:
        """Check if a tag+attrs represents a footnote element (FT-CORE-019)."""
        if tag in self.FOOTNOTE_TAGS:
            return True
        if tag == "sup":
            return True
        # Check epub:type="noteref" or epub:type="footnote"
        attrs_dict = dict(attrs)
        epub_type = attrs_dict.get("epub:type", "")
        if "noteref" in epub_type or "footnote" in epub_type:
            return True
        return False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif self._is_footnote_element(tag, attrs):
            self._footnote_depth += 1
            if self._footnote_depth == 1:
                self.output.write(self.FOOTNOTE_START)
        elif tag in self.BLOCK_TAGS:
            self._pending_newline = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in self.FOOTNOTE_TAGS or tag == "sup":
            if self._footnote_depth > 0:
                self._footnote_depth -= 1
                if self._footnote_depth == 0:
                    self.output.write(self.FOOTNOTE_END)
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


def process_footnotes(text: str, behavior: str = "inline") -> str:
    """
    Process footnote markers in extracted text (FT-CORE-019).

    Footnotes are delimited by FOOTNOTE_START / FOOTNOTE_END sentinels
    placed by HTMLTextExtractor.

    Args:
        text: Text containing footnote sentinels.
        behavior: "inline" (read in place), "end" (collect at chapter end),
                  "skip" (remove entirely).

    Returns:
        Processed text with footnotes handled according to behavior.
    """
    start = HTMLTextExtractor.FOOTNOTE_START
    end = HTMLTextExtractor.FOOTNOTE_END

    if start not in text:
        return text

    if behavior == "skip":
        # Remove all footnote content
        result = re.sub(
            re.escape(start) + r"(.*?)" + re.escape(end),
            "",
            text,
            flags=re.DOTALL,
        )
        return re.sub(r" {2,}", " ", result).strip()

    if behavior == "end":
        # Collect footnotes, replace inline with reference numbers
        footnotes: list[str] = []
        counter = 0

        def _collect(m: re.Match) -> str:
            nonlocal counter
            counter += 1
            content = m.group(1).strip()
            footnotes.append(f"Footnote {counter}: {content}")
            return f" [{counter}] "

        result = re.sub(
            re.escape(start) + r"(.*?)" + re.escape(end),
            _collect,
            text,
            flags=re.DOTALL,
        )
        if footnotes:
            result = result.rstrip() + "\n\n" + "\n".join(footnotes)
        return result

    # behavior == "inline" — just strip the sentinels, keep content in place
    result = text.replace(start, "").replace(end, "")
    return result


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
    except Exception as e:
        # F-CORE-B-012: Log instead of silently swallowing
        logger.warning("HTML parsing failed, falling back to tag stripping: %s", e)
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

    # F-CORE-B-003: Wrap read_epub with error handling for corrupt/DRM files
    from zipfile import BadZipFile
    try:
        book = epub.read_epub(str(path))
    except BadZipFile:
        raise ValueError(
            f"Cannot open '{path.name}' — the file appears to be corrupt or "
            "is not a valid EPUB (bad zip archive). Try re-downloading the file "
            "or opening it in Calibre to verify it."
        )
    except KeyError as e:
        raise ValueError(
            f"Cannot parse '{path.name}' — the EPUB is missing expected content: {e}. "
            "This can happen with DRM-protected books. Use Calibre to inspect "
            "or re-export the EPUB."
        ) from e
    except Exception as e:
        raise ValueError(
            f"Failed to read '{path.name}': {e}. "
            "The file may be DRM-protected, corrupt, or in an unsupported format. "
            "Try opening it in Calibre first to verify it's readable."
        ) from e

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

    # Publisher
    publisher_list = book.get_metadata("DC", "publisher")
    if publisher_list:
        metadata["publisher"] = publisher_list[0][0]

    # Date/Year
    date_list = book.get_metadata("DC", "date")
    if date_list:
        date_str = date_list[0][0]
        # Try to extract year from date string (ISO format or plain year)
        year_match = re.match(r"(\d{4})", date_str)
        if year_match:
            metadata["year"] = int(year_match.group(1))

    # Cover art extraction (FT-CORE-014)
    cover_image_data = None
    cover_image_ext = None
    try:
        # Try ITEM_COVER first
        cover_items = list(book.get_items_of_type(ebooklib.ITEM_COVER))
        if cover_items:
            cover_image_data = cover_items[0].get_content()
            cover_name = cover_items[0].get_name()
            cover_image_ext = Path(cover_name).suffix or ".jpg"
        else:
            # Fall back to first image item
            image_items = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
            # Look for items with "cover" in the name
            for img in image_items:
                name_lower = img.get_name().lower()
                if "cover" in name_lower:
                    cover_image_data = img.get_content()
                    cover_image_ext = Path(img.get_name()).suffix or ".jpg"
                    break
            # If no cover-named image, use the first image as fallback
            if cover_image_data is None and image_items:
                cover_image_data = image_items[0].get_content()
                cover_image_ext = Path(image_items[0].get_name()).suffix or ".jpg"
    except Exception as e:
        logger.warning("Failed to extract cover art: %s", e)

    if cover_image_data is not None:
        # Write cover art next to the EPUB
        cover_path = path.parent / f"{path.stem}_cover{cover_image_ext}"
        try:
            cover_path.write_bytes(cover_image_data)
            metadata["cover_art_path"] = str(cover_path)
            logger.info("Extracted cover art to %s", cover_path)
        except OSError as e:
            logger.warning("Could not save cover art: %s", e)

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

        # Try to extract title (reuse cached content instead of calling get_content() again)
        title = extract_title_from_html(content)

        # Skip short sections (unless titled and keep_titled_short_chapters)
        if word_count < min_chapter_words:
            if title and keep_titled_short_chapters:
                logger.info(
                    f"Keeping short titled section: {title!r} "
                    f"({word_count} words < {min_chapter_words} threshold)"
                )
            else:
                label = title or item.get_name()
                logger.info(
                    f"Skipping short section: {label!r} "
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
                    label = title or item.get_name()
                    logger.info(
                        f"Skipping short section: {label!r} "
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

    # F-CORE-B-004: Raise if no readable chapters found
    if not chapters:
        logger.warning("No readable chapters found in '%s'", path.name)
        raise ValueError(
            f"No readable chapters found in '{path.name}'. "
            "The EPUB may be DRM-protected, use an unsupported format, "
            "or contain only very short sections. "
            f"(Current minimum: {min_chapter_words} words per chapter — "
            "try lowering min_chapter_words in ProjectConfig if the book has short sections.)"
        )

    return metadata, chapters
