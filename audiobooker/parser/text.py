"""
Text/Markdown Parser for Audiobooker.

Parses plain text and Markdown files into chapters.
Supports various chapter delimiter patterns.

Chapter heading and scene-break patterns are drawn from a LanguageProfile.
Default is English.
"""

import logging
import re
import statistics
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

# FEAT-IN-007: sections headed by a bare numeral — "I / II / III" or
# "1 / 2 / 3" with no heading word at all — are common in literary fiction and
# in translated classics. No language profile can carry a pattern for them:
# ``^\d+$`` in a profile would match every page number in every book. They are
# therefore a language-neutral LAST-RESORT tier, scored only when no profile
# pattern produced a candidate, and admitted only when the matches look like
# chapters rather than pagination.
_BARE_NUMERAL_PATTERNS = (
    r"^([IVXLCDM]{1,7})$",
    r"^(\d{1,3})$",
)

# Longest bare numeral we will even look at (keeps the scan near-free).
_BARE_NUMERAL_MAX_LEN = 7

# Above this many bare-numeral matches the document is paginated, not
# chaptered — a 300-page book carries ~300 page numbers and ~30 chapters.
_MAX_BARE_NUMERAL_SECTIONS = 60

# Median words between consecutive bare numerals before they count as chapter
# breaks. Measured against book-scale fixtures: a typeset page carries ~250-350
# words (310 in the fixture), a bare-numeral chapter ~2600, and even a short
# vignette section ~650. 400 sits above the page ceiling and well below the
# shortest plausible section.
_MIN_BARE_NUMERAL_SECTION_WORDS = 400

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(text: str) -> Optional[int]:
    """Value of an uppercase Roman numeral, or None if it is not one."""
    total = 0
    previous = 0
    for char in reversed(text):
        value = _ROMAN_VALUES.get(char)
        if value is None:
            return None
        total += -value if value < previous else value
        previous = max(previous, value)
    return total or None


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


def _bare_numeral_candidate(lines: list[str], total_lines: int) -> Optional[str]:
    """Last-resort pattern for sections headed by a bare numeral (FEAT-IN-007).

    Returns the winning pattern string, or None when the bare numerals in the
    document look like pagination (or like nothing at all) rather than chapter
    breaks. Four guards, all of which must hold:

    * the numerals form a consecutive run starting at 1 / I,
    * there are at most ``_MAX_BARE_NUMERAL_SECTIONS`` of them,
    * their matches are DISTRIBUTED through the document (the same spread test
      the profile patterns get), and
    * the median gap between them is at least
      ``_MIN_BARE_NUMERAL_SECTION_WORDS`` words — the test that actually
      separates a chapter break from a page number.
    """
    best: Optional[tuple[int, float, str]] = None

    for pattern in _BARE_NUMERAL_PATTERNS:
        rx = re.compile(pattern)
        hits: list[tuple[int, int]] = []
        too_many = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            # Cheap pre-filter: a bare numeral is a very short line.
            if not stripped or len(stripped) > _BARE_NUMERAL_MAX_LEN:
                continue
            if not rx.match(stripped):
                continue
            value = int(stripped) if stripped.isdigit() else _roman_to_int(stripped)
            if value is None:
                continue
            hits.append((index, value))
            if len(hits) > _MAX_BARE_NUMERAL_SECTIONS:
                too_many = True
                break

        if too_many:
            logger.debug(
                "Bare-numeral pattern %s matched more than %d lines — that is "
                "pagination, not chapters.", pattern, _MAX_BARE_NUMERAL_SECTIONS,
            )
            continue
        if len(hits) < 2:
            continue

        values = [v for _, v in hits]
        if values != list(range(1, len(values) + 1)):
            logger.debug(
                "Bare-numeral pattern %s matched %d lines but they are not a "
                "consecutive run from 1 (%s…) — not chapter numbering.",
                pattern, len(values), values[:5],
            )
            continue

        positions = [i for i, _ in hits]
        spread = (positions[-1] - positions[0] + 1) / max(1, total_lines)
        if spread < _MIN_MATCH_SPREAD:
            continue

        # Count words per line rather than joining the slices: on a 100 MB
        # file the join would copy the whole document.
        word_gaps = [
            sum(len(lines[k].split()) for k in range(a + 1, b))
            for a, b in zip(positions, positions[1:])
        ]
        median_gap = statistics.median(word_gaps)
        if median_gap < _MIN_BARE_NUMERAL_SECTION_WORDS:
            logger.debug(
                "Bare-numeral pattern %s matched %d lines but the median gap "
                "is only %.0f words (< %d) — those are page numbers, not "
                "chapter headings.",
                pattern, len(positions), median_gap,
                _MIN_BARE_NUMERAL_SECTION_WORDS,
            )
            continue

        score = (len(positions), spread, pattern)
        if best is None or score[:2] > best[:2]:
            best = score

    if best is None:
        return None

    logger.warning(
        "No chapter-heading words were found in this document, but %d "
        "bare-numeral section headings were (pattern %s). Treating them as "
        "chapter breaks. If they are page numbers or verse numbers, pass "
        "--chapter-delimiter with a regex matching the real headings.",
        best[0], best[2],
    )
    return best[2]


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
        # FEAT-IN-007: nothing in the profile matched. Before giving up (and
        # narrating the whole book as one chapter), try the language-neutral
        # bare-numeral tier — "I / II / III" and "1 / 2 / 3" section heads.
        # It is deliberately last-resort: a bare-numeral pattern outscores
        # every real heading pattern on any paginated document, so it must
        # never compete with one.
        bare = _bare_numeral_candidate(lines, total_lines)
        if bare is not None:
            return re.compile(bare, re.MULTILINE)
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


