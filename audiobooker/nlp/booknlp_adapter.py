"""
BookNLP adapter — optional NLP-powered speaker attribution.

Detects whether BookNLP is installed and provides a clean adapter
for the pipeline. When unavailable, returns empty results so the
caller can fall back to heuristic attribution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("audiobooker.nlp.booknlp")


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    """A named entity detected in the text."""
    name: str
    start: int
    end: int
    entity_type: str = "PER"  # PER, LOC, ORG, etc.


@dataclass
class QuoteAttribution:
    """A quote attributed to a speaker by NLP."""
    quote_text: str
    speaker: str
    start: int
    end: int
    confidence: float = 0.0


@dataclass
class BookNLPResult:
    """Minimal output contract from BookNLP analysis."""
    entities: list[Entity] = field(default_factory=list)
    quotes: list[QuoteAttribution] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    success: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Adapter protocol (for testing / alternative backends)
# ---------------------------------------------------------------------------

@runtime_checkable
class NLPBackend(Protocol):
    """Interface for NLP analysis backends."""

    def analyze(self, text: str) -> BookNLPResult: ...

    def is_available(self) -> bool: ...


# ---------------------------------------------------------------------------
# BookNLP adapter
# ---------------------------------------------------------------------------

def _check_booknlp_available() -> bool:
    """Check if BookNLP is importable."""
    try:
        import booknlp  # noqa: F401
        return True
    except ImportError:
        return False


class BookNLPAdapter:
    """
    Adapter for BookNLP speaker attribution.

    When BookNLP is not installed, is_available() returns False and
    analyze() returns an empty result with a descriptive error.
    """

    def __init__(self, model_params: Optional[dict] = None) -> None:
        self._available = _check_booknlp_available()
        self._model_params = model_params or {}
        self._model = None

        if self._available:
            logger.info("BookNLP detected — NLP speaker resolution available")
        else:
            logger.info(
                "BookNLP not installed — speaker resolution will use heuristics. "
                "Install with: pip install booknlp"
            )

    def is_available(self) -> bool:
        """Check if BookNLP can be used."""
        return self._available

    def analyze(self, text: str) -> BookNLPResult:
        """
        Analyze text with BookNLP for entities, quotes, and speakers.

        Args:
            text: Full text to analyze.

        Returns:
            BookNLPResult with entities, quote attributions, and speakers.
            On failure or unavailability, returns empty result with error.
        """
        if not self._available:
            return BookNLPResult(
                success=False,
                error="BookNLP not installed. Install with: pip install booknlp",
            )

        try:
            return self._run_analysis(text)
        except Exception as e:
            logger.warning(f"BookNLP analysis failed: {e}")
            return BookNLPResult(success=False, error=str(e))

    def _run_analysis(self, text: str) -> BookNLPResult:
        """
        Run actual BookNLP analysis.

        This method is only called when BookNLP is confirmed available.
        It wraps the BookNLP output into our minimal contract.
        """
        import tempfile
        from pathlib import Path

        try:
            from booknlp.booknlp import BookNLP

            if self._model is None:
                self._model = BookNLP("en", self._model_params)

            # BookNLP requires file I/O
            with tempfile.TemporaryDirectory(prefix="audiobooker_nlp_") as tmpdir:
                input_path = Path(tmpdir) / "input.txt"
                input_path.write_text(text, encoding="utf-8")

                output_dir = Path(tmpdir) / "output"
                output_dir.mkdir()

                self._model.pipeline(
                    str(input_path),
                    str(output_dir),
                    "book",
                )

                return self._parse_output(output_dir)

        except Exception as e:
            logger.error(f"BookNLP pipeline error: {e}")
            return BookNLPResult(success=False, error=str(e))

    def _parse_output(self, output_dir) -> BookNLPResult:
        """Parse BookNLP output files into our contract."""
        from pathlib import Path

        entities = []
        quotes = []
        speakers = set()

        # Parse entities
        entities_path = Path(output_dir) / "book.entities"
        if entities_path.exists():
            for line in entities_path.read_text(encoding="utf-8").splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 4:
                    name = parts[0]
                    entities.append(Entity(
                        name=name,
                        start=int(parts[1]) if parts[1].isdigit() else 0,
                        end=int(parts[2]) if parts[2].isdigit() else 0,
                        entity_type=parts[3] if len(parts) > 3 else "PER",
                    ))
                    if parts[3] == "PER" if len(parts) > 3 else True:
                        speakers.add(name)

        # Parse quotes
        quotes_path = Path(output_dir) / "book.quotes"
        if quotes_path.exists():
            for line in quotes_path.read_text(encoding="utf-8").splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 4:
                    quotes.append(QuoteAttribution(
                        quote_text=parts[0],
                        speaker=parts[1],
                        start=int(parts[2]) if parts[2].isdigit() else 0,
                        end=int(parts[3]) if parts[3].isdigit() else 0,
                        confidence=float(parts[4]) if len(parts) > 4 else 0.5,
                    ))
                    speakers.add(parts[1])

        return BookNLPResult(
            entities=entities,
            quotes=quotes,
            speakers=sorted(speakers),
            success=True,
        )
