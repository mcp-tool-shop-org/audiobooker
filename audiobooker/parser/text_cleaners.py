"""
Text cleaning pipeline for Audiobooker (FT-CORE-015).

Composable cleaners that run after parsing, before chapter creation.
Each cleaner is a pure function: str -> str.
"""

from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Callable, Optional

# Type alias for a cleaner function
TextCleaner = Callable[[str], str]


# ---------------------------------------------------------------------------
# Individual cleaners
# ---------------------------------------------------------------------------

_PAGE_NUMBER_RE = re.compile(
    r"(?m)"                                 # multiline
    r"(?:"
    r"^\s*(?:Page\s+|p\.\s*)\d{1,5}\s*$"   # "Page 42" or "p. 42" on its own line
    r"|"
    r"^\s*-\s*\d{1,5}\s*-\s*$"              # "- 42 -" centered page numbers
    r")"
)


def strip_page_numbers(text: str) -> str:
    """Remove standalone page numbers (e.g., 'Page 42', 'p. 42', '- 42 -').

    Bare numeric lines (e.g. '3', '2021') are intentionally NOT stripped:
    they are often real narrated content (countdowns, years, verse numbers),
    so removal requires an explicit 'Page '/'p.' prefix or a centered '- N -'
    form (PARSER-A-003).
    """
    return _PAGE_NUMBER_RE.sub("", text)


_MULTI_WHITESPACE_RE = re.compile(r"[^\S\n]+")  # horizontal whitespace only
_MULTI_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs to single space; collapse 3+ blank lines to 2."""
    text = _MULTI_WHITESPACE_RE.sub(" ", text)
    text = _MULTI_BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


# Common abbreviations -> expanded form (English-centric)
_ABBREVIATIONS: dict[str, str] = {
    r"\bMr\.": "Mister",
    r"\bMrs\.": "Missus",
    r"\bDr\.": "Doctor",
    # NOTE: 'St.' (Saint/Street) and 'Co.' (Company/County) are inherently
    # ambiguous and were dropped from the default map — they mispronounced
    # 'Main St.' and 'Co. Cork' (PARSER-A-006). Callers wanting them can add
    # custom cleaners.
    r"\bProf\.": "Professor",
    r"\bSgt\.": "Sergeant",
    r"\bCpt\.": "Captain",
    r"\bGen\.": "General",
    r"\bLt\.": "Lieutenant",
    r"\bInc\.": "Incorporated",
    r"\betc\.": "etcetera",
    r"\bvs\.": "versus",
    r"\bJr\.": "Junior",
    r"\bSr\.": "Senior",
}

_COMPILED_ABBREVS: list[tuple[re.Pattern, str]] | None = None


def _get_compiled_abbrevs() -> list[tuple[re.Pattern, str]]:
    """Lazily compile abbreviation patterns."""
    global _COMPILED_ABBREVS
    if _COMPILED_ABBREVS is None:
        _COMPILED_ABBREVS = [
            (re.compile(pattern), replacement)
            for pattern, replacement in _ABBREVIATIONS.items()
        ]
    return _COMPILED_ABBREVS


def expand_common_abbreviations(text: str) -> str:
    """Expand common abbreviations for clearer TTS pronunciation."""
    for pattern, replacement in _get_compiled_abbrevs():
        text = pattern.sub(replacement, text)
    return text


def decode_html_entities(text: str) -> str:
    """Decode HTML entities like &amp; &lt; &nbsp; &#8220; etc."""
    return html.unescape(text)


# --- Markdown inline cleaning (FT-PARSE-007) --------------------------------
#
# These patterns unwrap Markdown formatting to the spoken text it decorates.
# They are applied ONLY for Markdown input (see MARKDOWN_CLEANERS / the .md
# gate in parse_text) so that plain .txt with legitimate asterisks, underscores
# or backticks (e.g. "the *real* problem", a code-looking literal) is untouched.

# Fenced code blocks: ```lang\n...\n``` or ~~~...~~~ — drop the fence and the
# code inside (read-aloud of source code is noise). Run before inline rules.
_MD_FENCED_CODE_RE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$")

# Images: ![alt](url) -> alt text (visible/spoken text is the alt).
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
# Links: [text](url) -> text. Reference-style [text][ref] -> text.
_MD_LINK_INLINE_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_LINK_REF_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")

# Inline code: `code` -> code (strip the backticks, keep the literal).
_MD_INLINE_CODE_RE = re.compile(r"`+([^`]+)`+")

# Emphasis: **bold** / __bold__ / *em* / _em_ / ~~strike~~ -> inner text.
# Bold/strike (double markers) handled before single so '**' isn't seen as two '*'.
_MD_BOLD_RE = re.compile(r"\*\*([^*]+?)\*\*|__([^_]+?)__")
_MD_STRIKE_RE = re.compile(r"~~([^~]+?)~~")
_MD_EM_STAR_RE = re.compile(r"\*([^*\n]+?)\*")
_MD_EM_UNDERSCORE_RE = re.compile(r"(?<![A-Za-z0-9_])_([^_\n]+?)_(?![A-Za-z0-9_])")

