"""
Voice suggestion engine for Audiobooker.

Provides ranked voice suggestions per speaker based on:
1. Voice registry metadata/tags (if available from voice-soundboard)
2. Curated heuristics (narrator vs dialogue, gender cues, diversity)

Suggestions are explainable: each comes with a human-readable reason.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("audiobooker.casting.suggester")


# ---------------------------------------------------------------------------
# Suggestion output
# ---------------------------------------------------------------------------

@dataclass
class VoiceSuggestion:
    """A single voice suggestion with reason."""
    voice_id: str
    score: float            # 0.0 - 1.0
    reason: str             # Human-readable explanation
    tags: list[str] = field(default_factory=list)


@dataclass
class SpeakerSuggestions:
    """Suggestions for a single speaker."""
    speaker: str
    suggestions: list[VoiceSuggestion] = field(default_factory=list)

    @property
    def top(self) -> Optional[VoiceSuggestion]:
        return self.suggestions[0] if self.suggestions else None


# ---------------------------------------------------------------------------
# Voice metadata (from voice-soundboard or fallback)
# ---------------------------------------------------------------------------

@dataclass
class VoiceInfo:
    """Metadata about a voice."""
    voice_id: str
    gender: str = "unknown"   # "male" | "female" | "unknown"
    accent: str = "american"  # "american" | "british" | "unknown"
    style: str = "neutral"    # "neutral" | "expressive" | "powerful" | "calm"
    tags: list[str] = field(default_factory=list)


# Known voice metadata (from voice-soundboard naming convention)
# Convention: af_ = american female, am_ = american male,
#             bf_ = british female, bm_ = british male
_VOICE_PREFIX_MAP = {
    "af_": ("female", "american"),
    "am_": ("male", "american"),
    "bf_": ("female", "british"),
    "bm_": ("male", "british"),
}

# Curated voice notes (personality traits for better matching)
_VOICE_NOTES: dict[str, dict] = {
    "af_heart": {"style": "calm", "tags": ["narrator", "warm", "default"]},
    "af_aoede": {"style": "expressive", "tags": ["narrator", "elegant"]},
    "af_jessica": {"style": "neutral", "tags": ["dialogue", "clear"]},
    "af_sky": {"style": "expressive", "tags": ["young", "energetic"]},
    "am_eric": {"style": "neutral", "tags": ["dialogue", "clear"]},
    "am_fenrir": {"style": "powerful", "tags": ["narrator", "deep", "commanding"]},
    "am_liam": {"style": "neutral", "tags": ["dialogue", "young"]},
    "am_onyx": {"style": "calm", "tags": ["narrator", "deep"]},
    "bf_alice": {"style": "neutral", "tags": ["dialogue", "refined"]},
    "bf_emma": {"style": "expressive", "tags": ["dialogue", "warm"]},
    "bf_isabella": {"style": "calm", "tags": ["narrator", "gentle"]},
    "bm_george": {"style": "calm", "tags": ["narrator", "authoritative"]},
    "bm_lewis": {"style": "neutral", "tags": ["dialogue", "clear"]},
}


def _get_voice_info(voice_id: str) -> VoiceInfo:
    """Build VoiceInfo from voice ID conventions and curated notes."""
    gender = "unknown"
    accent = "unknown"
    for prefix, (g, a) in _VOICE_PREFIX_MAP.items():
        if voice_id.startswith(prefix):
            gender = g
            accent = a
            break

    notes = _VOICE_NOTES.get(voice_id, {})
    style = notes.get("style", "neutral")
    tags = notes.get("tags", [])

    return VoiceInfo(
        voice_id=voice_id,
        gender=gender,
        accent=accent,
        style=style,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# Voice registry protocol (for testing)
# ---------------------------------------------------------------------------

@runtime_checkable
class VoiceRegistry(Protocol):
    """Interface for querying available voices."""
    def list_voices(self) -> list[str]: ...


class DefaultVoiceRegistry:
    """Queries real voice-soundboard."""

    def list_voices(self) -> list[str]:
        try:
            from audiobooker.casting.voice_registry import get_available_voices
            return sorted(get_available_voices())
        except ImportError:
            # Fall back to curated list
            return sorted(_VOICE_NOTES.keys())


# ---------------------------------------------------------------------------
# Suggester
# ---------------------------------------------------------------------------

# Gender-hinting patterns in speaker names / utterance text
_FEMALE_CUES = re.compile(
    r"\b(?:she|her|hers|herself|woman|girl|mother|sister|daughter|wife|queen"
    r"|princess|lady|madam|miss|mrs|ms)\b",
    re.IGNORECASE,
)
_MALE_CUES = re.compile(
    r"\b(?:he|him|his|himself|man|boy|father|brother|son|husband|king"
    r"|prince|lord|sir|mr)\b",
    re.IGNORECASE,
)


class VoiceSuggester:
    """
    Suggests voices for speakers based on heuristics and metadata.

    Args:
        registry: Voice registry to query (defaults to voice-soundboard).
        max_suggestions: Maximum suggestions per speaker.
    """

    def __init__(
        self,
        registry: Optional[VoiceRegistry] = None,
        max_suggestions: int = 3,
    ) -> None:
        self.registry = registry or DefaultVoiceRegistry()
        self.max_suggestions = max_suggestions
        self._used_voices: set[str] = set()

    def suggest_for_speaker(
        self,
        speaker: str,
        sample_utterances: list[str] = None,
        *,
        is_narrator: bool = False,
        already_cast: dict[str, str] = None,
    ) -> SpeakerSuggestions:
        """
        Generate voice suggestions for a single speaker.

        Args:
            speaker: Speaker name.
            sample_utterances: Sample lines for trait inference.
            is_narrator: Whether this is the narrator role.
            already_cast: {speaker: voice_id} of already-cast speakers.

        Returns:
            SpeakerSuggestions with ranked options.
        """
        if already_cast is None:
            already_cast = {}
        if sample_utterances is None:
            sample_utterances = []

        self._used_voices = set(already_cast.values())

        available = self.registry.list_voices()
        if not available:
            return SpeakerSuggestions(speaker=speaker)

        # Infer traits from name and utterances
        gender_pref = self._infer_gender(speaker, sample_utterances)

        # Score each voice
        scored: list[tuple[float, VoiceSuggestion]] = []

        for voice_id in available:
            info = _get_voice_info(voice_id)
            score = 0.0
            reasons = []

            # Gender match
            if gender_pref and info.gender == gender_pref:
                score += 0.3
                reasons.append(f"gender match ({gender_pref})")
            elif gender_pref and info.gender != "unknown" and info.gender != gender_pref:
                score -= 0.5
                reasons.append(f"gender mismatch ({info.gender})")

            # Role match (narrator vs dialogue)
            if is_narrator and "narrator" in info.tags:
                score += 0.4
                reasons.append("narrator voice")
            elif not is_narrator and "dialogue" in info.tags:
                score += 0.2
                reasons.append("dialogue voice")

            # Clarity bonus for narrator
            if is_narrator and info.style in ("calm", "neutral"):
                score += 0.1
                reasons.append(f"{info.style} style")

            # Diversity penalty (avoid reuse)
            if voice_id in self._used_voices:
                score -= 0.6
                reasons.append("already assigned to another speaker")

            # Known voice bonus
            if voice_id in _VOICE_NOTES:
                score += 0.05
                reasons.append("curated voice")

            reason_str = "; ".join(reasons) if reasons else "default suggestion"
            scored.append((
                score,
                VoiceSuggestion(
                    voice_id=voice_id,
                    score=max(0.0, min(1.0, (score + 1.0) / 2.0)),  # normalize to 0-1
                    reason=reason_str,
                    tags=info.tags,
                ),
            ))

        # Sort by score descending, then voice_id for determinism
        scored.sort(key=lambda x: (-x[0], x[1].voice_id))

        suggestions = [s for _, s in scored[:self.max_suggestions]]

        return SpeakerSuggestions(speaker=speaker, suggestions=suggestions)

    def suggest_all(
        self,
        speakers: list[str],
        speaker_utterances: Optional[dict[str, list[str]]] = None,
        already_cast: Optional[dict[str, str]] = None,
    ) -> list[SpeakerSuggestions]:
        """
        Generate suggestions for all speakers.

        Args:
            speakers: List of speaker names.
            speaker_utterances: {speaker: [sample_lines]}.
            already_cast: {speaker: voice_id} of already-cast speakers.

        Returns:
            List of SpeakerSuggestions, one per speaker.
        """
        if already_cast is None:
            already_cast = {}
        if speaker_utterances is None:
            speaker_utterances = {}

        results = []
        # Track which voices we've suggested to avoid duplicates
        cast_so_far = dict(already_cast)

        for speaker in speakers:
            is_narrator = speaker.lower() in ("narrator", "narration")
            samples = speaker_utterances.get(speaker, [])

            suggestions = self.suggest_for_speaker(
                speaker,
                sample_utterances=samples,
                is_narrator=is_narrator,
                already_cast=cast_so_far,
            )
            results.append(suggestions)

            # Record top suggestion as pseudo-cast for diversity
            if suggestions.top:
                cast_so_far[speaker] = suggestions.top.voice_id

        return results

    def _infer_gender(
        self,
        speaker: str,
        sample_utterances: list[str],
    ) -> Optional[str]:
        """Infer likely gender from name conventions and utterance cues."""
        combined = " ".join(sample_utterances)

        female_score = len(_FEMALE_CUES.findall(combined))
        male_score = len(_MALE_CUES.findall(combined))

        if female_score > male_score + 1:
            return "female"
        elif male_score > female_score + 1:
            return "male"

        return None
