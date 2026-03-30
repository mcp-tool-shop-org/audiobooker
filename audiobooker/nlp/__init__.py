"""
NLP enhancements for Audiobooker.

Optional intelligence layer for speaker resolution, emotion inference,
and text normalization for TTS.
"""

from audiobooker.nlp.booknlp_adapter import BookNLPAdapter, BookNLPResult
from audiobooker.nlp.speaker_resolver import SpeakerResolver
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
    "EmotionInferencer",
    "EmotionResult",
    "normalize",
    "normalize_numbers",
    "normalize_currency",
    "expand_abbreviations",
]
