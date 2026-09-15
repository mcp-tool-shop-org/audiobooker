"""
DOCX Parser for Audiobooker (FT-PARSE-004).

Extracts chapters and metadata from Word (.docx) files using python-docx.

Chapter boundaries are detected from paragraph styles first — a paragraph
styled ``Heading 1``, ``Heading 2`` or ``Title`` starts a new chapter. When a
document carries no such styled headings (common in flat exports), the parser
falls back to the language profile's ``chapter_patterns`` matched against the
plain paragraph text, mirroring the text/PDF parsers.

Tables are read too (FEAT-IN-005). ``document.paragraphs`` does not reach
inside table cells, so the parser walks the body element's children in
document order and renders each ``w:tbl`` as speakable rows in the position
the author put it.

Title and author are read from the document's core properties into the
metadata dict, matching ``parse_epub``'s return shape.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from audiobooker.models import Chapter
from audiobooker.language.profile import LanguageProfile
from audiobooker.parser.text import compose_chapter_title

logger = logging.getLogger("audiobooker.parser")

# Maximum DOCX file size (200 MB). Like EPUB, a .docx is a zip archive; the
# on-disk size is a cheap first guard (mirrors epub.py / pdf.py).
_MAX_DOCX_FILE_BYTES = 200 * 1024 * 1024

# Paragraph style names that start a new chapter. Compared case-insensitively
# and tolerant of a trailing style variant (e.g. "Heading 1 Char").
_HEADING_STYLES = frozenset({"heading 1", "heading 2", "title"})


def _is_heading_style(style_name: Optional[str]) -> bool:
    """True if a paragraph style name marks a chapter boundary."""
    if not style_name:
        return False
    name = style_name.strip().lower()
    if name in _HEADING_STYLES:
        return True
    # Tolerate suffixed variants like "Heading 1 Char" / "Title Char".
    for base in _HEADING_STYLES:
        if name.startswith(base):
            return True
    return False


def _compile_chapter_patterns(
    profile: Optional[LanguageProfile],
) -> list[re.Pattern]:
    """Compile the profile's chapter_patterns for the text fallback path."""
    if profile is None:
        return []
    compiled: list[re.Pattern] = []
    for pat in profile.chapter_patterns:
        try:
            compiled.append(re.compile(pat, re.MULTILINE))
        except re.error:
            logger.debug("Skipping invalid chapter pattern %r for %r", pat, profile.code)
    return compiled


def _heading_from_patterns(
    line: str,
    patterns: list[re.Pattern],
) -> Optional[str]:
    """Return a chapter title if a plain line matches a profile heading pattern."""
    line = line.strip()
    if not line:
        return None
    for pattern in patterns:
        match = pattern.match(line)
        if match:
            # FEAT-IN-006: shared composer — see parser/text.py.
            return compose_chapter_title(line, match)
    return None


# Body children that are structural, not narratable. Counted separately
# from unknown tags so a normal document does not log "skipped sectPr".
_IGNORABLE_BODY_TAGS = frozenset({
    "sectPr",
    "bookmarkStart", "bookmarkEnd",
    "commentRangeStart", "commentRangeEnd", "comment",
    "permStart", "permEnd",
    "moveFromRangeStart", "moveFromRangeEnd",
    "moveToRangeStart", "moveToRangeEnd",
    "del",
})


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _iter_child_blocks(element, parent, unknown_counts: dict):
    """Yield narratable blocks under ``element`` in document order.

    Walks ``w:p`` / ``w:tbl``, then the siblings FEAT-IN-005 left behind:
    ``w:sdt`` (content controls), nested ``w:sdtContent``, ``w:txbxContent``
    (text boxes / callouts), and ``w:customXml`` wrappers. ``w:altChunk``
    is logged and skipped — it is foreign embedded content, not a paragraph.
    """
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    qn_txbx = qn("w:txbxContent")

    def _top_txbx(node):
        for txbx in node.iter(qn_txbx):
            ancestor = txbx.getparent()
            nested = False
            while ancestor is not None and ancestor is not node:
                if ancestor.tag == qn_txbx:
                    nested = True
                    break
                ancestor = ancestor.getparent()
            if not nested:
                yield txbx

    for child in element.iterchildren():
        tag = child.tag
        local = _local_tag(tag)
        if tag == qn("w:p"):
            yield "paragraph", Paragraph(child, parent)
            # Text boxes live in drawings inside runs; Paragraph.text does
            # not reach them, so flatten each w:txbxContent as extra blocks.
            for txbx in _top_txbx(child):
                yield from _iter_child_blocks(txbx, parent, unknown_counts)
        elif tag == qn("w:tbl"):
            yield "table", Table(child, parent)
        elif tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _iter_child_blocks(content, parent, unknown_counts)
        elif tag == qn("w:txbxContent"):
            yield from _iter_child_blocks(child, parent, unknown_counts)
        elif local in {"customXml", "smartTag", "ins"}:
            yield from _iter_child_blocks(child, parent, unknown_counts)
        elif local == "altChunk":
            unknown_counts["altChunk"] = unknown_counts.get("altChunk", 0) + 1
            logger.info(
                "Skipping DOCX w:altChunk (embedded foreign content)."
            )
        elif local in _IGNORABLE_BODY_TAGS:
            continue
        else:
            unknown_counts[local] = unknown_counts.get(local, 0) + 1


