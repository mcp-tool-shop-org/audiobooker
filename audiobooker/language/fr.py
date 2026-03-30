"""
French language profile for Audiobooker.

Provides guillemets, French speech verbs, pronoun blacklist,
emotion hints, and chapter heading patterns for French prose.
"""

from audiobooker.language.profile import LanguageProfile, register_profile

FRENCH = LanguageProfile(
    code="fr",
    name="French",

    # --- Dialogue detection ---
    # French uses guillemets as primary dialogue markers
    dialogue_quotes=(
        ("\u00ab", "\u00bb"),   # « »  guillemets
        ('"', '"'),             # ASCII double quotes (common in digital texts)
    ),
    smart_quotes=(
        ("\u201c", "\u201d"),   # "" left/right double (borrowed English style)
    ),
    single_quotes=(
        ("\u2018", "\u2019"),   # '' left/right single
        ("'", "'"),
    ),

    # --- Speaker attribution ---
    speaker_verbs=frozenset({
        "dit", "demanda", "r\u00e9pondit", "murmura", "chuchota",
        "cria", "hurla", "s\u00e9cria", "souffla", "soupira",
        "grogna", "g\u00e9mit", "implora", "supplia", "ordonna",
        "d\u00e9clara", "annon\u00e7a", "affirma", "ajouta", "continua",
        "expliqua", "insista", "admit", "confessa", "observa",
        "remarqua", "commenta", "sugg\u00e9ra", "proposa", "rit",
        "ricana", "sanglota", "grommela", "marmonna", "b\u00e9gaya",
        "balbutia", "protesta", "objecta", "r\u00e9pliqua", "lan\u00e7a",
    }),

    emotion_hints={
        "chuchota": "whisper",
        "murmura": "whisper",
        "souffla": "whisper",
        "cria": "angry",
        "hurla": "angry",
        "s\u00e9cria": "excited",
        "ordonna": "angry",
        "g\u00e9mit": "sad",
        "sanglota": "sad",
        "soupira": "sad",
        "implora": "sad",
        "supplia": "sad",
        "rit": "happy",
        "ricana": "happy",
        "grogna": "grumpy",
        "grommela": "grumpy",
        "protesta": "angry",
    },

    speaker_blacklist=frozenset({
        # Subject pronouns
        "il", "elle", "ils", "elles", "je", "tu", "nous", "vous", "on",
        # Object pronouns
        "le", "la", "les", "lui", "leur", "me", "te", "se",
        # Possessive pronouns
        "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes",
        "notre", "votre", "nos", "vos", "leurs",
        # Adverbs of manner
        "doucement", "fort", "lentement", "rapidement", "calmement",
        "tristement", "joyeusement", "nerveusement", "furieusement",
        "froidement", "chaleureusement", "vivement", "brusquement",
        "soudain", "soudainement", "aussit\u00f4t", "enfin", "ensuite",
    }),

    # French name pattern: handles accented characters, particles (de, du, le, la)
    valid_name_pattern=r"^(?:(?:M\.|Mme|Mlle|Dr\.|Capitaine|Comte|Comtesse|le|la|du|de)\s+)?[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-\s\.]{0,48}[A-Za-z\u00C0-\u024F]$",

    # Gender cue words (French)
    female_cue_words=frozenset({
        "elle", "la", "sa", "ses", "femme", "fille", "m\u00e8re",
        "soeur", "dame", "reine", "princesse", "madame", "mademoiselle",
        "mme", "mlle",
    }),
    male_cue_words=frozenset({
        "il", "le", "son", "ses", "homme", "gar\u00e7on", "p\u00e8re",
        "fr\u00e8re", "fils", "mari", "roi", "prince", "seigneur",
        "monsieur", "m",
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^(?:Chapitre|CHAPITRE)\s+(\d+|[IVXLCDM]+|[A-Za-z\u00C0-\u024F]+)(?:\s*[:\-\.]\s*(.*))?$",
        r"^(?:Partie|PARTIE)\s+(\d+|[IVXLCDM]+)(?:\s*[:\-\.]\s*(.*))?$",
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

register_profile(FRENCH)
