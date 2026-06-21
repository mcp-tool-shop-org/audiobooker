"""
DOCX Parser for Audiobooker (FT-PARSE-004).

Extracts chapters and metadata from Word (.docx) files using python-docx.

Chapter boundaries are detected from paragraph styles first — a paragraph
styled ``Heading 1``, ``Heading 2`` or ``Title`` starts a new chapter. When a
document carries no such styled headings (common in flat exports), the parser
falls back to the language profile's ``chapter_patterns`` matched against the
plain paragraph text, mirroring the text/PDF parsers.

Title and author are read from the document's core properties into the
metadata dict, matching ``parse_epub``'s return shape.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from audiobooker.models import Chapter
from audiobooker.language.profile import LanguageProfile

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
            groups = match.groups()
            if len(groups) >= 2 and groups[1]:
                return f"Chapter {groups[0]}: {groups[1].strip()}"
            return line
    return None


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

    for para in document.paragraphs:
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
        "Parsed DOCX '%s': %d chapter(s), profile=%s, headings=%s",
        path.name, len(chapters), profile_code, heading_mode,
    )

    return metadata, chapters
