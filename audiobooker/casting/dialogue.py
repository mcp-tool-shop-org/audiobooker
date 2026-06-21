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
from typing import Optional

from audiobooker.models import Chapter, Utterance, UtteranceType, CastingTable
from audiobooker.language.profile import LanguageProfile, get_profile

logger = logging.getLogger("audiobooker.casting.dialogue")


# ---------------------------------------------------------------------------
# Quote-pattern compilation (from profile)
# ---------------------------------------------------------------------------

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
    for open_q, close_q in profile.dialogue_quotes:
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
    all_quote_pairs = list(profile.dialogue_quotes) + list(profile.smart_quotes)
    if include_single_quotes:
        all_quote_pairs += list(profile.single_quotes)

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

    Looks for "said X" patterns before/after the dialogue.

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
    if profile is None:
        profile = get_profile("en")

    # Look in a window around the dialogue
    window_before = text[max(0, dialogue_start - context_window):dialogue_start]
    window_after = text[dialogue_end:min(len(text), dialogue_end + context_window)]

    context = window_before + " " + window_after
    logger.debug(
        "Speaker context window (%d chars): before=%r after=%r",
        context_window, window_before[:60], window_after[:60],
    )

    said_patterns = profile.build_said_patterns()
    emotion_pattern = profile.build_emotion_verb_pattern()

    for pattern in said_patterns:
        match = pattern.search(context)
        if match:
            speaker = match.group(1).title()
            logger.debug("Said-pattern matched speaker=%r via %s", speaker, pattern.pattern)

            # Validate speaker name if casting table provided
            if casting is not None and not is_valid_speaker_name(speaker, casting, profile=profile):
                logger.debug("Speaker %r rejected by validation, trying next pattern", speaker)
                continue  # Try next pattern

            # Try to get emotion from verb
            emotion = None
            if emotion_pattern:
                verb_match = emotion_pattern.search(context)
                if verb_match:
                    emotion = profile.emotion_hints.get(verb_match.group(1).lower())
            return speaker, emotion

    logger.debug("No speaker attribution found in context window")
    return None, None


# ---------------------------------------------------------------------------
# Chapter compilation
# ---------------------------------------------------------------------------

_SCENE_BREAK_RE = re.compile(r'^\s*(?:\*\s*\*\s*\*|\-\s*\-\s*\-|~\s*~\s*~|###)\s*$')

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
        for content, is_dialogue, start, end in segments:
            if not content.strip():
                continue

            # FT-CAST-012: Compute absolute character offsets
            abs_start = para_start + para_lead + start
            abs_end = para_start + para_lead + end

            if is_dialogue:
                # Try to attribute speaker
                if override_char:
                    speaker = override_char
                    emotion = override_emotion
                    # FT-CAST-024: an inline [Char] override with no emotion is
                    # not a user-set emotion, so the scene fallback may fill it
                    # (still below explicit/inline; chapter mood stays lowest).
                    if emotion is None and active_scene_emotion:
                        emotion = active_scene_emotion
                    elif emotion is None and chapter_mood:
                        emotion = chapter_mood
                else:
                    speaker, emotion = extract_speaker_from_context(
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
                            logger.debug(
                                "Turn-tracking inferred speaker=%r at offset %d",
                                speaker, abs_start,
                            )
                        else:
                            speaker = "unknown"

                # FT-CAST-001: Track attributed speaker
                if speaker != "unknown":
                    _push_speaker(speaker)

                utterance = Utterance(
                    speaker=speaker,
                    text=content,
                    utterance_type=UtteranceType.DIALOGUE,
                    emotion=emotion,
                    chapter_index=chapter.index,
                    line_index=line_index,
                    start_pos=abs_start,
                    end_pos=abs_end,
                )
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

    for utterance in utterances:
        key = casting.normalize_key(utterance.speaker)
        line_counts[key] = line_counts.get(key, 0) + 1
        if utterance.utterance_type == UtteranceType.DIALOGUE:
            dialogue_count += 1
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

    # Warn when majority of utterances fall to 'unknown' (F-CAST-B-018)
    if len(utterances) > 0 and unknown_count > len(utterances) * 0.5:
        logger.warning(
            "Chapter %d: %d/%d utterances (%.0f%%) attributed to 'unknown' speaker — "
            "consider adding speaker attribution hints or inline overrides",
            chapter.index, unknown_count, len(utterances),
            100.0 * unknown_count / len(utterances),
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
            - unknown_rate: float (0.0-1.0)
            - emotion_distribution: {emotion: count}
            - top_unattributed: list of {text, chapter_index, line_index, context}
            - total_utterances: int
            - total_dialogue: int
            - total_narration: int
    """
    speaker_counts: dict[str, int] = {}
    emotion_counts: dict[str, int] = {}
    unattributed: list[dict] = []
    total = 0
    total_dialogue = 0
    total_narration = 0
    unknown_count = 0

    for chapter in chapters:
        for utt in chapter.utterances:
            total += 1
            key = casting.normalize_key(utt.speaker)
            speaker_counts[key] = speaker_counts.get(key, 0) + 1

            if utt.utterance_type == UtteranceType.DIALOGUE:
                total_dialogue += 1
            else:
                total_narration += 1

            if utt.emotion:
                emotion_counts[utt.emotion] = emotion_counts.get(utt.emotion, 0) + 1

            if utt.speaker == "unknown":
                unknown_count += 1
                if len(unattributed) < max_unattributed:
                    # Build context snippet from surrounding text
                    context = ""
                    if chapter.raw_text and utt.start_pos >= 0 and utt.end_pos >= 0:
                        ctx_start = max(0, utt.start_pos - 80)
                        ctx_end = min(len(chapter.raw_text), utt.end_pos + 80)
                        context = chapter.raw_text[ctx_start:ctx_end].strip()
                    unattributed.append({
                        "text": utt.text[:120],
                        "chapter_index": utt.chapter_index,
                        "line_index": utt.line_index,
                        "context": context[:200],
                    })

    unknown_rate = (unknown_count / total) if total > 0 else 0.0

    return {
        "speaker_line_counts": speaker_counts,
        "unknown_rate": unknown_rate,
        "emotion_distribution": emotion_counts,
        "top_unattributed": unattributed,
        "total_utterances": total,
        "total_dialogue": total_dialogue,
        "total_narration": total_narration,
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
