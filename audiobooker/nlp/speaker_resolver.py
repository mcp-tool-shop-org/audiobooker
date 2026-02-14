"""
SpeakerResolver — pipeline stage that improves speaker attribution.

Inputs: chapters + detected dialogue spans + current attribution.
If BookNLP is available and enabled, uses it for co-reference resolution.
Otherwise, falls back to existing heuristic attribution (no-op).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
    nlp_error: str = ""


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
                stats.nlp_error = result.error
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
                improved = self._match_utterance(utterance, nlp_attributions)
                if improved:
                    utterance.speaker = improved
                    stats.speakers_resolved += 1
                    logger.debug(
                        f"Resolved unknown → {improved!r} in ch{chapter.index} "
                        f"line {utterance.line_index}"
                    )
                else:
                    stats.speakers_unchanged += 1

        logger.info(
            f"SpeakerResolver: resolved={stats.speakers_resolved} "
            f"unchanged={stats.speakers_unchanged} chapters={stats.chapters_processed}"
        )
        return stats

    def _build_attribution_map(self, result: BookNLPResult) -> dict[str, str]:
        """Build a map from normalized quote text → speaker name."""
        mapping: dict[str, str] = {}
        for quote in result.quotes:
            key = quote.quote_text.strip().casefold()[:80]
            if quote.speaker and quote.confidence > 0.3:
                mapping[key] = quote.speaker
        return mapping

    def _match_utterance(
        self,
        utterance: "Utterance",
        nlp_attributions: dict[str, str],
    ) -> Optional[str]:
        """Try to match an utterance's text to an NLP-attributed quote."""
        text_key = utterance.text.strip().casefold()[:80]
        return nlp_attributions.get(text_key)
