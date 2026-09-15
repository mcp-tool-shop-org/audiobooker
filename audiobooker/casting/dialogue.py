"""
Dialogue Detection and Compilation for Audiobooker.

Detects dialogue (quoted text) vs narration in prose,
and compiles chapters into lists of Utterances.

Detection Heuristics:
1. Text in "quotes" -> dialogue
2. Text in 'single quotes' -> dialogue (configurable)
3. Everything else -> narration
4. Inline overrides: [Character|emotion] "text"

Attribution:
- Looks for "said X" / "X said" patterns
- Falls back to "unknown" which maps to narrator

All language-specific rules (verbs, blacklist, quote pairs, etc.)
are drawn from a LanguageProfile.  Default is English.
"""

import logging
import re
from functools import lru_cache
from typing import Optional

from audiobooker.models import Chapter, Utterance, UtteranceType, CastingTable
from audiobooker.language.profile import LanguageProfile, get_profile

logger = logging.getLogger("audiobooker.casting.dialogue")


# ---------------------------------------------------------------------------
# Quote-pattern compilation (from profile)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CAST-AMEND-2-005: line-initial dash dialogue (the Spanish "raya")
# ---------------------------------------------------------------------------

# Markers that can OPEN a line of speech. pt.py already models this as the quote
# pair ("—", "\n"); es.py documents the convention in a comment while
# shipping no marker for it.
_DEFAULT_RAYA_MARKERS = ("—", "―", "–")

# Languages whose prose conventionally opens direct speech with a line-initial
# dash. English is deliberately absent: an em-dash at the start of an English
# line is an interruption or an aside, not a speech marker.
_RAYA_LANGUAGES = frozenset({"es", "fr", "it", "pt", "ro", "ru", "pl", "uk", "ca", "gl"})


def _dash_dialogue_markers(profile: LanguageProfile) -> tuple[str, ...]:
    """
    Markers that open a line of direct speech in this language.

    Profile-driven, in priority order:

    1. an explicit ``dash_dialogue_markers`` field, when the profile grows one;
    2. any ``dialogue_quotes`` pair whose CLOSE is a newline — that pair shape is
       already how pt.py declares "this language opens speech with a dash";
    3. the default raya markers, for languages known to use the convention.
    """
    explicit = getattr(profile, "dash_dialogue_markers", None)
    if explicit:
        return tuple(explicit)

    from_pairs = tuple(
        open_q for open_q, close_q in profile.dialogue_quotes
        if close_q == "\n" and open_q
    )
    if from_pairs:
        return from_pairs

    if profile.code in _RAYA_LANGUAGES:
        return _DEFAULT_RAYA_MARKERS

    return ()


# FEAT-CAST-006: what a raya may legitimately be followed by when it OPENS a
# line of speech. A letter, or one of the marks a sentence of speech can start
# with — the inverted Spanish interrogative/exclamative, a nested quote. A raya
# followed by a comma or a full stop is the CLOSING raya of an interposed
# attribution tag ("—dijo Petrov—,"), which opens nothing.
_SPEECH_OPENER_RE = re.compile(r'^[ \t]*[^\W\d_¿¡]|^[ \t]*[¿¡«"“]')

# FEAT-CAST-004: punctuation that may sit between the closing raya of an
# interposed comment and the speech resuming after it. Per the RAE's raya
# convention the CLOSING raya is itself the signal that the comment has ended
# and the character is speaking again — "—Sí —respondió él—. Vamos ahora
# mismo." is all one person — so a full stop here ends a SENTENCE, not the
# speech, and is skipped rather than treated as a terminator.
_RAYA_RESUME_PUNCT = ",;:.!?…"

# Sentence-final punctuation immediately BEFORE a raya means that raya opens a
# new turn ("—dijo ella. —No quiero"), not that it closes a comment.
_RAYA_PRECEDED_BY_SENTENCE_END = frozenset(".!?…")


def _opens_speech(body: str) -> bool:
    """True when ``body`` (the text right after a raya) can begin speech."""
    return bool(_SPEECH_OPENER_RE.match(body))


@lru_cache(maxsize=16)
def _tag_opener_re(profile_code: str, verbs: frozenset[str]) -> Optional[re.Pattern]:
    """A speech verb sitting immediately after a raya, e.g. ``—dijo ella``.

    The profile's own ``said_patterns`` are not enough for this job: they
    require a capitalized NAME after the verb, and the commonest attributive
    tag in Spanish prose puts a pronoun there (``—dijo ella``). Matching the
    bare verb is what distinguishes "this raya introduces the tag" from "this
    raya opens speech".
    """
    if not verbs:
        return None
    alt = "|".join(re.escape(v) for v in sorted(verbs))
    return re.compile(rf'^[ \t]*(?i:{alt})\b')


def _raya_resumption(
    body: str,
    inner: "re.Match",
    inner_marker_re: "re.Pattern",
) -> Optional[tuple[int, str]]:
    """
    FEAT-CAST-004: the tail of a raya line that resumes the same speech.

    ``body`` is the text after the opening raya; ``inner`` is the raya that
    introduced the attribution tag. If a further raya CLOSES that tag, return
    the ``(offset_into_body, text)`` of the speech resuming after it —

        —Kessler —dijo Petrov con cuidado—, está en el manifiesto.
        —Sí —respondió él—. Vamos ahora mismo.
        —Ese hombre —el que viste ayer— vino otra vez.

    all of which are one person speaking one sentence. Return None when the
    comment is never closed (``—Vamos —insistió Marta, y salió.``, where the
    tail really is narration) or when the line ends with the comment.

    The trap this has to avoid: on a line carrying TWO turns
    (``—Vete —dijo ella. —No quiero —respondió él.``) the next raya found is
    not a closing raya at all, it opens the second turn. Sentence-final
    punctuation directly before the raya is what tells them apart, and the
    mid-line opener pass already claims that raya for the second speaker.
    """
    close = inner_marker_re.search(body, inner.end())
    if close is None:
        return None

    before = body[inner.end():close.start()].rstrip()
    if before and before[-1] in _RAYA_PRECEDED_BY_SENTENCE_END:
        return None

    rest = body[close.end():]
    lead = len(rest) - len(rest.lstrip())
    rest = rest.lstrip()
    if not rest:
        return None

    if rest[0] in _RAYA_RESUME_PUNCT:
        offset = close.end() + lead + 1
    elif rest[0].isalpha():
        offset = close.end() + lead
    else:
        return None

    resumed = body[offset:]
    # The resumed speech ends where the NEXT raya starts — otherwise a line
    # carrying both a parenthetical and a trailing tag ("—Ese hombre —el que
    # viste ayer— vino otra vez —dijo Elena.") swallows "—dijo Elena." into
    # the speech and reads the attribution out loud.
    next_marker = inner_marker_re.search(resumed)
    if next_marker is not None:
        resumed = resumed[:next_marker.start()]

    stripped = resumed.strip()
    if not stripped:
        return None
    offset += len(resumed) - len(resumed.lstrip())
    return offset, stripped


def _paired_quotes(
    pairs: tuple[tuple[str, str], ...],
) -> list[tuple[str, str]]:
    """
    Drop pairs whose close is a newline.

    Those are raya declarations, not real quote pairs: matching them as pairs
    requires a TRAILING newline, so the last line of a paragraph is never
    detected, and the "dialogue" swallows the attribution clause. The dedicated
    raya pass handles them properly.
    """
    return [(o, c) for o, c in pairs if c != "\n"]


def _build_quote_patterns(
    profile: LanguageProfile,
    include_single_quotes: bool = False,
) -> list[tuple[re.Pattern, bool]]:
    """
    Compile regex patterns for detecting quoted segments.

    Returns list of (pattern, is_dialogue) tuples.
    Each pattern has one capture group for the quoted content.
    """
    patterns = []

    # Double quotes — use negated character class for standard ASCII quotes
    # to avoid slow backtracking on unmatched quotes with DOTALL .+?
    for open_q, close_q in _paired_quotes(profile.dialogue_quotes):
        inner = f'[^{re.escape(close_q)}]+'
        pat = re.compile(
            rf'{re.escape(open_q)}({inner}){re.escape(close_q)}',
        )
        patterns.append((pat, True))

    # Smart/curly quotes — use negated character class to avoid
    # catastrophic backtracking on unmatched open-quotes with DOTALL .+?
    for open_q, close_q in profile.smart_quotes:
        inner = f'[^{re.escape(close_q)}]+'
        pat = re.compile(
            rf'{re.escape(open_q)}({inner}){re.escape(close_q)}',
        )
        patterns.append((pat, True))

    # Single quotes (optional) — same negated character class approach
    if include_single_quotes:
        for open_q, close_q in profile.single_quotes:
            inner = f'[^{re.escape(close_q)}]+'
            pat = re.compile(
                rf'{re.escape(open_q)}({inner}){re.escape(close_q)}',
            )
            patterns.append((pat, True))

    return patterns


# Inline override pattern: [Character|emotion] or [Character]
# Name part must contain at least one letter to reject e.g. [123|sad]
INLINE_OVERRIDE_PATTERN = re.compile(
    r'\[([^\]|]*[a-zA-Z][^\]|]*)(?:\|([^\]]+))?\]\s*',
)


# ---------------------------------------------------------------------------
# Speaker validation
# ---------------------------------------------------------------------------

