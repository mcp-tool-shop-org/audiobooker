"""
SpeakerResolver — pipeline stage that improves speaker attribution.

Inputs: chapters + detected dialogue spans + current attribution.
If BookNLP is available and enabled, uses it for co-reference resolution.
Otherwise, falls back to existing heuristic attribution (no-op).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional, TYPE_CHECKING

from audiobooker.nlp.booknlp_adapter import BookNLPAdapter, BookNLPResult, NLPBackend

if TYPE_CHECKING:
    from audiobooker.models import Chapter, Utterance, CastingTable

logger = logging.getLogger("audiobooker.nlp.resolver")


@dataclass
class LowConfidenceMatch:
    """A resolution that landed near the fuzzy threshold — worth a human glance."""
    speaker: str
    confidence: float
    chapter_index: int
    line_index: int


@dataclass
class ResolutionStats:
    """Statistics from a speaker resolution pass."""
    chapters_processed: int = 0
    utterances_examined: int = 0
    speakers_resolved: int = 0
    speakers_unchanged: int = 0
    nlp_used: bool = False
    nlp_errors: list[str] = field(default_factory=list)  # F-CORE-B-017: accumulate errors
    match_confidence: list[float] = field(default_factory=list)  # FT-CORE-022: per-resolution confidence
    # Resolutions whose fuzzy-match confidence landed below LOW_CONFIDENCE_BAND
    # (i.e. just over the FUZZY_THRESHOLD). The CLI can surface these so the
    # user can spot-check borderline attributions.
    low_confidence: list[LowConfidenceMatch] = field(default_factory=list)


class SpeakerResolver:
    """
    Pipeline stage that optionally enhances speaker attribution.

    Modes:
        - "on": Always attempt NLP resolution (fail if unavailable).
        - "off": Never use NLP (pure pass-through).
        - "auto": Use NLP if available, fall back silently.

    Args:
        mode: "on" | "off" | "auto" (default "auto").
        adapter: Injected NLP backend (defaults to BookNLPAdapter).
    """

    def __init__(
        self,
        mode: str = "auto",
        adapter: Optional[NLPBackend] = None,
    ) -> None:
        if mode not in ("on", "off", "auto"):
            raise ValueError(f"Invalid booknlp_mode: {mode!r}. Must be on|off|auto.")

        self.mode = mode
        self._adapter = adapter

    @property
    def adapter(self) -> NLPBackend:
        """Lazy-create adapter on first access."""
        if self._adapter is None:
            self._adapter = BookNLPAdapter()
        return self._adapter

    def resolve(
        self,
        chapters: list["Chapter"],
        casting: "CastingTable",
    ) -> ResolutionStats:
        """
        Run speaker resolution on compiled chapters.

        Updates utterances in-place where NLP provides better attribution.

        Args:
            chapters: List of compiled chapters.
            casting: CastingTable for validation.

        Returns:
            ResolutionStats with counts.
        """
        stats = ResolutionStats()

        if self.mode == "off":
            logger.info("BookNLP resolution disabled (mode=off)")
            return stats

        if self.mode == "auto" and not self.adapter.is_available():
            logger.info("BookNLP not available — using heuristic attribution")
            return stats

        if self.mode == "on" and not self.adapter.is_available():
            raise RuntimeError(
                "BookNLP mode is 'on' but BookNLP is not installed. "
                "Install with: pip install booknlp"
            )

        # NLP is available and enabled
        stats.nlp_used = True

        for chapter in chapters:
            if not chapter.utterances:
                continue

            stats.chapters_processed += 1

            # Analyze the full chapter text
            result = self.adapter.analyze(chapter.raw_text)

            if not result.success:
                stats.nlp_errors.append(result.error)
                logger.warning(
                    f"BookNLP failed on chapter {chapter.index}: {result.error}. "
                    "Keeping heuristic attributions."
                )
                continue

            # Build a lookup of quote positions → speakers from NLP
            nlp_attributions = self._build_attribution_map(result)

            # Try to improve "unknown" utterances
            for utterance in chapter.utterances:
                stats.utterances_examined += 1

                if utterance.speaker != "unknown":
                    stats.speakers_unchanged += 1
                    continue

                # See if NLP has a better attribution for this text
                match_result = self._match_utterance(utterance, nlp_attributions)
                if match_result is not None:
                    improved, confidence = match_result
                    utterance.speaker = improved
                    stats.speakers_resolved += 1
                    stats.match_confidence.append(confidence)
                    if confidence < self.LOW_CONFIDENCE_BAND:
                        stats.low_confidence.append(
                            LowConfidenceMatch(
                                speaker=improved,
                                confidence=confidence,
                                chapter_index=chapter.index,
                                line_index=utterance.line_index,
                            )
                        )
                    logger.debug(
                        f"Resolved unknown → {improved!r} (confidence={confidence:.2f}) "
                        f"in ch{chapter.index} line {utterance.line_index}"
                    )
                else:
                    stats.speakers_unchanged += 1

        logger.info(
            f"SpeakerResolver: resolved={stats.speakers_resolved} "
            f"unchanged={stats.speakers_unchanged} chapters={stats.chapters_processed}"
        )
        return stats

    # Minimum fuzzy match ratio for FT-CORE-009
    FUZZY_THRESHOLD: float = 0.85

    # Resolutions accepted (>= FUZZY_THRESHOLD) but below this band are flagged
    # as low-confidence so the CLI can surface them for a human spot-check.
    LOW_CONFIDENCE_BAND: float = 0.92

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """
        Normalize text for fuzzy matching (FT-CORE-009).

        Strips punctuation, collapses whitespace, normalizes quote chars,
        and casefolds for case-insensitive comparison.
        """
        # Normalize various quote characters to a single form
        text = text.replace("\u2018", "'").replace("\u2019", "'")
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        # Strip all punctuation
        text = re.sub(r"[^\w\s]", "", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text.casefold()

    def _build_attribution_map(self, result: BookNLPResult) -> dict[str, str]:
        """Build a map from normalized quote text -> speaker name."""
        mapping: dict[str, str] = {}
        for quote in result.quotes:
            key = self._normalize_for_match(quote.quote_text)
            if quote.speaker and quote.confidence > 0.3 and key:
                mapping[key] = quote.speaker
        return mapping

    # Minimum length for substring matching to avoid false positives (FT-CORE-022)
    SUBSTRING_MIN_LENGTH: int = 20

    def _match_utterance(
        self,
        utterance: "Utterance",
        nlp_attributions: dict[str, str],
    ) -> Optional[tuple[str, float]]:
        """
        Try to match an utterance's text to an NLP-attributed quote.

        FT-CORE-009: Uses fuzzy matching (difflib.SequenceMatcher) with
        a 0.85 threshold instead of exact casefold comparison. This handles
        minor whitespace, punctuation, and quote-character differences.

        FT-CORE-022: Also tries substring matching — if the NLP quote text
        is a substring of the utterance (or vice versa), that's a high-
        confidence match. Returns (speaker, confidence) tuple or None.
        """
        text_norm = self._normalize_for_match(utterance.text)
        if not text_norm:
            return None

        # Try exact match first (fast path)
        if text_norm in nlp_attributions:
            return nlp_attributions[text_norm], 1.0

        best_ratio = 0.0
        best_speaker: Optional[str] = None

        for quote_key, speaker in nlp_attributions.items():
            # FT-CORE-022: Substring matching (bidirectional)
            if len(text_norm) >= self.SUBSTRING_MIN_LENGTH and len(quote_key) >= self.SUBSTRING_MIN_LENGTH:
                if text_norm in quote_key or quote_key in text_norm:
                    # Substring match — compute a confidence based on length overlap
                    shorter = min(len(text_norm), len(quote_key))
                    longer = max(len(text_norm), len(quote_key))
                    sub_ratio = shorter / longer
                    if sub_ratio > best_ratio:
                        best_ratio = max(sub_ratio, 0.90)  # Substring is high confidence
                        best_speaker = speaker
                    continue

            # Fuzzy match via SequenceMatcher
            ratio = SequenceMatcher(None, text_norm, quote_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_speaker = speaker

        if best_ratio >= self.FUZZY_THRESHOLD and best_speaker is not None:
            return best_speaker, best_ratio

        return None


# ---------------------------------------------------------------------------
# FT-NLP-025: Alias discovery (proposal only — never auto-applied)
# ---------------------------------------------------------------------------

@dataclass
class AliasProposal:
    """
    A proposed alias for a confirmed speaker (FT-NLP-025).

    A pure suggestion: the candidate is a descriptor that failed
    ``is_valid_speaker_name`` (a title, a "the X" reference, or an
    honorific+surname) which co-occurs strongly with one confirmed speaker.
    The user decides whether to attach it; nothing here mutates the cast.
    """
    candidate: str          # the descriptor, e.g. "the Doctor", "Mr. Holmes"
    speaker: str            # the confirmed speaker it most co-occurs with
    score: float            # 0.0-1.0 co-occurrence strength
    co_occurrences: int     # raw co-occurrence count used for the score
    source: str = "co-occurrence"  # "co-occurrence" | "coref"


# Honorific+surname / title / "the X" attribution-candidate patterns.
# These deliberately match the kinds of names that is_valid_speaker_name tends
# to reject (titles, descriptors) so we surface them as ALIAS suggestions.
_HONORIFIC_RE = re.compile(
    r'\b((?:Mr\.|Mrs\.|Ms\.|Dr\.|Miss|Captain|Lord|Lady|Sir|Madam|Master|'
    r'Professor|Colonel|Major|Sergeant|Reverend|Father|Sister)\s+[A-Z][a-z]+)'
)
_THE_X_RE = re.compile(r'\b(the\s+[A-Z][a-z]+)')


def _collect_alias_candidates(
    text: str,
    casting: "CastingTable",
    profile,
) -> list[str]:
    """
    Collect attribution-candidate descriptors that are NOT confirmed speakers.

    These are the descriptor-shaped attributions the casting table does not yet
    recognize as a real speaker (titles, "the X", honorific+surname). The
    English profile's ``is_valid_speaker_name`` deliberately *accepts* these
    shapes as plausible names, so the discriminating filter for ALIAS proposals
    is "descriptor-shaped AND not already a confirmed character or existing
    alias" — a referring expression for someone, rather than its own cast slot.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for pat in (_HONORIFIC_RE, _THE_X_RE):
        for m in pat.finditer(text):
            descriptor = m.group(1).strip()
            key = descriptor.casefold()
            if key in seen:
                continue
            seen.add(key)
            # Skip descriptors that ARE already a confirmed speaker or a known
            # alias — those need no proposal.
            norm = casting.normalize_key(descriptor)
            if norm in casting.characters:
                continue
            if casting.resolve_alias(descriptor) is not None:
                continue
            candidates.append(descriptor)
    return candidates


