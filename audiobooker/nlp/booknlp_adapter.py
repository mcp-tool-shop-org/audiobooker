"""
BookNLP adapter — optional NLP-powered speaker attribution.

Detects whether BookNLP is installed and provides a clean adapter
for the pipeline. When unavailable, returns empty results so the
caller can fall back to heuristic attribution.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("audiobooker.nlp.booknlp")

# Upstream BookNLP CLI default (booknlp/booknlp.py proc()). EnglishBookNLP
# requires both keys; an empty dict KeyErrors at construction.
DEFAULT_MODEL_PARAMS: dict = {
    "pipeline": "entity,quote,supersense,event,coref",
    "model": "small",
}

# Upstream TSV headers from english_booknlp.py. Column names are the
# contract; positional fallbacks match the writer if the header is absent.
_QUOTES_COLUMNS = (
    "quote_start",
    "quote_end",
    "mention_start",
    "mention_end",
    "mention_phrase",
    "char_id",
    "quote",
)
_ENTITIES_COLUMNS = (
    "coref",
    "start_token",
    "end_token",
    "prop",
    "cat",
    "text",
)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])(?:\s+|$)")


def _safe_int(value: str, default: int = 0) -> int:
    """Parse an int, returning *default* on ValueError."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _header_index_map(
    header_line: str, columns: tuple[str, ...],
) -> Optional[dict[str, int]]:
    """Return {column_name: index} when *header_line* names every column."""
    parts = [p.strip().casefold() for p in header_line.split("\t")]
    if not all(col in parts for col in columns):
        return None
    return {col: parts.index(col) for col in columns}


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
    # Chunks that failed inside _analyze_chunked while others succeeded.
    # Resolver appends nlp_errors when this is non-zero even if success=True.
    skipped_chunks: int = 0


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

_BOOKNLP_PACKAGE = "booknlp"


