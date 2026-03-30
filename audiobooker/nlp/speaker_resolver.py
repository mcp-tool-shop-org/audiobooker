"""
SpeakerResolver — pipeline stage that improves speaker attribution.

Inputs: chapters + detected dialogue spans + current attribution.
If BookNLP is available and enabled, uses it for co-reference resolution.
Otherwise, falls back to existing heuristic attribution (no-op).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional, TYPE_CHECKING

from audiobooker.nlp.booknlp_adapter import BookNLPAdapter, BookNLPResult, NLPBackend

if TYPE_CHECKING:
    from audiobooker.models import Chapter, Utterance, CastingTable

logger = logging.getLogger("audiobooker.nlp.resolver")


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
