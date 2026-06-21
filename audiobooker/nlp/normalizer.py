"""
Text normalization for TTS preprocessing (FT-CORE-024).

Converts written forms into spoken forms for clearer synthesis:
- Numbers: cardinals, ordinals, years (1900-2099)
- Abbreviations: Dr. -> Doctor, Mrs. -> Missus, etc.
- Currency: $50 -> fifty dollars, EUR 100 -> one hundred euros

Applied during compile's preprocessing step when normalize_text=True.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Number word tables
# ---------------------------------------------------------------------------

_ONES = [
    "", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen",
    "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]

_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety",
]

_ORDINAL_SUFFIXES = {
    1: "first", 2: "second", 3: "third", 5: "fifth",
    8: "eighth", 9: "ninth", 12: "twelfth",
}

# Irregular ordinals keyed by the trailing cardinal WORD. Used to transform the
# last word of a compound number (e.g. "one hundred one" -> "one hundred first")
# where the digit-based _ORDINAL_SUFFIXES lookup doesn't apply.
_IRREGULAR_ORDINAL_WORDS = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}


def _int_to_words(n: int) -> str:
    """Convert a non-negative integer to English words (up to 999,999,999)."""
    if n == 0:
        return "zero"
    if n < 0:
        return "negative " + _int_to_words(-n)

    parts: list[str] = []

    if n >= 1_000_000:
        millions = n // 1_000_000
        parts.append(_int_to_words(millions) + " million")
        n %= 1_000_000

    if n >= 1_000:
        thousands = n // 1_000
        parts.append(_int_to_words(thousands) + " thousand")
        n %= 1_000

    if n >= 100:
        hundreds = n // 100
        parts.append(_ONES[hundreds] + " hundred")
        n %= 100

    if n >= 20:
        tens_word = _TENS[n // 10]
        ones_word = _ONES[n % 10]
        if ones_word:
            parts.append(f"{tens_word}-{ones_word}")
        else:
            parts.append(tens_word)
    elif n > 0:
        parts.append(_ONES[n])

    return " ".join(parts)


def _int_to_ordinal(n: int) -> str:
    """Convert an integer to an ordinal word (e.g., 1 -> first, 23 -> twenty-third)."""
    if n <= 0:
        return _int_to_words(n)

    # Special cases
    if n in _ORDINAL_SUFFIXES:
        return _ORDINAL_SUFFIXES[n]

    # For numbers > 19, only the last word changes
    words = _int_to_words(n)

    # Handle the last word
    last_word = words.split()[-1]
    # Handle hyphenated (e.g., "twenty-three")
    if "-" in last_word:
        prefix, suffix = last_word.rsplit("-", 1)
        # Irregular trailing word (e.g. "-one" -> "-first") takes precedence
        if suffix in _IRREGULAR_ORDINAL_WORDS:
            ordinal_suffix = _IRREGULAR_ORDINAL_WORDS[suffix]
        elif suffix.endswith("y"):
            ordinal_suffix = suffix[:-1] + "ieth"
        elif suffix.endswith("e"):
            ordinal_suffix = suffix + "th"
        else:
            ordinal_suffix = suffix + "th"
        return words[:words.rfind(last_word)] + f"{prefix}-{ordinal_suffix}"
    else:
        # Irregular trailing word (e.g. "one hundred one" -> "... first")
        if last_word in _IRREGULAR_ORDINAL_WORDS:
            return words[:-len(last_word)] + _IRREGULAR_ORDINAL_WORDS[last_word]
        elif last_word.endswith("y"):
            return words[:-len(last_word)] + last_word[:-1] + "ieth"
        elif last_word.endswith("e"):
            return words + "th"
        elif last_word.endswith("t"):
            return words + "h"
        else:
            return words + "th"


def _year_to_words(year: int) -> str:
    """Convert a year (1900-2099) to spoken form."""
    if 2000 <= year <= 2009:
        return "two thousand" + (" " + _ONES[year - 2000] if year > 2000 else "")
    elif 2010 <= year <= 2099:
        return "twenty " + _int_to_words(year - 2000)
    elif 1900 <= year <= 1999:
        first = year // 100
        second = year % 100
        first_words = _int_to_words(first)
        if second == 0:
            return first_words + " hundred"
        else:
            return first_words + " " + _int_to_words(second)
    else:
        return _int_to_words(year)


# ---------------------------------------------------------------------------
# Number normalization
# ---------------------------------------------------------------------------

# Year pattern: standalone 4-digit year in range 1900-2099
_YEAR_RE = re.compile(
    r"(?<!\d)"           # not preceded by digit
    r"(1[89]\d{2}|20\d{2})"  # 1800-2099
    r"(?!\d)"            # not followed by digit
)

# Ordinal pattern: 1st, 2nd, 3rd, 4th, 21st, etc.
_ORDINAL_RE = re.compile(
    r"\b(\d{1,4})\s*(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)

# Cardinal pattern: standalone numbers (up to 6 digits)
_CARDINAL_RE = re.compile(
    r"(?<!\d)(\d{1,6})(?!\d|st|nd|rd|th)",
)


def normalize_numbers(text: str) -> str:
    """
    Convert numbers to spoken form.

    Handles:
    - Years (1900-2099) -> spoken form (e.g., "nineteen eighty-four")
    - Ordinals (1st, 2nd, 3rd) -> spoken form (e.g., "first", "second")
    - Cardinals (plain digits) -> spoken form (e.g., "forty-two")
    """
    # Years first (before cardinal would catch them)
    def _replace_year(m: re.Match) -> str:
        year = int(m.group(1))
        if 1900 <= year <= 2099:
            return _year_to_words(year)
        return m.group(0)

    text = _YEAR_RE.sub(_replace_year, text)

    # Ordinals
    def _replace_ordinal(m: re.Match) -> str:
        n = int(m.group(1))
        if n > 0 and n <= 9999:
            return _int_to_ordinal(n)
        return m.group(0)

    text = _ORDINAL_RE.sub(_replace_ordinal, text)

    # Cardinals (only standalone small numbers to avoid mangling dates/IDs)
    def _replace_cardinal(m: re.Match) -> str:
        n = int(m.group(1))
        if 0 <= n <= 999999:
            return _int_to_words(n)
        return m.group(0)

    text = _CARDINAL_RE.sub(_replace_cardinal, text)

    return text


# ---------------------------------------------------------------------------
# Abbreviation expansion
# ---------------------------------------------------------------------------

_ABBREVIATIONS: dict[str, str] = {
    r"\bDr\.": "Doctor",
    r"\bMr\.": "Mister",
    r"\bMrs\.": "Missus",
    r"\bMs\.": "Miz",
    r"\bProf\.": "Professor",
    r"\bSgt\.": "Sergeant",
    r"\bCpt\.": "Captain",
    r"\bCpl\.": "Corporal",
    r"\bGen\.": "General",
    r"\bLt\.": "Lieutenant",
    r"\bCol\.": "Colonel",
    r"\bAdm\.": "Admiral",
    r"\bRev\.": "Reverend",
    r"\bSt\.": "Saint",
    r"\bJr\.": "Junior",
    r"\bSr\.": "Senior",
    r"\bInc\.": "Incorporated",
    r"\bCo\.": "Company",
    r"\bCorp\.": "Corporation",
    r"\bLtd\.": "Limited",
    r"\betc\.": "etcetera",
    r"\bvs\.": "versus",
    r"\bDept\.": "Department",
    r"\bEst\.": "Established",
    r"\bAve\.": "Avenue",
    r"\bBlvd\.": "Boulevard",
    r"\bPl\.": "Place",
}

_COMPILED_ABBREVS: Optional[list[tuple[re.Pattern, str]]] = None


def _get_compiled_abbrevs() -> list[tuple[re.Pattern, str]]:
    """Lazily compile abbreviation patterns."""
    global _COMPILED_ABBREVS
    if _COMPILED_ABBREVS is None:
        _COMPILED_ABBREVS = [
            (re.compile(pattern), replacement)
            for pattern, replacement in _ABBREVIATIONS.items()
        ]
    return _COMPILED_ABBREVS


def expand_abbreviations(text: str) -> str:
    """Expand common abbreviations for clearer TTS pronunciation."""
    for pattern, replacement in _get_compiled_abbrevs():
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Currency normalization
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS: dict[str, tuple[str, str]] = {
    "$": ("dollar", "dollars"),
    "\u00a3": ("pound", "pounds"),       # £
    "\u20ac": ("euro", "euros"),          # €
    "\u00a5": ("yen", "yen"),            # ¥
}

# Pattern: $50, $1,234.56, £100, €50
_CURRENCY_SYMBOL_RE = re.compile(
    r"([$\u00a3\u20ac\u00a5])\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)"
)

# Pattern: USD 50, EUR 100, GBP 25
_CURRENCY_CODE_RE = re.compile(
    r"\b(USD|EUR|GBP|JPY)\s+(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)"
)

_CURRENCY_CODES: dict[str, tuple[str, str]] = {
    "USD": ("dollar", "dollars"),
    "EUR": ("euro", "euros"),
    "GBP": ("pound", "pounds"),
    "JPY": ("yen", "yen"),
}


def normalize_currency(text: str) -> str:
    """
    Convert currency expressions to spoken form.

    Handles:
    - $50 -> fifty dollars
    - $1.50 -> one dollar and fifty cents
    - EUR 100 -> one hundred euros
    """
    def _replace_symbol(m: re.Match) -> str:
        symbol = m.group(1)
        amount_str = m.group(2).replace(",", "")
        singular, plural = _CURRENCY_SYMBOLS.get(symbol, ("unit", "units"))
        return _format_currency_amount(amount_str, singular, plural)

    def _replace_code(m: re.Match) -> str:
        code = m.group(1)
        amount_str = m.group(2).replace(",", "")
        singular, plural = _CURRENCY_CODES.get(code, ("unit", "units"))
        return _format_currency_amount(amount_str, singular, plural)

    text = _CURRENCY_SYMBOL_RE.sub(_replace_symbol, text)
    text = _CURRENCY_CODE_RE.sub(_replace_code, text)

    return text


def _format_currency_amount(
    amount_str: str,
    singular: str,
    plural: str,
) -> str:
    """Format a numeric currency amount into spoken words."""
    if "." in amount_str:
        whole_str, cents_str = amount_str.split(".", 1)
        whole = int(whole_str)
        cents = int(cents_str.ljust(2, "0")[:2])

        whole_words = _int_to_words(whole)
        unit = singular if whole == 1 else plural

        if cents > 0:
            cents_words = _int_to_words(cents)
            return f"{whole_words} {unit} and {cents_words} cents"
        else:
            return f"{whole_words} {unit}"
    else:
        whole = int(amount_str)
        whole_words = _int_to_words(whole)
        unit = singular if whole == 1 else plural
        return f"{whole_words} {unit}"


# ---------------------------------------------------------------------------
# Combined normalizer
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """
    Apply all text normalizations in the correct order.

    Order: abbreviations -> currency -> numbers
    (Currency before numbers so "$50" becomes "fifty dollars",
    not "dollar fifty".)
    """
    text = expand_abbreviations(text)
    text = normalize_currency(text)
    text = normalize_numbers(text)
    return text
