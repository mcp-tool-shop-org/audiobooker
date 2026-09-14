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


# PH-B-006: how far apart a pattern's first and last match must be, as a
# fraction of the document, before its matches count as DISTRIBUTED rather
# than CLUSTERED. A table of contents occupies a few percent of a book; real
# chapter headings span nearly all of it.
_MIN_MATCH_SPREAD = 0.25

# Scanning every line is O(lines x patterns). Above this, sample the head, the
# tail and a uniform stride through the middle instead — enough to measure both
# frequency and spread without walking a 100 MB file line by line.
_MAX_SCAN_LINES = 40_000

# Below this many matched heading lines the "matched a lot, emitted almost
# nothing" check is noise — a 3-heading file that yields 1 chapter is ordinary.
_IMPLAUSIBLE_MIN_MATCHES = 5


def _sampled_lines(lines: list[str]) -> list[tuple[int, str]]:
    """(index, line) pairs to score, covering head, tail and middle."""
    total = len(lines)
    if total <= _MAX_SCAN_LINES:
        return list(enumerate(lines))
    edge = _MAX_SCAN_LINES // 4
    picked = set(range(edge)) | set(range(total - edge, total))
    remaining = _MAX_SCAN_LINES - len(picked)
    if remaining > 0:
        stride = max(1, (total - 2 * edge) // remaining)
        picked.update(range(edge, total - edge, stride))
    return [(i, lines[i]) for i in sorted(picked)]


def detect_chapter_pattern(
    text: str,
    *,
    profile: Optional[LanguageProfile] = None,
) -> Optional[re.Pattern]:
    """
    Detect which chapter pattern is used in the text.

    Scores every profile pattern across the WHOLE document (sampled for very
    large files) and prefers a pattern whose matches are spread through the
    text over one whose matches are clustered in a single run.

    PH-B-006: this used to score only the first 200 lines and take whichever
    pattern matched most often there. On a Gutenberg-shaped file — title page,
    a 40-entry numbered contents list, then boilerplate, with the real
    ``Chapter N`` headings starting past line 200 — the numbered-list pattern
    won on a window it was the only thing visible in. A 40-chapter book parsed
    to TWO chapters, the body filed under a title lifted from the last contents
    entry, with no warning at any level. Frequency alone cannot tell a contents
    list from a book; distribution can.
    """
    chapter_patterns = _get_chapter_patterns(profile)
    if not chapter_patterns:  # Defensive: custom profiles may provide none
        return None

    lines = text.split("\n")
    total_lines = max(1, len(lines))
    counts: dict[str, int] = {p: 0 for p in chapter_patterns}
    first_at: dict[str, int] = {}
    last_at: dict[str, int] = {}

    compiled = [(p, re.compile(p, re.MULTILINE)) for p in chapter_patterns]
    for index, line in _sampled_lines(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for pattern, rx in compiled:
            if rx.match(stripped):
                counts[pattern] += 1
                first_at.setdefault(pattern, index)
                last_at[pattern] = index

    candidates = [p for p, c in counts.items() if c > 1]
    if not candidates:
        return None

    def spread(pattern: str) -> float:
        return (last_at[pattern] - first_at[pattern] + 1) / total_lines

    distributed = [p for p in candidates if spread(p) >= _MIN_MATCH_SPREAD]
    pool = distributed or candidates
    best = max(pool, key=lambda p: (counts[p], spread(p)))

    if not distributed:
        # Every candidate's matches sit in one run. That is the contents-list
        # shape; say so rather than returning a confident-looking pattern.
        logger.warning(
            "Detected chapter pattern %s matches %d times but all matches fall "
            "within lines %d-%d of %d (%.0f%% of the document) — this looks "
            "like a table of contents or an index rather than the book's "
            "headings. Check the result, and pass --chapter-delimiter if the "
            "chapters come out wrong.",
            best, counts[best], first_at[best], last_at[best], total_lines,
            100.0 * spread(best),
        )
    else:
        logger.info(
            "Detected chapter pattern (%d matches, spread over %.0f%% of the "
            "document): %s",
            counts[best], 100.0 * spread(best), best,
        )
        clustered_losers = [
            p for p in candidates
            if p not in distributed and counts[p] > counts[best]
        ]
        for loser in clustered_losers:
            logger.info(
                "Ignored chapter pattern %s: %d matches but all within lines "
                "%d-%d (%.0f%% of the document) — clustered, most likely a "
                "contents list.",
                loser, counts[loser], first_at[loser], last_at[loser],
                100.0 * spread(loser),
            )

    return re.compile(best, re.MULTILINE)


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
    matched_count = 0

    for line in lines:
        # Check if this line is a chapter delimiter
        match = pattern.match(line.strip())

        if match:
            matched_any = True
            matched_count += 1
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

    # PH-B-006: warn when the chapter count is implausible for what matched.
    #
    # A heading line only becomes a chapter if there is body text after it, so
    # a contents list — where every "heading" is immediately followed by the
    # next one — matches many times and emits almost nothing. That is exactly
    # how a 40-chapter book parsed to TWO chapters, and nothing said a word.
    if matched_count >= _IMPLAUSIBLE_MIN_MATCHES and len(chapters) * 2 < matched_count:
        logger.warning(
            "Chapter detection matched %d heading lines but produced only %d "
            "chapter(s) — most matches had no body text after them, which is "
            "what a table of contents or an index looks like. The chapters "
            "below are almost certainly wrong. Pass --chapter-delimiter with a "
            "regex matching the real headings, or strip the front matter.",
            matched_count, len(chapters),
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


# Splits a stem into alternating text / number runs so digits are compared
# numerically wherever they appear, not only as a leading prefix.
_NUM_RUN_RE = re.compile(r"(\d+)")


def _natural_sort_key(stem: str) -> tuple:
    """Sort key that orders numbers inside a filename numerically.

    "1", "01", "1.", "1_intro", "10_end" sort so 2 < 10 (not lexicographic
    "10" < "2"). Files with no numeric prefix sort after numbered ones, then
    naturally (case-insensitive).

    The number no longer has to be a LEADING prefix (PARSER-AMEND-5). The
    previous key only parsed a leading run, so a book split as
    "chapter1.txt"…"chapter12.txt" fell back to a lexicographic compare and was
    narrated 1, 10, 11, 12, 2, 3 — while the docstring advertised natural
    sorting, so the user got no signal. The whole stem is tokenized into
    alternating text and number runs and compared run by run.
    """
    m = _FILENAME_NUM_PREFIX_RE.match(stem)
    # Numbered-prefix files still sort ahead of unnumbered ones.
    group = 0 if (m and m.group(1)) else 1
    runs = tuple(
        (1, int(part), "") if part.isdigit() else (0, 0, part)
        for part in _NUM_RUN_RE.split(stem.casefold())
        if part != ""
    )
    return (group, runs)


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