# Leading block markers, per line: list bullets (-, *, +), ordered list
# numbers (1.), and blockquote '>' chevrons. Only the marker is stripped;
# the content stays.
_MD_LEADING_MARKER_RE = re.compile(
    r"(?m)^[ \t]*"
    r"(?:>[ \t]*)*"          # zero or more blockquote chevrons
    r"(?:[-*+][ \t]+"        # unordered bullet
    r"|\d{1,3}[.)][ \t]+)?"  # or ordered list "1." / "1)"
)


def strip_markdown_inline(text: str) -> str:
    """Unwrap Markdown formatting to its spoken text (FT-PARSE-007).

    - ``**bold**`` / ``__bold__`` / ``*em*`` / ``_em_`` / ``~~strike~~`` ->
      inner text.
    - ``[text](url)`` -> ``text``; ``![alt](url)`` -> ``alt``;
      reference links ``[text][ref]`` -> ``text``.
    - Inline code ``` `code` ``` -> ``code`` (backticks stripped); fenced code
      blocks are removed entirely.
    - Leading list markers (``- ``, ``* ``, ``1. ``) and blockquote ``> ``
      chevrons are stripped, keeping the line content.

    Intended for Markdown input only. ``parse_text`` gates this on a .md /
    .markdown extension so plain .txt with legitimate ``*asterisks*`` is
    left alone.
    """
    # Code first so emphasis/link rules never touch code contents.
    text = _MD_FENCED_CODE_RE.sub("", text)
    text = _MD_INLINE_CODE_RE.sub(r"\1", text)

    # Images before links (image syntax is a superset starting with '!').
    text = _MD_IMAGE_RE.sub(r"\1", text)
    text = _MD_LINK_INLINE_RE.sub(r"\1", text)
    text = _MD_LINK_REF_RE.sub(r"\1", text)

    # Emphasis: double markers before single.
    text = _MD_BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    text = _MD_EM_STAR_RE.sub(r"\1", text)
    text = _MD_EM_UNDERSCORE_RE.sub(r"\1", text)

    # Leading block markers per line.
    text = _MD_LEADING_MARKER_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

# Default cleaner sequence
DEFAULT_CLEANERS: list[TextCleaner] = [
    decode_html_entities,
    strip_page_numbers,
    expand_common_abbreviations,
    normalize_whitespace,
]

# Markdown cleaner sequence (FT-PARSE-007). Used only for Markdown input —
# strip_markdown_inline runs first to unwrap formatting to spoken text, then
# the usual default cleaners normalize the result. Gated by extension in
# parse_text so plain .txt with legitimate asterisks is never markdown-stripped.
MARKDOWN_CLEANERS: list[TextCleaner] = [
    strip_markdown_inline,
    *DEFAULT_CLEANERS,
]


def clean_text(text: str, cleaners: list[TextCleaner] | None = None) -> str:
    """
    Run text through a pipeline of cleaners.

    Args:
        text: Raw text to clean.
        cleaners: Optional list of cleaner functions. Defaults to DEFAULT_CLEANERS.

    Returns:
        Cleaned text.
    """
    if cleaners is None:
        cleaners = DEFAULT_CLEANERS
    for cleaner in cleaners:
        text = cleaner(text)
    return text


def apply_pronunciation_overrides(text: str, overrides: dict[str, str]) -> str:
    """
    Substitute pronunciation overrides in text (FT-CORE-011).

    Performs whole-word, case-insensitive replacement.

    Args:
        text: Text to process.
        overrides: Dict mapping word -> replacement pronunciation.

    Returns:
        Text with overrides applied.
    """
    if not overrides:
        return text
    for word, replacement in overrides.items():
        # Whole-word match, case-insensitive
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Pronunciation lexicon load/save (FT-PARSE-001)
# ---------------------------------------------------------------------------
#
# A lexicon is a flat mapping of word -> replacement pronunciation, the same
# shape apply_pronunciation_overrides consumes. It persists to CSV or JSON so a
# user can build a reusable dictionary of name/term pronunciations.
#
# 'type' is an optional per-entry tag. The default is "text" (a plain spoken-out
# replacement). Entries tagged "phoneme" are kept DISTINCT — phoneme strings
# (e.g. an IPA or engine-specific spelling) must round-trip without being
# treated as ordinary text, so save_lexicon re-emits their type and a CSV/JSON
# round-trip preserves it.

_LEXICON_PHONEME_TYPE = "phoneme"
_LEXICON_TEXT_TYPE = "text"


