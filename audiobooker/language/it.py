"""
Italian language profile for Audiobooker.

Provides Italian dialogue quote styles (guillemets «» and curly “”),
speech verbs, pronoun/adverb blacklist, emotion hints, accented name
pattern, and chapter heading patterns (Capitolo/Parte).
"""

from audiobooker.language.profile import LanguageProfile, register_profile

ITALIAN = LanguageProfile(
    code="it",
    name="Italian",

    # --- Dialogue detection ---
    # Italian prose uses guillemets «» as the primary dialogue markers,
    # with curly double quotes also common in modern digital editions.
    dialogue_quotes=(
        ("«", "»"),   # «» guillemets (primary)
        ('"', '"'),             # ASCII double quotes
    ),
    smart_quotes=(
        ("“", "”"),   # "" curly double quotes
    ),
    single_quotes=(
        ("‘", "’"),   # '' curly single quotes
        ("'", "'"),
    ),

    # --- Speaker attribution ---
    speaker_verbs=frozenset({
        "disse", "chiese", "rispose", "domandò", "esclamò",
        "gridò", "urlò", "sussurrò", "mormorò",
        "borbottò", "ribatté", "replicò", "aggiunse",
        "continuò", "spiegò", "osservò", "commento",
        "commentò", "ammise", "confessò", "annunciò",
        "dichiarò", "ordinò", "implòrò", "implorò",
        "supplicò", "pregò", "sospirò", "gemette",
        "singhiozzò", "rise", "ridacchiò", "ringhiò",
        "sibilò", "insistette", "protestò", "ripeté",
        "promise", "avvertì",
    }),

    emotion_hints={
        "sussurrò": "whisper",
        "mormorò": "whisper",
        "gridò": "angry",
        "urlò": "angry",
        "ordinò": "angry",
        "ringhiò": "grumpy",
        "borbottò": "grumpy",
        "sibilò": "angry",
        "esclamò": "excited",
        "singhiozzò": "sad",
        "sospirò": "sad",
        "gemette": "sad",
        "implorò": "sad",
        "supplicò": "sad",
        "pregò": "sad",
        "rise": "happy",
        "ridacchiò": "happy",
        "avvertì": "fearful",
    },

    speaker_blacklist=frozenset({
        # Personal/subject pronouns
        "io", "tu", "lui", "lei", "esso", "essa", "noi", "voi", "loro",
        "egli", "ella", "essi", "esse",
        # Object/clitic pronouns
        "mi", "ti", "ci", "vi", "si", "lo", "la", "li", "le", "gli", "ne",
        "me", "te", "se",
        # Possessives
        "mio", "mia", "tuo", "tua", "suo", "sua", "nostro", "nostra",
        "vostro", "vostra", "loro",
        # Adverbs of manner
        "piano", "forte", "lentamente", "rapidamente", "dolcemente",
        "tristemente", "allegramente", "nervosamente", "freddamente",
        "calorosamente", "improvvisamente", "subito", "infine",
        "finalmente", "tuttavia", "comunque", "inoltre", "quindi",
        "dunque", "poi", "allora",
    }),

    # Italian name pattern: handles accented vowels (àèéìòù) and particles
    # like di/de/della used in surnames.
    valid_name_pattern=r"^(?:(?:Signor|Signora|Signorina|Dottor|Dottore|Don|Donna|Padre|Capitano|Conte|Contessa|di|de|della|del)\s+)?[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'\-\s\.]{0,48}[A-Za-zÀ-ɏ]$",

    # Gender cue words (Italian)
    female_cue_words=frozenset({
        "lei", "ella", "essa", "sua", "donna", "ragazza", "madre",
        "sorella", "figlia", "moglie", "regina", "principessa", "signora",
        "signorina", "contessa",
    }),
    male_cue_words=frozenset({
        "lui", "egli", "esso", "suo", "uomo", "ragazzo", "padre",
        "fratello", "figlio", "marito", "re", "principe", "signore",
        "don", "conte", "cavaliere",
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^(?:Capitolo|CAPITOLO)\s+(\d+|[IVXLCDM]+|[A-Za-zÀ-ɏ]+)(?:\s*[:\-\.]\s*(.*))?$",
        r"^(?:Parte|PARTE)\s+(\d+|[IVXLCDM]+)(?:\s*[:\-\.]\s*(.*))?$",
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

register_profile(ITALIAN)