def is_valid_speaker_name(
    name: str,
    casting: CastingTable,
    *,
    profile: Optional[LanguageProfile] = None,
) -> bool:
    """
    Check if a detected name is likely a valid speaker.

    Rules:
    1. If name is in casting table (any case), it's valid
    2. If name matches a character alias, it's valid
    3. If name is blacklisted, it's invalid
    4. Name must match pattern (capitalized, reasonable length)

    Args:
        name: Detected speaker name
        casting: CastingTable to check against
        profile: Language profile (defaults to English)

    Returns:
        True if name should be accepted as a speaker
    """
    if not name:
        return False

    if profile is None:
        profile = get_profile("en")

    name_key = casting.normalize_key(name)

    # Rule 1: Already in casting table = valid
    if name_key in casting.characters:
        return True

    # Rule 2: Matches a character alias = valid
    if casting.resolve_alias(name) is not None:
        return True

    # Rule 3: Blacklisted = invalid
    if name_key in profile.speaker_blacklist:
        return False

    # Rule 4: Must match valid name pattern
    if not profile.is_valid_name(name):
        return False

    return True


# ---------------------------------------------------------------------------
# FT-CAST-023: Emotion + intensity script tag (de)serialization
# ---------------------------------------------------------------------------

# Matches the leading emotion tag in a script line: '(angry)' or '(angry:0.7)'.
# The intensity group is optional so legacy '(emotion)' tags parse unchanged.
_EMOTION_SCRIPT_TAG_RE = re.compile(
    r'^\(([^():]+?)(?::([0-9]*\.?[0-9]+))?\)\s*'
)


def _format_emotion_tag(
    emotion: Optional[str],
    intensity: Optional[float] = None,
) -> str:
    """
    Serialize an emotion (+ optional intensity) into the script tag prefix.

    FT-CAST-023. Examples:
        ("angry", None) -> "(angry) "      (byte-identical to legacy format)
        ("angry", 0.7)  -> "(angry:0.7) "

    Returns an empty string when there is no emotion.
    """
    if not emotion:
        return ""
    if intensity is None:
        return f"({emotion}) "
    return f"({emotion}:{_fmt_intensity(intensity)}) "


def _fmt_intensity(intensity: float) -> str:
    """Format an intensity for the script tag: one decimal, trailing-zero trimmed."""
    text = f"{float(intensity):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_emotion_tag(text: str) -> tuple[Optional[str], Optional[float], str]:
    """
    Parse a leading '(emotion)' or '(emotion:intensity)' tag from a script line.

    FT-CAST-023 — the inverse of :func:`_format_emotion_tag`.

    Args:
        text: A script-line body possibly starting with an emotion tag.

    Returns:
        (emotion, intensity, remainder). emotion is None when no tag is present;
        intensity is None for a bare '(emotion)' tag.
    """
    match = _EMOTION_SCRIPT_TAG_RE.match(text)
    if not match:
        return None, None, text
    emotion = match.group(1).strip()
    intensity: Optional[float] = None
    if match.group(2) is not None:
        try:
            intensity = max(0.0, min(1.0, float(match.group(2))))
        except ValueError:
            intensity = None
    return (emotion or None), intensity, text[match.end():]


# ---------------------------------------------------------------------------
# Inline override parsing
# ---------------------------------------------------------------------------

def parse_inline_override(text: str) -> tuple[Optional[str], Optional[str], str]:
    """
    Parse inline override tags from text.

    Format: [Character|emotion] "dialogue"
    Or: [Character] "dialogue"

    Args:
        text: Text possibly containing override

    Returns:
        Tuple of (character, emotion, cleaned_text)
    """
    match = INLINE_OVERRIDE_PATTERN.match(text)
    if match:
        character = match.group(1).strip()
        emotion = match.group(2).strip() if match.group(2) else None
        cleaned = text[match.end():]
        return character, emotion, cleaned
    return None, None, text


# ---------------------------------------------------------------------------
# Dialogue detection
# ---------------------------------------------------------------------------

def detect_dialogue(
    text: str,
    include_single_quotes: bool = False,
    *,
    profile: Optional[LanguageProfile] = None,
) -> list[tuple[str, bool, int, int]]:
    """
    Detect dialogue segments in text.

    FT-CAST-009: Advanced dialogue detection handles:
    1. Standard quoted dialogue
    2. Em-dash interrupted dialogue ("I was\u2014" she started)
    3. Paragraph-spanning quotes (open without close on one paragraph,
       close without open on next \u2014 merged into one dialogue segment)
    4. Action beats between dialogue without speech verbs

    Args:
        text: Text to analyze
        include_single_quotes: Also treat 'single quotes' as dialogue
        profile: Language profile (defaults to English)

    Returns:
        List of (content, is_dialogue, start, end) tuples
    """
    if not text or not text.strip():
        return []

    if profile is None:
        profile = get_profile("en")

    segments = []

    # Find all quoted segments
    quote_positions = []

    patterns = _build_quote_patterns(profile, include_single_quotes)

    for pat, _is_dialogue in patterns:
        for match in pat.finditer(text):
            start, end = match.start(), match.end()
            # Avoid duplicates if overlapping position
            if not any(start < e and end > s for s, e, _, _ in quote_positions):
                quote_positions.append((start, end, match.group(1), True))

    # FT-CAST-009: Detect paragraph-spanning quotes (continued dialogue).
    # An open quote without a matching close on the same line suggests
    # dialogue that continues to the next paragraph. We detect unmatched
    # open-quotes and try to find the matching close-quote later in the text.
    all_quote_pairs = _paired_quotes(profile.dialogue_quotes) + _paired_quotes(profile.smart_quotes)
    if include_single_quotes:
        all_quote_pairs += _paired_quotes(profile.single_quotes)

    for open_q, close_q in all_quote_pairs:
        # Find open quotes that are NOT already covered by matched pairs
        for m in re.finditer(re.escape(open_q), text):
            ostart = m.start()
            # Skip if already inside a matched quote region
            if any(s <= ostart < e for s, e, _, _ in quote_positions):
                continue
            # Look for the next close quote after this open
            close_idx = text.find(close_q, ostart + len(open_q))
            if close_idx == -1:
                continue
            # Only treat as continued dialogue if the close is on a different
            # "paragraph" (separated by newline) — this avoids false positives
            between = text[ostart:close_idx + len(close_q)]
            if '\n' not in between:
                continue  # Same line — should have been caught by normal patterns
            content = text[ostart + len(open_q):close_idx]
            cend = close_idx + len(close_q)
            # Check for overlap with existing matches
            if not any(ostart < e and cend > s for s, e, _, _ in quote_positions):
                quote_positions.append((ostart, cend, content, True))
                logger.debug(
                    "FT-CAST-009: Continued dialogue detected at %d-%d (spanning paragraphs)",
                    ostart, cend,
                )

    # FT-CAST-009: Detect em-dash interrupted dialogue.
    # Pattern: text followed by em-dash then closing quote, where the
    # opening quote was not captured by standard patterns.
    for open_q, close_q in all_quote_pairs:
        emdash_pat = re.compile(
            rf'{re.escape(open_q)}([^{re.escape(close_q)}]*\u2014){re.escape(close_q)}',
        )
        for match in emdash_pat.finditer(text):
            start, end = match.start(), match.end()
            if not any(start < e and end > s for s, e, _, _ in quote_positions):
                quote_positions.append((start, end, match.group(1), True))
                logger.debug(
                    "FT-CAST-009: Em-dash interrupted dialogue at %d-%d",
                    start, end,
                )

    # CAST-AMEND-2-005: line-initial dash (raya) dialogue.
    # Detection above is driven purely by open/close quote PAIRS, and the
    # FT-CAST-009 em-dash support only matches a dash INSIDE an already-quoted
    # span — never a dash that OPENS a line of speech. So a raya-punctuated
    # source produced a single narration segment and no utterances at all.
    markers = _dash_dialogue_markers(profile)
    if markers:
        marker_alt = "|".join(re.escape(m) for m in markers)
        # FEAT-CAST-006: the raya is no longer anchored to line start alone.
        #
        # `^[ \t]*(?:marker)` missed every mid-paragraph turn — "Ella dejó la
        # pluma. —La balanza está mal." — and the miss was INVISIBLE to every
        # quality metric, because undetected speech becomes NARRATION and
        # narration counts as correctly attributed. It did not raise the
        # unknown rate; it LOWERED it, the same compounding as the alternation
        # guess. The second alternative admits a raya that follows
        # sentence-final punctuation and horizontal whitespace; `[ \t]` never
        # matches a newline, so the line-initial case still goes through the
        # first alternative and is untouched.
        line_open_re = re.compile(
            rf'(?m)(?:^[ \t]*|(?<=[.!?…])[ \t]+)(?:{marker_alt})[ \t]*'
        )
        line_start_re = re.compile(rf'(?m)^[ \t]*(?:{marker_alt})')
        inner_marker_re = re.compile(rf'(?:{marker_alt})')
        said_patterns = profile.build_said_patterns()

        for m in line_open_re.finditer(text):
            span_start = m.start()
            body_start = m.end()
            line_end = text.find("\n", body_start)
            if line_end == -1:
                line_end = len(text)
            if body_start >= line_end:
                continue
            if any(span_start < e and line_end > s for s, e, _, _ in quote_positions):
                continue

            body = text[body_start:line_end]

            # FEAT-CAST-006 guard. Mid-line, a raya is ambiguous: it opens
            # speech, but it also INTRODUCES and CLOSES the attributive tag
            # ("—Vete. —dijo ella." / "—dijo Petrov—,"). Only the line-initial
            # raya is unambiguous, so the two tag shapes are excluded here and
            # nowhere else.
            if not line_start_re.match(text, m.start()):
                if not _opens_speech(body):
                    logger.debug(
                        "FEAT-CAST-006: mid-line raya at %d is punctuation, "
                        "not a speech opener", span_start,
                    )
                    continue
                tag_opener = _tag_opener_re(profile.code, profile.speaker_verbs)
                if (
                    (tag_opener is not None and tag_opener.match(body))
                    or any(pattern.match(body) for pattern in said_patterns)
                ):
                    logger.debug(
                        "FEAT-CAST-006: mid-line raya at %d introduces an "
                        "attribution tag, not speech", span_start,
                    )
                    continue

            # The speech ends at a second marker when the line uses the full
            # convention (—speech —tag), otherwise at a trailing
            # attribution clause ("...? preguntó Ana."), otherwise at EOL.
            cut = len(body)
            inner = inner_marker_re.search(body)
            if inner:
                cut = inner.start()
            else:
                for pattern in said_patterns:
                    tag = pattern.search(body)
                    if tag and 0 < tag.start() < cut:
                        cut = tag.start()

            content = body[:cut].strip()
            if not content:
                continue
            dialogue_end = body_start + len(body[:cut].rstrip())
            quote_positions.append((span_start, dialogue_end, content, True))
            logger.debug(
                "CAST-AMEND-2-005: raya dialogue detected at %d-%d (%s)",
                span_start, dialogue_end, profile.code,
            )

            # FEAT-CAST-004: the interposed tag may be CLOSED by a third raya
            # that hands the sentence back to the speaker —
            # "—Kessler —dijo Petrov con cuidado—, está en el manifiesto."
            # Without this the resumption is narration, so half of one spoken
            # sentence is read in the narrator's voice.
            if inner:
                resumed = _raya_resumption(body, inner, inner_marker_re)
                if resumed is not None:
                    res_off, res_text = resumed
                    res_start = body_start + res_off
                    res_end = res_start + len(res_text)
                    if not any(
                        res_start < e and res_end > s
                        for s, e, _, _ in quote_positions
                    ):
                        quote_positions.append((
                            res_start, res_end, res_text, True,
                        ))
                        logger.debug(
                            "FEAT-CAST-004: raya speech resumes at %d after "
                            "the closing raya of its tag", res_start,
                        )

    # Sort by position
    quote_positions.sort(key=lambda x: x[0])

    # Build segments (alternating narration and dialogue)
    pos = 0
    for start, end, content, is_dialogue in quote_positions:
        # Add narration before this quote
        if start > pos:
            narration = text[pos:start].strip()
            if narration:
                segments.append((narration, False, pos, start))

        # Add dialogue
        segments.append((content, True, start, end))
        pos = end

    # Add remaining narration
    if pos < len(text):
        remaining = text[pos:].strip()
        if remaining:
            segments.append((remaining, False, pos, len(text)))

    return segments