class Lexicon(dict):
    """A word -> replacement mapping that also carries per-entry types.

    Behaves as a plain ``dict[str, str]`` (so it drops straight into
    :func:`apply_pronunciation_overrides`), but keeps a side ``types`` map of
    word -> ``"text"``/``"phoneme"`` so phoneme entries stay DISTINCT and
    round-trip losslessly through :func:`save_lexicon`. A plain ``dict`` cannot
    carry attributes, hence this subclass.
    """

    def __init__(self, *args, types: Optional[dict[str, str]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.types: dict[str, str] = types if types is not None else {}


def load_lexicon(path) -> dict[str, str]:
    """Load a pronunciation lexicon from CSV or JSON (FT-PARSE-001).

    Format is chosen by extension: ``.json`` is parsed as JSON, everything else
    (``.csv``/``.tsv``/no suffix) is parsed as CSV.

    CSV columns: ``word,replacement`` with an optional third ``type`` column.
    A header row naming the columns is supported (and recommended) but optional;
    a leading row of literally ``word,replacement[,type]`` is treated as a
    header and skipped.

    JSON forms accepted:
      - ``{"word": "replacement", ...}`` — flat mapping (all type "text").
      - ``{"word": {"replacement": "...", "type": "phoneme"}, ...}`` — explicit
        per-entry type.
      - ``[{"word": "...", "replacement": "...", "type": "..."}, ...]`` — list
        of row objects.

    Returns:
        A :class:`Lexicon` (a ``dict[str, str]`` subclass) mapping word ->
        replacement. ``type=phoneme`` entries are kept DISTINCT from text
        entries: their replacement is stored verbatim and ``save_lexicon``
        re-emits their ``phoneme`` type so a round-trip is lossless. The
        per-entry types live on the returned object's ``.types`` map; the
        mapping itself is a plain word -> replacement dict, so it drops straight
        into :func:`apply_pronunciation_overrides`.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Lexicon file not found: {p}")

    overrides: dict[str, str] = {}
    types: dict[str, str] = {}

    if p.suffix.lower() == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Cannot parse lexicon '{p.name}' — invalid JSON: {e}. "
                "Expected a {word: replacement} object, a "
                "{word: {replacement, type}} object, or a list of row objects."
            ) from e
        _load_json_into(data, overrides, types, p.name)
    else:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(
                f"Cannot read lexicon '{p.name}' — the file is not valid UTF-8: {e}. "
                "Save it as UTF-8 and try again."
            ) from e
        _load_csv_into(text, overrides, types)

    return Lexicon(overrides, types=types)


def _load_json_into(data, overrides: dict, types: dict, name: str) -> None:
    """Populate overrides/types from a parsed-JSON lexicon structure."""
    if isinstance(data, dict):
        for word, value in data.items():
            if isinstance(value, dict):
                repl = value.get("replacement", "")
                etype = value.get("type", _LEXICON_TEXT_TYPE)
            else:
                repl = value
                etype = _LEXICON_TEXT_TYPE
            overrides[str(word)] = str(repl)
            types[str(word)] = str(etype)
    elif isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            word = row.get("word")
            if not word:
                continue
            overrides[str(word)] = str(row.get("replacement", ""))
            types[str(word)] = str(row.get("type", _LEXICON_TEXT_TYPE))
    else:
        raise ValueError(
            f"Cannot parse lexicon '{name}' — expected a JSON object or list, "
            f"got {type(data).__name__}."
        )


def _load_csv_into(text: str, overrides: dict, types: dict) -> None:
    """Populate overrides/types from CSV text."""
    reader = csv.reader(text.splitlines())
    for i, row in enumerate(reader):
        if not row or all(not cell.strip() for cell in row):
            continue
        cells = [c.strip() for c in row]
        # Skip an optional header row.
        if i == 0 and cells[0].lower() == "word" and len(cells) >= 2 and \
                cells[1].lower() == "replacement":
            continue
        if len(cells) < 2:
            continue
        word, repl = cells[0], cells[1]
        if not word:
            continue
        etype = cells[2].lower() if len(cells) >= 3 and cells[2] else _LEXICON_TEXT_TYPE
        overrides[word] = repl
        types[word] = etype


def save_lexicon(path, overrides: dict[str, str]) -> None:
    """Save a pronunciation lexicon to CSV or JSON (FT-PARSE-001).

    Format is chosen by extension: ``.json`` writes JSON, everything else writes
    CSV with a ``word,replacement,type`` header.

    ``type=phoneme`` entries are kept DISTINCT: if ``overrides`` is a
    :class:`Lexicon` (as returned by :func:`load_lexicon`), each entry's type is
    re-emitted from its ``.types`` map, so phoneme entries round-trip
    losslessly. Plain dicts and entries with no recorded type default to
    ``text``.
    """
    p = Path(path)
    types: dict[str, str] = getattr(overrides, "types", {}) or {}

    if p.suffix.lower() == ".json":
        # Emit the explicit {word: {replacement, type}} form so types survive.
        out: dict[str, dict[str, str]] = {}
        for word, repl in overrides.items():
            out[word] = {
                "replacement": repl,
                "type": types.get(word, _LEXICON_TEXT_TYPE),
            }
        p.write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return

    # CSV — lineterminator="\n" so StringIO doesn't get blank lines from the
    # default "\r\n" being re-split when written through write_text.
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["word", "replacement", "type"])
    for word, repl in overrides.items():
        writer.writerow([word, repl, types.get(word, _LEXICON_TEXT_TYPE)])
    p.write_text(buf.getvalue(), encoding="utf-8")
