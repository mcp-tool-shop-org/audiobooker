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
"""

import re
from typing import Optional

from audiobooker.models import Chapter, Utterance, UtteranceType, CastingTable


# Patterns for detecting dialogue
DOUBLE_QUOTE_PATTERN = re.compile(
    r'"([^"]+)"',
    re.DOTALL
)

SINGLE_QUOTE_PATTERN = re.compile(
    r"'([^']+)'",
    re.DOTALL
)

# Smart/curly quotes
SMART_QUOTE_PATTERN = re.compile(
    r'[""]([^""]+)[""]',
    re.DOTALL
)

# Inline override pattern: [Character|emotion] or [Character]
INLINE_OVERRIDE_PATTERN = re.compile(
    r'\[([^\]|]+)(?:\|([^\]]+))?\]\s*',
)

# Speaker attribution patterns (for auto-detection)
# "said Alice", "Alice said", "whispered Bob", "Bob muttered"
# Pattern captures single capitalized word (name), not followed by lowercase continuation
SAID_PATTERNS = [
    # "said Alice" - verb then name
    re.compile(
        r'(?:said|asked|replied|answered|whispered|shouted|muttered|exclaimed|'
        r'cried|called|yelled|screamed|murmured|demanded|pleaded|begged|'
        r'suggested|agreed|added|continued|explained|insisted|admitted|'
        r'confessed|announced|declared|stated|mentioned|noted|observed|'
        r'remarked|commented|groaned|sighed|laughed|chuckled|giggled|sobbed)\s+'
        r'([A-Z][a-z]+)(?:\s|[,.\!\?]|$)',
        re.IGNORECASE
    ),
    # "Alice said" - name then verb
    re.compile(
        r'([A-Z][a-z]+)\s+'
        r'(?:said|asked|replied|answered|whispered|shouted|muttered|exclaimed|'
        r'cried|called|yelled|screamed|murmured|demanded|pleaded|begged|'
        r'suggested|agreed|added|continued|explained|insisted|admitted|'
        r'confessed|announced|declared|stated|mentioned|noted|observed|'
        r'remarked|commented|groaned|sighed|laughed|chuckled|giggled|sobbed)',
        re.IGNORECASE
    ),
]

# Emotion hints from attribution verbs
EMOTION_HINTS = {
    "whispered": "whisper",
    "shouted": "angry",
    "yelled": "angry",
    "screamed": "fearful",
    "muttered": "grumpy",
    "exclaimed": "excited",
    "cried": "sad",
    "sobbed": "sad",
    "laughed": "happy",
    "chuckled": "happy",
    "giggled": "happy",
    "sighed": "sad",
    "groaned": "grumpy",
    "demanded": "angry",
    "pleaded": "sad",
    "begged": "sad",
}

# Blacklist: words that look like names but are adverbs/manner descriptions
# These should NEVER be treated as speaker names
SPEAKER_BLACKLIST = {
    # Pronouns (often match patterns like "said he")
    "he", "she", "it", "they", "we", "i", "you",
    "him", "her", "them", "us", "me",
    "his", "hers", "its", "theirs", "ours", "mine", "yours",
    # Adverbs of manner (how someone speaks)
    "softly", "loudly", "quietly", "gruffly", "sharply", "gently",
    "slowly", "quickly", "rapidly", "carefully", "angrily", "sadly",
    "happily", "nervously", "anxiously", "fearfully", "excitedly",
    "calmly", "coldly", "warmly", "coolly", "hotly", "flatly",
    "dryly", "wryly", "sweetly", "bitterly", "harshly", "roughly",
    "smoothly", "evenly", "unevenly", "breathlessly", "hoarsely",
    "huskily", "shrilly", "deeply", "lightly", "heavily", "urgently",
    "desperately", "frantically", "hysterically", "sarcastically",
    "mockingly", "teasingly", "playfully", "seriously", "solemnly",
    "thoughtfully", "absently", "distractedly", "sleepily", "wearily",
    "tiredly", "briskly", "curtly", "abruptly", "suddenly",
    # Other non-name words that might match
    "finally", "immediately", "eventually", "meanwhile", "instead",
    "however", "therefore", "moreover", "furthermore", "nevertheless",
    # Time/manner phrases that could false-match
    "wonderfully", "terribly", "horribly", "awfully", "incredibly",
}

# Valid name pattern: Capitalized word, 2-15 chars, no weird suffixes
VALID_NAME_PATTERN = re.compile(r'^[A-Z][a-z]{1,14}$')


def is_valid_speaker_name(name: str, casting: CastingTable) -> bool:
    """
    Check if a detected name is likely a valid speaker.

    Rules:
    1. If name is in casting table (any case), it's valid
    2. If name is blacklisted, it's invalid
    3. Name must match pattern (capitalized, reasonable length)

    Args:
        name: Detected speaker name
        casting: CastingTable to check against

    Returns:
        True if name should be accepted as a speaker
    """
    if not name:
        return False

    name_lower = name.lower()

    # Rule 1: Already in casting table = valid
    if name_lower in casting.characters:
        return True

    # Rule 2: Blacklisted = invalid
    if name_lower in SPEAKER_BLACKLIST:
        return False

    # Rule 3: Must match valid name pattern
    if not VALID_NAME_PATTERN.match(name):
        return False

    return True


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


def detect_dialogue(
    text: str,
    include_single_quotes: bool = False,
) -> list[tuple[str, bool, int, int]]:
    """
    Detect dialogue segments in text.

    Args:
        text: Text to analyze
        include_single_quotes: Also treat 'single quotes' as dialogue

    Returns:
        List of (content, is_dialogue, start, end) tuples
    """
    segments = []

    # Find all quoted segments
    quote_positions = []

    # Double quotes
    for match in DOUBLE_QUOTE_PATTERN.finditer(text):
        quote_positions.append((match.start(), match.end(), match.group(1), True))

    # Smart quotes
    for match in SMART_QUOTE_PATTERN.finditer(text):
        # Avoid duplicates if same position
        start, end = match.start(), match.end()
        if not any(s <= start < e for s, e, _, _ in quote_positions):
            quote_positions.append((start, end, match.group(1), True))

    # Single quotes (optional)
    if include_single_quotes:
        for match in SINGLE_QUOTE_PATTERN.finditer(text):
            start, end = match.start(), match.end()
            # Only if not inside another quote
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


def extract_speaker_from_context(
    text: str,
    dialogue_start: int,
    dialogue_end: int,
    casting: Optional[CastingTable] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Try to extract speaker name from surrounding context.

    Looks for "said X" patterns before/after the dialogue.

    Args:
        text: Full text
        dialogue_start: Start position of dialogue
        dialogue_end: End position of dialogue
        casting: Optional CastingTable for validation

    Returns:
        Tuple of (speaker_name, emotion_hint)
    """
    # Look in a window around the dialogue
    window_before = text[max(0, dialogue_start - 100):dialogue_start]
    window_after = text[dialogue_end:min(len(text), dialogue_end + 100)]

    context = window_before + " " + window_after

    for pattern in SAID_PATTERNS:
        match = pattern.search(context)
        if match:
            speaker = match.group(1)

            # Validate speaker name if casting table provided
            if casting is not None and not is_valid_speaker_name(speaker, casting):
                continue  # Try next pattern

            # Try to get emotion from verb
            verb_match = re.search(
                r'\b(whispered|shouted|yelled|screamed|muttered|exclaimed|'
                r'cried|sobbed|laughed|chuckled|giggled|sighed|groaned|'
                r'demanded|pleaded|begged)\b',
                context,
                re.IGNORECASE
            )
            emotion = None
            if verb_match:
                emotion = EMOTION_HINTS.get(verb_match.group(1).lower())
            return speaker, emotion

    return None, None


def compile_chapter(
    chapter: Chapter,
    casting: CastingTable,
    include_single_quotes: bool = False,
) -> list[Utterance]:
    """
    Compile a chapter's raw text into a list of Utterances.

    This is the core compilation step that transforms prose into
    a sequence of speaker-attributed utterances.

    Args:
        chapter: Chapter to compile
        casting: CastingTable for voice mapping
        include_single_quotes: Treat single quotes as dialogue

    Returns:
        List of Utterances ready for synthesis
    """
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
        segments = detect_dialogue(para, include_single_quotes)

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
                        para, start, end, casting
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
        key = utterance.speaker.lower()
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
        speaker = utterance.speaker.lower()

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