# ---------------------------------------------------------------------------
# Speaker attribution
# ---------------------------------------------------------------------------

# CAST-AMEND-2-001: text that may legitimately sit between an attribution tag
# and the quote it tags — whitespace and punctuation only. Anything with LETTERS
# in it is intervening prose (an action beat, another sentence, another quote's
# body), which severs the link.
_ATTRIB_GAP_RE = re.compile(r'^[\s,;:.!?—–…·\-]*$')

# Characters a profile may list in `dialogue_quotes` that must NOT be treated
# as delimiters when measuring the gap between a quote and its attribution.
# Both are raya-convention markers, and both appear in _ATTRIB_GAP_RE above as
# attributive separators — a character cannot be a delimiter and a separator
# at once. Kept next to that regex so the two stay in view of each other.
_NON_DELIMITING_QUOTES = frozenset({"\n", "—", "–"})

# A sentence boundary inside the gap means the tag was already closed off: it is
# the PREVIOUS quote's trailing tag, not this quote's leading tag. Such a tag may
# still carry over (same speaker continuing in the same paragraph) but loses to
# any tag that is directly attached to this quote.
_SENTENCE_END_RE = re.compile(r'[.!?…]')


def _attribution_quote_chars(profile: LanguageProfile) -> str:
    """
    Quote characters that delimit dialogue in this language.

    Single quotes are deliberately EXCLUDED: ' and ’ double as apostrophes,
    so counting them would treat "Alice's" as an intervening quote. The newline
    used as a pseudo close-quote by the raya convention is excluded too.

    F-9f2e0c74-A: the raya OPENER is excluded for the same reason the newline
    closer already was, and leaving it in broke Spanish and Portuguese
    attribution outright. ``es`` declares ``("—", "\\n")``, so ``—`` was
    harvested here as a quote character, and ``_gap_is_attributive(...,
    allow_quotes=False)`` then rejected any candidate whose gap contained the
    attributive raya of ``—dijo María``. Meanwhile ``_ATTRIB_GAP_RE`` (above)
    explicitly whitelists ``—`` and ``–`` AS attributive separators — the two
    mechanisms contradicted each other, and this one won.

    The failure was silent and it shifted the whole chapter: attribution
    returned None, turn-tracking filled the hole with the PREVIOUS speaker, so
    every line landed one voice out of step and only the FIRST was ``unknown``.
    On a real chapter the unattributed rate therefore tends to zero as the
    chapter grows — the quality signal improves while every voice is wrong,
    the same compounding this module was fixed for in wave 4.

    Only ``es`` and ``pt`` declared the pair and only they were broken; ``fr``
    and ``it`` never declare it and reach the raya path through
    ``_RAYA_LANGUAGES`` instead. So declaring the pair — the change that makes
    raya dialogue DETECTABLE — was what broke attribution for that language.
    """
    chars: set[str] = set()
    for pair in tuple(profile.dialogue_quotes) + tuple(profile.smart_quotes):
        for quote in pair:
            if quote and quote not in _NON_DELIMITING_QUOTES:
                chars.add(quote)
    return "".join(sorted(chars))


def _gap_is_attributive(gap: str, quote_chars: str, *, allow_quotes: bool) -> bool:
    """
    True when ``gap`` (the text between a candidate tag and the quote) is thin
    enough that the tag can be attributing THIS quote.

    ``allow_quotes`` is True for the before-window because callers may pass
    either the full quoted span or just the quoted CONTENT, so the opening quote
    character itself can legitimately appear in the gap. It is False for the
    after-window, where a quote character means a different quote has started
    and owns everything past it.
    """
    if quote_chars:
        if allow_quotes:
            gap = "".join(ch for ch in gap if ch not in quote_chars)
        elif any(ch in quote_chars for ch in gap):
            return False
    return bool(_ATTRIB_GAP_RE.match(gap))


# ---------------------------------------------------------------------------
# FEAT-CAST-004: split quotes.
#
#   "Kessler," Petrov said carefully, "is on the manifest."
#
# is ONE spoken sentence with the attribution wedged into the middle. It was
# detected as two quotes, attributed twice, and the back half — having no tag
# of its own — fell to the alternation guess, so a single sentence came out of
# the speakers in TWO voices. The same shape appears in Spanish with the raya
# ("—Kessler —dijo Petrov—, está en el manifiesto.") and throughout the
# classic register ("said Mr. Darcy, ...").
#
# The discriminator is the punctuation at the two ends of the interposed tag,
# not the tag's content:
#
#   - the front half must NOT end a sentence — "Kessler," is interrupted,
#     "Was it?" is finished and the next quote is a new utterance;
#   - the tag must HAND THE SENTENCE BACK — it ends in a comma or a dash.
#     "said Alice. " ends in a full stop, which closes the utterance, and
#     that is exactly what separates a split quote from two consecutive
#     quotes by the same speaker.
# ---------------------------------------------------------------------------

# Trailing punctuation on the front half that means the sentence FINISHED.
_SENTENCE_FINAL_RE = re.compile(r'[.!?…]["”»\']?\s*$')

# Trailing punctuation on the interposed tag that hands the sentence back.
_TAG_RESUMES_RE = re.compile(r'[,;:—–]\s*$')

# A tag longer than this is prose, not an attribution.
_SPLIT_TAG_MAX_CHARS = 140


def _is_split_quote_gap(
    front_content: str,
    gap: str,
    profile: LanguageProfile,
    dash_markers: tuple[str, ...] = (),
) -> bool:
    """True when ``gap`` is an attribution wedged inside ONE spoken sentence."""
    stripped = gap.strip()
    if not stripped or len(gap) > _SPLIT_TAG_MAX_CHARS:
        return False

    # Raya languages mark the interposition explicitly: it OPENS and CLOSES
    # with a dash, and that is the convention's own statement that the same
    # person is still speaking. No verb test and no sentence-final test are
    # needed (or correct) here — "—¿Vienes? —preguntó—. No me obligues." is
    # one speaker across a finished question, and "—Ese hombre —el que viste
    # ayer— vino otra vez." carries no speech verb at all.
    if dash_markers and stripped[0] in dash_markers:
        if any(marker in stripped[1:] for marker in dash_markers):
            return True

    if _SENTENCE_FINAL_RE.search(front_content):
        return False
    if not _TAG_RESUMES_RE.search(gap):
        return False
    verb_re = _speech_verb_re(profile.code, profile.speaker_verbs)
    return verb_re is not None and bool(verb_re.search(gap))


@lru_cache(maxsize=16)
def _speech_verb_re(profile_code: str, verbs: frozenset[str]) -> Optional[re.Pattern]:
    """Any of the profile's speech verbs, anywhere.

    Deliberately looser than ``build_said_patterns``, which also demands a
    capitalized name. A split quote whose tag names nobody — ``"Kessler," she
    said, "is on the manifest."`` — still has to be recognized as ONE turn,
    even though there is no name in it to attribute to. Recognizing it is what
    stops the two halves being read in two different voices.
    """
    if not verbs:
        return None
    alt = "|".join(re.escape(v) for v in sorted(verbs))
    return re.compile(rf'\b(?i:{alt})\b')


