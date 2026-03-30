"""
English language profile for Audiobooker.

All rules that were previously hardcoded in casting/dialogue.py
and parser/text.py are consolidated here.
"""

from audiobooker.language.profile import LanguageProfile, register_profile

ENGLISH = LanguageProfile(
    code="en",
    name="English",

    # --- Dialogue detection ---
    dialogue_quotes=(
        ('"', '"'),
    ),
    smart_quotes=(
        ('\u201c', '\u201d'),   # "" left/right double
    ),
    single_quotes=(
        ('\u2018', '\u2019'),   # '' left/right single
        ("'", "'"),
    ),

    # --- Speaker attribution ---
    speaker_verbs=frozenset({
        "said", "asked", "replied", "answered", "whispered", "shouted",
        "muttered", "exclaimed", "cried", "called", "yelled", "screamed",
        "murmured", "demanded", "pleaded", "begged", "suggested", "agreed",
        "added", "continued", "explained", "insisted", "admitted",
        "confessed", "announced", "declared", "stated", "mentioned",
        "noted", "observed", "remarked", "commented", "groaned", "sighed",
        "laughed", "chuckled", "giggled", "sobbed",
    }),

    emotion_hints={
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
    },

    speaker_blacklist=frozenset({
        # Pronouns
        "he", "she", "it", "they", "we", "i", "you",
        "him", "her", "them", "us", "me",
        "his", "hers", "its", "theirs", "ours", "mine", "yours",
        # Adverbs of manner
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
        # Other non-name words
        "finally", "immediately", "eventually", "meanwhile", "instead",
        "however", "therefore", "moreover", "furthermore", "nevertheless",
        "wonderfully", "terribly", "horribly", "awfully", "incredibly",
    }),

    # Multi-word names: "Mr. Holmes", "Captain Ahab", "the Doctor", "Old Tom"
    # Also single names: Unicode letters, hyphens, apostrophes; 2-50 chars (B-017)
    valid_name_pattern=r"^(?:(?:Mr\.|Mrs\.|Ms\.|Dr\.|Miss|Captain|Lord|Lady|Sir|the|Old|Young)\s+)?[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-\s\.]{0,48}[A-Za-z\u00C0-\u024F]$",

    # Gender cue words for voice suggestion (B-013)
    female_cue_words=frozenset({
        "she", "her", "hers", "herself", "woman", "girl", "mother",
        "sister", "daughter", "wife", "queen", "princess", "lady",
        "madam", "miss", "mrs", "ms",
    }),
    male_cue_words=frozenset({
        "he", "him", "his", "himself", "man", "boy", "father",
        "brother", "son", "husband", "king", "prince", "lord", "sir", "mr",
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^(?:Chapter|CHAPTER)\s+(\d+|[IVXLCDM]+|[A-Za-z]+)(?:\s*[:\-\.]\s*(.*))?$",
        r"^(?:Part|PART)\s+(\d+|[IVXLCDM]+)(?:\s*[:\-\.]\s*(.*))?$",
        r"^(\d+)\s*[\.\:\-]\s+(.+)$",
        r"^#\s+(.+)$",
        r"^##\s+(.+)$",
    ),

    scene_break_patterns=(
        r"^\*\s*\*\s*\*\s*$",
        r"^-\s*-\s*-\s*$",
        r"^~\s*~\s*~\s*$",
        r"^###\s*$",
    ),
)

register_profile(ENGLISH)