def _cell_text(cell) -> str:
    """Flatten one table cell — including nested tables, SDTs, and text boxes."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parts: list[str] = []
    unknown: dict[str, int] = {}
    for child in cell._element.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            text = (Paragraph(child, cell).text or "").strip()
            if text:
                parts.append(text)
            qn_txbx = qn("w:txbxContent")
            for txbx in child.iter(qn_txbx):
                ancestor = txbx.getparent()
                skip = False
                while ancestor is not None and ancestor is not child:
                    if ancestor.tag == qn_txbx:
                        skip = True
                        break
                    ancestor = ancestor.getparent()
                if skip:
                    continue
                nested = _container_text(txbx, cell, unknown)
                if nested:
                    parts.append(nested)
        elif tag == qn("w:tbl"):
            nested = _table_to_speakable(Table(child, cell))
            if nested:
                parts.append(nested)
        elif tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                nested = _container_text(content, cell, unknown)
                if nested:
                    parts.append(nested)
        elif tag == qn("w:txbxContent"):
            nested = _container_text(child, cell, unknown)
            if nested:
                parts.append(nested)
    return " ".join(parts).strip()


def _container_text(element, parent, unknown_counts: dict) -> str:
    """Speakable text of a nested SDT / text-box container."""
    parts: list[str] = []
    for kind, block in _iter_child_blocks(element, parent, unknown_counts):
        if kind == "paragraph":
            text = (block.text or "").strip()
            if text:
                parts.append(text)
        elif kind == "table":
            nested = _table_to_speakable(block)
            if nested:
                parts.append(nested)
    return " ".join(parts).strip()


def _table_to_speakable(table) -> str:
    """Render a table as lines a narrator can read.

    FEAT-IN-005. Each row becomes one line, cells joined by ", " and
    terminated with a full stop so the TTS engine does not run consecutive
    rows together. Horizontally merged cells repeat in python-docx's row view,
    so consecutive duplicates are collapsed.
    """
    lines: list[str] = []
    for row in table.rows:
        try:
            cells = list(row.cells)
        except (IndexError, ValueError):  # malformed grid
            continue
        texts: list[str] = []
        for cell in cells:
            value = _cell_text(cell)
            # A merged cell appears once per grid column it spans.
            if value and (not texts or texts[-1] != value):
                texts.append(value)
        if not texts:
            continue
        line = ", ".join(texts)
        if not line.endswith((".", "!", "?", ":", ";")):
            line += "."
        lines.append(line)
    return "\n".join(lines)


def _iter_body_blocks(document):
    """Yield the document body's paragraphs AND tables in document order.

    FEAT-IN-005. ``document.paragraphs`` does not include paragraphs inside
    table cells — those live under ``document.tables``, a separate collection
    that is not interleaved with the body flow. Walking only ``paragraphs``
    therefore DELETED every table: a dramatis-personae list, a timeline or an
    appendix vanished outright, sometimes leaving a dangling "The following
    table lists…" behind it. Walking the body element's children instead keeps
    each table in the position the author put it.

    Yields ``("paragraph", Paragraph)`` and ``("table", Table)`` pairs.

    Degrades to ``document.paragraphs`` for any document object that exposes
    no XML body — a document model without tables loses nothing by it.
    """
    try:
        body = document.element.body
    except (ImportError, AttributeError) as e:
        logger.debug(
            "DOCX body element unavailable (%s) — walking paragraphs only; "
            "any tables in this document will not be read.", e,
        )
        for para in document.paragraphs:
            yield "paragraph", para
        return

    unknown: dict[str, int] = {}
    yield from _iter_child_blocks(body, document, unknown)
    if unknown:
        logger.info(
            "Skipped %d unknown DOCX body tag(s): %s",
            sum(unknown.values()),
            ", ".join(f"{k}×{v}" for k, v in sorted(unknown.items())),
        )


def _part_lines(part, parent) -> list[str]:
    """Flatten a header/footer part to speakable lines (paragraphs + tables)."""
    try:
        element = part._element
    except AttributeError:
        return [
            (p.text or "").strip()
            for p in getattr(part, "paragraphs", [])
            if (p.text or "").strip()
        ]
    unknown: dict[str, int] = {}
    lines: list[str] = []
    for kind, block in _iter_child_blocks(element, parent, unknown):
        if kind == "paragraph":
            text = (block.text or "").strip()
            if text:
                lines.append(text)
        elif kind == "table":
            rendered = _table_to_speakable(block)
            if rendered:
                lines.append(rendered)
    return lines


def _unique_header_footer_lines(document) -> tuple[list[str], list[str]]:
    """Keep unique header/footer prose; drop running heads that repeat.

    Policy: a line that appears in more than one header/footer part is a
    running head and is omitted. A line that appears once (letterhead,
    a first-page-only dispatch, a unique footer note) is kept and attached
    to the first / last chapter so the short-section filter cannot drop it.
    Single-section running heads therefore speak once, not per page.
    """
    try:
        sections = list(document.sections)
    except Exception as e:
        logger.debug("DOCX sections unavailable (%s) — skipping headers/footers.", e)
        return [], []

    def _parts(section, kind: str):
        try:
            primary = getattr(section, kind, None)
        except Exception:
            primary = None
        if primary is not None:
            try:
                if not getattr(primary, "is_linked_to_previous", False):
                    yield primary
            except Exception:
                yield primary
        try:
            different_first = bool(section.different_first_page_header_footer)
        except Exception:
            different_first = False
        if different_first:
            try:
                first = getattr(section, f"first_page_{kind}", None)
            except Exception:
                first = None
            if first is not None:
                yield first

    def _collect(kind: str) -> list[str]:
        counts: dict[str, int] = {}
        order: list[str] = []
        for section in sections:
            for part in _parts(section, kind):
                for line in _part_lines(part, document):
                    if line not in counts:
                        order.append(line)
                    counts[line] = counts.get(line, 0) + 1
        unique = [line for line in order if counts[line] == 1]
        dropped = [line for line in order if counts[line] > 1]
        if dropped:
            logger.info(
                "Dropping %d repeating DOCX %s running-head line(s).",
                len(dropped), kind,
            )
        if unique:
            logger.info(
                "Keeping %d unique DOCX %s paragraph(s).",
                len(unique), kind,
            )
        return unique

    return _collect("header"), _collect("footer")


def parse_docx(
    path: Path,
    *,
    min_chapter_words: int = 50,
    profile: Optional[LanguageProfile] = None,
) -> tuple[dict, list[Chapter]]:
    """
    Parse a Word (.docx) file into chapters (FT-PARSE-004).

    Chapter boundaries come from paragraph styles (``Heading 1``, ``Heading 2``,
    ``Title``). When no styled headings are present, the parser falls back to
    matching the language profile's ``chapter_patterns`` against plain paragraph
    text. Title and author are read from the document's core properties.

    Args:
        path: Path to the .docx file.
        min_chapter_words: Minimum word count for a section to be kept as a
            chapter.
        profile: Language profile for the fallback heading patterns (default
            English-less: with no profile, the style-based split is used and the
            whole document falls back to a single chapter if it has no styled
            headings).

    Returns:
        Tuple of (metadata dict, list of Chapters), mirroring ``parse_epub``.

    Raises:
        ImportError: If python-docx is not installed.
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is corrupt or has no readable chapters.
    """
    try:
        import docx  # python-docx
    except ImportError:
        raise ImportError(
            "python-docx is required for DOCX parsing. "
            "Install with: pip install python-docx"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX not found: {path}")

    # Size guard (mirrors epub.py / pdf.py).
    file_size = path.stat().st_size
    if file_size > _MAX_DOCX_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise ValueError(
            f"DOCX file is too large ({size_mb:.1f} MB, limit is 200 MB). "
            "Consider splitting the document into smaller parts."
        )

    # Wrap open with error handling for corrupt/non-docx files.
    from zipfile import BadZipFile
    try:
        document = docx.Document(str(path))
    except BadZipFile:
        raise ValueError(
            f"Cannot open '{path.name}' — the file appears to be corrupt or is "
            "not a valid .docx (bad zip archive). If it is an older .doc file, "
            "open it in Word and 'Save As' .docx first."
        )
    except Exception as e:
        raise ValueError(
            f"Failed to read '{path.name}': {e}. "
            "The file may be corrupt, password-protected, or in an unsupported "
            "format (e.g. legacy .doc). Open it in Word and re-save as .docx."
        ) from e

    # --- Metadata from core properties ---
    metadata: dict = {}
    try:
        props = document.core_properties
        if getattr(props, "title", None):
            metadata["title"] = props.title
        if getattr(props, "author", None):
            metadata["author"] = props.author
    except Exception as e:
        logger.debug("Could not read DOCX core properties: %s", e)

    # --- Walk paragraphs, splitting on heading styles ---
    chapter_patterns = _compile_chapter_patterns(profile)
    chapters: list[Chapter] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []
    style_headings_seen = 0
    pattern_headings_seen = 0

    def _flush() -> None:
        """Emit the accumulated section as a chapter if it qualifies."""
        nonlocal current_title, current_lines
        content = "\n".join(current_lines).strip()
        current_lines = []
        if not content:
            current_title = None
            return
        word_count = len(content.split())
        if word_count < min_chapter_words:
            if current_title:
                logger.info(
                    "Keeping short titled section: %r (%d words < %d)",
                    current_title, word_count, min_chapter_words,
                )
            else:
                logger.info(
                    "Skipping short section (%d words < %d)",
                    word_count, min_chapter_words,
                )
                current_title = None
                return
        title = current_title or f"Chapter {len(chapters) + 1}"
        chapters.append(Chapter(
            index=len(chapters),
            title=title,
            raw_text=content,
            source_file=str(path),
        ))
        current_title = None

    tables_seen = 0

    for kind, block in _iter_body_blocks(document):
        if kind == "table":
            # FEAT-IN-005: table content is body text, in its authored
            # position. It never starts a chapter.
            rendered = _table_to_speakable(block)
            if rendered:
                tables_seen += 1
                current_lines.append(rendered)
            continue

        para = block
        text = (para.text or "").strip()
        style_name = None
        try:
            style_name = para.style.name if para.style is not None else None
        except Exception:
            style_name = None

        if _is_heading_style(style_name):
            # Heading style starts a new chapter.
            style_headings_seen += 1
            _flush()
            current_title = text or current_title
            continue

        # Fallback: a plain paragraph whose text matches a profile chapter
        # pattern also starts a new chapter (only used when no styled headings
        # have driven the split — see post-loop check).
        if text and chapter_patterns:
            pat_title = _heading_from_patterns(text, chapter_patterns)
            if pat_title is not None:
                pattern_headings_seen += 1
                _flush()
                current_title = pat_title
                continue

        if text:
            current_lines.append(text)

    # Emit the trailing section.
    _flush()

    # Unique header/footer prose (letterhead, a first-page dispatch) is
    # attached once so the short-section filter cannot drop a 6-word
    # letterhead. Repeating running heads were already filtered out.
    header_lines, footer_lines = _unique_header_footer_lines(document)
    if not chapters and (header_lines or footer_lines):
        content = "\n".join(header_lines + footer_lines).strip()
        if content:
            chapters.append(Chapter(
                index=0,
                title=metadata.get("title") or path.stem,
                raw_text=content,
                source_file=str(path),
            ))
    elif chapters:
        if header_lines:
            chapters[0].raw_text = "\n".join(
                header_lines + [chapters[0].raw_text]
            ).strip()
        if footer_lines:
            chapters[-1].raw_text = "\n".join(
                [chapters[-1].raw_text] + footer_lines
            ).strip()

    # If style headings drove the split, pattern matches inside body text may
    # have spuriously created extra chapters — but in practice styled docs do
    # not also use literal "Chapter N" lines, and the fallback only fires on a
    # match, so we accept the combined result. The dominant signal is reported
    # in observability below.

    if not chapters:
        raise ValueError(
            f"No readable chapters found in '{path.name}'. "
            "The document may be empty or contain only very short sections. "
            f"(Current minimum: {min_chapter_words} words per chapter — "
            "lower min_chapter_words in ProjectConfig if the document has short "
            "sections.)"
        )

    if len(chapters) == 1:
        logger.warning(
            "Only one chapter found in '%s' — the whole document is being "
            "treated as a single chapter. If it should have multiple chapters, "
            "apply Word's 'Heading 1'/'Heading 2'/'Title' styles to its chapter "
            "headings, or set --lang so 'Chapter N'-style headings are detected.",
            path.name,
        )

    # Default title from filename if core properties had none.
    if "title" not in metadata:
        metadata["title"] = path.stem

    # Parse-observability summary (PARSER-C).
    profile_code = profile.code if profile is not None else "en"
    if style_headings_seen:
        heading_mode = f"styles ({style_headings_seen})"
    elif pattern_headings_seen:
        heading_mode = f"patterns ({pattern_headings_seen})"
    else:
        heading_mode = "none (single-chapter fallback)"
    logger.info(
        "Parsed DOCX '%s': %d chapter(s), profile=%s, headings=%s, tables=%d",
        path.name, len(chapters), profile_code, heading_mode, tables_seen,
    )

    return metadata, chapters
