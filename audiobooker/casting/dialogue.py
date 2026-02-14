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

import re
from typing import Optional

from audiobooker.models import Chapter, Utterance, UtteranceType, CastingTable
from audiobooker.language.profile import LanguageProfile, get_profile


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

    # Double quotes
    for open_q, close_q in profile.dialogue_quotes:
        pat = re.compile(
            rf'{re.escape(open_q)}([^{re.escape(close_q)}]+){re.escape(close_q)}',
            re.DOTALL,
        )
        patterns.append((pat, True))

    # Smart/curly quotes
    for open_q, close_q in profile.smart_quotes:
        pat = re.compile(
            rf'{re.escape(open_q)}([^{re.escape(close_q)}]+){re.escape(close_q)}',
            re.DOTALL,
        )
        patterns.append((pat, True))

    # Single quotes (optional)
    if include_single_quotes:
        for open_q, close_q in profile.single_quotes:
            pat = re.compile(
                rf'{re.escape(open_q)}([^{re.escape(close_q)}]+){re.escape(close_q)}',
                re.DOTALL,
            )
            patterns.append((pat, True))

    return patterns


# Inline override pattern: [Character|emotion] or [Character]
INLINE_OVERRIDE_PATTERN = re.compile(
    r'\[([^\]|]+)(?:\|([^\]]+))?\]\s*',
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
    2. If name is blacklisted, it's invalid
    3. Name must match pattern (capitalized, reasonable length)

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

    # Rule 2: Blacklisted = invalid
    if name_key in profile.speaker_blacklist:
        return False

    # Rule 3: Must match valid name pattern
    if not profile.is_valid_name(name):
        return False

    return True


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

    Args:
        text: Text to analyze
        include_single_quotes: Also treat 'single quotes' as dialogue
        profile: Language profile (defaults to English)

    Returns:
        List of (content, is_dialogue, start, end) tuples
    """
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
            if not any(s <= start < e for s, e, _, _ in quote_positions):
                quote_positions.append((start, end, match.group(1), True))

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

    Returns:
        Tuple of (speaker_name, emotion_hint)
    """
    if profile is None:
        profile = get_profile("en")

    # Look in a window around the dialogue
    window_before = text[max(0, dialogue_start - 100):dialogue_start]
    window_after = text[dialogue_end:min(len(text), dialogue_end + 100)]

    context = window_before + " " + window_after

    said_patterns = profile.build_said_patterns()
    emotion_pattern = profile.build_emotion_verb_pattern()

    for pattern in said_patterns:
        match = pattern.search(context)
        if match:
            speaker = match.group(1)

            # Validate speaker name if casting table provided
            if casting is not None and not is_valid_speaker_name(speaker, casting, profile=profile):
                continue  # Try next pattern

            # Try to get emotion from verb
            emotion = None
            if emotion_pattern:
                verb_match = emotion_pattern.search(context)
                if verb_match:
                    emotion = profile.emotion_hints.get(verb_match.group(1).lower())
            return speaker, emotion

    return None, None


# ---------------------------------------------------------------------------
# Chapter compilation
# ---------------------------------------------------------------------------

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

    Args:
        chapter: Chapter to compile
        casting: CastingTable for voice mapping
        include_single_quotes: Treat single quotes as dialogue
        profile: Language profile (defaults to English)

    Returns:
        List of Utterances ready for synthesis
    """
    if profile is None:
        profile = get_profile("en")

    utterances = []
    line_index = 0

    # Split into paragraphs first
    paragraphs = re.split(r'\n\s*\n', chapter.raw_text)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Check for inline override at start of paragraph
        override_char, override_emotion, para = parse_inline_override(para)

        # Detect dialogue segments in this paragraph
        segments = detect_dialogue(para, include_single_quotes, profile=profile)

        if not segments:
            # Pure narration paragraph
            utterance = Utterance(
                speaker=override_char or "narrator",
                text=para,
                utterance_type=UtteranceType.NARRATION,
                emotion=override_emotion,
                chapter_index=chapter.index,
                line_index=line_index,
            )
            utterances.append(utterance)
            line_index += 1
            continue

        # Process segments
        for content, is_dialogue, start, end in segments:
            if not content.strip():
                continue

            if is_dialogue:
                # Try to attribute speaker
                if override_char:
                    speaker = override_char
                    emotion = override_emotion
                else:
                    speaker, emotion = extract_speaker_from_context(
                        para, start, end, casting, profile=profile,
                    )
                    if speaker is None:
                        speaker = "unknown"

                utterance = Utterance(
                    speaker=speaker,
                    text=content,
                    utterance_type=UtteranceType.DIALOGUE,
                    emotion=emotion,
                    chapter_index=chapter.index,
                    line_index=line_index,
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
                )

            utterances.append(utterance)
            line_index += 1

    # Update character line counts in casting table
    for utterance in utterances:
        key = casting.normalize_key(utterance.speaker)
        if key in casting.characters:
            casting.characters[key].line_count += 1

    return utterances


def utterances_to_script(
    utterances: list[Utterance],
    casting: CastingTable,
) -> str:
    """
    Convert utterances to voice-soundboard dialogue script format.

    Args:
        utterances: List of utterances
        casting: CastingTable for voice mapping

    Returns:
        Script string for speak_dialogue
    """
    lines = []
    speaker_ids = {}
    next_id = 1

    for utterance in utterances:
        speaker = CastingTable.normalize_key(utterance.speaker)

        # Assign speaker ID
        if speaker not in speaker_ids:
            speaker_ids[speaker] = f"S{next_id}"
            next_id += 1

        sid = speaker_ids[speaker]

        # Build line
        emotion_part = f"({utterance.emotion}) " if utterance.emotion else ""
        line = f"[{sid}:{speaker}] {emotion_part}{utterance.text}"
        lines.append(line)

    return "\n".join(lines)
