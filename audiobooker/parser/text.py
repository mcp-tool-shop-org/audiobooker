"""
Text/Markdown Parser for Audiobooker.

Parses plain text and Markdown files into chapters.
Supports various chapter delimiter patterns.

Chapter heading and scene-break patterns are drawn from a LanguageProfile.
Default is English.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from audiobooker.models import Chapter
from audiobooker.language.profile import LanguageProfile, get_profile
from audiobooker.parser.text_cleaners import strip_markdown_inline

logger = logging.getLogger("audiobooker.parser")

# Maximum file size for parse_text (100 MB)
_MAX_TEXT_FILE_BYTES = 100 * 1024 * 1024

# Extensions treated as Markdown — these get strip_markdown_inline applied so
# **bold**, [links](url), `code`, list markers and '>' blockquotes are unwrapped
# to their spoken text (FT-PARSE-007). Plain .txt is intentionally NOT in this
# set: legitimate asterisks/underscores there must survive untouched.
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})


def _get_chapter_patterns(profile: Optional[LanguageProfile] = None) -> list[str]:
    """Return chapter patterns from the given profile (default: English)."""
    if profile is None:
        profile = get_profile("en")
    return list(profile.chapter_patterns)


def _get_scene_break_patterns(profile: Optional[LanguageProfile] = None) -> list[str]:
    """Return scene break patterns from the given profile (default: English)."""
    if profile is None:
        profile = get_profile("en")
    return list(profile.scene_break_patterns)


def detect_chapter_pattern(
    text: str,
    *,
    profile: Optional[LanguageProfile] = None,
) -> Optional[re.Pattern]:
    """
    Detect which chapter pattern is used in the text.

    Scans the text and returns the most commonly matching pattern.
    """
    chapter_patterns = _get_chapter_patterns(profile)
    pattern_counts = {pattern: 0 for pattern in chapter_patterns}

    for line in text.split("\n")[:200]:  # Check first 200 lines
        line = line.strip()
        if not line:
            continue
        for pattern in chapter_patterns:
            if re.match(pattern, line, re.MULTILINE):
                pattern_counts[pattern] += 1

    # Return pattern with most matches (if > 1)
    if not pattern_counts:  # Defensive: empty when custom profiles provide no patterns
        return None
    best_pattern = max(pattern_counts, key=pattern_counts.get)
    if pattern_counts[best_pattern] > 1:
        logger.info(
            "Detected chapter pattern (%d matches): %s",
            pattern_counts[best_pattern], best_pattern,
        )
        return re.compile(best_pattern, re.MULTILINE)

    return None


def is_scene_break(
    line: str,
    *,
    profile: Optional[LanguageProfile] = None,
) -> bool:
    """Check if a line is a scene break (not a chapter break)."""
    line = line.strip()
    for pattern in _get_scene_break_patterns(profile):
        if re.match(pattern, line):
            return True
    return False


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter if present.

    Returns:
        Tuple of (metadata dict, remaining text)
    """
    metadata = {}

    # Check for YAML frontmatter
    if text.startswith("---"):
        end_match = re.search(r"\n---\s*(?:\n|$)", text[3:])
        if end_match:
            frontmatter = text[3:end_match.start() + 3]
            remaining = text[end_match.end() + 3:]

            # Simple YAML parsing (key: value)
            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    metadata[key] = value

            return metadata, remaining

    return metadata, text


def split_into_chapters(
    text: str,
    delimiter_pattern: Optional[str] = None,
    *,
    profile: Optional[LanguageProfile] = None,
) -> list[tuple[str, str]]:
    """
    Split text into chapters using delimiter pattern.

    Args:
        text: Full text content
        delimiter_pattern: Optional custom regex pattern
        profile: Language profile (defaults to English)

    Returns:
        List of (title, content) tuples
    """
    if delimiter_pattern:
        try:
            pattern = re.compile(delimiter_pattern, re.MULTILINE)
        except re.error as e:
            raise ValueError(
                f"Invalid chapter delimiter regex: {delimiter_pattern!r} — {e}. "
                "Check your pattern for unbalanced parentheses, bad escapes, "
                "or unsupported syntax."
            ) from e
    else:
        pattern = detect_chapter_pattern(text, profile=profile)

    if pattern is None:
        # No chapters detected - treat as single chapter. Warn so the user knows
        # detection found nothing rather than silently assuming one chapter.
        if delimiter_pattern:
            logger.warning(
                "Chapter delimiter %r matched no lines — treating the whole file "
                "as a single chapter. Check the pattern against your headings.",
                delimiter_pattern,
            )
        else:
            logger.warning(
                "No chapter headings detected — treating the whole file as a "
                "single chapter. If it has chapters, check that the heading style "
                "is recognized (e.g. 'Chapter 1', '# Title'), set --lang to the "
                "file's language, or pass --chapter-delimiter with a custom regex "
                "matching your headings.",
            )
        return [("Chapter 1", text)]

    chapters = []
    lines = text.split("\n")
    current_title = None
    current_content = []
    matched_any = False

    for line in lines:
        # Check if this line is a chapter delimiter
        match = pattern.match(line.strip())

        if match:
            matched_any = True
            # Save previous chapter if exists
            if current_title is not None or current_content:
                title = current_title or "Untitled"
                content = "\n".join(current_content).strip()
                if content:
                    chapters.append((title, content))

            # Start new chapter
            groups = match.groups()
            if len(groups) >= 2 and groups[1]:
                # Pattern has chapter number and title
                current_title = f"Chapter {groups[0]}: {groups[1]}"
            elif len(groups) >= 1:
                current_title = groups[0] if groups[0] else line.strip()
            else:
                current_title = line.strip()

            current_content = []
        else:
            # Add to current chapter
            current_content.append(line)

    # Don't forget the last chapter
    if current_title is not None or current_content:
        title = current_title or "Untitled"
        content = "\n".join(current_content).strip()
        if content:
            chapters.append((title, content))

    # An explicit delimiter that matched no line yields a single untitled
    # chapter — warn so the user knows their pattern did nothing.
    if delimiter_pattern and not matched_any:
        logger.warning(
            "Chapter delimiter %r matched no lines — treating the whole file "
            "as a single chapter. Check the pattern against your headings.",
            delimiter_pattern,
        )

    return chapters


