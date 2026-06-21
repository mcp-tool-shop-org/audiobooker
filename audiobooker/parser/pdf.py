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


def _is_chapter_heading(
    line: str,
    patterns: Optional[list[re.Pattern]] = None,
) -> Optional[str]:
    """
    Check if a line looks like a chapter heading.

    Args:
        line: A single line of text.
        patterns: Compiled heading patterns to test (default: English).

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

    # All-caps line that looks like a title (3-60 chars, mostly letters)
    if (
        line.isupper()
        and 3 <= len(line) <= 60
        and sum(c.isalpha() for c in line) > len(line) * 0.5
        and not line.startswith("PAGE")
    ):
        return line.title()

    return None


def parse_pdf(
    path: Path,
    min_chapter_words: int = 50,
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
    try:
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
            "real text, the Python API accepts parse_pdf(..., force_text=True) "
            "to parse it anyway."
        )

    # Split into chapters using heading detection
    chapters: list[Chapter] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []
    headings_seen = 0

    full_text = "\n".join(page_texts)
    lines = full_text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue

        heading = _is_chapter_heading(stripped, chapter_patterns)
        if heading is not None:
            headings_seen += 1
            # Save previous chapter
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content and len(content.split()) >= min_chapter_words:
                    title = current_title or f"Chapter {len(chapters) + 1}"
                    chapters.append(Chapter(
                        index=len(chapters),
                        title=title,
                        raw_text=content,
                        source_file=str(path),
                    ))

            current_title = heading
            current_lines = []
        else:
            current_lines.append(stripped)

    # Don't forget the last section
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content and len(content.split()) >= min_chapter_words:
            title = current_title or f"Chapter {len(chapters) + 1}"
            chapters.append(Chapter(
                index=len(chapters),
                title=title,
                raw_text=content,
                source_file=str(path),
            ))

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

    # Parse-observability summary (PARSER-C).
    logger.info(
        "Parsed PDF '%s': %d chapter(s), profile=%s, headings=%s",
        path.name, len(chapters), profile_code,
        "none (single-chapter fallback)" if single_chapter and headings_seen == 0 else headings_seen,
    )

    return metadata, chapters
