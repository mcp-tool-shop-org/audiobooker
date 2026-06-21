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

logger = logging.getLogger("audiobooker.parser")

# Maximum PDF file size (200 MB)
_MAX_PDF_FILE_BYTES = 200 * 1024 * 1024

# Chapter heading patterns
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


def _is_chapter_heading(line: str) -> Optional[str]:
    """
    Check if a line looks like a chapter heading.

    Returns the chapter title if it is, None otherwise.
    """
    line = line.strip()
    if not line:
        return None

    # Check explicit chapter patterns
    for pattern in _CHAPTER_PATTERNS:
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
) -> tuple[dict, list[Chapter]]:
    """
    Parse a PDF file into chapters.

    Uses PyMuPDF (fitz) for text extraction with lazy import.
    Detects chapter boundaries using text heading heuristics
    ("Chapter N"/"Part N"/"Prologue" patterns and all-caps title lines).
    Scanned PDFs are detected and rejected with a clear OCR suggestion.

    Args:
        path: Path to PDF file.
        min_chapter_words: Minimum word count for a section to be kept.

    Returns:
        Tuple of (metadata dict, list of Chapters).

    Raises:
        ImportError: If pymupdf is not installed.
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the PDF is scanned/image-only or corrupt.
    """
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

    # Detect scanned PDFs
    total_pages = len(page_texts)
    if total_pages > 0 and pages_with_text / total_pages < _MIN_TEXT_PAGE_FRACTION:
        raise ValueError(
            f"'{path.name}' appears to be a scanned PDF — "
            f"only {pages_with_text}/{total_pages} pages contain extractable text. "
            "Audiobooker cannot process scanned/image-only PDFs directly. "
            "Please run OCR first using one of:\n"
            "  - ocrmypdf: ocrmypdf input.pdf output.pdf\n"
            "  - Adobe Acrobat: File → Save As Other → Searchable PDF\n"
            "  - Google Drive: upload PDF, open as Google Doc, download as PDF"
        )

    # Split into chapters using heading detection
    chapters: list[Chapter] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []

    full_text = "\n".join(page_texts)
    lines = full_text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue

        heading = _is_chapter_heading(stripped)
        if heading is not None:
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

    # If no chapter breaks detected, treat the whole thing as one chapter
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

    if not chapters:
        raise ValueError(
            f"No readable chapters found in '{path.name}'. "
            "The PDF may be empty, password-protected, or contain only images. "
            f"(Current minimum: {min_chapter_words} words per chapter.)"
        )

    # Default title from filename if not in metadata
    if "title" not in metadata:
        metadata["title"] = path.stem

    return metadata, chapters
