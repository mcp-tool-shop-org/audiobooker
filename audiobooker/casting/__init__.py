"""
Casting module for Audiobooker.

Handles:
- Dialogue detection (quoted text vs narration)
- Speaker attribution
- Compiling chapters to utterances
- Voice suggestion and validation
- Stage directions and pauses (FT-CAST-017)
- Voice audition helper (FT-CAST-010)
"""

from audiobooker.casting.dialogue import (
    AUSTEN_STYLE,
    FANTASY_MULTI_SPEAKER,
    HEMINGWAY_STYLE,
    MODERN_THRILLER,
    compile_chapter,
    compile_report,
    detect_dialogue,
    extract_speaker_from_context,
    is_valid_speaker_name,
    parse_inline_override,
    utterances_to_script,
)
from audiobooker.casting.voice_registry import (
    VoiceNotFoundError,
    get_available_voices,
    validate_voices,
)
from audiobooker.casting.voice_suggester import (
    DefaultVoiceRegistry,
    SpeakerSuggestions,
    VoiceInfo,
    VoiceRegistry,
    VoiceSuggester,
    VoiceSuggestion,
    audition_voices,
)

__all__ = [
    # dialogue
    "compile_chapter",
    "compile_report",
    "detect_dialogue",
    "extract_speaker_from_context",
    "is_valid_speaker_name",
    "parse_inline_override",
    "utterances_to_script",
    # dialogue test data (FT-CAST-018)
    "AUSTEN_STYLE",
    "HEMINGWAY_STYLE",
    "MODERN_THRILLER",
    "FANTASY_MULTI_SPEAKER",
    # voice_registry
    "VoiceNotFoundError",
    "get_available_voices",
    "validate_voices",
    # voice_suggester
    "DefaultVoiceRegistry",
    "SpeakerSuggestions",
    "VoiceInfo",
    "VoiceRegistry",
    "VoiceSuggester",
    "VoiceSuggestion",
    "audition_voices",
]
