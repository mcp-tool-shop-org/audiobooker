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
from audiobooker.language.profile import LanguageProfile

logger = logging.getLogger("audiobooker.parser")

# Maximum EPUB file size (200 MB). EPUBs are zip archives that can decompress
# to far more, but the on-disk file is a cheap first guard (PARSER-A-001).
_MAX_EPUB_FILE_BYTES = 200 * 1024 * 1024

# Allowed cover-image extensions. The internal item name is attacker-controlled,
# so its suffix is validated against this allowlist before being used to build
# the on-disk cover path (PARSER-A-005).
_ALLOWED_COVER_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def _safe_cover_ext(name: str) -> str:
    """Return the cover image extension if allowlisted, else '.jpg' (PARSER-A-005)."""
    ext = Path(name).suffix.lower()
    return ext if ext in _ALLOWED_COVER_EXTS else ".jpg"


def _decode_item_content(content: bytes, name: str) -> str:
    """
    Decode EPUB item bytes to text, honoring a UTF-16/UTF-8 BOM (PARSER-A-008).

    ebooklib returns raw bytes; blindly decoding as UTF-8 mojibakes UTF-16
    documents. Sniff a BOM first; otherwise default to UTF-8 with replacement,
    logging a warning when replacement characters are introduced.
    """
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        # "utf-16" consumes the BOM and infers LE/BE from it.
        return content.decode("utf-16")
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig")
    text = content.decode("utf-8", errors="replace")
    if "�" in text:
        logger.warning(
            "Replacement characters introduced while decoding %r as UTF-8 — "
            "the document may use a non-UTF-8 encoding.", name,
        )
    return text


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


def _flatten_toc(toc) -> list[tuple[str, str]]:
    """Flatten a (possibly nested) ebooklib TOC into ordered (title, href) pairs.

    ebooklib's ``book.toc`` is a list whose entries are either ``epub.Link``
    objects or ``(epub.Section, [children])`` tuples. Sections are containers;
    we descend into their children and only emit leaf links that point at a
    document href. Order is preserved (depth-first, document order).
    """
    flat: list[tuple[str, str]] = []

    def _walk(entries) -> None:
        for entry in entries:
            # (Section, children) tuple — descend into children.
            if isinstance(entry, tuple):
                section, children = entry[0], entry[1] if len(entry) > 1 else []
                # A Section may itself carry an href (rare); emit it if present.
                href = getattr(section, "href", None)
                title = getattr(section, "title", None)
                if href:
                    flat.append(((title or "").strip(), href))
                if children:
                    _walk(children)
            else:
                href = getattr(entry, "href", None)
                title = getattr(entry, "title", None)
                if href:
                    flat.append(((title or "").strip(), href))

    try:
        _walk(toc or [])
    except Exception as e:  # defensive: malformed TOC must not crash parsing
        logger.debug("TOC flattening failed: %s", e)
        return []
    return flat


def _split_href(href: str) -> tuple[str, Optional[str]]:
    """Split an EPUB href into (document path, anchor) — anchor is None if absent."""
    if "#" in href:
        doc, anchor = href.split("#", 1)
        return doc, (anchor or None)
    return href, None


# Match an element bearing id="X" or name="X" (anchor targets) in raw HTML.
def _anchor_pos(html_content: str, anchor: str) -> Optional[int]:
    """Return the character offset of an anchor's element in HTML, or None."""
    # id="anchor" or name="anchor" (single or double quoted)
    pat = re.compile(
        r"""<[^>]*\b(?:id|name)\s*=\s*['"]""" + re.escape(anchor) + r"""['"]""",
        re.IGNORECASE,
    )
    m = pat.search(html_content)
    return m.start() if m else None


