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


def _safe_float(value: str, default: float = 0.0) -> float:
    """Parse a float, returning *default* on ValueError."""
    try:
        return float(value)
    except ValueError:
        return default


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

    FT-CORE-008: Supports chunking for long chapters. When chapter text
    exceeds max_chunk_words, it is split at paragraph boundaries and each
    chunk is analyzed independently. Results are merged with position
    offset correction to prevent OOM on novel-length chapters.
    """

    def __init__(
        self,
        model_params: Optional[dict] = None,
        language_code: str = "en",
        max_chunk_words: int = 10000,
    ) -> None:
        self._available = _check_booknlp_available()
        self._model_params = model_params or {}
        self._model = None
        self._language_code = language_code
        self.max_chunk_words = max_chunk_words

        # F-CORE-B-010: Warn on non-English
        if language_code != "en":
            logger.warning(
                "BookNLP is optimized for English. Language '%s' may produce "
                "lower-quality speaker attribution results.",
                language_code,
            )

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

        FT-CORE-008: When the text exceeds max_chunk_words, it is split
        at paragraph boundaries and each chunk is analyzed independently.
        Results are merged with position offset correction.

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
            word_count = len(text.split())
            if word_count <= self.max_chunk_words:
                return self._run_analysis(text)

            # FT-CORE-008: Chunk and merge
            return self._analyze_chunked(text)
        except Exception as e:
            logger.warning(f"BookNLP analysis failed: {e}")
            return BookNLPResult(success=False, error=str(e))

    def _split_at_paragraphs(self, text: str) -> list[tuple[str, int]]:
        """
        Split text into chunks at paragraph boundaries (FT-CORE-008).

        Each chunk stays at or below max_chunk_words. Returns list of
        (chunk_text, char_offset) tuples.
        """
        paragraphs = text.split("\n\n")
        chunks: list[tuple[str, int]] = []
        current_parts: list[str] = []
        current_words = 0
        current_offset = 0
        running_offset = 0

        for para in paragraphs:
            para_words = len(para.split())
            if current_words + para_words > self.max_chunk_words and current_parts:
                # Emit current chunk
                chunk_text = "\n\n".join(current_parts)
                chunks.append((chunk_text, current_offset))
                current_offset = running_offset
                current_parts = [para]
                current_words = para_words
            else:
                current_parts.append(para)
                current_words += para_words
            # +2 for the "\n\n" separator
            running_offset += len(para) + 2

        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append((chunk_text, current_offset))

        return chunks

    def _analyze_chunked(self, text: str) -> BookNLPResult:
        """
        Analyze long text by chunking at paragraph boundaries (FT-CORE-008).

        Splits text, analyzes each chunk, then merges results with position
        offset correction.
        """
        chunks = self._split_at_paragraphs(text)
        logger.info(
            "FT-CORE-008: Splitting %d-word text into %d chunks for BookNLP",
            len(text.split()), len(chunks),
        )

        merged = BookNLPResult(success=True)
        all_speakers: set[str] = set()

        for chunk_text, char_offset in chunks:
            result = self._run_analysis(chunk_text)
            if not result.success:
                logger.warning(
                    "Chunk at offset %d failed: %s — skipping",
                    char_offset, result.error,
                )
                continue

            # Merge entities with offset correction
            for entity in result.entities:
                merged.entities.append(Entity(
                    name=entity.name,
                    start=entity.start + char_offset,
                    end=entity.end + char_offset,
                    entity_type=entity.entity_type,
                ))

            # Merge quotes with offset correction
            for quote in result.quotes:
                merged.quotes.append(QuoteAttribution(
                    quote_text=quote.quote_text,
                    speaker=quote.speaker,
                    start=quote.start + char_offset,
                    end=quote.end + char_offset,
                    confidence=quote.confidence,
                ))

            all_speakers.update(result.speakers)

        merged.speakers = sorted(all_speakers)
        return merged

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
                self._model = BookNLP(self._language_code, self._model_params)

            # BookNLP requires file I/O
            # F-CORE-B-009: Catch disk-space errors with helpful message
            try:
                tmpdir_ctx = tempfile.TemporaryDirectory(prefix="audiobooker_nlp_")
            except OSError as e:
                raise OSError(
                    f"Cannot create temporary directory for BookNLP analysis: {e}. "
                    "You may be running low on disk space. Free up space in your "
                    "system temp folder and try again."
                ) from e

            with tmpdir_ctx as tmpdir:
                input_path = Path(tmpdir) / "input.txt"
                try:
                    input_path.write_text(text, encoding="utf-8")
                except OSError as e:
                    raise OSError(
                        f"Cannot write text for BookNLP analysis: {e}. "
                        "Insufficient disk space — free up space and try again."
                    ) from e

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
        # F-CORE-B-019: Validate column counts, skip malformed lines
        entities_path = Path(output_dir) / "book.entities"
        if entities_path.exists():
            for line_num, line in enumerate(
                entities_path.read_text(encoding="utf-8").splitlines()[1:], start=2
            ):
                parts = line.split("\t")
                if len(parts) < 4:
                    logger.warning(
                        "Skipping malformed entity line %d (expected >=4 columns, got %d): %s",
                        line_num, len(parts), line[:80],
                    )
                    continue
                name = parts[0]
                entities.append(Entity(
                    name=name,
                    start=int(parts[1]) if parts[1].isdigit() else 0,
                    end=int(parts[2]) if parts[2].isdigit() else 0,
                    entity_type=parts[3] if len(parts) > 3 else "PER",
                ))
                if parts[3] == "PER":
                    speakers.add(name)

        # Parse quotes
        quotes_path = Path(output_dir) / "book.quotes"
        if quotes_path.exists():
            for line_num, line in enumerate(
                quotes_path.read_text(encoding="utf-8").splitlines()[1:], start=2
            ):
                parts = line.split("\t")
                if len(parts) < 4:
                    logger.warning(
                        "Skipping malformed quote line %d (expected >=4 columns, got %d): %s",
                        line_num, len(parts), line[:80],
                    )
                    continue
                quotes.append(QuoteAttribution(
                    quote_text=parts[0],
                    speaker=parts[1],
                    start=int(parts[2]) if parts[2].isdigit() else 0,
                    end=int(parts[3]) if parts[3].isdigit() else 0,
                    confidence=_safe_float(parts[4]) if len(parts) > 4 else 0.5,
                ))
                speakers.add(parts[1])

        return BookNLPResult(
            entities=entities,
            quotes=quotes,
            speakers=sorted(speakers),
            success=True,
        )