def parse_text(
    path: Path,
    chapter_delimiter: Optional[str] = None,
    *,
    profile: Optional[LanguageProfile] = None,
) -> tuple[dict, list[Chapter]]:
    """
    Parse a text or Markdown file into chapters.

    Args:
        path: Path to text file
        chapter_delimiter: Optional custom delimiter pattern
        profile: Language profile (defaults to English)

    Returns:
        Tuple of (metadata dict, list of Chapters)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")

    # F-CORE-B-001: Reject files larger than 100 MB
    file_size = path.stat().st_size
    if file_size > _MAX_TEXT_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise ValueError(
            f"Text file is too large ({size_mb:.1f} MB, limit is 100 MB). "
            "Consider splitting the file into smaller parts — most text editors "
            "have a split-by-size or split-by-chapter feature. You can then "
            "process each part separately."
        )

    # F-CORE-B-002 + BOM sniff: honor a UTF-16 LE/BE or UTF-8 BOM before falling
    # back to strict UTF-8. Notepad's "Unicode" save format is UTF-16 LE with a
    # BOM, which strict utf-8 would reject; the same BOM handling the EPUB parser
    # uses lets those files work.
    raw = path.read_bytes()
    if not raw:
        raise ValueError(
            f"'{path.name}' is empty — no text to convert."
        )
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            # "utf-16" consumes the BOM and infers LE/BE from it.
            text = raw.decode("utf-16")
        elif raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        else:
            text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(
            f"Cannot read '{path.name}' — the file is not valid UTF-8 (error at byte {e.start}). "
            "Please convert it to UTF-8 first. Common tools:\n"
            "  - Notepad++: Encoding → Convert to UTF-8\n"
            "  - VS Code: click the encoding in the status bar → 'Reopen with Encoding' / 'Save with Encoding'\n"
            "  - CLI: iconv -f LATIN1 -t UTF-8 input.txt > output.txt"
        ) from e

    # Extract frontmatter if present
    metadata, text = extract_frontmatter(text)

    # Default title from filename
    if "title" not in metadata:
        metadata["title"] = path.stem

    # Split into chapters
    chapter_data = split_into_chapters(text, chapter_delimiter, profile=profile)

    # FT-PARSE-007: For Markdown input, unwrap inline formatting (**bold**,
    # [links](url), `code`, fenced blocks, list markers, blockquotes) to the
    # spoken text. Gated on the extension so plain .txt with real asterisks is
    # left alone.
    is_markdown = path.suffix.lower() in _MARKDOWN_SUFFIXES

    # Create Chapter objects
    chapters = []
    for i, (title, content) in enumerate(chapter_data):
        if is_markdown:
            content = strip_markdown_inline(content)
        chapter = Chapter(
            index=i,
            title=title,
            raw_text=content,
            source_file=str(path),
        )
        chapters.append(chapter)

    # Parse-observability summary (PARSER-C).
    profile_code = profile.code if profile is not None else "en"
    single_chapter = len(chapters) == 1 and chapters[0].title == "Chapter 1"
    logger.info(
        "Parsed text '%s': %d chapter(s), profile=%s, headings=%s",
        path.name, len(chapters), profile_code,
        "none (single-chapter fallback)" if single_chapter else "detected",
    )

    return metadata, chapters


# ---------------------------------------------------------------------------
# Folder input (FT-PARSE-005)
# ---------------------------------------------------------------------------

# Splits a leading chapter-number prefix off a filename stem so files like
# "01_intro", "1. The Road", "10-finale" sort and title correctly. Captures the
# number and the human title remainder.
_FILENAME_NUM_PREFIX_RE = re.compile(
    r"^\s*(\d+)\s*[._\-)]*\s*(.*)$"
)


def _natural_sort_key(stem: str) -> tuple:
    """Sort key that orders numeric filename prefixes numerically.

    "1", "01", "1.", "1_intro", "10_end" sort so 2 < 10 (not lexicographic
    "10" < "2"). Files with no numeric prefix sort after numbered ones, then
    alphabetically (case-insensitive).
    """
    m = _FILENAME_NUM_PREFIX_RE.match(stem)
    if m and m.group(1):
        # (0 => numbered first) , numeric value, then remainder for ties.
        return (0, int(m.group(1)), m.group(2).casefold())
    return (1, 0, stem.casefold())


def _title_from_stem(stem: str) -> str:
    """Derive a readable chapter title from a filename stem.

    Strips a leading numeric/ordinal prefix ("01_", "1.", "10-"), replaces
    underscores/hyphens with spaces, collapses whitespace, and title-cases when
    the result has no existing capitalization.
    """
    m = _FILENAME_NUM_PREFIX_RE.match(stem)
    remainder = m.group(2) if (m and m.group(1)) else stem
    if not remainder.strip():
        # Pure-number filename like "01" -> "Chapter 1".
        if m and m.group(1):
            return f"Chapter {int(m.group(1))}"
        remainder = stem
    cleaned = re.sub(r"[_\-]+", " ", remainder)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return stem
    # Title-case only if it looks all-lowercase (preserve intentional casing).
    if cleaned == cleaned.lower():
        cleaned = cleaned.title()
    return cleaned


def read_folder_chapters(
    directory,
    *,
    pattern: str = "*.txt;*.md",
    profile: Optional[LanguageProfile] = None,
) -> list[tuple[str, str]]:
    """Read a directory of per-chapter files into ordered (title, text) pairs.

    Each matching file becomes one chapter, in natural-sorted order so
    "01_intro", "2_middle", "10_end" order numerically rather than
    lexicographically.

    Args:
        directory: Folder containing one file per chapter.
        pattern: Semicolon-separated glob(s) of files to include
            (default ``"*.txt;*.md"``). Globs are matched case-insensitively
            against the filename.
        profile: Language profile, threaded through for parity with the other
            parsers (Markdown stripping and frontmatter handling do not need it,
            but callers pass it uniformly).

    Returns:
        List of ``(title, text)`` tuples in reading order. The title is derived
        from the cleaned filename, unless the file has YAML frontmatter with a
        ``title:`` key, which wins.

    Raises:
        FileNotFoundError: If the directory does not exist.
        ValueError: If the directory contains no files matching ``pattern``.
    """
    folder = Path(directory)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")

    globs = [g.strip() for g in pattern.split(";") if g.strip()]
    if not globs:
        globs = ["*.txt", "*.md"]

    # Collect matching files. Match case-insensitively by lowercasing both the
    # glob suffix and the filename so ".TXT"/".Md" are picked up on every OS.
    import fnmatch

    seen: set[Path] = set()
    matched: list[Path] = []
    for entry in folder.iterdir():
        if not entry.is_file():
            continue
        name_lower = entry.name.lower()
        for g in globs:
            if fnmatch.fnmatch(name_lower, g.lower()):
                if entry not in seen:
                    seen.add(entry)
                    matched.append(entry)
                break

    if not matched:
        raise ValueError(
            f"No files matching {pattern!r} found in '{folder}'. "
            "Folder input expects one text/Markdown file per chapter "
            "(e.g. 01_intro.txt, 02_chapter.md). Check the folder path and the "
            "--pattern glob."
        )

    matched.sort(key=lambda p: _natural_sort_key(p.stem))

    chapters: list[tuple[str, str]] = []
    for file_path in matched:
        raw = file_path.read_bytes()
        if not raw:
            logger.warning("Skipping empty file in folder input: %s", file_path.name)
            continue
        # Honor BOM-prefixed UTF-16/UTF-8 the same way parse_text does.
        try:
            if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                content = raw.decode("utf-16")
            elif raw.startswith(b"\xef\xbb\xbf"):
                content = raw.decode("utf-8-sig")
            else:
                content = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(
                f"Cannot read '{file_path.name}' — the file is not valid UTF-8 "
                f"(error at byte {e.start}). Convert it to UTF-8 first."
            ) from e

        # Frontmatter title (if any) wins over the filename-derived title.
        fm_meta, body = extract_frontmatter(content)
        title = fm_meta.get("title") or _title_from_stem(file_path.stem)

        # Markdown files get inline formatting unwrapped to spoken text.
        if file_path.suffix.lower() in _MARKDOWN_SUFFIXES:
            body = strip_markdown_inline(body)

        chapters.append((title, body.strip()))

    if not chapters:
        raise ValueError(
            f"All matching files in '{folder}' were empty — no text to convert."
        )

    profile_code = profile.code if profile is not None else "en"
    logger.info(
        "Read folder '%s': %d chapter file(s), profile=%s, pattern=%s",
        folder.name, len(chapters), profile_code, pattern,
    )

    return chapters
