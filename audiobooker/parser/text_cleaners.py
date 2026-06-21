"""
Text cleaning pipeline for Audiobooker (FT-CORE-015).

Composable cleaners that run after parsing, before chapter creation.
Each cleaner is a pure function: str -> str.
"""

from __future__ import annotations

import html
import re
from typing import Callable

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