def _check_booknlp_available() -> bool:
    """
    Check if BookNLP is importable.

    The exception is no longer discarded. ``ModuleNotFoundError`` subclasses
    ``ImportError``, so a BROKEN install — booknlp present but one of ITS
    dependencies missing — used to be reported identically to an absent one,
    and the user was told to ``pip install booknlp``, a package they already
    had. Genuine absence stays quiet (it is an optional dependency); drift is
    surfaced at WARNING naming the module that actually failed.
    """
    try:
        import booknlp  # noqa: F401
        return True
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", None) or ""
        if not missing or missing == _BOOKNLP_PACKAGE:
            logger.debug("BookNLP is not installed — speaker attribution falls back")
            return False
        logger.warning(
            "BookNLP is INSTALLED but not importable: no module named %r (%s). "
            "This is a broken or incompatible install, not an absent one — "
            "'pip install booknlp' will not fix it; install the missing "
            "dependency or check the booknlp version.",
            missing, exc,
        )
        return False
    except ImportError as exc:
        logger.warning(
            "BookNLP is INSTALLED but failed to import (%s). This is a broken "
            "or incompatible install, not an absent one.", exc,
        )
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
        # BookNLP.__init__ only assigns self.booknlp when language == "en";
        # any other code leaves process() to AttributeError. Fail here rather
        # than swallowing that as a per-chapter heuristic fallback.
        if language_code != "en":
            raise ValueError(
                f"BookNLP is English-only; language_code={language_code!r} "
                "is not supported."
            )

        self._available = _check_booknlp_available()
        merged = dict(DEFAULT_MODEL_PARAMS)
        if model_params:
            merged.update(model_params)
        self._model_params = merged
        self._model = None
        self._language_code = language_code
        self.max_chunk_words = max_chunk_words

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

        Each chunk stays at or below max_chunk_words. A single paragraph
        that itself exceeds the cap is split at sentence boundaries, then
        at word windows, so we never emit the OOM-sized chunk chunking
        was added to prevent. Returns list of (chunk_text, char_offset).
        """
        max_words = self.max_chunk_words
        paragraphs = text.split("\n\n")
        chunks: list[tuple[str, int]] = []
        current_parts: list[str] = []
        current_words = 0
        current_offset = 0
        running_offset = 0

        def emit_current() -> None:
            nonlocal current_parts, current_words
            if current_parts:
                chunks.append(("\n\n".join(current_parts), current_offset))
                current_parts = []
                current_words = 0

        for para in paragraphs:
            para_words = len(para.split())
            if para_words > max_words:
                emit_current()
                chunks.extend(self._split_oversize_paragraph(para, running_offset))
                current_offset = running_offset + len(para) + 2
            elif current_words + para_words > max_words and current_parts:
                emit_current()
                current_offset = running_offset
                current_parts = [para]
                current_words = para_words
            else:
                if not current_parts:
                    current_offset = running_offset
                current_parts.append(para)
                current_words += para_words
            running_offset += len(para) + 2

        emit_current()
        return chunks

    def _split_oversize_paragraph(
        self, para: str, para_offset: int,
    ) -> list[tuple[str, int]]:
        """Split one paragraph that exceeds max_chunk_words."""
        spans = self._sentence_spans(para)
        if not spans:
            return self._chunks_by_words(para, para_offset)

        out: list[tuple[str, int]] = []
        cur_start: Optional[int] = None
        cur_end: Optional[int] = None
        cur_words = 0
        max_words = self.max_chunk_words

        def emit_cur() -> None:
            nonlocal cur_start, cur_end, cur_words
            if cur_start is not None and cur_end is not None:
                out.append((para[cur_start:cur_end], para_offset + cur_start))
            cur_start = cur_end = None
            cur_words = 0

        for start, end in spans:
            n_words = len(para[start:end].split())
            if n_words > max_words:
                emit_cur()
                out.extend(self._chunks_by_words(para[start:end], para_offset + start))
                continue
            if cur_start is not None and cur_words + n_words > max_words:
                emit_cur()
            if cur_start is None:
                cur_start = start
            cur_end = end
            cur_words += n_words
        emit_cur()
        return out

    @staticmethod
    def _sentence_spans(text: str) -> list[tuple[int, int]]:
        """[start, end) spans of sentences in *text*, original whitespace kept."""
        spans: list[tuple[int, int]] = []
        start = 0
        for match in _SENTENCE_BOUNDARY.finditer(text):
            end = match.end()
            if start < end:
                spans.append((start, end))
            start = end
        if start < len(text):
            spans.append((start, len(text)))
        return [(s, e) for s, e in spans if text[s:e].strip()]

    def _chunks_by_words(
        self, text: str, offset: int,
    ) -> list[tuple[str, int]]:
        """Last-resort split: windows of at most max_chunk_words tokens."""
        tokens = list(re.finditer(r"\S+", text))
        if not tokens:
            return [(text, offset)] if text else []
        max_words = max(1, self.max_chunk_words)
        if len(tokens) <= max_words:
            return [(text, offset)]
        out: list[tuple[str, int]] = []
        i = 0
        while i < len(tokens):
            j = min(i + max_words, len(tokens))
            start = tokens[i].start()
            chunk_end = tokens[j].start() if j < len(tokens) else len(text)
            out.append((text[start:chunk_end], offset + start))
            i = j
        return out

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

        merged = BookNLPResult(success=False)
        all_speakers: set[str] = set()
        last_error = ""
        skipped = 0
        succeeded = 0

        for chunk_text, char_offset in chunks:
            result = self._run_analysis(chunk_text)
            if not result.success:
                skipped += 1
                last_error = result.error
                logger.warning(
                    "Chunk at offset %d failed: %s — skipping",
                    char_offset, result.error,
                )
                continue

            succeeded += 1
            # Merge entities with offset correction. BookNLP start/end are
            # token ids, not char offsets; the shift keeps chunks distinct
            # after merge. Resolver matches on quote text, not these spans.
            for entity in result.entities:
                merged.entities.append(Entity(
                    name=entity.name,
                    start=entity.start + char_offset,
                    end=entity.end + char_offset,
                    entity_type=entity.entity_type,
                ))

            for quote in result.quotes:
                merged.quotes.append(QuoteAttribution(
                    quote_text=quote.quote_text,
                    speaker=quote.speaker,
                    start=quote.start + char_offset,
                    end=quote.end + char_offset,
                    confidence=quote.confidence,
                ))

            all_speakers.update(result.speakers)

        if succeeded == 0:
            return BookNLPResult(
                success=False,
                error=last_error or f"All {len(chunks)} BookNLP chunk(s) failed",
                skipped_chunks=skipped or len(chunks),
            )

        merged.success = True
        merged.speakers = sorted(all_speakers)
        merged.skipped_chunks = skipped
        if skipped:
            merged.error = (
                f"{skipped} of {len(chunks)} BookNLP chunk(s) failed"
                + (f": {last_error}" if last_error else "")
            )
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
            if self._model is None:
                from booknlp.booknlp import BookNLP
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

                # Upstream BookNLP exposes process(inputFile, outputFolder, idd)
                # only — there is no pipeline() method.
                self._model.process(
                    str(input_path),
                    str(output_dir),
                    "book",
                )

                return self._parse_output(output_dir)

        except Exception as e:
            logger.error(f"BookNLP process error: {e}")
            return BookNLPResult(success=False, error=str(e))

    def _parse_output(self, output_dir) -> BookNLPResult:
        """Parse BookNLP ``book.entities`` / ``book.quotes`` TSVs.

        Real writer contract (english_booknlp.py):

        * entities: ``COREF start_token end_token prop cat text``
        * quotes: ``quote_start quote_end mention_start mention_end
          mention_phrase char_id quote``

        Speakers are the most frequent PROP PER string for each COREF id,
        never the mention pronoun and never the COREF integer. BookNLP
        does not emit a confidence column; resolved quotes score 1.0
        (binary attribution) so the resolver can cap fuzzy text-matches
        separately.
        """
        from pathlib import Path

        entities: list[Entity] = []
        quotes: list[QuoteAttribution] = []
        speakers: set[str] = set()
        prop_per_counts: dict[str, Counter] = {}

        entities_path = Path(output_dir) / "book.entities"
        entities_exist = entities_path.exists()
        if entities_exist:
            lines = entities_path.read_text(encoding="utf-8").splitlines()
            idx_map = _header_index_map(lines[0], _ENTITIES_COLUMNS) if lines else None
            body = lines[1:] if idx_map is not None else lines
            if idx_map is None:
                idx_map = {col: i for i, col in enumerate(_ENTITIES_COLUMNS)}
            for line_num, line in enumerate(body, start=2 if lines else 1):
                parts = line.split("\t")
                need = max(idx_map.values()) + 1
                if len(parts) < need:
                    logger.warning(
                        "Skipping malformed entity line %d (expected >=%d columns, got %d): %s",
                        line_num, need, len(parts), line[:80],
                    )
                    continue
                coref = parts[idx_map["coref"]].strip()
                name = parts[idx_map["text"]].strip()
                prop = parts[idx_map["prop"]].strip()
                cat = parts[idx_map["cat"]].strip()
                start = _safe_int(parts[idx_map["start_token"]])
                end = _safe_int(parts[idx_map["end_token"]])
                entities.append(Entity(
                    name=name,
                    start=start,
                    end=end,
                    entity_type=cat or "PER",
                ))
                if prop.casefold() == "prop" and cat.casefold() == "per" and name:
                    speakers.add(name)
                    prop_per_counts.setdefault(coref, Counter())[name] += 1

        coref_to_name: dict[str, str] = {
            coref: _canonical_prop_per(counts)
            for coref, counts in prop_per_counts.items()
        }

        quotes_path = Path(output_dir) / "book.quotes"
        quotes_exist = quotes_path.exists()
        quote_rows_seen = 0
        skipped_missing_prop_per = 0
        if quotes_exist:
            lines = quotes_path.read_text(encoding="utf-8").splitlines()
            idx_map = _header_index_map(lines[0], _QUOTES_COLUMNS) if lines else None
            body = lines[1:] if idx_map is not None else lines
            if idx_map is None:
                idx_map = {col: i for i, col in enumerate(_QUOTES_COLUMNS)}
            for line_num, line in enumerate(body, start=2 if lines else 1):
                parts = line.split("\t")
                need = max(idx_map.values()) + 1
                if len(parts) < need:
                    logger.warning(
                        "Skipping malformed quote line %d (expected >=%d columns, got %d): %s",
                        line_num, need, len(parts), line[:80],
                    )
                    continue
                quote_rows_seen += 1
                quote_text = parts[idx_map["quote"]]
                char_id = parts[idx_map["char_id"]].strip()
                if not quote_text or not char_id or char_id.casefold() == "none":
                    continue
                speaker = coref_to_name.get(char_id, "")
                if not speaker:
                    skipped_missing_prop_per += 1
                    logger.debug(
                        "Skipping quote line %d: no PROP PER name for char_id %s",
                        line_num, char_id,
                    )
                    continue
                quotes.append(QuoteAttribution(
                    quote_text=quote_text,
                    speaker=speaker,
                    start=_safe_int(parts[idx_map["quote_start"]]),
                    end=_safe_int(parts[idx_map["quote_end"]]),
                    confidence=1.0,
                ))
                speakers.add(speaker)

        # F-503cd84c: empty quotes with success=True is only honest when the
        # quotes TSV is present and truly empty (header-only / no rows).
        # Missing files, or quote rows whose char_id never maps to a PROP PER
        # name, used to look like a successful NLP pass that found nothing.
        if not entities_exist and not quotes_exist:
            return BookNLPResult(
                entities=entities,
                quotes=quotes,
                speakers=sorted(speakers),
                success=False,
                error="BookNLP produced no book.entities or book.quotes",
            )
        if not quotes_exist:
            return BookNLPResult(
                entities=entities,
                quotes=quotes,
                speakers=sorted(speakers),
                success=False,
                error="BookNLP produced no book.quotes",
            )
        if quote_rows_seen > 0 and not quotes and skipped_missing_prop_per > 0:
            return BookNLPResult(
                entities=entities,
                quotes=quotes,
                speakers=sorted(speakers),
                success=False,
                error="BookNLP quotes had no PROP PER name for any char_id",
            )

        return BookNLPResult(
            entities=entities,
            quotes=quotes,
            speakers=sorted(speakers),
            success=True,
        )


def _canonical_prop_per(counts: Counter) -> str:
    """Most frequent PROP PER string; ties break toward the longer name."""
    best_n = max(counts.values())
    tied = [name for name, n in counts.items() if n == best_n]
    return max(tied, key=lambda n: (len(n), n))