def _split_quote_continuations(
    para: str,
    segments: list[tuple[str, bool, int, int]],
    profile: LanguageProfile,
) -> set[int]:
    """Indices of segments that CONTINUE the previous dialogue segment."""
    continuations: set[int] = set()
    dash_markers = _dash_dialogue_markers(profile)
    prev_dialogue: Optional[int] = None
    for index, (content, is_dialogue, start, _end) in enumerate(segments):
        if not is_dialogue:
            continue
        if prev_dialogue is not None:
            front_content, _, _, front_end = segments[prev_dialogue]
            if front_end <= start and _is_split_quote_gap(
                front_content, para[front_end:start], profile, dash_markers,
            ):
                continuations.add(index)
                logger.debug(
                    "FEAT-CAST-004: segment %d continues segment %d "
                    "across an interposed tag %r",
                    index, prev_dialogue, para[front_end:start][:60],
                )
        prev_dialogue = index
    return continuations


def _collect_candidates(
    window: str,
    pattern: re.Pattern,
    pattern_rank: int,
    quote_chars: str,
    *,
    before: bool,
) -> list[tuple[int, int, int, int, str, str]]:
    """
    Gather attribution candidates from ONE window, scored by DISTANCE to the
    quote boundary rather than by position in a concatenated string.

    Nearest first: rightmost match in the before-window, leftmost in the after-
    window. The gap test is monotone — a further match's gap is a superset of a
    nearer one's — so the scan stops at the first match whose gap fails.

    Returns tuples of (carry_over, distance, side_rank, pattern_rank, name, tag).
    """
    matches = list(pattern.finditer(window))
    if before:
        matches.reverse()

    out: list[tuple[int, int, int, int, str, str]] = []
    for match in matches:
        if before:
            gap = window[match.end():]
            distance = len(window) - match.end()
        else:
            gap = window[:match.start()]
            distance = match.start()

        if not _gap_is_attributive(gap, quote_chars, allow_quotes=before):
            break

        # Tier 0 — directly attached to this quote.
        # Tier 1 — carry-over: the previous quote's trailing tag, same speaker
        #          continuing in the same sentence run.
        # Tier 2 — the tag is on a DIFFERENT LINE. Single-newline-separated
        #          dialogue puts the next speaker's tag one character past this
        #          quote, which would otherwise beat this quote's own tag on raw
        #          distance. A line break is a penalty, not a hard block, so
        #          hard-wrapped prose still attributes.
        # FEAT-CAST-001: the tag's own terminal punctuation counts as a
        # sentence boundary even though it never reaches `gap`.
        # `name_boundary` CONSUMES it — "dijo Elena." matches through the full
        # stop — so a tag that plainly closed the previous sentence arrived
        # here with an EMPTY gap and was scored tier 0, "directly attached to
        # this quote". On "—Vete —dijo Elena. —No quiero —respondió Marcos."
        # that made the previous speaker beat the tag actually attached to
        # this line, and the wrong voice was returned at full confidence.
        tag_tail = match.group(0).rstrip()[-1:]
        if "\n" in gap or "\r" in gap:
            tier = 2
        elif before and (
            _SENTENCE_END_RE.search(gap) or _SENTENCE_END_RE.match(tag_tail)
        ):
            tier = 1
        else:
            tier = 0

        out.append((
            tier,
            distance,
            1 if before else 0,
            pattern_rank,
            match.group(1),
            match.group(0),
        ))
    return out


# ---------------------------------------------------------------------------
# FEAT-CAST-001: attribution confidence.
#
# `_collect_candidates` above already computes the only signal that matters
# here — a TIER: 0 = the tag is welded to this quote, 1 = it carried over
# across a sentence boundary, 2 = it is on a different line. The tier was
# used to SORT the candidates and then thrown away, so a cross-line guess and
# a directly attached tag were reported identically: as "attributed".
#
# The numbers are a ladder, not a calibration. What they must satisfy is the
# ordering (attached > carry-over > cross-line > alternation guess) and which
# side of LOW_CONFIDENCE_THRESHOLD each lands on, and the tests assert the
# ordering rather than the constants.
LOW_CONFIDENCE_THRESHOLD = 0.5

_TIER_CONFIDENCE = {
    0: 0.95,   # tag directly attached to this quote
    1: 0.70,   # carry-over across a sentence boundary, same paragraph
    2: 0.45,   # tag on a DIFFERENT line — below the threshold on purpose
}

# A speaker produced by `_infer_next_speaker`'s alternation. Deliberately the
# lowest non-zero score in the ladder: the text said nothing about who is
# speaking, the previous turn did.
TURN_INFERENCE_CONFIDENCE = 0.25

# A `[Character]` override typed by the user into the source text.
INLINE_OVERRIDE_CONFIDENCE = 1.0


def extract_speaker_with_confidence(
    text: str,
    dialogue_start: int,
    dialogue_end: int,
    casting: Optional[CastingTable] = None,
    *,
    profile: Optional[LanguageProfile] = None,
    context_window: int = 150,
) -> tuple[Optional[str], Optional[str], Optional[str], float]:
    """
    FEAT-CAST-001: :func:`extract_speaker_from_context` plus provenance.

    Identical logic; returns two more things the old signature discarded —
    the source (``"tag"`` or ``None``) and a 0.0-1.0 confidence derived from
    the winning candidate's tier.

    ``extract_speaker_from_context`` remains the 2-tuple public API and simply
    drops the extra fields, because it is exported from
    ``audiobooker.casting`` and callers across the suite unpack exactly two
    values (and compare the whole tuple to ``("Bob", "whisper")``).

    Returns:
        (speaker, emotion_hint, attribution_source, confidence). When no
        attribution is found: ``(None, None, None, 0.0)``.
    """
    return _extract_speaker(
        text, dialogue_start, dialogue_end, casting,
        profile=profile, context_window=context_window,
    )


def extract_speaker_from_context(
    text: str,
    dialogue_start: int,
    dialogue_end: int,
    casting: Optional[CastingTable] = None,
    *,
    profile: Optional[LanguageProfile] = None,
    context_window: int = 150,
) -> tuple[Optional[str], Optional[str]]:
    """
    Try to extract speaker name from surrounding context.

    Looks for "said X" patterns before/after the dialogue and keeps the one
    NEAREST the quote.

    CAST-AMEND-2-001 (the wave-2 fix). This used to build
    ``context = window_before + ' ' + window_after`` and take
    ``pattern.search(context)`` — the LEFTMOST match in the concatenation — so an
    attribution belonging to a PREVIOUS quote beat the one that actually tagged
    this quote, and proximity was never considered. The emotion-verb search had
    the identical flaw, which let one quote's "whispered" colour another's.

    The blast radius was far wider than one paragraph: ``compile_chapter``
    splits paragraphs on BLANK lines only, so any source whose dialogue is
    separated by single newlines — plain .txt, PDF-extracted text, many EPUBs —
    is ONE paragraph, and the first speaker took every quote in the chapter. It
    failed silently in every direction: attribution "succeeded", so turn-tracking
    never fired and nothing was unknown, so the >50%-unknown warning never fired.

    The rules now are:

    1. ``window_before`` and ``window_after`` are searched SEPARATELY, so no
       pattern can match across the join.
    2. Nearest wins: rightmost match in the before-window, leftmost in the after.
    3. A match is disqualified when prose intervenes between it and the quote —
       an action beat ("Bob shook his head.") severs the link — or, in the
       after-window, when another quote character intervenes.
    4. A before-window tag separated from the quote by a sentence boundary is a
       CARRY-OVER (the previous quote's trailing tag, same speaker continuing).
       It is still accepted, but loses to any directly-attached tag.
    5. At equal distance the after-window tag wins.
    6. The emotion hint is read from the WINNING tag's own text, never from the
       whole context.

    Args:
        text: Full text
        dialogue_start: Start position of dialogue
        dialogue_end: End position of dialogue
        casting: Optional CastingTable for validation
        profile: Language profile (defaults to English)
        context_window: Character window around dialogue for attribution (default 150)

    Returns:
        Tuple of (speaker_name, emotion_hint)
    """
    speaker, emotion, _source, _confidence = _extract_speaker(
        text, dialogue_start, dialogue_end, casting,
        profile=profile, context_window=context_window,
    )
    return speaker, emotion


