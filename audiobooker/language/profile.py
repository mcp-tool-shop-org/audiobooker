"""
LanguageProfile — bundles all language-specific rules for the pipeline.

Each profile provides:
- Dialogue quote pairs (double, smart, optional single)
- Speech verbs for speaker attribution
- Emotion hints from verbs
- Speaker blacklist (pronouns, adverbs, etc.)
- Chapter heading patterns
- Scene break patterns
- Name validation regex
- Name normalization function
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LanguageProfile:
    """Immutable set of language-specific rules."""

    code: str
    name: str

    # Dialogue detection
    dialogue_quotes: tuple[tuple[str, str], ...] = ()
    smart_quotes: tuple[tuple[str, str], ...] = ()
    single_quotes: tuple[tuple[str, str], ...] = ()

    # Speaker attribution
    speaker_verbs: frozenset[str] = frozenset()
    emotion_hints: dict[str, str] = field(default_factory=dict)
    speaker_blacklist: frozenset[str] = frozenset()
    valid_name_pattern: str = r"^[A-Z][a-z]{1,14}$"

    # Chapter parsing
    chapter_patterns: tuple[str, ...] = ()
    scene_break_patterns: tuple[str, ...] = ()

    def normalize_name(self, name: str) -> str:
        """Canonical form for speaker lookup keys."""
        return name.casefold().strip()

    def is_valid_name(self, name: str) -> bool:
        """Check if a string looks like a valid speaker name."""
        return bool(re.match(self.valid_name_pattern, name))

    def build_said_patterns(self) -> list[re.Pattern]:
        """Build compiled verb-name / name-verb regex patterns."""
        if not self.speaker_verbs:
            return []
        verb_alt = "|".join(re.escape(v) for v in sorted(self.speaker_verbs))
        return [
            # "said Alice" — verb then name
            re.compile(
                rf"(?:{verb_alt})\s+([A-Z][a-z]+)(?:\s|[,.\!\?]|$)",
                re.IGNORECASE,
            ),
            # "Alice said" — name then verb
            re.compile(
                rf"([A-Z][a-z]+)\s+(?:{verb_alt})",
                re.IGNORECASE,
            ),
        ]

    def build_emotion_verb_pattern(self) -> Optional[re.Pattern]:
        """Build a pattern matching verbs that carry emotion hints."""
        keys = [k for k in self.emotion_hints if k in self.speaker_verbs]
        if not keys:
            return None
        alt = "|".join(re.escape(k) for k in sorted(keys))
        return re.compile(rf"\b({alt})\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROFILES: dict[str, LanguageProfile] = {}


def register_profile(profile: LanguageProfile) -> None:
    _PROFILES[profile.code] = profile


def get_profile(code: str = "en") -> LanguageProfile:
    """Look up a language profile by ISO code. Defaults to English."""
    if code not in _PROFILES:
        # Lazy import to populate registry
        import audiobooker.language.en  # noqa: F401
    if code not in _PROFILES:
        raise ValueError(
            f"Unsupported language: {code!r}. "
            f"Available: {', '.join(sorted(_PROFILES)) or 'none'}"
        )
    return _PROFILES[code]


def available_profiles() -> list[str]:
    """Return codes of all registered language profiles."""
    if not _PROFILES:
        import audiobooker.language.en  # noqa: F401
    return sorted(_PROFILES.keys())
