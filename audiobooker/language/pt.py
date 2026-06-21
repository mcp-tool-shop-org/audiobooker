"""
Portuguese language profile for Audiobooker.

Provides Portuguese dialogue markers (em-dash travessão for direct speech,
plus guillemets «» and curly “” used in some editions), speech verbs,
pronoun/adverb blacklist, emotion hints, accented name pattern, and chapter
heading patterns (Capítulo/Parte).
"""

from audiobooker.language.profile import LanguageProfile, register_profile

PORTUGUESE = LanguageProfile(
    code="pt",
    name="Portuguese",

    # --- Dialogue detection ---
    # Portuguese prose marks direct speech primarily with the em-dash
    # (travessão) at line start; guillemets «» and curly “” also appear,
    # especially in European Portuguese editions.
    dialogue_quotes=(
        ("—", "\n"),    # em-dash travessão (line-leading direct speech)
        ("«", "»"),    # «» guillemets
        ('"', '"'),               # ASCII double quotes
    ),
    smart_quotes=(
        ("“", "”"),     # "" curly double quotes
    ),
    single_quotes=(
        ("‘", "’"),     # '' curly single quotes
        ("'", "'"),
    ),

    # --- Speaker attribution ---
    speaker_verbs=frozenset({
        "disse", "perguntou", "respondeu", "indagou", "exclamou",
        "gritou", "berrou", "sussurrou", "murmurou",
        "resmungou", "retrucou", "replicou", "acrescentou",
        "continuou", "explicou", "observou", "comentou",
        "admitiu", "confessou", "anunciou", "declarou",
        "ordenou", "implorou", "suplicou", "rogou",
        "suspirou", "gemeu", "soluçou", "riu",
        "gargalhou", "rosnou", "sibilou", "insistiu",
        "protestou", "repetiu", "prometeu", "avisou",
    }),

    emotion_hints={
        "sussurrou": "whisper",
        "murmurou": "whisper",
        "gritou": "angry",
        "berrou": "angry",
        "ordenou": "angry",
        "rosnou": "grumpy",
        "resmungou": "grumpy",
        "sibilou": "angry",
        "exclamou": "excited",
        "soluçou": "sad",
        "suspirou": "sad",
        "gemeu": "sad",
        "implorou": "sad",
        "suplicou": "sad",
        "rogou": "sad",
        "riu": "happy",
        "gargalhou": "happy",
        "avisou": "fearful",
    },

    speaker_blacklist=frozenset({
        # Personal/subject pronouns
        "eu", "tu", "ele", "ela", "nós", "vós", "eles", "elas",
        "você", "vocês",
        # Object/clitic pronouns
        "me", "te", "se", "lhe", "lhes", "nos", "vos", "o", "a", "os", "as",
        "mim", "ti", "si",
        # Possessives
        "meu", "minha", "teu", "tua", "seu", "sua", "nosso", "nossa",
        "vosso", "vossa", "dele", "dela", "deles", "delas",
        # Adverbs of manner
        "baixo", "alto", "lentamente", "rapidamente", "suavemente",
        "tristemente", "alegremente", "nervosamente", "friamente",
        "calorosamente", "subitamente", "logo", "finalmente",
        "entretanto", "contudo", "porém", "todavia", "além",
        "portanto", "então", "depois",
    }),

    # Portuguese name pattern: handles accented vowels (áàâãéêíóôõúç) and
    # particles like da/de/do/dos used in surnames.
    valid_name_pattern=r"^(?:(?:Senhor|Senhora|Senhorita|Doutor|Doutora|Dom|Dona|Padre|Capitão|Conde|Condessa|da|de|do|dos|das)\s+)?[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'\-\s\.]{0,48}[A-Za-zÀ-ɏ]$",

    # Gender cue words (Portuguese)
    female_cue_words=frozenset({
        "ela", "sua", "dela", "mulher", "menina", "garota", "mãe",
        "irmã", "filha", "esposa", "rainha", "princesa", "senhora",
        "senhorita", "condessa", "dona",
    }),
    male_cue_words=frozenset({
        "ele", "seu", "dele", "homem", "menino", "garoto", "pai",
        "irmão", "filho", "marido", "rei", "príncipe", "senhor",
        "dom", "conde", "cavaleiro",
    }),

    # --- Chapter parsing ---
    chapter_patterns=(
        r"^(?:Capítulo|CAPÍTULO|Capitulo|CAPITULO)\s+(\d+|[IVXLCDM]+|[A-Za-zÀ-ɏ]+)(?:\s*[:\-\.]\s*(.*))?$",
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

register_profile(PORTUGUESE)