def _chapters_from_toc(
    toc_entries: list[tuple[str, str]],
    *,
    min_chapter_words: int,
    keep_titled_short_chapters: bool,
    docs_by_name: dict,
) -> Optional[list[Chapter]]:
    """Build chapters from flattened TOC entries (FT-PARSE-003).

    For each TOC entry, resolve its document + optional anchor, slice the
    document's HTML between consecutive anchors that target the same document,
    convert each slice to text, and use the TOC title. Returns None if the TOC
    does not resolve to at least two usable chapters (caller falls back to
    spine splitting).
    """
    # Resolve each entry to (title, doc_name, anchor). Drop entries whose
    # document isn't a known document item.
    resolved: list[tuple[str, str, Optional[str]]] = []
    for title, href in toc_entries:
        doc_name, anchor = _split_href(href)
        # Normalize: hrefs may be relative with directories; match by suffix.
        item = docs_by_name.get(doc_name)
        if item is None:
            # Try matching on the basename / any doc whose name ends with href.
            for name, it in docs_by_name.items():
                if name.endswith(doc_name) or doc_name.endswith(name):
                    item = it
                    doc_name = name
                    break
        if item is None:
            continue
        resolved.append((title, doc_name, anchor))

    if len(resolved) < 2:
        return None

    chapters: list[Chapter] = []
    chapter_index = 0

    # Group consecutive entries by document so we can slice multi-anchor docs.
    i = 0
    n = len(resolved)
    while i < n:
        title, doc_name, anchor = resolved[i]
        item = docs_by_name[doc_name]
        content = item.get_content()
        if isinstance(content, bytes):
            content = _decode_item_content(content, doc_name)

        # Collect all consecutive entries that point at THIS same document.
        same_doc: list[tuple[str, Optional[str]]] = [(title, anchor)]
        j = i + 1
        while j < n and resolved[j][1] == doc_name:
            same_doc.append((resolved[j][0], resolved[j][2]))
            j += 1

        # Compute slice boundaries within the HTML for each entry.
        # An entry with an anchor starts at that anchor's position; the first
        # entry (no anchor or anchor missing) starts at 0. Each slice ends where
        # the next same-doc anchor begins, or at end of document.
        positions: list[int] = []
        for k, (_t, a) in enumerate(same_doc):
            pos = 0
            if a:
                found = _anchor_pos(content, a)
                if found is not None:
                    pos = found
                elif k > 0:
                    # Anchor not found mid-document — abandon TOC slicing for
                    # safety; fall back to spine (return None).
                    return None
            positions.append(pos)

        for k, (entry_title, _a) in enumerate(same_doc):
            start = positions[k]
            end = positions[k + 1] if k + 1 < len(positions) else len(content)
            slice_html = content[start:end]
            text = html_to_text(slice_html)
            word_count = len(text.split())

            if word_count < min_chapter_words:
                if entry_title and keep_titled_short_chapters:
                    logger.info(
                        "Keeping short titled TOC section: %r (%d words < %d)",
                        entry_title, word_count, min_chapter_words,
                    )
                else:
                    logger.info(
                        "Skipping short TOC section: %r (%d words < %d)",
                        entry_title or doc_name, word_count, min_chapter_words,
                    )
                    continue

            chap_title = entry_title or f"Chapter {chapter_index + 1}"
            chapters.append(Chapter(
                index=chapter_index,
                title=chap_title,
                raw_text=text,
                source_file=doc_name,
            ))
            chapter_index += 1

        i = j

    if len(chapters) < 2:
        return None
    return chapters


