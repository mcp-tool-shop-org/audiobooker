"""
English language profile for Audiobooker.

All rules that were previously hardcoded in casting/dialogue.py
and parser/text.py are consolidated here.
"""

import re

from audiobooker.language._titles import (
    TITLE_CANONICAL,
    all_title_spellings,
)
from audiobooker.language.profile import LanguageProfile, register_profile

# PH-B-003: name_titles and the TTS normalizer's expansion table are derived
# from one source (audiobooker.language._titles) instead of being two
# hand-maintained lists that drifted. Two independent gaps closed here:
# the expanded spellings ("Mister", "Doctor", "Professor") were absent, so
# normalize_text=True — the DEFAULT, applied before compile_chapter — turned
# `said Mr. Holmes` into the phantom speaker "Mister"; and `Prof.` was absent
# in BOTH spellings, so `said Prof. Lindqvist` attributed to "Prof" even with
# normalization off.
_NAME_TITLES: tuple[str, ...] = tuple(
    re.escape(spelling) for spelling in all_title_spellings()
)

# Prefix accepted in front of a name, shared by name_titles and
# valid_name_pattern so a title can never be attributable-but-invalid.
_TITLE_PREFIX_ALT: str = "|".join(_NAME_TITLES)


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
        # PH-B-004: indefinite pronouns. The backstop for the re.IGNORECASE
        # defect that let the `[A-Z][a-z]+` name fragment match lowercase
        # words, so `"Hello?" asked nobody in particular` produced the ACCEPTED
        # speaker "Nobody" \u2014 a phantom cast member that also lowered the
        # unknown rate. The case fix in language/profile.py is the real fix;
        # this list catches the same shape when a source really does capitalize
        # such a word at the start of a tag.
        "nobody", "somebody", "anybody", "everybody",
        "someone", "anyone", "everyone", "no one",
        "nothing", "something", "anything", "everything",
        "none", "neither", "either", "both", "each", "all",
    }),

    # Multi-word names: "Mr. Holmes", "Captain Ahab", "the Doctor", "Old Tom"
    # Also single names: Unicode letters, hyphens, apostrophes; 2-50 chars (B-017)
    # PH-B-003: the title prefix is the derived one, so every title attribution
    # can MATCH is also a title validation can ACCEPT.
    valid_name_pattern=(
        rf"^(?:(?:{_TITLE_PREFIX_ALT})\s+)?"
        r"[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-\s\.]{0,48}[A-Za-z\u00C0-\u024F]$"
    ),

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

    # --- Speaker-attribution regex fragments ---
    # PH-B-003: derived, not restated. Ordered longest-first by
    # all_title_spellings(); the order is the alternation order.
    name_titles=_NAME_TITLES,
    # Spoken expansion -> written abbreviation, applied to a matched speaker so
    # `said Mister Holmes` (after TTS normalization) and `said Mr. Holmes`
    # (before it) resolve to the SAME cast member instead of two.
    title_aliases=tuple(sorted(TITLE_CANONICAL.items())),

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
