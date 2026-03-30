"""
Spanish language profile for Audiobooker.

Provides angular quotes (guillemets), Spanish speech verbs,
pronoun blacklist, emotion hints, and chapter heading patterns
for Spanish prose.
"""

from audiobooker.language.profile import LanguageProfile, register_profile

SPANISH = LanguageProfile(
    code="es",
    name="Spanish",

    # --- Dialogue detection ---
    # Spanish uses angular quotes (guillemets) and em-dash style dialogue
    dialogue_quotes=(
        ("\u00ab", "\u00bb"),   # « »  guillemets (primary)
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
        "dijo", "pregunt\u00f3", "respondi\u00f3", "contest\u00f3",
        "susurr\u00f3", "grit\u00f3", "exclam\u00f3", "murmur\u00f3",
        "a\u00f1adi\u00f3", "continu\u00f3", "explic\u00f3", "insisti\u00f3",
        "admiti\u00f3", "confes\u00f3", "declar\u00f3", "anunci\u00f3",
        "afirm\u00f3", "observ\u00f3", "coment\u00f3", "sugiri\u00f3",
        "propuso", "orden\u00f3", "suplic\u00f3", "implor\u00f3",
        "ri\u00f3", "solloz\u00f3", "suspir\u00f3", "gimi\u00f3",
        "gru\u00f1\u00f3", "protest\u00f3", "replic\u00f3", "interrumpi\u00f3",
        "balbuci\u00f3", "tartamude\u00f3", "chill\u00f3", "llam\u00f3",
        "pidi\u00f3", "rog\u00f3", "repiti\u00f3", "se\u00f1al\u00f3",
    }),

    emotion_hints={
        "susurr\u00f3": "whisper",
        "murmur\u00f3": "whisper",
        "grit\u00f3": "angry",
        "chill\u00f3": "angry",
        "orden\u00f3": "angry",
        "protest\u00f3": "angry",
        "exclam\u00f3": "excited",
        "solloz\u00f3": "sad",
        "gimi\u00f3": "sad",
        "suspir\u00f3": "sad",
        "suplic\u00f3": "sad",
        "implor\u00f3": "sad",
        "ri\u00f3": "happy",
        "gru\u00f1\u00f3": "grumpy",
    },

    speaker_blacklist=frozenset({
        # Subject pronouns
        "\u00e9l", "ella", "ellos", "ellas", "yo", "t\u00fa", "usted",
        "nosotros", "nosotras", "vosotros", "vosotras", "ustedes",
        # Object pronouns
        "lo", "la", "los", "las", "le", "les", "me", "te", "se", "nos", "os",
        # Possessive pronouns
        "su", "sus", "mi", "mis", "tu", "tus", "nuestro", "nuestra",
        "nuestros", "nuestras", "vuestro", "vuestra", "vuestros", "vuestras",
        # Adverbs of manner
        "suavemente", "fuerte", "lentamente", "r\u00e1pidamente",
        "tranquilamente", "tristemente", "alegremente", "nerviosamente",
        "furiosamente", "fr\u00edamente", "c\u00e1lidamente",
        "bruscamente", "repentinamente", "finalmente", "luego",
        "sin embargo", "adem\u00e1s", "entonces", "despu\u00e9s",
    }),

    # Spanish name pattern: handles accented characters, particles (de, del, la)
    valid_name_pattern=r"^(?:(?:Sr\.|Sra\.|Srta\.|Dr\.|Don|Do\u00f1a|Capit\u00e1n|Conde|Condesa|el|la|de|del)\s+)?[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-\s\.]{0,48}[A-Za-z\u00C0-\u024F]$",

    # Gender cue words (Spanish)
    female_cue_words=frozenset({
        "ella", "la", "su", "mujer", "chica", "madre",
        "hermana", "hija", "esposa", "reina", "princesa",
        "dama", "se\u00f1ora", "se\u00f1orita", "sra", "srta",
        "do\u00f1a",
    }),
    male_cue_words=frozenset({
        "\u00e9l", "lo", "su", "hombre", "chico", "padre",
        "hermano", "hijo", "esposo", "rey", "pr\u00edncipe",
        "se\u00f1or", "sr", "don", "caballero",
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^(?:Cap\u00edtulo|CAP\u00cdTULO)\s+(\d+|[IVXLCDM]+|[A-Za-z\u00C0-\u024F]+)(?:\s*[:\-\.]\s*(.*))?$",
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

register_profile(SPANISH)