def format_parse_summary(
    words_kept: int,
    dropped_reasons: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> str:
    """PARSER-C one-liner: words kept vs dropped, plus optional extras.

    ``dropped_reasons`` maps a short reason token to a word count (or a
    count of items when words are not available). Zero/empty reasons are
    omitted; if none remain the field is ``none``.
    """
    reasons = {
        str(key): int(value)
        for key, value in (dropped_reasons or {}).items()
        if value
    }
    words_dropped = sum(reasons.values())
    reason_field = ",".join(f"{k}:{v}" for k, v in reasons.items()) or "none"
    parts = [
        f"words_kept={int(words_kept)}",
        f"words_dropped={words_dropped}",
        f"dropped_reasons={reason_field}",
    ]
    for key, value in (extra or {}).items():
        if value:
            parts.append(f"{key}={int(value)}")
    return ", ".join(parts)


def compose_chapter_title(line: str, match: "re.Match") -> str:
    """Build a chapter title from a heading line and its pattern match.

    FEAT-IN-006. A chapter pattern's capture groups hold the chapter NUMBER
    and (optionally) a subtitle — not the title. ``split_into_chapters`` used
    the first capture on its own whenever there was no subtitle, so
    ``Chapter 1`` was titled ``1``, ``Capítulo Uno`` was titled ``Uno``, and
    the subtitle separator ``[:\\-\\.]`` swallowing the hyphen inside a
    compound spelled-out number turned ``CHAPTER TWENTY-ONE`` into
    ``Chapter TWENTY: ONE``.

    The rule is the one a reader would apply: if the heading line carries any
    word the pattern did NOT capture — ``Chapter``, ``Capítulo``, ``Part`` —
    the line is already a complete, correctly-worded title, so use it
    verbatim. That fixes all seven language profiles at once, and it stops
    ``Capítulo Uno: El Puerto`` being re-titled in English as
    ``Chapter Uno: El Puerto``. Only when the non-captured text is pure
    punctuation (``# One``, ``1. The Harbour``) are the captures composed.

    ``line`` must be the exact string that ``match`` was produced from — the
    group offsets are indices into it.
    """
    groups = match.groups()
    if not groups:
        return line

    # Reconstruct the parts of the heading the pattern did not capture.
    spans = sorted(
        (match.start(i), match.end(i))
        for i in range(1, len(groups) + 1)
        if match.start(i) >= 0
    )
    leftover_parts: list[str] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            leftover_parts.append(line[cursor:start])
        cursor = max(cursor, end)
    leftover_parts.append(line[cursor:])
    leftover = "".join(leftover_parts)

    if any(ch.isalpha() for ch in leftover):
        # "Chapter 1", "CHAPTER TWENTY-ONE", "Capítulo Uno: El Puerto" — the
        # heading word lives outside the captures, so the line IS the title.
        return line

    number = (groups[0] or "").strip()
    subtitle = (groups[1] or "").strip() if len(groups) >= 2 else ""
    if number and subtitle:
        return f"Chapter {number}: {subtitle}"
    return subtitle or number or line


# FEAT-IN-004: Project Gutenberg brackets the actual work with these literal
# markers. Everything before the START line is the legal header and title
# page; everything from the END line on is the licence. Both variants ("THE"
# in modern files, "THIS" in older ones) are accepted. Older dumps spell
# ETEXT rather than EBOOK; HTML-wrapped dumps put the marker inside a <p>.
# The early-return needle is casefolded so title-case "Project Gutenberg"
# still reaches the IGNORECASE regex (F-4e188049).
_PG_MARKER = "project gutenberg"
_PG_START_RE = re.compile(
    r"\*\*\*[ \t]*START OF (?:THE|THIS) PROJECT GUTENBERG (?:EBOOK|ETEXT)\b[^\n]*",
    re.IGNORECASE,
)
_PG_END_RE = re.compile(
    r"\*\*\*[ \t]*END OF (?:THE|THIS) PROJECT GUTENBERG (?:EBOOK|ETEXT)\b[^\n]*",
    re.IGNORECASE,
)

# Refuse to trim down to less than this — a marker in a file that is not
# actually a Gutenberg book must not delete the book.
_PG_MIN_BODY_WORDS = 200


def strip_gutenberg_boilerplate(text: str, *, stats: Optional[dict] = None) -> str:
    """Drop the Project Gutenberg header and licence around the real work.

    FEAT-IN-004. The legal header and title page became chapter 0, and the
    trailing ``*** END OF THE PROJECT GUTENBERG EBOOK ***`` plus the full
    licence FUSED into the last real chapter — where ``chapters exclude``
    cannot reach it, because it is not a chapter of its own.

    This trims on PG's own literal brackets only. It is deliberately not a
    general front/back-matter heuristic: that is a separate, larger effort.
    Text with no PG markers is returned unchanged.

    F-4e188049: the needle is casefolded; START/END accept EBOOK or ETEXT;
    the marker may sit inside a simple HTML wrapper (no whole-line anchors).
    ``_PG_MIN_BODY_WORDS`` still refuses to empty a book on a stray mention.
    """
    if _PG_MARKER not in text.casefold():
        return text

    start = 0
    end = len(text)
    start_match = _PG_START_RE.search(text)
    if start_match:
        # Consume the rest of the marker line so a closing </p> is not spoken.
        line_end = text.find("\n", start_match.end())
        start = line_end + 1 if line_end != -1 else start_match.end()
    end_match = _PG_END_RE.search(text, start)
    if end_match:
        # Drop the whole END marker line (including an HTML wrapper).
        line_start = text.rfind("\n", 0, end_match.start())
        end = line_start + 1 if line_start != -1 else end_match.start()

    if start == 0 and end == len(text):
        return text

    body = text[start:end]
    body_words = len(body.split())
    if body_words < _PG_MIN_BODY_WORDS:
        logger.warning(
            "Found Project Gutenberg markers in this text, but the content "
            "between them is only %d words — leaving the text untrimmed.",
            body_words,
        )
        return text

    dropped_words = max(0, len(text.split()) - body_words)
    if stats is not None:
        stats["gutenberg"] = stats.get("gutenberg", 0) + dropped_words
    logger.info(
        "Trimmed Project Gutenberg boilerplate: %d word(s) of header/licence "
        "dropped, %d word(s) of body kept. You asked to narrate the book; "
        "the PG wrapper is not part of it.",
        dropped_words, body_words,
    )
    return body


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
    # FEAT-IN-004: trim Project Gutenberg's own header/licence brackets before
    # anything looks for chapter boundaries. Done here rather than in
    # ``parse_text`` so the raw-string entry points get it too; it is a no-op
    # on text without the literal markers.
    text = strip_gutenberg_boilerplate(text)

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
        stripped = line.strip()
        match = pattern.match(stripped)

        if match:
            matched_any = True
            matched_count += 1
            # Save previous chapter if exists
            if current_title is not None or current_content:
                title = current_title or "Untitled"
                content = "\n".join(current_content).strip()
                if content:
                    chapters.append((title, content))

            # Start new chapter (FEAT-IN-006: the captures are the chapter
            # NUMBER, not the title — see compose_chapter_title).
            current_title = compose_chapter_title(stripped, match)

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

    # FEAT-IN-004 / F-4e188049: trim PG brackets before split so the
    # summary can report how many licence/header words were dropped.
    # split_into_chapters also trims; a second pass is a no-op.
    dropped: dict = {}
    text = strip_gutenberg_boilerplate(text, stats=dropped)

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

    # Parse-observability summary (PARSER-C / F-2f3303fb).
    profile_code = profile.code if profile is not None else "en"
    single_chapter = len(chapters) == 1 and chapters[0].title == "Chapter 1"
    words_kept = sum(len((c.raw_text or "").split()) for c in chapters)
    logger.info(
        "Parsed text '%s': %d chapter(s), profile=%s, headings=%s, %s",
        path.name, len(chapters), profile_code,
        "none (single-chapter fallback)" if single_chapter else "detected",
        format_parse_summary(words_kept, dropped),
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
    chapter_delimiter: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Read a directory of per-chapter files into ordered (title, text) pairs.

    Each matching file becomes one chapter, including files in subdirectories
    (``rglob``), in natural-sorted relative-path order so "01_intro",
    "2_middle", "appendix/10_end" order numerically rather than
    lexicographically.

    Args:
        directory: Folder containing one file per chapter.
        pattern: Semicolon-separated glob(s) of files to include
            (default ``"*.txt;*.md"``). Globs are matched case-insensitively
            against the filename and the relative path.
        profile: Language profile, threaded through for parity with the other
            parsers (Markdown stripping and frontmatter handling do not need it,
            but callers pass it uniformly).
        chapter_delimiter: Ignored. Folder input is one file per chapter;
            a delimiter regex cannot split a file that is already a chapter.
            Passing it logs a warning so the advertised flag is not dropped
            on the floor.

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

    if chapter_delimiter:
        logger.warning(
            "Folder input treats each matching file as one chapter and does "
            "not split on chapter_delimiter (%r). Remove the flag or split "
            "the files yourself.",
            chapter_delimiter,
        )

    globs = [g.strip() for g in pattern.split(";") if g.strip()]
    if not globs:
        globs = ["*.txt", "*.md"]

    # Collect matching files, including nested ones. Match case-insensitively
    # against both the filename and the relative posix path so "*.txt" still
    # hits appendix/99_appendix.txt and "appendix/*.txt" can pin a subfolder.
    import fnmatch

    seen: set[Path] = set()
    matched: list[Path] = []
    for entry in folder.rglob("*"):
        if not entry.is_file():
            continue
        rel_parts = entry.relative_to(folder).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        name_lower = entry.name.lower()
        rel_lower = entry.relative_to(folder).as_posix().lower()
        for g in globs:
            g_lower = g.lower()
            if fnmatch.fnmatch(name_lower, g_lower) or fnmatch.fnmatch(
                rel_lower, g_lower,
            ):
                if entry not in seen:
                    seen.add(entry)
                    matched.append(entry)
                break

    if not matched:
        raise ValueError(
            f"No files matching {pattern!r} found in '{folder}' "
            "(including subfolders). Folder input expects one text/Markdown "
            "file per chapter (e.g. 01_intro.txt, appendix/99_appendix.txt). "
            "Check the folder path and the pattern glob."
        )

    matched.sort(
        key=lambda p: _natural_sort_key(p.relative_to(folder).as_posix()),
    )

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
        # FEAT-IN-004: a Gutenberg download dropped into a chapter folder
        # carries the same header/licence brackets; no-op without them.
        body = strip_gutenberg_boilerplate(body)
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
    nested = sum(1 for p in matched if p.parent != folder)
    logger.info(
        "Read folder '%s': %d chapter file(s) (%d nested), profile=%s, pattern=%s",
        folder.name, len(chapters), nested, profile_code, pattern,
    )

    return chapters