def _extract_speaker(
    text: str,
    dialogue_start: int,
    dialogue_end: int,
    casting: Optional[CastingTable] = None,
    *,
    profile: Optional[LanguageProfile] = None,
    context_window: int = 150,
) -> tuple[Optional[str], Optional[str], Optional[str], float]:
    """Shared body of the two public extractors. See their docstrings."""
    if profile is None:
        profile = get_profile("en")

    # Look in a window around the dialogue
    window_before = text[max(0, dialogue_start - context_window):dialogue_start]
    window_after = text[dialogue_end:min(len(text), dialogue_end + context_window)]

    logger.debug(
        "Speaker context window (%d chars): before=%r after=%r",
        context_window, window_before[:60], window_after[:60],
    )

    said_patterns = profile.build_said_patterns()
    emotion_pattern = profile.build_emotion_verb_pattern()
    quote_chars = _attribution_quote_chars(profile)

    candidates: list[tuple[int, int, int, int, str, str]] = []
    for pattern_rank, pattern in enumerate(said_patterns):
        candidates.extend(
            _collect_candidates(
                window_after, pattern, pattern_rank, quote_chars, before=False,
            )
        )
        candidates.extend(
            _collect_candidates(
                window_before, pattern, pattern_rank, quote_chars, before=True,
            )
        )

    # Attached tags before carry-overs before cross-line tags; then nearest;
    # then after-window before before-window at equal distance; then the
    # profile's own pattern order.
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))

    for tier, distance, side, _rank, raw_name, tag_text in candidates:
        # PH-B-003: fold a spoken honorific back to its written abbreviation
        # ("Mister Holmes" -> "Mr. Holmes"). TTS normalization runs BEFORE
        # compile_chapter and normalize_text defaults to True, so without this
        # the same character is two cast members depending on whether the text
        # had been normalized yet.
        speaker = profile.canonicalize_speaker_name(raw_name.title())
        logger.debug(
            "Attribution candidate speaker=%r distance=%d side=%s tier=%d",
            speaker, distance, "after" if side == 0 else "before", tier,
        )

        # Validate speaker name if casting table provided
        if casting is not None and not is_valid_speaker_name(speaker, casting, profile=profile):
            logger.debug("Speaker %r rejected by validation, trying next candidate", speaker)
            continue

        # FEAT-CAST-003: fold the matched name through the alias table so one
        # character stops becoming three cast slots. `get_voice` already
        # resolved aliases, so the AUDIO was correct -- what stayed broken was
        # everything that keys on the speaker STRING: a permanently dirty
        # uncast warning, split line counts, and split report rows.
        if casting is not None:
            alias_char = casting.resolve_alias(speaker)
            if alias_char is not None and alias_char.name != speaker:
                logger.debug(
                    "FEAT-CAST-003: canonicalized %r -> %r via alias table",
                    speaker, alias_char.name,
                )
                speaker = alias_char.name

        # Emotion comes from the WINNING tag only — a verb in some other tag
        # belongs to some other quote.
        emotion = None
        if emotion_pattern:
            verb_match = emotion_pattern.search(tag_text)
            if verb_match:
                emotion = profile.emotion_hints.get(verb_match.group(1).lower())
        return speaker, emotion, "tag", _TIER_CONFIDENCE.get(tier, 0.45)

    logger.debug("No speaker attribution found in context window")
    return None, None, None, 0.0


# ---------------------------------------------------------------------------
# Chapter compilation
# ---------------------------------------------------------------------------

_SCENE_BREAK_RE = re.compile(r'^\s*(?:\*\s*\*\s*\*|\-\s*\-\s*\-|~\s*~\s*~|###)\s*$')

# CAST-AMEND-2-005: a line that OPENS with a dash is the raya convention. Used
# only for the zero-dialogue diagnostic, so it is language-agnostic on purpose.
_LINE_INITIAL_DASH_RE = re.compile(r'(?m)^[ \t]*[–—―]')

# FT-CAST-009: Em-dash interrupted dialogue pattern
# Matches dialogue ending with em-dash before closing quote: "I was—"
_EMDASH_PATTERN = re.compile(r'\u2014["\u201d]\s*')

# FT-CAST-017: Inline stage direction tags
_PAUSE_TAG_RE = re.compile(r'\[pause:(\d+(?:\.\d+)?)(s|ms)\]')
_SFX_TAG_RE = re.compile(r'\[sfx:([^\]]+)\]')

# FT-CAST-024: Scene emotion span tags — [scene:<emotion>] ... [/scene].
# Mirrors the _PAUSE_TAG_RE / _SFX_TAG_RE convention. The emotion inside the
# span is applied only as a FALLBACK (precedence: explicit/inline > scene >
# chapter mood); it never overrides a user-set or attribution-derived emotion.
_SCENE_OPEN_TAG_RE = re.compile(r'\[scene:([^\]]+)\]')
_SCENE_CLOSE_TAG_RE = re.compile(r'\[/scene\]')


# ---------------------------------------------------------------------------
# PH-B-001 / PH-B-002: attribution-quality thresholds.
#
# The >50%-unknown guard divided unknown_count by ALL utterances, narration
# included. Real prose runs 2-4 narration paragraphs per quote, so a chapter
# where 100% OF THE DIALOGUE is unattributed measured 0.20-0.33 against a
# `> 0.5` test and the guard could not fire. Even a contrived 1:1 narration:
# dialogue ratio lands at exactly 0.50, still below the threshold. Because
# `unknown_character_behavior` defaults to 'narrator', that book renders as a
# single-voice reading and the user finds out after paying for the TTS run.
#
# The rate is now computed over DIALOGUE utterances only. Narration is always
# attributed to the narrator by construction, so including it in the
# denominator measures nothing but the book's prose style.
#
# Exported so the CLI does not re-derive its own thresholds: `compile` and
# `diagnose` should read `compile_report()["quality"]` rather than comparing
# floats of their own.
DIALOGUE_UNKNOWN_WARN_RATE = 0.4
DIALOGUE_UNKNOWN_FAIL_RATE = 0.8


# FEAT-CAST-001, coordinator call. `attribution_quality` gets its OWN
# thresholds rather than reusing the unknown-rate ones, because it measures a
# different and more dangerous quantity.
#
# An `unknown` line is the tool being honest: the user sees it in the report,
# sees it in the review export, and can fix it. An UNVERIFIED line is a guess
# the tool presented as an answer — invisible in every surface that existed
# before this wave, and wrong often enough to matter (the passage that drove
# this measured 52% hand-scored speaker accuracy while reporting quality ok).
#
# So a guess is worse for the user than an admission, and unverified must
# fail EARLIER than unknown, not at the same 0.80. At 0.80 the 6-of-8-guessed
# passage read `degraded` — a book that is three-quarters guesswork is not
# degraded, it is unusable, and the user should be stopped before paying for
# a TTS run of it.
#
# These are new keys with no published history, so they are set on their own
# merits. `--force` remains the override, which is what makes erring toward
# halting the right side to err on for an irreversible spend.
UNVERIFIED_WARN_RATE = 0.30
UNVERIFIED_FAIL_RATE = 0.60


def attribution_quality_verdict(dialogue_unverified_rate: float) -> str:
    """Classify the share of dialogue whose speaker was GUESSED.

    Distinct from :func:`dialogue_quality_verdict`, which classifies the
    share the tool admits it could not attribute. See the threshold comment
    above for why this one is stricter.
    """
    if dialogue_unverified_rate >= UNVERIFIED_FAIL_RATE:
        return "failed"
    if dialogue_unverified_rate >= UNVERIFIED_WARN_RATE:
        return "degraded"
    return "ok"


def dialogue_quality_verdict(dialogue_unknown_rate: float) -> str:
    """Classify an unattributed-DIALOGUE rate (PH-B-002).

    Returns ``'ok'``, ``'degraded'`` or ``'failed'``. ``'failed'`` means the
    book would render as a near-single-voice reading and a caller should halt
    before spending a TTS run on it.
    """
    if dialogue_unknown_rate >= DIALOGUE_UNKNOWN_FAIL_RATE:
        return "failed"
    if dialogue_unknown_rate >= DIALOGUE_UNKNOWN_WARN_RATE:
        return "degraded"
    return "ok"


