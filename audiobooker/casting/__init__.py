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
    DIALOGUE_UNKNOWN_FAIL_RATE,
    DIALOGUE_UNKNOWN_WARN_RATE,
    FANTASY_MULTI_SPEAKER,
    HEMINGWAY_STYLE,
    LOW_CONFIDENCE_THRESHOLD,
    MODERN_THRILLER,
    compile_chapter,
    compile_report,
    detect_dialogue,
    dialogue_quality_verdict,
    extract_speaker_from_context,
    extract_speaker_with_confidence,
    is_valid_speaker_name,
    parse_inline_override,
    utterances_to_script,
)
from audiobooker.casting.voice_registry import (
    VoiceBackendError,
    VoiceBackendIncompatibleError,
    VoiceBackendUnavailableError,
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
    "dialogue_quality_verdict",
    "extract_speaker_from_context",
    # FEAT-CAST-001: attribution provenance + confidence. `cli.py` belongs to
    # another agent this wave; a `speakers merge <from> <to>` command and the
    # `compile` low-confidence summary need these names and
    # `audiobooker.nlp.speaker_resolver.suggest_aliases`.
    "extract_speaker_with_confidence",
    "LOW_CONFIDENCE_THRESHOLD",
    "DIALOGUE_UNKNOWN_WARN_RATE",
    "DIALOGUE_UNKNOWN_FAIL_RATE",
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
    "VoiceBackendError",
    "VoiceBackendIncompatibleError",
    "VoiceBackendUnavailableError",
    # voice_suggester
    "DefaultVoiceRegistry",
    "SpeakerSuggestions",
    "VoiceInfo",
    "VoiceRegistry",
    "VoiceSuggester",
    "VoiceSuggestion",
    "audition_voices",
]
