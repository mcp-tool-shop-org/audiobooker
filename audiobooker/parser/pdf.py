"""
PDF Parser for Audiobooker (FT-CORE-001).

Extracts chapters from PDF files using PyMuPDF (fitz).
Detects chapter boundaries using text heading heuristics:
- "Chapter N" / "Part N" / "Book N" / "Prologue" / "Epilogue" patterns
- All-caps lines that look like titles

Scanned PDFs are detected and rejected with a clear OCR suggestion.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from audiobooker.models import Chapter
from audiobooker.language.profile import LanguageProfile

logger = logging.getLogger("audiobooker.parser")

# Maximum PDF file size (200 MB)
_MAX_PDF_FILE_BYTES = 200 * 1024 * 1024

# English chapter heading patterns. These are the default used when no language
# profile is supplied (or the profile is English) — kept for byte-for-byte
# identical English behavior. Localized headings come from the profile's
# ``chapter_patterns`` (e.g. "Kapitel", "Capítulo", "Chapitre", "第N章").
_CHAPTER_PATTERNS = [
    re.compile(r"^Chapter\s+(\d+)\s*[:\.\-—]?\s*(.*)", re.IGNORECASE),
    re.compile(r"^CHAPTER\s+([IVXLCDM]+)\s*[:\.\-—]?\s*(.*)"),
    re.compile(r"^Part\s+(\d+|[IVXLCDM]+)\s*[:\.\-—]?\s*(.*)", re.IGNORECASE),
    re.compile(r"^Book\s+(\d+|[IVXLCDM]+)\s*[:\.\-—]?\s*(.*)", re.IGNORECASE),
    re.compile(r"^Prologue\s*$", re.IGNORECASE),
    re.compile(r"^Epilogue\s*$", re.IGNORECASE),
]

# Minimum words on a page to count as text (vs scanned image)
_MIN_TEXT_WORDS_PER_PAGE = 5

# Minimum fraction of pages that must have text to not be considered scanned
_MIN_TEXT_PAGE_FRACTION = 0.3


def _compile_chapter_patterns(
    profile: Optional[LanguageProfile],
) -> list[re.Pattern]:
    """
    Return the compiled chapter-heading patterns for ``profile``.

    English (profile is None or code == 'en') uses the module-level
    ``_CHAPTER_PATTERNS`` unchanged. Any other profile contributes its localized
    ``chapter_patterns`` first (so e.g. "Kapitel 1" matches), with the English
    patterns appended as a fallback for mixed-language books.
    """
    if profile is None or profile.code == "en":
        return _CHAPTER_PATTERNS
    compiled: list[re.Pattern] = []
    for pat in profile.chapter_patterns:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            logger.debug("Skipping invalid chapter pattern %r for %r", pat, profile.code)
    # Keep the English patterns as a fallback for mixed-language headings.
    compiled.extend(_CHAPTER_PATTERNS)
    return compiled


# Corroboration thresholds for the all-caps heading fallback (PARSER-AMEND-6).
# Print-origin PDFs carry an all-caps running head on every page and page text
# is concatenated with no header/footer removal, so an uncorroborated all-caps
# rule turns a 300-page book into ~300 identically titled chapters.
_MAX_ALLCAPS_HEADING_WORDS = 6
_ALLCAPS_TRAILING_PUNCT = (".", "!", "?", ",", ";", ":")
# A candidate seen on more than this fraction of pages is a running head.
_RUNNING_HEAD_PAGE_FRACTION = 0.25
_RUNNING_HEAD_MIN_PAGES = 4


def _is_chapter_heading(
    line: str,
    patterns: Optional[list[re.Pattern]] = None,
    *,
    isolated: bool = True,
    banned_lines: frozenset = frozenset(),
) -> Optional[str]:
    """
    Check if a line looks like a chapter heading.

    Args:
        line: A single line of text.
        patterns: Compiled heading patterns to test (default: English).
        isolated: Whether the line stands alone (blank line above and below).
            Only the all-caps fallback consults this: a typographic heading sits
            on its own, while all-caps prose ("HE SLAMMED THE DOOR") sits inside
            a paragraph. Explicit "Chapter N" patterns are unaffected.
        banned_lines: All-caps lines already identified as recurring running
            heads; never treated as headings.

    Returns the chapter title if it is, None otherwise.
    """
    if patterns is None:
        patterns = _CHAPTER_PATTERNS

    line = line.strip()
    if not line:
        return None

    # Check explicit chapter patterns
    for pattern in patterns:
        match = pattern.match(line)
        if match:
            groups = match.groups()
            if len(groups) >= 2 and groups[1]:
                return f"Chapter {groups[0]}: {groups[1].strip()}"
            elif len(groups) >= 1 and groups[0]:
                return line
            else:
                return line

    # All-caps line that looks like a title (3-60 chars, mostly letters) AND
    # carries a corroborating signal: it stands alone, is short, does not end
    # like a sentence, and is not a page-recurring running head.
    if (
        line.isupper()
        and 3 <= len(line) <= 60
        and sum(c.isalpha() for c in line) > len(line) * 0.5
        and not line.startswith("PAGE")
        and isolated
        and len(line.split()) <= _MAX_ALLCAPS_HEADING_WORDS
        and not line.endswith(_ALLCAPS_TRAILING_PUNCT)
        and line not in banned_lines
    ):
        return line.title()

    return None


def _find_running_heads(page_texts: list[str]) -> frozenset:
    """All-caps lines that recur on more than a small fraction of the pages.

    These are running heads/feet, not chapter headings (PARSER-AMEND-6).
    """
    total_pages = len(page_texts)
    if total_pages < _RUNNING_HEAD_MIN_PAGES:
        return frozenset()

    counts: dict[str, int] = {}
    for page_text in page_texts:
        seen = {
            s for s in (raw.strip() for raw in page_text.split("\n"))
            if s and s.isupper()
        }
        for s in seen:
            counts[s] = counts.get(s, 0) + 1

    limit = max(2, int(total_pages * _RUNNING_HEAD_PAGE_FRACTION))
    heads = frozenset(s for s, c in counts.items() if c > limit)
    if heads:
        logger.info(
            "Ignoring %d recurring all-caps line(s) as running heads: %s",
            len(heads), ", ".join(sorted(heads)[:3]),
        )
    return heads


def _chapters_from_outline(
    outline: list,
    page_texts: list[str],
    source: str,
    *,
    min_chapter_words: int,
    keep_titled_short_chapters: bool,
) -> Optional[list[Chapter]]:
    """Build chapters from the PDF's own outline / bookmarks (PARSER-AMEND-6).

    The outline is authored metadata, so it is a far better chapter source than
    a text heuristic. Only the top outline level is used, so a deep outline does
    not shred the book into sections. Returns None when the outline does not
    yield at least two usable chapters (caller falls back to text heuristics).
    """
    rows: list[tuple[int, str, int]] = []
    for row in outline or []:
        try:
            level, title, page = row[0], row[1], row[2]
            level = int(level)
            page_idx = int(page) - 1
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        title = str(title or "").strip()
        if not title or page_idx < 0 or page_idx >= len(page_texts):
            continue
        rows.append((level, title, page_idx))

    if len(rows) < 2:
        return None

    top_level = min(r[0] for r in rows)
    entries = [(t, p) for lvl, t, p in rows if lvl == top_level]
    entries.sort(key=lambda e: e[1])

    # One slice per page: two outline entries on the same page would otherwise
    # produce overlapping (or empty) slices.
    deduped: list[tuple[str, int]] = []
    seen_pages: set[int] = set()
    for title, page_idx in entries:
        if page_idx in seen_pages:
            continue
        seen_pages.add(page_idx)
        deduped.append((title, page_idx))

    if len(deduped) < 2:
        return None

    chapters: list[Chapter] = []
    for k, (title, start_page) in enumerate(deduped):
        end_page = deduped[k + 1][1] if k + 1 < len(deduped) else len(page_texts)
        content = "\n".join(
            line.strip() for line in "\n".join(page_texts[start_page:end_page]).split("\n")
        ).strip()
        word_count = len(content.split())
        if word_count == 0:
            logger.info("Dropping empty PDF outline section: %r", title)
            continue
        if word_count < min_chapter_words:
            if keep_titled_short_chapters:
                logger.info(
                    "Keeping short titled section: %r (%d words < %d threshold)",
                    title, word_count, min_chapter_words,
                )
            else:
                logger.info(
                    "Skipping short section: %r (%d words < %d threshold)",
                    title, word_count, min_chapter_words,
                )
                continue
        chapters.append(Chapter(
            index=len(chapters),
            title=title,
            raw_text=content,
            source_file=source,
        ))

    if len(chapters) < 2:
        return None
    return chapters


def parse_pdf(
    path: Path,
    min_chapter_words: int = 50,
    keep_titled_short_chapters: bool = False,
    *,
    profile: Optional[LanguageProfile] = None,
    force_text: bool = False,
) -> tuple[dict, list[Chapter]]:
    """
    Parse a PDF file into chapters.

    Uses PyMuPDF (fitz) for text extraction with lazy import.
    Detects chapter boundaries using text heading heuristics
    ("Chapter N"/"Part N"/"Prologue" patterns and all-caps title lines).
    Chapter-heading words are localized via ``profile`` (e.g. "Kapitel",
    "Capítulo", "Chapitre", "第N章"); English is used when ``profile`` is None.
    PDFs that look scanned (little/no extractable text) are rejected with a
    clear OCR suggestion unless ``force_text`` is set.

    Args:
        path: Path to PDF file.
        min_chapter_words: Minimum word count for a section to be kept.
        keep_titled_short_chapters: Keep short sections that have a detected
            title, mirroring ``parse_epub``. Defaults to False, which is the
            historical PDF behavior — but the drop is now LOGGED either way
            (PARSER-AMEND-7): a short prologue, dedication, or poem used to
            vanish from the audiobook with no signal at all, while
            ``parse_epub``/``parse_docx`` both logged the equivalent.
        profile: Language profile for chapter-heading detection (default English).
        force_text: Parse even when the PDF looks scanned/sparse. Use this for a
            legitimately sparse PDF (lots of blank or figure-only pages) that
            still has real text you want extracted.

    Returns:
        Tuple of (metadata dict, list of Chapters).

    Raises:
        ImportError: If pymupdf is not installed.
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the PDF is scanned/image-only or corrupt.
    """
    chapter_patterns = _compile_chapter_patterns(profile)
    profile_code = profile.code if profile is not None else "en"
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError(
            "pymupdf is required for PDF parsing. "
            "Install with: pip install pymupdf"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    # Size guard
    file_size = path.stat().st_size
    if file_size > _MAX_PDF_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise ValueError(
            f"PDF file is too large ({size_mb:.1f} MB, limit is 200 MB). "
            "Consider splitting the PDF into smaller parts."
        )

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise ValueError(
            f"Cannot open '{path.name}': {e}. "
            "The file may be corrupted, password-protected, or not a valid PDF."
        ) from e

    # Extract metadata and page text. Use try/finally so the document handle
    # is always closed even if extraction raises mid-loop — otherwise a leaked
    # handle keeps a file lock on Windows (PARSER-A-002).
    metadata: dict = {}
    page_texts: list[str] = []
    pages_with_text = 0
    outline: list = []
    try:
        # The PDF's own outline is authored metadata and beats any text
        # heuristic — read it before the handle is closed (PARSER-AMEND-6).
        get_toc = getattr(doc, "get_toc", None)
        if callable(get_toc):
            try:
                outline = list(get_toc(simple=True) or [])
            except Exception as e:  # malformed/absent outline must not abort
                logger.debug("PDF outline unavailable for '%s': %s", path.name, e)

        pdf_meta = doc.metadata or {}
        if pdf_meta.get("title"):
            metadata["title"] = pdf_meta["title"]
        if pdf_meta.get("author"):
            metadata["author"] = pdf_meta["author"]
        if pdf_meta.get("subject"):
            metadata["subject"] = pdf_meta["subject"]

        # Extract text from all pages
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                text = page.get_text("text")
            except Exception as e:
                # Skip the bad page rather than aborting the whole document.
                logger.warning(
                    "Skipping page %d of '%s' — text extraction failed: %s",
                    page_num + 1, path.name, e,
                )
                text = ""
            page_texts.append(text)
            if len(text.split()) >= _MIN_TEXT_WORDS_PER_PAGE:
                pages_with_text += 1
    finally:
        doc.close()

    # Detect scanned PDFs. This is a heuristic (fraction of pages with text),
    # so it can misfire on legitimately sparse PDFs — force_text lets the user
    # override it.
    total_pages = len(page_texts)
    total_words = sum(len(t.split()) for t in page_texts)
    looks_scanned = (
        total_pages > 0 and pages_with_text / total_pages < _MIN_TEXT_PAGE_FRACTION
    )
    if looks_scanned and force_text:
        logger.warning(
            "'%s' looks scanned (%d/%d pages with text, %d words extractable) "
            "but force_text=True — parsing anyway.",
            path.name, pages_with_text, total_pages, total_words,
        )
    elif looks_scanned:
        raise ValueError(
            f"'{path.name}': most pages contain little or no extractable text "
            f"({pages_with_text}/{total_pages} pages, {total_words} words total) "
            "— this is usually a scanned or image-only PDF. "
            "If it really is scanned, run OCR first using one of:\n"
            "  - ocrmypdf: ocrmypdf input.pdf output.pdf\n"
            "  - Adobe Acrobat: File → Save As Other → Searchable PDF\n"
            "  - Google Drive: upload PDF, open as Google Doc, download as PDF\n"
            "If the PDF is just sparse (mostly blank or figure pages) but has "
            "real text, pass --force-text to parse it anyway."
        )

    # Split into chapters. The PDF outline is the primary source; text heading
    # heuristics are the fallback when there is no usable outline
    # (PARSER-AMEND-6).
    chapters: list[Chapter] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []
    headings_seen = 0
    split_source = "text-heuristics"

    outline_chapters = _chapters_from_outline(
        outline,
        page_texts,
        str(path),
        min_chapter_words=min_chapter_words,
        keep_titled_short_chapters=keep_titled_short_chapters,
    )
    if outline_chapters:
        chapters = outline_chapters
        split_source = "outline"
        logger.info(
            "Using PDF outline for chapter boundaries (%d entries -> %d chapters).",
            len(outline), len(chapters),
        )

    full_text = "\n".join(page_texts)
    lines = full_text.split("\n")
    banned_lines = frozenset() if chapters else _find_running_heads(page_texts)

    def _emit_section(section_lines: list[str], title: Optional[str]) -> None:
        """Close out one detected section, logging any short-section drop."""
        content = "\n".join(section_lines).strip()
        if not content:
            return
        word_count = len(content.split())
        label = title or f"Chapter {len(chapters) + 1}"
        if word_count < min_chapter_words:
            # PARSER-AMEND-7: parse_epub logs this and parse_docx logs an
            # equivalent; parse_pdf discarded the section with no log at all,
            # so a short prologue/dedication/poem simply vanished.
            if title and keep_titled_short_chapters:
                logger.info(
                    "Keeping short titled section: %r "
                    "(%d words < %d threshold)",
                    label, word_count, min_chapter_words,
                )
            else:
                logger.info(
                    "Skipping short section: %r (%d words < %d threshold)",
                    label, word_count, min_chapter_words,
                )
                return
        chapters.append(Chapter(
            index=len(chapters),
            title=label,
            raw_text=content,
            source_file=str(path),
        ))

    if not chapters:
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                current_lines.append("")
                continue

            # A typographic heading stands alone; all-caps prose does not.
            prev_blank = idx == 0 or not lines[idx - 1].strip()
            next_blank = idx + 1 >= len(lines) or not lines[idx + 1].strip()

            heading = _is_chapter_heading(
                stripped,
                chapter_patterns,
                isolated=prev_blank and next_blank,
                banned_lines=banned_lines,
            )
            if heading is not None:
                headings_seen += 1
                # Save previous chapter
                if current_lines:
                    _emit_section(current_lines, current_title)

                current_title = heading
                current_lines = []
            else:
                current_lines.append(stripped)

        # Don't forget the last section
        if current_lines:
            _emit_section(current_lines, current_title)

    # If no chapter breaks detected, treat the whole thing as one chapter.
    used_empty_fallback = False
    if not chapters:
        content = "\n".join(line.strip() for line in lines).strip()
        if content and len(content.split()) >= min_chapter_words:
            title = metadata.get("title", path.stem)
            chapters.append(Chapter(
                index=0,
                title=title,
                raw_text=content,
                source_file=str(path),
            ))
            used_empty_fallback = True

    if not chapters:
        raise ValueError(
            f"No readable chapters found in '{path.name}'. "
            "The PDF may be empty, password-protected, or contain only images. "
            f"(Current minimum: {min_chapter_words} words per chapter.)"
        )

    # Warn when chapter detection found nothing and the whole file became one
    # chapter. This covers both the explicit empty-fallback above and the main
    # loop producing a single untitled section. Distinguish a genuinely
    # single-chapter file (no headings at all) from a detection miss (headings
    # present but none split the document).
    single_chapter = len(chapters) == 1
    if single_chapter and headings_seen == 0:
        logger.warning(
            "No chapter headings detected in '%s' — treating the whole PDF "
            "as a single chapter. If it has chapters, check that the heading "
            "style is recognized (e.g. 'Chapter 1', 'Kapitel 1') or set "
            "--lang to the book's language.",
            path.name,
        )
    elif single_chapter and used_empty_fallback:
        logger.warning(
            "Chapter headings were seen in '%s' but none split into separate "
            "chapters — treating the whole PDF as a single chapter. The "
            "headings may not match a recurring style; check heading "
            "formatting or set --lang to the book's language.",
            path.name,
        )

    # Default title from filename if not in metadata
    if "title" not in metadata:
        metadata["title"] = path.stem

    # PARSER-AMEND-6: make a suspicious split visible BEFORE rendering. A
    # running head promoted to a heading yields roughly one chapter per page.
    if total_pages >= 5 and len(chapters) > max(3, total_pages * 0.5):
        logger.warning(
            "Detected %d chapter(s) across %d page(s) of '%s' — heading "
            "detection may be latching onto a running head or a per-page "
            "title. Check the chapter list before rendering.",
            len(chapters), total_pages, path.name,
        )

    # Parse-observability summary (PARSER-C).
    logger.info(
        "Parsed PDF '%s': %d chapter(s), profile=%s, source=%s, headings=%s",
        path.name, len(chapters), profile_code, split_source,
        "none (single-chapter fallback)" if single_chapter and headings_seen == 0 else headings_seen,
    )

    return metadata, chapters