def compile_chapter(
    chapter: Chapter,
    casting: CastingTable,
    include_single_quotes: bool = False,
    *,
    profile: Optional[LanguageProfile] = None,
) -> list[Utterance]:
    """
    Compile a chapter's raw text into a list of Utterances.

    This is the core compilation step that transforms prose into
    a sequence of speaker-attributed utterances.

    Includes conversation turn-tracking: when a quote has no attribution,
    the speaker is inferred by alternating from the previous attributed
    speaker. The turn stack resets on scene breaks, narration blocks
    longer than 3 paragraphs, or chapter boundaries.

    Character offsets (start_pos, end_pos) are recorded on each Utterance
    for downstream context windowing and review matching.

    Side effect (CAST-DIAL-A-003): for backward compatibility this updates
    ``casting.characters[key].line_count`` for any cast speaker, setting it to
    this chapter's line count for that speaker. Because the mutation happens
    on whatever CastingTable object is passed in, it is observable in the
    SEQUENTIAL compile path but LOST in the parallel path (where each worker
    receives a pickled copy of the table). Callers who need authoritative,
    cross-chapter line counts should NOT rely on this side effect and should
    instead tally from the returned utterances.

    Args:
        chapter: Chapter to compile
        casting: CastingTable for voice mapping
        include_single_quotes: Treat single quotes as dialogue
        profile: Language profile (defaults to English)

    Returns:
        List of Utterances ready for synthesis
    """
    if not chapter.raw_text or not chapter.raw_text.strip():
        return []

    if profile is None:
        profile = get_profile("en")

    # FT-CAST-015: Chapter-level mood/direction
    # If chapter has a mood attribute, use it as context bias for emotion inference
    chapter_mood = getattr(chapter, 'mood', '') or ''

    utterances = []
    line_index = 0

    # FT-CAST-001: Conversation turn-tracking state
    # Stack of last 2 attributed speakers for alternation inference
    speaker_stack: list[str] = []
    consecutive_narration_paragraphs = 0

    # FT-CAST-024: Active scene emotion. Set by a [scene:<emotion>] open tag and
    # cleared by [/scene]; persists across paragraphs within the span. Applied
    # only as a FALLBACK (precedence: explicit/inline > scene > chapter mood).
    active_scene_emotion: Optional[str] = None

    def _reset_turn_stack() -> None:
        nonlocal speaker_stack, consecutive_narration_paragraphs
        speaker_stack = []
        consecutive_narration_paragraphs = 0

    def _push_speaker(name: str) -> None:
        nonlocal speaker_stack
        # Keep only the last 2 speakers
        speaker_stack.append(name)
        if len(speaker_stack) > 2:
            speaker_stack = speaker_stack[-2:]

    def _infer_next_speaker() -> Optional[str]:
        """Infer next speaker by alternating from the last attributed speaker."""
        if len(speaker_stack) == 0:
            return None
        if len(speaker_stack) == 1:
            # Only one known speaker — can't alternate, return None
            return None
        # Alternate: return the speaker before the most recent one
        return speaker_stack[-2]

    # Track character offset within the raw text
    # We'll compute paragraph offsets from the original text
    raw_text = chapter.raw_text

    # Split into paragraphs first, tracking positions
    paragraphs = re.split(r'\n\s*\n', raw_text)
    para_offset = 0  # Running offset into raw_text

    for para in paragraphs:
        # Find actual position of this paragraph in raw_text
        para_start = raw_text.find(para, para_offset)
        if para_start == -1:
            para_start = para_offset
        para_offset = para_start + len(para)

        # CAST-DIAL-A-002: para_start points at the UN-stripped paragraph.
        # Capture the leading whitespace that strip() removes so absolute
        # offsets line up with the original raw_text (preserving the invariant
        # raw_text[start_pos:end_pos] == utterance text for indented paragraphs).
        para_lead = len(para) - len(para.lstrip())
        para = para.strip()
        if not para:
            continue

        # FT-CAST-001: Check for scene break — reset turn stack
        if _SCENE_BREAK_RE.match(para):
            _reset_turn_stack()
            logger.debug("Scene break detected at offset %d — turn stack reset", para_start)
            continue

        # FT-CAST-024: Process scene emotion span tags BEFORE the inline-override
        # parse (the override pattern would otherwise swallow '[scene:tense]' as
        # a '[character]' tag). [scene:<emotion>] sets the active fallback
        # emotion; [/scene] clears it. Tags are stripped from the text. Multiple
        # tags in one paragraph apply in order — the LAST wins for trailing text.
        if _SCENE_OPEN_TAG_RE.search(para) or _SCENE_CLOSE_TAG_RE.search(para):
            scene_events: list[tuple[int, Optional[str]]] = []
            for m in _SCENE_OPEN_TAG_RE.finditer(para):
                scene_events.append((m.start(), m.group(1).strip() or None))
            for m in _SCENE_CLOSE_TAG_RE.finditer(para):
                scene_events.append((m.start(), None))
            scene_events.sort(key=lambda x: x[0])
            for _pos, emotion_val in scene_events:
                active_scene_emotion = emotion_val
                logger.debug(
                    "FT-CAST-024: scene emotion -> %r at offset %d",
                    active_scene_emotion, para_start,
                )
            para = _SCENE_OPEN_TAG_RE.sub('', para)
            para = _SCENE_CLOSE_TAG_RE.sub('', para)
            para = para.strip()
            if not para:
                continue

        # Check for inline override at start of paragraph
        override_char, override_emotion, para = parse_inline_override(para)

        # FT-CAST-017: Extract inline stage direction tags before dialogue detection
        # [pause:2s] or [pause:500ms] -> PAUSE utterance
        # [sfx:description] -> DIRECTION utterance
        pause_matches = list(_PAUSE_TAG_RE.finditer(para))
        sfx_matches = list(_SFX_TAG_RE.finditer(para))

        if pause_matches or sfx_matches:
            # Collect all tags with their positions for ordered insertion
            tag_items = []
            for m in pause_matches:
                duration_val = float(m.group(1))
                duration_unit = m.group(2)
                # Normalize to milliseconds
                if duration_unit == 's':
                    duration_ms = int(duration_val * 1000)
                else:
                    duration_ms = int(duration_val)
                tag_items.append((m.start(), m.end(), 'pause', f"pause:{duration_ms}ms"))
            for m in sfx_matches:
                tag_items.append((m.start(), m.end(), 'sfx', m.group(1).strip()))
            tag_items.sort(key=lambda x: x[0])

            # Create special utterances for each tag
            for _ts, _te, tag_type, tag_content in tag_items:
                abs_start = para_start + para_lead + _ts
                abs_end = para_start + para_lead + _te
                utt_type = UtteranceType.PAUSE if tag_type == 'pause' else UtteranceType.DIRECTION
                utterances.append(Utterance(
                    speaker="narrator",
                    text=tag_content,
                    utterance_type=utt_type,
                    emotion=None,
                    chapter_index=chapter.index,
                    line_index=line_index,
                    start_pos=abs_start,
                    end_pos=abs_end,
                ))
                line_index += 1

            # Strip the tags from the paragraph text for further processing
            para = _PAUSE_TAG_RE.sub('', para)
            para = _SFX_TAG_RE.sub('', para)
            para = para.strip()
            if not para:
                continue

        # Detect dialogue segments in this paragraph
        segments = detect_dialogue(para, include_single_quotes, profile=profile)

        # FEAT-CAST-004: which dialogue segments are the BACK HALF of a split
        # quote. Computed once per paragraph, before attribution, because the
        # back half must inherit the front half's speaker rather than be
        # attributed (and guessed at) on its own.
        continuations = _split_quote_continuations(para, segments, profile)
        carried: Optional[tuple[str, Optional[str], Optional[str], float]] = None
        carried_utterance: Optional[Utterance] = None

        # Check if any segment is actual dialogue
        has_dialogue = any(is_dia for _, is_dia, _, _ in segments)

        if not has_dialogue:
            # Pure narration paragraph (no quoted dialogue found)
            consecutive_narration_paragraphs += 1
            # FT-CAST-001: Reset turn stack after 3+ consecutive narration paragraphs
            if consecutive_narration_paragraphs > 3:
                _reset_turn_stack()
                logger.debug(
                    "Narration block > 3 paragraphs at offset %d — turn stack reset",
                    para_start,
                )

            utterance = Utterance(
                speaker=override_char or "narrator",
                text=para,
                utterance_type=UtteranceType.NARRATION,
                emotion=override_emotion,
                chapter_index=chapter.index,
                line_index=line_index,
                start_pos=para_start + para_lead,
                end_pos=para_start + para_lead + len(para),
            )
            utterances.append(utterance)
            line_index += 1
            continue

        # Has dialogue — reset narration counter
        consecutive_narration_paragraphs = 0

        # Process segments
        for seg_index, (content, is_dialogue, start, end) in enumerate(segments):
            if not content.strip():
                continue

            # FT-CAST-012: Compute absolute character offsets
            abs_start = para_start + para_lead + start
            abs_end = para_start + para_lead + end

            if is_dialogue:
                # FEAT-CAST-004: the back half of a split quote is the SAME
                # turn. It inherits the front half's speaker, provenance and
                # confidence, and is deliberately not pushed onto the turn
                # stack below — pushing the same name twice would leave
                # [X, X] and make the next alternation guess return X.
                is_continuation = seg_index in continuations and carried is not None
                if is_continuation:
                    speaker, emotion, attribution_source, confidence = carried
                    # The tag usually hangs off the FRONT half, but not
                    # always: in "—Ese hombre —el que viste ayer— vino otra
                    # vez —dijo Elena." only the BACK half touches the tag.
                    # Take whichever half actually has evidence and give it to
                    # both, retro-fixing the front utterance in place — one
                    # sentence, one voice, decided once.
                    if speaker in (None, "unknown") or confidence < _TIER_CONFIDENCE[0]:
                        back = _extract_speaker(
                            para, start, end, casting, profile=profile,
                        )
                        if back[0] is not None and back[3] > confidence:
                            speaker, emotion, attribution_source, confidence = back
                            if carried_utterance is not None:
                                carried_utterance.speaker = speaker
                                carried_utterance.attribution_source = (
                                    attribution_source
                                )
                                carried_utterance.confidence = confidence
                                if carried_utterance.emotion is None:
                                    carried_utterance.emotion = emotion
                            if speaker != "unknown":
                                _push_speaker(speaker)
                # Try to attribute speaker
                elif override_char:
                    speaker = override_char
                    emotion = override_emotion
                    attribution_source = "inline"
                    confidence = INLINE_OVERRIDE_CONFIDENCE
                    # FT-CAST-024: an inline [Char] override with no emotion is
                    # not a user-set emotion, so the scene fallback may fill it
                    # (still below explicit/inline; chapter mood stays lowest).
                    if emotion is None and active_scene_emotion:
                        emotion = active_scene_emotion
                    elif emotion is None and chapter_mood:
                        emotion = chapter_mood
                else:
                    speaker, emotion, attribution_source, confidence = _extract_speaker(
                        para, start, end, casting, profile=profile,
                    )
                    # FT-CAST-024 / FT-CAST-015: emotion fallback precedence —
                    # explicit/attribution (above) > scene > chapter mood.
                    if emotion is None and active_scene_emotion:
                        emotion = active_scene_emotion
                        logger.debug(
                            "FT-CAST-024: Using scene emotion %r as fallback at offset %d",
                            active_scene_emotion, abs_start,
                        )
                    elif emotion is None and chapter_mood:
                        emotion = chapter_mood
                        logger.debug(
                            "FT-CAST-015: Using chapter mood %r as emotion hint at offset %d",
                            chapter_mood, abs_start,
                        )
                    if speaker is None:
                        # FT-CAST-001: Try turn-tracking inference
                        inferred = _infer_next_speaker()
                        if inferred is not None:
                            speaker = inferred
                            # FEAT-CAST-001: a guess must be VISIBLY a guess.
                            # This line is the reason the whole feature exists:
                            # the alternation fill was recorded as a successful
                            # attribution, so it LOWERED the unattributed rate
                            # and the quality signal improved as attribution
                            # degraded.
                            attribution_source = "turn"
                            confidence = TURN_INFERENCE_CONFIDENCE
                            logger.debug(
                                "Turn-tracking inferred speaker=%r at offset %d",
                                speaker, abs_start,
                            )
                        else:
                            speaker = "unknown"
                            attribution_source = None
                            confidence = 0.0

                # FT-CAST-001: Track attributed speaker
                if speaker != "unknown" and not is_continuation:
                    _push_speaker(speaker)

                carried = (speaker, emotion, attribution_source, confidence)

                utterance = Utterance(
                    speaker=speaker,
                    text=content,
                    utterance_type=UtteranceType.DIALOGUE,
                    emotion=emotion,
                    chapter_index=chapter.index,
                    line_index=line_index,
                    start_pos=abs_start,
                    end_pos=abs_end,
                    attribution_source=attribution_source,
                    confidence=confidence,
                )
                if not is_continuation:
                    carried_utterance = utterance
            else:
                # Narration
                utterance = Utterance(
                    speaker="narrator",
                    text=content,
                    utterance_type=UtteranceType.NARRATION,
                    emotion=None,
                    chapter_index=chapter.index,
                    line_index=line_index,
                    start_pos=abs_start,
                    end_pos=abs_end,
                )

            utterances.append(utterance)
            line_index += 1

    # Build line counts as a separate dict (safe for parallel use)
    line_counts: dict[str, int] = {}
    dialogue_count = 0
    narration_count = 0
    unknown_count = 0
    unknown_dialogue_count = 0
    guessed_dialogue_count = 0

    for utterance in utterances:
        key = casting.normalize_key(utterance.speaker)
        line_counts[key] = line_counts.get(key, 0) + 1
        if utterance.utterance_type == UtteranceType.DIALOGUE:
            dialogue_count += 1
            if utterance.speaker == "unknown":
                unknown_dialogue_count += 1
            elif (
                utterance.confidence is not None
                and utterance.confidence < LOW_CONFIDENCE_THRESHOLD
            ):
                guessed_dialogue_count += 1
        else:
            narration_count += 1
        if utterance.speaker == "unknown":
            unknown_count += 1

    # CAST-DIAL-A-003: Update casting table line counts from the computed dict.
    # Kept for backward compatibility (CLI `info`/`speakers` display and the
    # existing line-count contract). Observable in the sequential compile path
    # only; the parallel path operates on a pickled copy where this is lost.
    # See the docstring caveat; authoritative counts come from the utterances.
    for key, count in line_counts.items():
        if key in casting.characters:
            casting.characters[key].line_count = count

    # Summary logging (F-CAST-B-004)
    logger.info(
        "Compiled chapter %d: %d utterances (%d dialogue, %d narration), %d unknown speakers",
        chapter.index, len(utterances), dialogue_count, narration_count, unknown_count,
    )

    # CAST-AMEND-2-005: warn when a chapter yields NO dialogue at all while the
    # text is full of dialogue-ish markers. The raya bug was silent precisely
    # because nothing checked this: a whole Spanish chapter compiled to pure
    # narration and no counter noticed.
    if len(utterances) > 0 and dialogue_count == 0:
        marker_chars = set(_attribution_quote_chars(profile))
        has_quote_marker = any(ch in raw_text for ch in marker_chars)
        has_line_initial_dash = bool(_LINE_INITIAL_DASH_RE.search(raw_text))
        if has_quote_marker or has_line_initial_dash:
            logger.warning(
                "Chapter %d: no dialogue detected in %d utterances, but the text "
                "contains dialogue markers (quotes=%s, line-initial dash=%s). "
                "The language profile may not match the source's punctuation — "
                "check --lang.",
                chapter.index, len(utterances), has_quote_marker, has_line_initial_dash,
            )

    # Warn when dialogue falls to 'unknown' (F-CAST-B-018, fixed by PH-B-001).
    #
    # The denominator is DIALOGUE utterances, not all of them. With the old
    # all-utterance denominator this branch was unreachable for real prose:
    # 2-4 narration paragraphs per quote put a 100%-unattributed chapter at
    # 0.20-0.33 against a `> 0.5` test. The all-utterance figure is kept as a
    # secondary number in the message because it is what the user will see if
    # they go counting lines by hand.
    if dialogue_count > 0:
        dialogue_unknown_rate = unknown_dialogue_count / dialogue_count
        all_rate = unknown_count / len(utterances) if utterances else 0.0
        verdict = dialogue_quality_verdict(dialogue_unknown_rate)
        if verdict == "failed":
            # 'Loud' matters: unknown_character_behavior defaults to
            # 'narrator', so this book renders as a single-voice reading and
            # nothing downstream will say so. The caller should halt before
            # paying for the TTS run — compile_report()['quality'] carries the
            # same verdict in machine-readable form.
            logger.error(
                "Chapter %d: %d/%d DIALOGUE lines (%.0f%%) are unattributed — "
                "at this rate the chapter renders as a single-voice reading, "
                "because unknown speakers fall back to %r. Do not render until "
                "this is resolved: check --lang, add inline [character] "
                "overrides, or cast the missing speakers. "
                "(%.0f%% of all %d utterances, narration included.)",
                chapter.index, unknown_dialogue_count, dialogue_count,
                100.0 * dialogue_unknown_rate, casting.unknown_character_behavior,
                100.0 * all_rate, len(utterances),
            )
        elif verdict == "degraded":
            logger.warning(
                "Chapter %d: %d/%d DIALOGUE lines (%.0f%%) are unattributed — "
                "consider adding speaker attribution hints or inline overrides. "
                "(%.0f%% of all %d utterances, narration included.)",
                chapter.index, unknown_dialogue_count, dialogue_count,
                100.0 * dialogue_unknown_rate, 100.0 * all_rate, len(utterances),
            )

        # FEAT-CAST-001: the case the warnings above CANNOT see. Turn-tracking
        # answers every question it is asked, so a chapter whose prose names
        # nobody after the first exchange reports zero unknowns and a clean
        # verdict while most of its voices were produced by alternating. The
        # unattributed rate does not rise as attribution degrades — it FALLS.
        unverified = unknown_dialogue_count + guessed_dialogue_count
        unverified_rate = unverified / dialogue_count
        if (
            guessed_dialogue_count
            and dialogue_quality_verdict(unverified_rate) != "ok"
        ):
            logger.warning(
                "Chapter %d: %d/%d DIALOGUE lines (%.0f%%) have no attribution "
                "in the text and were inferred by alternating turns — a guess, "
                "not a reading. The unattributed rate above cannot show this, "
                "because an inferred speaker LOWERS it. Spot-check "
                "compile_report()['low_confidence'] before rendering.",
                chapter.index, guessed_dialogue_count, dialogue_count,
                100.0 * guessed_dialogue_count / dialogue_count,
            )

    return utterances


