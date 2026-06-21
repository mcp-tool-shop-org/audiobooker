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

import importlib
import logging
import pkgutil
import re
import types
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("audiobooker.language")


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
    # emotion_hints is wrapped in MappingProxyType by __post_init__
    # to prevent mutation of this frozen dataclass's contents.
    emotion_hints: dict[str, str] = field(default_factory=dict)
    speaker_blacklist: frozenset[str] = frozenset()
    valid_name_pattern: str = r"^[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-]{0,22}[A-Za-z\u00C0-\u024F]$"

    # Gender cue words for voice suggestion (language-specific)
    female_cue_words: frozenset[str] = frozenset({
        "she", "her", "hers", "herself", "woman", "girl", "mother",
        "sister", "daughter", "wife", "queen", "princess", "lady",
        "madam", "miss", "mrs", "ms",
    })
    male_cue_words: frozenset[str] = frozenset({
        "he", "him", "his", "himself", "man", "boy", "father",
        "brother", "son", "husband", "king", "prince", "lord", "sir", "mr",
    })

    # Chapter parsing
    chapter_patterns: tuple[str, ...] = ()
    scene_break_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Freeze the mutable emotion_hints dict into a read-only view.
        # object.__setattr__ is required because the dataclass is frozen.
        object.__setattr__(
            self,
            "emotion_hints",
            types.MappingProxyType(dict(self.emotion_hints)),
        )

    def normalize_name(self, name: str) -> str:
        """Canonical form for speaker lookup keys."""
        return name.casefold().strip()

    def is_valid_name(self, name: str) -> bool:
        """Check if a string looks like a valid speaker name."""
        return bool(re.match(self.valid_name_pattern, name))

    def build_said_patterns(self) -> list[re.Pattern]:
        """Build compiled verb-name / name-verb regex patterns (cached)."""
        return _cached_said_patterns(self.code, self.speaker_verbs)

    def build_emotion_verb_pattern(self) -> Optional[re.Pattern]:
        """Build a pattern matching verbs that carry emotion hints (cached)."""
        emotion_keys = frozenset(k for k in self.emotion_hints if k in self.speaker_verbs)
        return _cached_emotion_verb_pattern(self.code, emotion_keys)


# ---------------------------------------------------------------------------
# Cached pattern builders (keyed on profile.code for stable cache identity;
# id(self) is unsound because GC can reuse object IDs)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16)
def _cached_said_patterns(
    profile_code: str,
    speaker_verbs: frozenset[str],
) -> list[re.Pattern]:
    if not speaker_verbs:
        return []
    verb_alt = "|".join(re.escape(v) for v in sorted(speaker_verbs))
    # Multi-word name pattern: captures "Mr. Holmes", "Captain Ahab",
    # "the Doctor", "Old Tom", or simple "Alice"
    # Title prefixes: Mr., Mrs., Ms., Dr., Captain, Lord, Lady, Sir, the, Old, Young
    name_pat = r'(?:(?:Mr\.|Mrs\.|Ms\.|Dr\.|Miss|Captain|Lord|Lady|Sir|the|Old|Young)\s+)?[A-Z][a-z]+'
    return [
        # "said Mr. Holmes" / "whispered the Doctor"
        re.compile(
            rf"(?:{verb_alt})\s+({name_pat})(?:\s|[,.\!\?]|$)",
            re.IGNORECASE,
        ),
        # "Mr. Holmes said" / "Captain Ahab whispered"
        re.compile(
            rf"({name_pat})\s+(?:{verb_alt})",
            re.IGNORECASE,
        ),
        # "said the Doctor" (explicit 'the' pattern)
        re.compile(
            rf"(?:{verb_alt})\s+(the\s+[A-Z][a-z]+)(?:\s|[,.\!\?]|$)",
        ),
    ]


@lru_cache(maxsize=16)
def _cached_emotion_verb_pattern(
    profile_code: str,
    emotion_keys: frozenset[str],
) -> Optional[re.Pattern]:
    if not emotion_keys:
        return None
    alt = "|".join(re.escape(k) for k in sorted(emotion_keys))
    return re.compile(rf"\b({alt})\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROFILES: dict[str, LanguageProfile] = {}


def register_profile(profile: LanguageProfile) -> None:
    """Register a LanguageProfile so get_profile(code) can find it.

    Adding a language
    -----------------
    1. Create ``audiobooker/language/<code>.py`` (e.g. ``it.py`` for Italian),
       using ``en.py`` as a template.
    2. Build a ``LanguageProfile(code="<code>", name="...", ...)`` with that
       language's dialogue quotes, speaker verbs, emotion hints, name pattern,
       and — for chapter detection — its ``chapter_patterns`` (the localized
       heading words, e.g. "Capitolo" for Italian).
    3. Call ``register_profile(<PROFILE>)`` at module bottom.
    The discovery scan (``available_profiles``/``get_profile``) imports the new
    module automatically; no central list needs editing.
    """
    _PROFILES[profile.code] = profile


def _discover_profiles(requested_code: Optional[str] = None) -> None:
    """Scan audiobooker.language.* submodules to populate the registry.

    If ``requested_code`` is given and the module of that exact name fails to
    import, the failure is logged at WARNING (not DEBUG) so a user who asked for
    a specific language sees why it was unavailable.
    """
    try:
        import audiobooker.language as lang_pkg
        for importer, modname, ispkg in pkgutil.iter_modules(lang_pkg.__path__):
            if modname == "profile" or modname.startswith("_"):
                continue
            try:
                importlib.import_module(f"audiobooker.language.{modname}")
            except Exception:
                if modname == requested_code:
                    logger.warning(
                        "Language module %r failed to import; %r is unavailable.",
                        modname, requested_code, exc_info=True,
                    )
                else:
                    logger.debug("Failed to import language module %r", modname, exc_info=True)
    except Exception:
        logger.debug("Language profile discovery failed", exc_info=True)


def get_profile(code: str = "en") -> LanguageProfile:
    """Look up a language profile by ISO code. Defaults to English."""
    if code not in _PROFILES:
        # Try direct import first (fast path)
        try:
            importlib.import_module(f"audiobooker.language.{code}")
        except ImportError:
            pass
    if code not in _PROFILES:
        # Fall back to full discovery scan
        _discover_profiles(requested_code=code)
    if code not in _PROFILES:
        raise ValueError(
            f"Unsupported language: {code!r}. "
            f"Available: {', '.join(sorted(_PROFILES)) or 'none'}"
        )
    return _PROFILES[code]


def available_profiles() -> list[str]:
    """Return codes of all registered language profiles (scans submodules)."""
    _discover_profiles()
    return sorted(_PROFILES.keys())
