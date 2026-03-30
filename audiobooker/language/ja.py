"""
Japanese language profile for Audiobooker.

Provides corner brackets (\u300c \u300d), Japanese speech verbs,
pronoun blacklist, emotion hints, and chapter heading patterns
for Japanese prose.

Japanese dialogue uses corner brackets (\u300c\u300d) as primary dialogue markers,
and double corner brackets (\u300e\u300f) for nested quotes.
"""

from audiobooker.language.profile import LanguageProfile, register_profile

JAPANESE = LanguageProfile(
    code="ja",
    name="Japanese",

    # --- Dialogue detection ---
    # Japanese uses corner brackets as primary dialogue markers
    dialogue_quotes=(
        ("\u300c", "\u300d"),   # corner brackets (primary)
        ("\u300e", "\u300f"),   # double corner brackets (nested/inner quotes)
    ),
    smart_quotes=(
        ("\u201c", "\u201d"),   # "" left/right double (occasionally used)
    ),
    single_quotes=(
        ("\u2018", "\u2019"),   # '' left/right single (rarely used)
    ),

    # --- Speaker attribution ---
    # Japanese speech verbs (past tense forms commonly used in narration)
    speaker_verbs=frozenset({
        "\u8a00\u3063\u305f",       # itta (said)
        "\u7b54\u3048\u305f",       # kotaeta (answered)
        "\u8a71\u3057\u305f",       # hanashita (spoke)
        "\u53eb\u3093\u3060",       # sakenda (shouted)
        "\u3055\u3055\u3084\u3044\u305f",  # sasayaita (whispered)
        "\u3064\u3076\u3084\u3044\u305f",  # tsubuyaita (muttered)
        "\u5c0b\u306d\u305f",       # tazuneta (asked)
        "\u805e\u3044\u305f",       # kiita (asked/listened)
        "\u6b4c\u3063\u305f",       # utatta (sang)
        "\u7b11\u3063\u305f",       # waratta (laughed)
        "\u6ce3\u3044\u305f",       # naita (cried)
        "\u547d\u3058\u305f",       # meijita (ordered)
        "\u8a34\u3048\u305f",       # uttaeta (pleaded)
        "\u52df\u3063\u305f",       # tsunotta (appealed)
        "\u8aac\u660e\u3057\u305f",  # setsumei shita (explained)
        "\u8ffd\u52a0\u3057\u305f",  # tsuika shita (added)
        "\u7d9a\u3051\u305f",       # tsuzuketa (continued)
        "\u4e3b\u5f35\u3057\u305f",  # shuchou shita (insisted)
        "\u544a\u3052\u305f",       # tsugeta (told/informed)
        "\u6050\u9cf4\u3057\u305f",  # kyoumei shita (exclaimed in fear)
    }),

    emotion_hints={
        "\u3055\u3055\u3084\u3044\u305f": "whisper",
        "\u3064\u3076\u3084\u3044\u305f": "whisper",
        "\u53eb\u3093\u3060": "angry",
        "\u547d\u3058\u305f": "angry",
        "\u6ce3\u3044\u305f": "sad",
        "\u8a34\u3048\u305f": "sad",
        "\u7b11\u3063\u305f": "happy",
        "\u6b4c\u3063\u305f": "happy",
    },

    speaker_blacklist=frozenset({
        # Personal pronouns (various formality levels)
        "\u79c1",     # watashi (I)
        "\u4ffa",     # ore (I, masculine)
        "\u50d5",     # boku (I, masculine)
        "\u3042\u305f\u3057",  # atashi (I, feminine)
        "\u5f7c",     # kare (he)
        "\u5f7c\u5973",  # kanojo (she)
        "\u305d\u308c",  # sore (it)
        "\u3053\u308c",  # kore (this)
        "\u3042\u308c",  # are (that)
        "\u8ab0",     # dare (who)
        "\u4eca",     # ima (now)
        "\u305d\u3057\u3066",  # soshite (and then)
        "\u3057\u304b\u3057",  # shikashi (however)
        "\u3060\u304b\u3089",  # dakara (therefore)
        "\u3067\u3082",  # demo (but)
        "\u3084\u304c\u3066",  # yagate (eventually)
        "\u7a81\u7136",  # totsuzen (suddenly)
        "\u9759\u304b\u306b",  # shizuka ni (quietly)
        "\u5927\u304d\u306a\u58f0\u3067",  # ookina koe de (loudly)
    }),

    # Japanese name pattern: handles kanji, hiragana, katakana names
    # Also allows romanized names for mixed-language texts
    valid_name_pattern=r"^[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffA-Za-z\u00C0-\u024F][\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffA-Za-z\u00C0-\u024F'\-\s\.]{0,28}[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffA-Za-z\u00C0-\u024F]$",

    # Gender cue words (Japanese)
    female_cue_words=frozenset({
        "\u5f7c\u5973",   # kanojo (she/her)
        "\u5973",       # onna (woman)
        "\u5973\u306e\u5b50",  # onna no ko (girl)
        "\u6bcd",       # haha (mother)
        "\u59c9",       # ane (older sister)
        "\u59b9",       # imouto (younger sister)
        "\u5a18",       # musume (daughter)
        "\u59bb",       # tsuma (wife)
        "\u5973\u738b",   # joou (queen)
        "\u59eb",       # hime (princess)
    }),
    male_cue_words=frozenset({
        "\u5f7c",       # kare (he/him)
        "\u7537",       # otoko (man)
        "\u7537\u306e\u5b50",  # otoko no ko (boy)
        "\u7236",       # chichi (father)
        "\u5144",       # ani (older brother)
        "\u5f1f",       # otouto (younger brother)
        "\u606f\u5b50",   # musuko (son)
        "\u592b",       # otto (husband)
        "\u738b",       # ou (king)
        "\u738b\u5b50",   # ouji (prince)
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^\u7b2c(.+)\u7ae0(?:\s*(.*))?$",        # 第X章 (Chapter X)
        r"^\u7b2c(.+)\u90e8(?:\s*(.*))?$",        # 第X部 (Part X)
        r"^(?:Chapter|CHAPTER)\s+(\d+|[IVXLCDM]+)(?:\s*[:\-\.]\s*(.*))?$",
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

register_profile(JAPANESE)