def compile_report(
    chapters: list[Chapter],
    casting: CastingTable,
    *,
    max_unattributed: int = 5,
) -> dict:
    """
    FT-CAST-014: Generate a compilation quality report.

    Analyzes compiled utterances across chapters and returns
    diagnostic metrics for cast quality review.

    Args:
        chapters: Compiled chapters (must have utterances populated).
        casting: CastingTable used during compilation.
        max_unattributed: Max unattributed lines to include with context.

    Returns:
        Dict with keys:
            - speaker_line_counts: {speaker: count}
            - unknown_rate: float (0.0-1.0) — over ALL utterances. Diluted by
              narration; kept because it is a published key, but it is the
              SECONDARY number. Use dialogue_unknown_rate to judge quality.
            - dialogue_unknown_rate: float (0.0-1.0) — over DIALOGUE only
              (PH-B-002). This is the real signal.
            - total_dialogue_unknown: int
            - quality: 'ok' | 'degraded' | 'failed' (PH-B-002). Computed from
              dialogue_unknown_rate ALONE, and therefore gameable — see
              attribution_quality below. Unchanged because it is published.
            - emotion_distribution: {emotion: count}
            - top_unattributed: list of {text, chapter_index, line_index, context}
            - total_utterances: int
            - total_dialogue: int
            - total_narration: int

    FEAT-CAST-001 adds, alongside the above and without changing any of it:

            - low_confidence: list of {text, speaker, confidence,
              attribution_source, chapter_index, line_index, context} —
              attributed lines whose attribution is weak. Sits beside
              top_unattributed because the two are the same problem.
            - total_low_confidence: int
            - dialogue_low_confidence_rate: float
            - dialogue_unverified_rate: float — (unknown + low-confidence) over
              DIALOGUE. **This is the number that cannot be gamed.**
            - attribution_quality: the verdict on dialogue_unverified_rate.
            - attribution_source_distribution: {source: count} over dialogue.

    Why the unverified rate exists
    ------------------------------
    ``_infer_next_speaker`` fills every attribution gap by alternating from
    the last known speaker, and the fill was recorded as a SUCCESSFUL
    attribution. So a chapter where the text names nobody after line two
    scored ``dialogue_unknown_rate = 0.0`` and ``quality = 'ok'`` while three
    quarters of its voices were manufactured: **the quality signal improved as
    attribution degraded**, and guessing harder was the fastest way to a clean
    report.

    ``dialogue_unverified_rate`` closes that: a guess moves a line out of
    ``unknown`` and into ``low_confidence``, and the sum does not move. The
    only way to improve it is to attribute more lines from the text.

    PH-B-002: the report used to carry ``unknown_rate`` and nothing that let a
    caller tell a healthy book from a collapsed one, so every caller would have
    had to re-derive a threshold — and ``compile``, the command everyone runs
    before rendering, never printed the rate at all. ``quality`` exists so the
    threshold is decided once, here.

    Note for the CLI: surfacing this is ``cli.py``'s job and that file belongs
    to another agent. This function provides the data; ``compile`` should print
    ``dialogue_unknown_rate`` and refuse to proceed to render on
    ``quality == 'failed'``.
    """
    speaker_counts: dict[str, int] = {}
    emotion_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    unattributed: list[dict] = []
    low_confidence: list[dict] = []
    total = 0
    total_dialogue = 0
    total_narration = 0
    unknown_count = 0
    unknown_dialogue = 0
    low_confidence_dialogue = 0

    def _context_for(chapter: Chapter, utt: Utterance) -> str:
        if not chapter.raw_text or utt.start_pos < 0 or utt.end_pos < 0:
            return ""
        ctx_start = max(0, utt.start_pos - 80)
        ctx_end = min(len(chapter.raw_text), utt.end_pos + 80)
        return chapter.raw_text[ctx_start:ctx_end].strip()[:200]

    for chapter in chapters:
        for utt in chapter.utterances:
            total += 1
            key = casting.normalize_key(utt.speaker)
            speaker_counts[key] = speaker_counts.get(key, 0) + 1

            if utt.utterance_type == UtteranceType.DIALOGUE:
                total_dialogue += 1
                if utt.speaker == "unknown":
                    unknown_dialogue += 1
                if utt.attribution_source:
                    source_counts[utt.attribution_source] = (
                        source_counts.get(utt.attribution_source, 0) + 1
                    )
                # FEAT-CAST-001: attributed, but weakly. Counted separately
                # from 'unknown' so the two cannot be traded against each
                # other — an alternation guess moves a line from the first
                # bucket to the second and the total does not change.
                if (
                    utt.speaker != "unknown"
                    and utt.confidence is not None
                    and utt.confidence < LOW_CONFIDENCE_THRESHOLD
                ):
                    low_confidence_dialogue += 1
                    if len(low_confidence) < max_unattributed:
                        low_confidence.append({
                            "text": utt.text[:120],
                            "speaker": utt.speaker,
                            "confidence": utt.confidence,
                            "attribution_source": utt.attribution_source,
                            "chapter_index": utt.chapter_index,
                            "line_index": utt.line_index,
                            "context": _context_for(chapter, utt),
                        })
            else:
                total_narration += 1

            if utt.emotion:
                emotion_counts[utt.emotion] = emotion_counts.get(utt.emotion, 0) + 1

            if utt.speaker == "unknown":
                unknown_count += 1
                if len(unattributed) < max_unattributed:
                    unattributed.append({
                        "text": utt.text[:120],
                        "chapter_index": utt.chapter_index,
                        "line_index": utt.line_index,
                        "context": _context_for(chapter, utt),
                    })

    unknown_rate = (unknown_count / total) if total > 0 else 0.0
    dialogue_unknown_rate = (
        (unknown_dialogue / total_dialogue) if total_dialogue > 0 else 0.0
    )
    dialogue_low_confidence_rate = (
        (low_confidence_dialogue / total_dialogue) if total_dialogue > 0 else 0.0
    )
    dialogue_unverified_rate = (
        ((unknown_dialogue + low_confidence_dialogue) / total_dialogue)
        if total_dialogue > 0 else 0.0
    )

    return {
        "speaker_line_counts": speaker_counts,
        # Secondary: diluted by narration. See the docstring.
        "unknown_rate": unknown_rate,
        # Primary quality signal (PH-B-002).
        "dialogue_unknown_rate": dialogue_unknown_rate,
        "total_dialogue_unknown": unknown_dialogue,
        "quality": dialogue_quality_verdict(dialogue_unknown_rate),
        "emotion_distribution": emotion_counts,
        "top_unattributed": unattributed,
        "total_utterances": total,
        "total_dialogue": total_dialogue,
        "total_narration": total_narration,
        # FEAT-CAST-001 — the ungameable half of the picture.
        "low_confidence": low_confidence,
        "total_low_confidence": low_confidence_dialogue,
        "dialogue_low_confidence_rate": dialogue_low_confidence_rate,
        "dialogue_unverified_rate": dialogue_unverified_rate,
        "attribution_quality": attribution_quality_verdict(dialogue_unverified_rate),
        "attribution_source_distribution": source_counts,
    }


