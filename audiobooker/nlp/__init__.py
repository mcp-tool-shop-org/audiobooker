"""
NLP enhancements for Audiobooker.

Optional intelligence layer for speaker resolution, emotion inference,
and text normalization for TTS.
"""

from audiobooker.nlp.booknlp_adapter import BookNLPAdapter, BookNLPResult
from audiobooker.nlp.speaker_resolver import (
    AliasProposal,
    SpeakerResolver,
    suggest_aliases,
)
from audiobooker.nlp.emotion import EmotionInferencer, EmotionResult
from audiobooker.nlp.normalizer import (
    normalize,
    normalize_numbers,
    normalize_currency,
    expand_abbreviations,
)

__all__ = [
    "BookNLPAdapter",
    "BookNLPResult",
    "SpeakerResolver",
    # FEAT-CAST-003: alias/merge proposals. `cli.py` belongs to another
    # agent this wave and needs these for `speakers merge <from> <to>`,
    # alongside `CastingTable.merge_speaker` which applies one.
    "AliasProposal",
    "suggest_aliases",
    "EmotionInferencer",
    "EmotionResult",
    "normalize",
    "normalize_numbers",
    "normalize_currency",
    "expand_abbreviations",
]