def parse_epub(
    path: Path,
    min_chapter_words: int = 50,
    keep_titled_short_chapters: bool = True,
    *,
    profile: Optional[LanguageProfile] = None,
    use_toc: str = "auto",
) -> tuple[dict, list[Chapter]]:
    """
    Parse an EPUB file into chapters.

    Args:
        path: Path to EPUB file
        min_chapter_words: Minimum word count for a section to be kept.
        keep_titled_short_chapters: Keep short sections that have a heading/title.
        profile: Language profile (used for the parse summary; EPUB chapter
            boundaries come from the book's own spine/document structure rather
            than heading-pattern detection, so this does not change splitting).
        use_toc: How to use the EPUB's table of contents for chapter
            boundaries (FT-PARSE-003). One of:
            - ``"auto"`` (default): use the TOC when it yields at least two
              usable chapters; otherwise fall back to spine/document splitting.
            - ``"on"``: same as auto — prefer the TOC, fall back to spine if it
              is unusable.
            - ``"off"``: ignore the TOC and always split on spine documents
              (the historical behavior).
            The spine fallback is byte-for-byte identical to the pre-FT-PARSE-003
            behavior, so the no-usable-TOC case is unchanged.

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

    _VALID_USE_TOC = ("auto", "on", "off")
    if use_toc not in _VALID_USE_TOC:
        raise ValueError(
            f"Invalid use_toc: {use_toc!r}. Must be one of: {', '.join(_VALID_USE_TOC)}"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EPUB not found: {path}")

    # Size guard (PARSER-A-001): mirror the PDF/text parsers.
    file_size = path.stat().st_size
    if file_size > _MAX_EPUB_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise ValueError(
            f"EPUB file is too large ({size_mb:.1f} MB, limit is 200 MB). "
            "Consider splitting the EPUB into smaller parts."
        )

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
            cover_image_ext = _safe_cover_ext(cover_items[0].get_name())
        else:
            # Fall back to first image item
            image_items = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
            # Look for items with "cover" in the name
            for img in image_items:
                name_lower = img.get_name().lower()
                if "cover" in name_lower:
                    cover_image_data = img.get_content()
                    cover_image_ext = _safe_cover_ext(img.get_name())
                    break
            # If no cover-named image, use the first image as fallback
            if cover_image_data is None and image_items:
                cover_image_data = image_items[0].get_content()
                cover_image_ext = _safe_cover_ext(image_items[0].get_name())
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

    # FT-PARSE-003: TOC-driven splitting. When use_toc is 'auto'/'on' and the
    # book's TOC resolves to >= 2 usable chapters, build chapters from the TOC
    # (titles + anchor-sliced text). Otherwise fall back to the spine/document
    # splitting below, which is byte-for-byte identical to the historical
    # behavior. 'off' skips the TOC entirely.
    chapters: list[Chapter] = []
    chapter_index = 0
    split_pattern = "spine/structure"

    if use_toc in ("auto", "on"):
        toc_entries = _flatten_toc(getattr(book, "toc", None))
        if len(toc_entries) >= 2:
            docs_by_name = {
                it.get_name(): it
                for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
            }
            toc_chapters = _chapters_from_toc(
                toc_entries,
                min_chapter_words=min_chapter_words,
                keep_titled_short_chapters=keep_titled_short_chapters,
                docs_by_name=docs_by_name,
            )
            if toc_chapters:
                chapters = toc_chapters
                split_pattern = "toc"
                logger.info(
                    "Using EPUB table of contents for chapter boundaries "
                    "(%d entries -> %d chapters).",
                    len(toc_entries), len(chapters),
                )
            else:
                logger.info(
                    "EPUB table of contents was not usable for splitting "
                    "(too few resolvable entries) — falling back to spine/document "
                    "structure.",
                )

    # Extract chapters from spine (reading order) — runs when TOC splitting was
    # off, absent, or unusable. This block is byte-for-byte identical to the
    # pre-FT-PARSE-003 behavior.
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT) if not chapters else ():
        # Get HTML content
        content = item.get_content()
        if isinstance(content, bytes):
            content = _decode_item_content(content, item.get_name())

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
                content = _decode_item_content(content, item.get_name())

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

    # Single-chapter EPUBs are usually genuine (one big document), but warn so
    # the user can tell detection apart from a one-section file.
    if len(chapters) == 1:
        logger.warning(
            "Only one chapter found in '%s' — the whole book is being treated as "
            "a single chapter. If it should have multiple chapters, the EPUB may "
            "store them in one document; check the file in Calibre.",
            path.name,
        )

    # Parse-observability summary (PARSER-C). EPUB splits on either the table of
    # contents (pattern=toc) or document/spine structure (pattern=spine/structure),
    # so the reported pattern reflects which path produced the chapters
    # (FT-PARSE-003).
    profile_code = profile.code if profile is not None else "en"
    logger.info(
        "Parsed EPUB '%s': %d chapter(s), profile=%s, pattern=%s",
        path.name, len(chapters), profile_code, split_pattern,
    )

    return metadata, chapters