def suggest_aliases(
    chapters: list["Chapter"],
    casting: "CastingTable",
    *,
    profile=None,
    adapter: Optional[NLPBackend] = None,
    use_booknlp: bool = True,
    min_score: float = 0.3,
    window: int = 160,
) -> list[AliasProposal]:
    """
    FT-NLP-025: Propose aliases for confirmed speakers — proposal only.

    Scans chapter text for attribution-candidate descriptors that fail
    ``is_valid_speaker_name`` (titles, "the X", honorific+surname) and scores
    each by how strongly it co-occurs with a confirmed speaker within a sliding
    character window. When BookNLP is available and ``use_booknlp`` is set, its
    coref/entity output is used to corroborate (boosting the score and tagging
    the source as "coref").

    Nothing here mutates the casting table; the returned proposals are surfaced
    by the CLI (``speakers --suggest-aliases``) for the user to accept or ignore.

    Args:
        chapters: Compiled (or at least raw-text-bearing) chapters.
        casting: CastingTable with the confirmed speakers.
        profile: Optional LanguageProfile (defaults to English).
        adapter: Optional NLP backend (defaults to BookNLPAdapter when used).
        use_booknlp: Use BookNLP coref to corroborate when available.
        min_score: Drop proposals scoring below this (0.0-1.0).
        window: Character co-occurrence window around each candidate mention.

    Returns:
        List of AliasProposal sorted by score descending, then candidate.
    """
    from audiobooker.language.profile import get_profile

    if profile is None:
        profile = get_profile("en")

    # Confirmed speakers = the current cast (exclude the synthetic narrator).
    confirmed: dict[str, str] = {}  # normalized -> display name
    for key, char in casting.characters.items():
        if key in ("narrator", "narration"):
            continue
        confirmed[casting.normalize_key(char.name)] = char.name
    if not confirmed:
        logger.info("FT-NLP-025: no confirmed speakers — no alias proposals")
        return []

    # candidate -> {confirmed_speaker: co_occurrence_count}
    co_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    candidate_display: dict[str, str] = {}

    for chapter in chapters:
        text = getattr(chapter, "raw_text", "") or ""
        if not text.strip():
            continue

        candidates = _collect_alias_candidates(text, casting, profile)
        for descriptor in candidates:
            cand_key = descriptor.casefold()
            candidate_display.setdefault(cand_key, descriptor)
            # Count confirmed-speaker mentions within `window` chars of each
            # occurrence of this descriptor. Count the NUMBER of mentions (not
            # mere presence) so a nearby, frequently-named speaker outweighs a
            # distant one that merely appears once in the window.
            for m in re.finditer(re.escape(descriptor), text):
                lo = max(0, m.start() - window)
                hi = min(len(text), m.end() + window)
                neighborhood = text[lo:hi].casefold()
                for norm_name, display in confirmed.items():
                    if not norm_name:
                        continue
                    mentions = neighborhood.count(norm_name)
                    if mentions:
                        co_counts[cand_key][display] += mentions

    # Optional BookNLP coref corroboration.
    coref_pairs: set[tuple[str, str]] = set()
    if use_booknlp:
        backend = adapter or BookNLPAdapter()
        try:
            available = backend.is_available()
        except Exception:  # pragma: no cover - defensive
            available = False
        if available:
            for chapter in chapters:
                text = getattr(chapter, "raw_text", "") or ""
                if not text.strip():
                    continue
                try:
                    result = backend.analyze(text)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("FT-NLP-025: BookNLP analyze failed: %s", exc)
                    continue
                if not getattr(result, "success", False):
                    continue
                # Build the set of (candidate, confirmed) pairs that BookNLP
                # links to the same entity span. We approximate coref by
                # checking which confirmed speaker shares an entity name with a
                # candidate descriptor.
                entity_names = {e.name.casefold() for e in result.entities}
                for cand_key in candidate_display:
                    # surname of an honorific+surname candidate
                    surname = candidate_display[cand_key].split()[-1].casefold()
                    if surname in entity_names:
                        for display in confirmed.values():
                            if display.casefold() in entity_names:
                                coref_pairs.add((cand_key, display))

    proposals: list[AliasProposal] = []
    for cand_key, speaker_counts in co_counts.items():
        if not speaker_counts:
            continue
        best_speaker = max(speaker_counts, key=lambda s: speaker_counts[s])
        best_count = speaker_counts[best_speaker]
        total = sum(speaker_counts.values())
        # Score = share of co-occurrences that went to the winning speaker,
        # scaled by a saturating count factor so a single hit isn't 1.0.
        share = best_count / total if total else 0.0
        count_factor = min(1.0, best_count / 3.0)
        score = round(share * count_factor, 3)
        source = "co-occurrence"
        if (cand_key, best_speaker) in coref_pairs:
            score = round(min(1.0, score + 0.25), 3)
            source = "coref"
        if score < min_score:
            continue
        proposals.append(
            AliasProposal(
                candidate=candidate_display[cand_key],
                speaker=best_speaker,
                score=score,
                co_occurrences=best_count,
                source=source,
            )
        )

    proposals.sort(key=lambda p: (-p.score, p.candidate.casefold()))
    logger.info("FT-NLP-025: proposed %d aliases", len(proposals))
    return proposals
