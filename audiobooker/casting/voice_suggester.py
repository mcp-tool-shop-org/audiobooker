"""
Voice suggestion engine for Audiobooker.

Provides ranked voice suggestions per speaker based on:
1. Voice registry metadata/tags (if available from voice-soundboard)
2. Curated heuristics (narrator vs dialogue, gender cues, diversity)
3. Name-based gender inference (FT-CAST-005)
4. Age/archetype detection for style matching (FT-CAST-006)
5. Dynamic voice metadata from voice-soundboard (FT-CAST-016)

Suggestions are explainable: each comes with a human-readable reason.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from audiobooker.language.profile import LanguageProfile, get_profile
from audiobooker.models import CastingTable

logger = logging.getLogger("audiobooker.casting.suggester")


# ---------------------------------------------------------------------------
# FT-CAST-005: Name-based gender inference — curated top 50 per gender
# ---------------------------------------------------------------------------

_FEMALE_NAMES: frozenset[str] = frozenset({
    "mary", "patricia", "jennifer", "linda", "barbara", "elizabeth",
    "susan", "jessica", "sarah", "karen", "lisa", "nancy", "betty",
    "margaret", "sandra", "ashley", "dorothy", "kimberly", "emily",
    "donna", "michelle", "carol", "amanda", "melissa", "deborah",
    "stephanie", "rebecca", "sharon", "laura", "cynthia", "kathleen",
    "amy", "angela", "shirley", "anna", "brenda", "pamela", "emma",
    "nicole", "helen", "samantha", "katherine", "christine", "alice",
    "rachel", "carolyn", "janet", "catherine", "maria", "heather",
})

_MALE_NAMES: frozenset[str] = frozenset({
    "james", "robert", "john", "michael", "david", "william", "richard",
    "joseph", "thomas", "charles", "christopher", "daniel", "matthew",
    "anthony", "mark", "donald", "steven", "paul", "andrew", "joshua",
    "kenneth", "kevin", "brian", "george", "timothy", "ronald", "edward",
    "jason", "jeffrey", "ryan", "jacob", "gary", "nicholas", "eric",
    "jonathan", "stephen", "larry", "justin", "scott", "brandon",
    "benjamin", "samuel", "raymond", "gregory", "frank", "alexander",
    "patrick", "jack", "henry", "peter",
})


# ---------------------------------------------------------------------------
# FT-CAST-006: Age and archetype keyword maps
# ---------------------------------------------------------------------------

_AGE_KEYWORDS: dict[str, str] = {
    "child": "young",
    "boy": "young",
    "girl": "young",
    "kid": "young",
    "young": "young",
    "old": "old",
    "elderly": "old",
    "ancient": "old",
    "aged": "old",
    "grandfather": "old",
    "grandmother": "old",
    "grandpa": "old",
    "grandma": "old",
}

_ARCHETYPE_KEYWORDS: dict[str, str] = {
    "captain": "commanding",
    "king": "commanding",
    "queen": "commanding",
    "general": "commanding",
    "commander": "commanding",
    "servant": "calm",
    "maid": "calm",
    "butler": "calm",
    "witch": "expressive",
    "wizard": "expressive",
    "sorcerer": "expressive",
    "doctor": "neutral",
    "priest": "calm",
    "monk": "calm",
    "soldier": "powerful",
    "warrior": "powerful",
    "knight": "powerful",
    "guard": "powerful",
}

# Map age/archetype style preferences to voice style bonuses
_STYLE_PREFERENCE: dict[str, dict[str, float]] = {
    "young": {"tags_bonus": {"young", "energetic"}, "style": "expressive"},
    "old": {"tags_bonus": {"deep", "authoritative"}, "style": "calm"},
    "commanding": {"tags_bonus": {"commanding", "authoritative", "deep"}, "style": "powerful"},
    "calm": {"tags_bonus": {"gentle", "warm"}, "style": "calm"},
    "expressive": {"tags_bonus": {"expressive", "elegant"}, "style": "expressive"},
    "neutral": {"tags_bonus": {"clear", "neutral"}, "style": "neutral"},
    "powerful": {"tags_bonus": {"commanding", "deep", "powerful"}, "style": "powerful"},
}


# ---------------------------------------------------------------------------
# Suggestion output
# ---------------------------------------------------------------------------

@dataclass
class VoiceSuggestion:
    """A single voice suggestion with reason."""
    voice_id: str
    score: float            # 0.0 - 1.0 (normalized)
    reason: str             # Human-readable explanation
    tags: list[str] = field(default_factory=list)
    low_confidence: bool = False  # True when the pick has no real matching signal


# Reasons that carry no speaker-specific matching signal — a pick whose ONLY
# reasons are these is a baseline guess, not a real match.
_BASELINE_REASONS: frozenset[str] = frozenset({
    "default suggestion",
    "curated voice",
})


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


# FT-CAST-016: Runtime voice metadata cache (populated from voice-soundboard)
_RUNTIME_VOICE_METADATA: dict[str, dict] = {}
_RUNTIME_METADATA_LOADED: bool = False


def _load_runtime_voice_metadata() -> None:
    """FT-CAST-016: Try to load voice metadata from voice-soundboard at runtime."""
    global _RUNTIME_VOICE_METADATA, _RUNTIME_METADATA_LOADED
    if _RUNTIME_METADATA_LOADED:
        return
    _RUNTIME_METADATA_LOADED = True
    try:
        from voice_soundboard.config import VOICES
        for vid, vdata in VOICES.items():
            meta = {}
            if isinstance(vdata, dict):
                meta = {
                    "style": vdata.get("style", "neutral"),
                    "tags": vdata.get("tags", []),
                    "gender": vdata.get("gender"),
                    "accent": vdata.get("accent"),
                }
            _RUNTIME_VOICE_METADATA[vid] = meta
        logger.info(
            "FT-CAST-016: Loaded runtime voice metadata for %d voices from voice-soundboard",
            len(_RUNTIME_VOICE_METADATA),
        )
    except (ImportError, AttributeError):
        logger.debug(
            "FT-CAST-016: voice-soundboard not available — using fallback _VOICE_NOTES"
        )


def _get_voice_info(voice_id: str) -> VoiceInfo:
    """Build VoiceInfo from voice ID conventions, runtime metadata, and curated notes."""
    # FT-CAST-016: Try runtime metadata first
    _load_runtime_voice_metadata()

    gender = "unknown"
    accent = "unknown"
    matched_prefix = False
    for prefix, (g, a) in _VOICE_PREFIX_MAP.items():
        if voice_id.startswith(prefix):
            gender = g
            accent = a
            matched_prefix = True
            break

    if not matched_prefix:
        logger.debug(
            "Voice %r has unknown prefix — gender/accent will be 'unknown'", voice_id,
        )

    # FT-CAST-016: Prefer runtime metadata, fall back to curated notes
    runtime = _RUNTIME_VOICE_METADATA.get(voice_id)
    if runtime:
        style = runtime.get("style", "neutral")
        tags = runtime.get("tags", [])
        if runtime.get("gender"):
            gender = runtime["gender"]
        if runtime.get("accent"):
            accent = runtime["accent"]
        logger.debug("Voice %r: using runtime metadata", voice_id)
    else:
        notes = _VOICE_NOTES.get(voice_id, {})
        style = notes.get("style", "neutral")
        tags = notes.get("tags", [])
        logger.debug("Voice %r: using fallback curated notes", voice_id)

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
            logger.info(
                "voice-soundboard not available — falling back to curated voice list (%d voices)",
                len(_VOICE_NOTES),
            )
            return sorted(_VOICE_NOTES.keys())


# ---------------------------------------------------------------------------
# Suggester
# ---------------------------------------------------------------------------

def _build_gender_cue_pattern(words: frozenset[str]) -> re.Pattern:
    """Build a compiled regex from a set of gender cue words."""
    if not words:
        return re.compile(r"(?!)")  # never matches
    alt = "|".join(re.escape(w) for w in sorted(words))
    return re.compile(rf"\b(?:{alt})\b", re.IGNORECASE)


class VoiceSuggester:
    """
    Suggests voices for speakers based on heuristics and metadata.

    Args:
        registry: Voice registry to query (defaults to voice-soundboard).
        max_suggestions: Maximum suggestions per speaker.
        profile: Language profile for gender cue words (defaults to English).
    """

    def __init__(
        self,
        registry: Optional[VoiceRegistry] = None,
        max_suggestions: int = 3,
        profile: Optional[LanguageProfile] = None,
    ) -> None:
        self.registry = registry or DefaultVoiceRegistry()
        self.max_suggestions = max_suggestions
        self.profile = profile or get_profile("en")
        self._female_cues = _build_gender_cue_pattern(self.profile.female_cue_words)
        self._male_cues = _build_gender_cue_pattern(self.profile.male_cue_words)

    def suggest_for_speaker(
        self,
        speaker: str,
        sample_utterances: Optional[list[str]] = None,
        *,
        is_narrator: bool = False,
        already_cast: Optional[dict[str, str]] = None,
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

        used_voices = set(already_cast.values())

        available = self.registry.list_voices()
        if not available:
            return SpeakerSuggestions(speaker=speaker)

        # FT-CAST-005: Infer gender — name-based is primary, pronoun counting is fallback
        gender_pref = self._infer_gender(speaker, sample_utterances)

        # FT-CAST-006: Detect age and archetype cues from name + utterances
        style_prefs = self._infer_style_preferences(speaker, sample_utterances)

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

            # FT-CAST-006: Age/archetype style preference scoring
            for pref_key in style_prefs:
                pref = _STYLE_PREFERENCE.get(pref_key)
                if not pref:
                    continue
                # Style match bonus
                if info.style == pref.get("style"):
                    score += 0.15
                    reasons.append(f"{pref_key} style match")
                # Tag overlap bonus
                bonus_tags = pref.get("tags_bonus", set())
                tag_overlap = bonus_tags & set(info.tags)
                if tag_overlap:
                    score += 0.1 * len(tag_overlap)
                    reasons.append(f"{pref_key} tag match ({', '.join(tag_overlap)})")

            # Diversity penalty (avoid reuse)
            if voice_id in used_voices:
                score -= 0.6
                reasons.append("already assigned to another speaker")

            # Known voice bonus
            if voice_id in _VOICE_NOTES:
                score += 0.05
                reasons.append("curated voice")

            reason_str = "; ".join(reasons) if reasons else "default suggestion"

            # Low-confidence flag: the pick has no real matching signal when
            # every reason it carries is a baseline ("default suggestion" /
            # "curated voice"). Derived from the RAW reasons, not the
            # normalized score (which floors a no-signal pick at ~0.50 and
            # makes a blind guess look like a real match).
            effective_reasons = reasons or ["default suggestion"]
            low_confidence = all(r in _BASELINE_REASONS for r in effective_reasons)

            scored.append((
                score,
                VoiceSuggestion(
                    voice_id=voice_id,
                    score=max(0.0, min(1.0, (score + 1.0) / 2.0)),  # normalize to 0-1
                    reason=reason_str,
                    tags=info.tags,
                    low_confidence=low_confidence,
                ),
            ))

        # Sort by score descending, then voice_id for determinism
        scored.sort(key=lambda x: (-x[0], x[1].voice_id))

        suggestions = [s for _, s in scored[:self.max_suggestions]]

        # Log top-3 scores for debugging (B-015)
        if suggestions:
            top3 = [(s.voice_id, f"{s.score:.2f}") for s in suggestions[:3]]
            logger.debug("Suggestions for %r: %s", speaker, top3)

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
        """
        Infer likely gender from name and utterance cues.

        FT-CAST-005: Name-based inference is the primary signal.
        Falls back to pronoun counting from sample utterances.
        """
        # FT-CAST-005: Primary signal — curated name lists
        # Extract the first name (handles "Mr. Holmes" -> "Holmes",
        # "Captain Ahab" -> "Ahab", or simple "Alice" -> "Alice")
        first_name = speaker.strip().split()[-1].casefold() if speaker.strip() else ""
        if first_name in _FEMALE_NAMES:
            logger.debug("Name-based gender: %r -> female (curated list)", speaker)
            return "female"
        if first_name in _MALE_NAMES:
            logger.debug("Name-based gender: %r -> male (curated list)", speaker)
            return "male"

        # Fallback: pronoun counting from utterance context
        # Cap to first 5000 chars to avoid excessive regex work (B-014)
        combined = " ".join(sample_utterances)[:5000]

        female_score = len(self._female_cues.findall(combined))
        male_score = len(self._male_cues.findall(combined))

        if female_score > male_score + 1:
            return "female"
        elif male_score > female_score + 1:
            return "male"

        return None

    def _infer_style_preferences(
        self,
        speaker: str,
        sample_utterances: list[str],
    ) -> list[str]:
        """
        FT-CAST-006: Detect age cues and archetype keywords.

        Returns a list of style preference keys (e.g. ["young", "commanding"])
        that map to voice style bonuses via _STYLE_PREFERENCE.
        """
        prefs: list[str] = []
        # Combine speaker name + sample text for keyword scanning
        combined = (speaker + " " + " ".join(sample_utterances)[:3000]).casefold()

        # Age cue detection
        seen_age: set[str] = set()
        for keyword, age_class in _AGE_KEYWORDS.items():
            if age_class not in seen_age and re.search(rf"\b{re.escape(keyword)}\b", combined):
                prefs.append(age_class)
                seen_age.add(age_class)
                logger.debug("FT-CAST-006: age cue %r -> %r for %r", keyword, age_class, speaker)

        # Archetype detection
        seen_archetype: set[str] = set()
        for keyword, arch_class in _ARCHETYPE_KEYWORDS.items():
            if arch_class not in seen_archetype and re.search(rf"\b{re.escape(keyword)}\b", combined):
                prefs.append(arch_class)
                seen_archetype.add(arch_class)
                logger.debug("FT-CAST-006: archetype %r -> %r for %r", keyword, arch_class, speaker)

        return prefs


# ---------------------------------------------------------------------------
# FT-CAST-010: Voice audition helper
# ---------------------------------------------------------------------------

def audition_voices(
    speaker: str,
    casting: CastingTable,
    sample_utterances: list[str],
    registry: Optional[VoiceRegistry] = None,
) -> list[dict]:
    """
    Return top 5 voice suggestions for a speaker with audition data.

    Provides the data backing the CLI ``audiobooker audition`` command.

    Args:
        speaker: Speaker name to audition voices for.
        casting: CastingTable for context (already-cast speakers used
                 for diversity scoring).
        sample_utterances: Sample dialogue lines for trait inference.
        registry: Optional VoiceRegistry override (defaults to
                  DefaultVoiceRegistry).

    Returns:
        List of up to 5 dicts, each with keys:
            - voice_id: str
            - gender: str
            - style: str
            - sample_text: str (first utterance truncated to 100 chars)
            - score: float (0.0-1.0)
            - low_confidence: bool (no real matching signal — a baseline guess)
    """
    suggester = VoiceSuggester(
        registry=registry,
        max_suggestions=5,
    )

    # Build already-cast map from casting table
    already_cast: dict[str, str] = {}
    for key, char in casting.characters.items():
        if char.voice_id:
            already_cast[key] = char.voice_id

    is_narrator = speaker.lower() in ("narrator", "narration")
    result = suggester.suggest_for_speaker(
        speaker,
        sample_utterances=sample_utterances,
        is_narrator=is_narrator,
        already_cast=already_cast,
    )

    sample_text = ""
    if sample_utterances:
        sample_text = sample_utterances[0][:100]

    audition_list: list[dict] = []
    for suggestion in result.suggestions:
        info = _get_voice_info(suggestion.voice_id)
        audition_list.append({
            "voice_id": suggestion.voice_id,
            "gender": info.gender,
            "style": info.style,
            "sample_text": sample_text,
            "score": suggestion.score,
            "low_confidence": suggestion.low_confidence,
        })

    return audition_list
