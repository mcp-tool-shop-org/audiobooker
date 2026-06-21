"""
German language profile for Audiobooker.

Provides German low-high quotes, speech verbs, pronoun blacklist,
emotion hints, and chapter heading patterns for German prose.
"""

from audiobooker.language.profile import LanguageProfile, register_profile

GERMAN = LanguageProfile(
    code="de",
    name="German",

    # --- Dialogue detection ---
    # German uses low-high quotes as primary dialogue markers
    dialogue_quotes=(
        ("\u201e", "\u201c"),   # lower/upper double quotes
        ('"', '"'),             # ASCII double quotes (common in digital texts)
    ),
    smart_quotes=(
        ("\u00ab", "\u00bb"),   # guillemets (used in Swiss German)
    ),
    single_quotes=(
        ("\u201a", "\u2018"),   # lower/upper single quotes
        ("'", "'"),
    ),

    # --- Speaker attribution ---
    speaker_verbs=frozenset({
        "sagte", "fragte", "antwortete", "erwiderte", "fl\u00fcsterte",
        "schrie", "rief", "murmelte", "brummte", "seufzte",
        "st\u00f6hnte", "jammerte", "flehte", "befahl", "forderte",
        "erkl\u00e4rte", "bemerkte", "f\u00fcgte", "fuhr", "meinte",
        "entgegnete", "protestierte", "schluchzte", "lachte", "kicherte",
        "knurrte", "zischte", "hauchte", "bat", "dr\u00e4ngte",
        "best\u00e4tigte", "widersprach", "unterbrach", "wiederholte",
        "betonte", "mahnte", "warnte", "versprach", "schimpfte",
    }),

    emotion_hints={
        "fl\u00fcsterte": "whisper",
        "hauchte": "whisper",
        "murmelte": "whisper",
        "schrie": "angry",
        "rief": "excited",
        "befahl": "angry",
        "forderte": "angry",
        "schimpfte": "angry",
        "schluchzte": "sad",
        "jammerte": "sad",
        "seufzte": "sad",
        "st\u00f6hnte": "sad",
        "flehte": "sad",
        "lachte": "happy",
        "kicherte": "happy",
        "brummte": "grumpy",
        "knurrte": "grumpy",
        "zischte": "angry",
        "warnte": "fearful",
    },

    speaker_blacklist=frozenset({
        # Personal pronouns
        "er", "sie", "es", "ich", "du", "wir", "ihr",
        # Accusative/dative pronouns
        "ihn", "ihm", "ihnen", "mich", "mir", "dich", "dir", "uns", "euch",
        # Possessive pronouns
        "sein", "seine", "seiner", "ihr", "ihre", "ihrer",
        "mein", "meine", "dein", "deine", "unser", "unsere", "euer", "eure",
        # Reflexive
        "sich",
        # Adverbs of manner
        "leise", "laut", "langsam", "schnell", "ruhig", "sanft",
        "traurig", "fr\u00f6hlich", "nerv\u00f6s", "w\u00fctend", "kalt",
        "warm", "pl\u00f6tzlich", "sofort", "schlie\u00dflich", "dann",
        "endlich", "jedoch", "dennoch", "trotzdem", "au\u00dferdem",
    }),

    # German name pattern: handles umlauts, von/van particles
    valid_name_pattern=r"^(?:(?:Herr|Frau|Dr\.|Prof\.|Hauptmann|Graf|Gr\u00e4fin|von|van|der|die)\s+)?[A-Za-z\u00C0-\u024F\u00df][A-Za-z\u00C0-\u024F\u00df'\-\s\.]{0,48}[A-Za-z\u00C0-\u024F\u00df]$",

    # Gender cue words (German)
    female_cue_words=frozenset({
        "sie", "ihre", "ihrer", "frau", "m\u00e4dchen", "mutter",
        "schwester", "tochter", "ehefrau", "k\u00f6nigin", "prinzessin",
        "dame", "gr\u00e4fin",
    }),
    male_cue_words=frozenset({
        "er", "sein", "seiner", "ihm", "herr", "junge", "vater",
        "bruder", "sohn", "ehemann", "k\u00f6nig", "prinz", "graf",
        "ritter",
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^(?:Kapitel|KAPITEL)\s+(\d+|[IVXLCDM]+|[A-Za-z\u00C0-\u024F\u00df]+)(?:\s*[:\-\.]\s*(.*))?$",
        r"^(?:Teil|TEIL)\s+(\d+|[IVXLCDM]+)(?:\s*[:\-\.]\s*(.*))?$",
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

register_profile(GERMAN)
