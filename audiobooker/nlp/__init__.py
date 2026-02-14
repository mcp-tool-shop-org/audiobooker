"""
NLP enhancements for Audiobooker.

Optional intelligence layer for speaker resolution and emotion inference.
"""

from audiobooker.nlp.booknlp_adapter import BookNLPAdapter, BookNLPResult
from audiobooker.nlp.speaker_resolver import SpeakerResolver
from audiobooker.nlp.emotion import EmotionInferencer, EmotionResult

__all__ = [
    "BookNLPAdapter",
    "BookNLPResult",
    "SpeakerResolver",
    "EmotionInferencer",
    "EmotionResult",
]
