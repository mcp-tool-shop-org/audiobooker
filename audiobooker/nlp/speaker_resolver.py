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
        language_code: ISO code passed to BookNLPAdapter. BookNLP is
            English-only; non-English is auto-off rather than English NLP,
            and mode=on raises the adapter's ValueError (F-79363bb9).
    """

    def __init__(
        self,
        mode: str = "auto",
        adapter: Optional[NLPBackend] = None,
        language_code: str = "en",
    ) -> None:
        if mode not in ("on", "off", "auto"):
            raise ValueError(f"Invalid booknlp_mode: {mode!r}. Must be on|off|auto.")

        self.mode = mode
        self._adapter = adapter
        self.language_code = language_code or "en"

    @property
    def adapter(self) -> NLPBackend:
        """Lazy-create adapter on first access, with the resolver's language."""
        if self._adapter is None:
            self._adapter = BookNLPAdapter(language_code=self.language_code)
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

        # F-79363bb9: BookNLPAdapter() defaulted to English, so a non-English
        # book never hit the English-only guard. Auto-off rather than running
        # English NLP; mode=on constructs the adapter so the existing
        # ValueError fires on this path.
        if self._adapter is None and self.language_code != "en":
            if self.mode == "auto":
                logger.info(
                    "BookNLP skipped — language_code=%r is not English; "
                    "using heuristic attribution",
                    self.language_code,
                )
                return stats

        if self.mode == "auto" and not self.adapter.is_available():
            logger.info("BookNLP not available — using heuristic attribution")
            return stats

        if self.mode == "on" and not self.adapter.is_available():
            raise RuntimeError(
                "BookNLP mode is 'on' but BookNLP is not installed. "
                "Install with: pip install booknlp"
            )

        from audiobooker.casting.dialogue import LOW_CONFIDENCE_THRESHOLD

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

            skipped = getattr(result, "skipped_chunks", 0) or 0
            if skipped:
                skip_msg = (
                    f"BookNLP skipped {skipped} chunk(s) on chapter "
                    f"{chapter.index}"
                )
                if result.error:
                    skip_msg = f"{skip_msg}: {result.error}"
                stats.nlp_errors.append(skip_msg)

            quotes_usable = sum(
                1 for q in result.quotes if q.speaker and q.quote_text
            )
            # F-503cd84c / Lock B1: empty quotes after a claimed success must
            # not look like a successful NLP pass (Ewaschuk implicit 200).
            if quotes_usable == 0:
                stats.nlp_errors.append(
                    result.error
                    or (
                        f"BookNLP returned no usable quotes on chapter "
                        f"{chapter.index}"
                    )
                )
                logger.warning(
                    "BookNLP returned no usable quotes on chapter %s — "
                    "keeping heuristic attributions.",
                    chapter.index,
                )
                continue

            stats.nlp_used = True

            # Build a lookup of quote positions → speakers from NLP
            nlp_attributions = self._build_attribution_map(result)

            # Improve unknown utterances, and turn-tracking guesses below
            # LOW_CONFIDENCE_THRESHOLD (F-79363bb9). Tagged attributions stay.
            for utterance in chapter.utterances:
                stats.utterances_examined += 1

                if not self._nlp_may_overwrite(
                    utterance, LOW_CONFIDENCE_THRESHOLD,
                ):
                    stats.speakers_unchanged += 1
                    continue

                # See if NLP has a better attribution for this text
                match_result = self._match_utterance(utterance, nlp_attributions)
                if match_result is not None:
                    improved, confidence = match_result
                    # Fuzzy NLP fills are already capped at NLP_FUZZY_CONFIDENCE
                    # so overwriting a turn guess cannot raise confidence above
                    # that cap. Exact matches keep the backend score (1.0).
                    utterance.speaker = improved
                    # FEAT-CAST-001: record WHERE this speaker came from. The
                    # resolver already computed a confidence and kept it only
                    # in its own stats object, so nothing downstream of the
                    # pipeline could tell an NLP resolution from a tagged
                    # attribution.
                    utterance.attribution_source = "nlp"
                    utterance.confidence = confidence
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

    @staticmethod
    def _nlp_may_overwrite(utterance: "Utterance", low_confidence: float) -> bool:
        """True when NLP is allowed to stamp this utterance.

        Unknown lines are the original fill target. F-79363bb9 also lets NLP
        correct a turn-tracking guess below LOW_CONFIDENCE_THRESHOLD; tagged
        / inline / user attributions are left alone.
        """
        if utterance.speaker == "unknown":
            return True
        if (
            utterance.attribution_source == "turn"
            and utterance.confidence is not None
            and utterance.confidence < low_confidence
        ):
            return True
        return False

    # Minimum fuzzy match ratio for FT-CORE-009
    FUZZY_THRESHOLD: float = 0.85

    # Resolutions accepted (>= FUZZY_THRESHOLD) but below this band are flagged
    # as low-confidence so the CLI can surface them for a human spot-check.
    LOW_CONFIDENCE_BAND: float = 0.92

    # Non-exact NLP fills are capped here — same ladder as turn-tracking
    # (TURN_INFERENCE_CONFIDENCE = 0.25) — so they move unknown →
    # low_confidence and cannot improve dialogue_unverified_rate.
    NLP_FUZZY_CONFIDENCE: float = 0.25

    # Backend scores at or below this are not usable attributions.
    BACKEND_CONFIDENCE_FLOOR: float = 0.3

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

    def _build_attribution_map(
        self, result: BookNLPResult,
    ) -> dict[str, tuple[str, float]]:
        """Build a map from normalized quote text -> (speaker, backend score).

        Duplicate quote texts keep the higher backend confidence; they do
        not last-writer-win. The backend score is kept so _match_utterance
        can take min(text_ratio, backend_confidence).
        """
        mapping: dict[str, tuple[str, float]] = {}
        for quote in result.quotes:
            key = self._normalize_for_match(quote.quote_text)
            if not quote.speaker or not key:
                continue
            backend = quote.confidence
            if backend <= self.BACKEND_CONFIDENCE_FLOOR:
                continue
            existing = mapping.get(key)
            if existing is None:
                mapping[key] = (quote.speaker, backend)
            elif existing[0] and existing[0] != quote.speaker:
                # Same normalized text, two speakers ('Yes.' / 'Yes!').
                # First-writer-win at confidence 1.0 would improve
                # attribution_quality as identity degrades (F-7feed459).
                mapping[key] = ("", 0.0)
            elif existing[0] == quote.speaker and backend > existing[1]:
                mapping[key] = (quote.speaker, backend)
        return mapping

    # Minimum length for substring matching to avoid false positives (FT-CORE-022)
    SUBSTRING_MIN_LENGTH: int = 20

    def _match_utterance(
        self,
        utterance: "Utterance",
        nlp_attributions: dict[str, tuple[str, float]],
    ) -> Optional[tuple[str, float]]:
        """
        Try to match an utterance's text to an NLP-attributed quote.

        FT-CORE-009: Uses fuzzy matching (difflib.SequenceMatcher) with
        a 0.85 threshold instead of exact casefold comparison. This handles
        minor whitespace, punctuation, and quote-character differences.

        FT-CORE-022: Also tries substring matching — if the NLP quote text
        is a substring of the utterance (or vice versa), that's a match.
        Confidence is min(text_ratio, backend_confidence). Non-exact fills
        are then capped at NLP_FUZZY_CONFIDENCE so they cannot improve
        attribution_quality the way turn-tracking used to.
        """
        text_norm = self._normalize_for_match(utterance.text)
        if not text_norm:
            return None

        # Try exact match first (fast path). Backend score is kept; BookNLP
        # itself does not emit one so resolved quotes score 1.0.
        exact = nlp_attributions.get(text_norm)
        if exact is not None:
            speaker, backend = exact
            if not speaker:
                return None
            return speaker, min(1.0, backend)

        best_ratio = 0.0
        best_speaker: Optional[str] = None
        best_backend = 1.0

        for quote_key, (speaker, backend) in nlp_attributions.items():
            # FT-CORE-022: Substring matching (bidirectional)
            if len(text_norm) >= self.SUBSTRING_MIN_LENGTH and len(quote_key) >= self.SUBSTRING_MIN_LENGTH:
                if text_norm in quote_key or quote_key in text_norm:
                    shorter = min(len(text_norm), len(quote_key))
                    longer = max(len(text_norm), len(quote_key))
                    sub_ratio = shorter / longer
                    if sub_ratio > best_ratio:
                        best_ratio = sub_ratio
                        best_speaker = speaker
                        best_backend = backend
                    continue

            # Fuzzy match via SequenceMatcher
            ratio = SequenceMatcher(None, text_norm, quote_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_speaker = speaker
                best_backend = backend

        if best_ratio >= self.FUZZY_THRESHOLD and best_speaker is not None:
            combined = min(best_ratio, best_backend)
            return best_speaker, min(combined, self.NLP_FUZZY_CONFIDENCE)

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
    # "co-occurrence" | "coref" | "name-overlap" (FEAT-CAST-003: a merge
    # between two CONFIRMED cast slots, justified by shared surname or
    # title+surname rather than by proximity).
    source: str = "co-occurrence"


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
    Collect descriptors worth proposing as an alias of a confirmed speaker.

    These are the descriptor-shaped attributions the casting table does not yet
    recognize as a real speaker (titles, "the X", honorific+surname). The
    English profile's ``is_valid_speaker_name`` deliberately *accepts* these
    shapes as plausible names, so the discriminating filter for ALIAS proposals
    is "descriptor-shaped AND a referring expression for someone" rather than
    its own cast slot.

    FEAT-CAST-003: the confirmed-speaker guard used to be absolute — any
    descriptor already in ``casting.characters`` was skipped outright. That
    skipped the case that actually hurts. ``Dr. Merrin`` / ``Merrin`` /
    ``The Doctor`` all become cast slots during compile, so by the time anyone
    asks for suggestions the duplicates are confirmed speakers and the guard
    threw every one of them away — leaving a permanently dirty uncast warning,
    split line counts, and one character occupying three report rows.

    The guard is now shape-aware rather than absolute. A confirmed speaker is
    still skipped when it is a proper NAME (``Halloway`` names a person, and
    co-occurrence alone is not evidence that it names the same person as
    someone standing next to them). It is kept when it is a ``the X``
    REFERRING EXPRESSION, which by construction stands in for a name rather
    than being one. Merges between two confirmed proper names are the job of
    :func:`_name_overlap_merges`, which uses name overlap as its evidence
    instead of proximity.

    Existing aliases are still skipped in both cases — those are already
    resolved and need no proposal.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for pat, is_referring_expression in ((_HONORIFIC_RE, False), (_THE_X_RE, True)):
        for m in pat.finditer(text):
            descriptor = m.group(1).strip()
            key = descriptor.casefold()
            if key in seen:
                continue
            seen.add(key)
            if casting.resolve_alias(descriptor) is not None:
                continue
            norm = casting.normalize_key(descriptor)
            if norm in casting.characters:
                if not is_referring_expression:
                    continue
                # Name the CAST SLOT, not the spelling that happened to appear
                # in the prose — the user is merging slots, so "The Doctor"
                # rather than "the Doctor".
                descriptor = casting.characters[norm].name
            candidates.append(descriptor)
    return candidates


def _strip_title(name: str, profile) -> str:
    """``name`` with any of the profile's title prefixes removed."""
    titles = getattr(profile, "name_titles", ()) or ()
    if not titles:
        return name.strip()
    pattern = re.compile(rf'^(?:(?i:{"|".join(titles)}))\s+')
    stripped = pattern.sub("", name.strip(), count=1)
    return stripped.strip() or name.strip()


def _name_overlap_merges(
    casting: "CastingTable",
    profile,
) -> list[AliasProposal]:
    """
    FEAT-CAST-003: propose merges BETWEEN confirmed cast slots.

    ``Dr. Merrin`` and ``Merrin`` are one person holding two slots. The audio
    was already right — ``CastingTable.get_voice`` resolves aliases — so this
    was never a wrong-voice bug; it was a wrong-CAST bug, and it does not heal
    on its own because both halves keep getting re-attributed every compile.

    The evidence here is the NAMES, read off the cast table, not proximity in
    the text: two slots overlap when one is the other with a title in front, or
    when they share a surname and at most one of them carries a title. Two
    DIFFERENT titles over the same surname (``Mr. Holmes`` / ``Mrs. Holmes``)
    are two people and are deliberately not proposed.

    The merge direction points at the slot with the most lines — the dominant
    identity — and ties break toward the untitled form, because the title is a
    decoration on the name rather than part of it.
    """
    slots: list[tuple[str, str, str, int]] = []  # (name, core, surname, lines)
    for key, char in casting.characters.items():
        if key in ("narrator", "narration"):
            continue
        core = _strip_title(char.name, profile)
        slots.append((
            char.name, core, core.split()[-1] if core.split() else core,
            getattr(char, "line_count", 0) or 0,
        ))

    proposals: list[AliasProposal] = []
    for i, (name_a, core_a, sur_a, lines_a) in enumerate(slots):
        for name_b, core_b, sur_b, lines_b in slots[i + 1:]:
            titled_a = core_a.casefold() != name_a.casefold()
            titled_b = core_b.casefold() != name_b.casefold()
            same_core = core_a.casefold() == core_b.casefold()
            same_surname = sur_a.casefold() == sur_b.casefold()
            if not (same_core or same_surname):
                continue
            if titled_a and titled_b:
                title_a = name_a[: len(name_a) - len(core_a)].strip().casefold()
                title_b = name_b[: len(name_b) - len(core_b)].strip().casefold()
                if title_a != title_b:
                    # Mr. Holmes and Mrs. Holmes are two people.
                    continue

            # Target = most lines; tie -> the untitled form.
            if (lines_a, not titled_a) >= (lines_b, not titled_b):
                target, candidate = name_a, name_b
            else:
                target, candidate = name_b, name_a
            if candidate.casefold() == target.casefold():
                continue
            proposals.append(AliasProposal(
                candidate=candidate,
                speaker=target,
                # A full-core match ("Dr. Merrin" vs "Merrin") is stronger
                # evidence than a bare shared surname.
                score=1.0 if same_core else 0.75,
                co_occurrences=lines_a + lines_b,
                source="name-overlap",
            ))
            logger.debug(
                "FEAT-CAST-003: proposing merge %r -> %r (same_core=%s)",
                candidate, target, same_core,
            )
    return proposals


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
                    # FEAT-CAST-003: a confirmed speaker may now BE a
                    # candidate (a "the X" slot), and every mention of it sits
                    # inside its own neighborhood. Counting that would make it
                    # an alias of itself and drown the real target.
                    if norm_name == casting.normalize_key(descriptor):
                        continue
                    mentions = neighborhood.count(norm_name)
                    if mentions:
                        co_counts[cand_key][display] += mentions

    # Optional BookNLP coref corroboration.
    # F-79363bb9: BookNLP is English-only. A non-English profile used to
    # construct BookNLPAdapter() with the default language_code='en' and run
    # English NLP. Skip rather than that; an injected adapter is honored.
    coref_pairs: set[tuple[str, str]] = set()
    if use_booknlp:
        backend = adapter
        if backend is None:
            lang = getattr(profile, "code", "en") or "en"
            if lang == "en":
                backend = BookNLPAdapter(language_code="en")
            else:
                logger.info(
                    "FT-NLP-025: BookNLP skipped — profile %r is not English",
                    lang,
                )
                backend = None
        available = False
        if backend is not None:
            try:
                available = backend.is_available()
            except Exception:  # pragma: no cover - defensive
                available = False
        if available and backend is not None:
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
        candidate = candidate_display[cand_key]
        if casting.normalize_key(candidate) == casting.normalize_key(best_speaker):
            continue
        proposals.append(
            AliasProposal(
                candidate=candidate,
                speaker=best_speaker,
                score=score,
                co_occurrences=best_count,
                source=source,
            )
        )

    # FEAT-CAST-003: merges between two CONFIRMED slots. Evidence is name
    # overlap read off the cast table, so this pass needs no text and fires
    # even on a cast assembled by hand. Already-proposed candidates win — a
    # co-occurrence proposal carries corroboration from the prose.
    proposed = {casting.normalize_key(p.candidate) for p in proposals}
    for merge in _name_overlap_merges(casting, profile):
        if casting.normalize_key(merge.candidate) in proposed:
            continue
        if merge.score < min_score:
            continue
        proposals.append(merge)
        proposed.add(casting.normalize_key(merge.candidate))

    proposals.sort(key=lambda p: (-p.score, p.candidate.casefold()))
    logger.info("FT-NLP-025: proposed %d aliases", len(proposals))
    return proposals