# ---------------------------------------------------------------------------
# FT-CAST-018: Real-world dialogue edge case test data
# ---------------------------------------------------------------------------

AUSTEN_STYLE = (
    '"I have not the pleasure of understanding you," said he, when she had finished. '
    '"Could you expect me to rejoice in the inferiority of your connections? '
    'To congratulate myself on the hope of relations, whose condition in life is so '
    'decidedly beneath my own?"\n\n'
    'Elizabeth felt herself growing more angry every moment; yet she tried to the '
    'utmost to speak with composure when she said,\n\n'
    '"You are mistaken, Mr. Darcy, if you suppose that the mode of your '
    'declaration affected me in any other way, than as it spared me the concern '
    'which I might have felt in refusing you, had you behaved in a more '
    'gentleman-like manner."\n\n'
    'She saw him start at this, but he said nothing, and she continued.\n\n'
    '"You could not have made me the offer of your hand in any possible way '
    'that would have tempted me to accept it."'
)

HEMINGWAY_STYLE = (
    '"What do you want to do?" he asked.\n\n'
    '"I don\'t know."\n\n'
    '"We could go to the fights."\n\n'
    '"Sure."\n\n'
    '"Or we could eat first."\n\n'
    '"Let\'s eat."\n\n'
    '"All right."'
)

MODERN_THRILLER = (
    '"Run!" Sarah screamed.\n\n'
    'The door slammed shut.\n\n'
    '"They\'re coming," whispered Jake, pressing against the wall.\n\n'
    '"How many?" she demanded.\n\n'
    '"Three. Maybe four."\n\n'
    '"We need a way out\u2014" Sarah started, but the glass shattered.\n\n'
    '"Down!" Jake shouted, pulling her to the floor.\n\n'
    'Silence.\n\n'
    '"Are you hurt?" he asked.\n\n'
    '"No. You?"\n\n'
    '"I\'m fine. Move. Now."'
)

FANTASY_MULTI_SPEAKER = (
    '"The council will decide," King Aldric declared from his throne.\n\n'
    '"With respect, Your Majesty," said Lady Morgaine, "we cannot wait for '
    'the council. The Shadow advances."\n\n'
    '"She speaks true," old Theron muttered. "I have seen it in the stars."\n\n'
    '"Stars!" Captain Voss laughed bitterly. "Give me steel over starlight."\n\n'
    '"You will have both before this is done," whispered the Seer, her blind '
    'eyes fixed on nothing.\n\n'
    '"Then it is war," the King said quietly.\n\n'
    '"It was always war," replied Morgaine. "We simply refused to see it."\n\n'
    'Theron sighed and lowered his head. "May the old gods forgive us," he murmured.\n\n'
    '"The gods have nothing to do with this," Voss said, drawing his sword.\n\n'
    'The Seer smiled. "On that, Captain, you are profoundly wrong."'
)


def utterances_to_script(
    utterances: list[Utterance],
    casting: Optional[CastingTable] = None,
) -> str:
    """
    Convert utterances to internal intermediate script format.

    Output uses [S1:speaker] tagged lines for downstream processing.
    FT-CAST-011: Includes per-character voice parameter hints (speed,
    pitch_shift, emphasis) when a casting table is provided.

    FT-CAST-017: PAUSE and DIRECTION utterances are emitted as
    special tagged lines.

    Args:
        utterances: List of utterances
        casting: Optional CastingTable for voice parameter hints

    Returns:
        Script string in [SN:speaker] intermediate format
    """
    lines = []
    speaker_ids = {}
    next_id = 1

    for utterance in utterances:
        # FT-CAST-017: Special handling for PAUSE and DIRECTION utterances
        if utterance.utterance_type == UtteranceType.PAUSE:
            lines.append(f"[PAUSE] {utterance.text}")
            continue
        if utterance.utterance_type == UtteranceType.DIRECTION:
            lines.append(f"[SFX] {utterance.text}")
            continue

        speaker = CastingTable.normalize_key(utterance.speaker)

        # Assign speaker ID
        if speaker not in speaker_ids:
            speaker_ids[speaker] = f"S{next_id}"
            next_id += 1

        sid = speaker_ids[speaker]

        # Build line
        # FT-CAST-023: serialize intensity alongside the emotion when present
        # ('(angry:0.7)'). A bare emotion with no intensity stays '(angry)' —
        # byte-identical to the historical script format.
        emotion_part = _format_emotion_tag(
            utterance.emotion, getattr(utterance, "intensity", None)
        )

        # FT-CAST-011: Per-character voice parameter hints
        param_parts = []
        if casting is not None:
            key = casting.normalize_key(utterance.speaker)
            if key in casting.characters:
                char = casting.characters[key]
                if char.speed != 1.0:
                    param_parts.append(f"{{speed:{char.speed:.1f}}}")
                if char.pitch_shift != 0.0:
                    param_parts.append(f"{{pitch:{char.pitch_shift:.1f}}}")
                if char.emphasis != 1.0:
                    param_parts.append(f"{{emphasis:{char.emphasis:.1f}}}")
        param_str = " ".join(param_parts) + " " if param_parts else ""

        line = f"[{sid}:{speaker}] {emotion_part}{param_str}{utterance.text}"
        lines.append(line)

    return "\n".join(lines)
