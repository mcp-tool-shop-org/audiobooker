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

from audiobooker.models import normalize_speaker_key

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
    # Line-initial dash (raya) openers. Empty means derive them: first from
    # dialogue_quotes pairs whose close is a newline, then from the ISO
    # raya-language set in casting.dialogue. A synthetic profile that uses
    # U+2015 HORIZONTAL BAR can set this explicitly instead of relying on
    # getattr against a field that did not exist (F-fc1ac386).
    dash_dialogue_markers: tuple[str, ...] = ()

    # Speaker attribution
    speaker_verbs: frozenset[str] = frozenset()
    # emotion_hints is wrapped in MappingProxyType by __post_init__
    # to prevent mutation of this frozen dataclass's contents.
    emotion_hints: dict[str, str] = field(default_factory=dict)
    speaker_blacklist: frozenset[str] = frozenset()
    valid_name_pattern: str = r"^[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\-]{0,22}[A-Za-z\u00C0-\u024F]$"

    # --- Speaker-attribution regex fragments (i18n) ---
    # build_said_patterns used to hardcode an ASCII-English name shape
    # (`[A-Z][a-z]+` plus English titles) and join verb and name with `\s+`.
    # That made "sagte M\u00FCller" unmatchable, and made Japanese \u2014 written without
    # spaces \u2014 structurally unreachable, so dialogue in 6 of the 7 shipped
    # languages fell to the narrator voice. Each profile now supplies its own
    # fragments; the defaults below reproduce the historical English patterns
    # byte-for-byte.
    #
    # name_fragment: matches a bare name, no anchors, no capture group.
    name_fragment: str = r"[A-Z][a-z]+"
    # name_titles: ordered regex alternatives for optional title prefixes.
    # Order is load-bearing \u2014 it is the alternation order in the built pattern.
    name_titles: tuple[str, ...] = (
        r"Mr\.", r"Mrs\.", r"Ms\.", r"Dr\.", "Miss", "Captain",
        "Lord", "Lady", "Sir", "the", "Old", "Young",
    )
    # PH-B-003: (spoken expansion casefolded, written abbreviation) pairs. A
    # matched speaker whose title is an expansion is rewritten to the
    # abbreviation, so TTS normalization \u2014 which runs BEFORE compile_chapter
    # and defaults to on \u2014 cannot split one character into two cast members
    # ("Mr. Holmes" pre-normalization, "Mister Holmes" post-). A tuple of pairs
    # rather than a dict so the frozen dataclass stays hashable.
    title_aliases: tuple[tuple[str, str], ...] = ()
    # Separator between a speech verb and an adjacent name. Space-delimited
    # languages use whitespace; Japanese uses topic/quotative particles with no
    # whitespace at all.
    attribution_separator: str = r"\s+"
    # What may follow a matched name.
    # FEAT-CAST-006: the raya and en dash are boundaries too. Without them
    # `respondió Marcos—.` — the ordinary Spanish shape where an interposed
    # comment is CLOSED by a dash — matched no attribution pattern at all, so
    # the speaker came back None and turn-tracking guessed one. The failure
    # was silent in the usual way: a guess is recorded as a successful
    # attribution, so the unattributed rate went DOWN.
    name_boundary: str = r"(?:\s|[,.\!\?—–]|$)"
    # Definite article used in the "said the Doctor" pattern. Empty disables
    # that third pattern for languages where it does not apply.
    definite_article: str = "the"
    # PH-B-004: what may follow the definite article as a referent
    # ("said the guard", "the traveler replied"). Unlike name_fragment this is
    # deliberately case-INSENSITIVE in its first character: the article is the
    # evidence that a referent follows, so capitalization is not needed and
    # English prose overwhelmingly writes these common nouns in lower case.
    # Without an article there is no such evidence, which is exactly why the
    # bare name fragment must stay capital-initial.
    common_noun_fragment: str = r"[A-Za-z][a-z]+"

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
        """Canonical form for speaker lookup keys.

        PH-B-007: delegates to the same helper ``CastingTable.normalize_key``
        uses. These two were independent ``casefold().strip()`` calls, so a
        profile-normalized name and a casting-table key could disagree on any
        input where Unicode normalization matters.
        """
        return normalize_speaker_key(name)

    def is_valid_name(self, name: str) -> bool:
        """Check if a string looks like a valid speaker name."""
        return bool(re.match(self.valid_name_pattern, name))

    def name_pattern_fragment(self) -> str:
        """The profile's name shape, with its optional title prefixes.

        PH-B-004: the title alternation is wrapped in an inline ``(?i:...)``
        because titles are a CLOSED vocabulary where case is noise, while the
        name fragment itself stays case-SENSITIVE. The patterns used to carry a
        blanket ``re.IGNORECASE``, which let ``[A-Z][a-z]+`` match lowercase
        words and manufacture speakers out of ``nobody`` and ``something``.

        The one place a lowercase referent IS accepted is directly after the
        definite article — ``said the guard``, ``the traveler replied``. The
        article is positive evidence that a referent follows; ``said nobody``
        has no such evidence, which is the whole difference between the two.
        """
        if self.name_titles:
            titles = "|".join(self.name_titles)
            titled = rf"(?:(?i:{titles})\s+)?{self.name_fragment}"
        else:
            titled = self.name_fragment
        if self.definite_article and self.common_noun_fragment:
            article_ref = (
                rf"(?i:{self.definite_article})\s+{self.common_noun_fragment}"
            )
            return rf"(?:{article_ref}|{titled})"
        return titled

    def canonicalize_speaker_name(self, name: str) -> str:
        """Rewrite a spoken title back to its written abbreviation (PH-B-003).

        ``"Mister Holmes"`` -> ``"Mr. Holmes"``. Returns ``name`` unchanged for
        profiles that declare no ``title_aliases`` and for names that do not
        start with a known expansion.
        """
        if not self.title_aliases or not name:
            return name
        head, sep, tail = name.partition(" ")
        if not sep or not tail.strip():
            return name
        for expansion, abbreviation in self.title_aliases:
            if head.casefold() == expansion:
                return f"{abbreviation} {tail}"
        return name

    def build_said_patterns(self) -> list[re.Pattern]:
        """Build compiled verb-name / name-verb regex patterns (cached)."""
        return _cached_said_patterns(
            self.code,
            self.speaker_verbs,
            self.name_pattern_fragment(),
            self.attribution_separator,
            self.name_boundary,
            self.definite_article,
            self.name_fragment,
        )

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
    name_pat: str = r'(?:(?i:Mr\.|Mrs\.|Ms\.|Dr\.|Miss|Captain|Lord|Lady|Sir|the|Old|Young)\s+)?[A-Z][a-z]+',
    separator: str = r"\s+",
    boundary: str = r"(?:\s|[,.\!\?]|$)",
    article: str = "the",
    bare_name: str = r"[A-Z][a-z]+",
) -> list[re.Pattern]:
    """Compile the verb/name attribution patterns for one profile.

    ``name_pat``, ``separator`` and ``boundary`` come from the profile
    (``LanguageProfile.name_pattern_fragment`` etc.), so the name shape is that
    language's own — the Unicode ranges its ``valid_name_pattern`` already
    declared — and the verb/name join is whitespace only for languages that
    actually delimit words with whitespace. The cache stays correct because it
    is keyed on ``profile_code`` plus every fragment that shapes the output.

    PH-B-004: case-insensitivity is applied per FRAGMENT, not to the whole
    pattern. Speech verbs, titles and the definite article are closed
    vocabularies where case carries no information, so they get an inline
    ``(?i:...)``. The name fragment does NOT: every profile's ``name_fragment``
    opens with an uppercase class (``[A-Z][a-z]+``,
    ``[A-ZÀ-ɏ][a-zÀ-ɏ]+``, …) precisely because capitalization is the only
    evidence a word is a name. A blanket ``re.IGNORECASE`` destroyed that
    evidence and turned every lowercase word after a speech verb into a
    speaker: ``"Hello?" asked nobody in particular`` attributed to ``Nobody``
    and ``"Listen," said something in the dark`` to ``Something``. Because a
    phantom is an ACCEPTED attribution rather than an ``unknown``, it also
    lowered the unattributed rate — the quality signal improved as attribution
    got worse.
    """
    if not speaker_verbs:
        return []
    verb_alt = "(?i:" + "|".join(re.escape(v) for v in sorted(speaker_verbs)) + ")"
    patterns = [
        # "said Mr. Holmes" / "whispered the Doctor" / "sagte Müller"
        re.compile(rf"(?:{verb_alt}){separator}({name_pat}){boundary}"),
        # "Mr. Holmes said" / "Captain Ahab whispered" / "太郎は言った"
        re.compile(rf"({name_pat}){separator}(?:{verb_alt})"),
    ]
    if article:
        # "said the Doctor" (explicit definite-article pattern)
        patterns.append(re.compile(
            rf"(?:{verb_alt}){separator}((?i:{article})\s+{bare_name}){boundary}",
        ))
    return patterns


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
