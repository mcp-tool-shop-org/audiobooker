"""
Regression tests for Stage A casting/NLP health fixes.

Covers:
- NLP-NORM-A-001: compound ordinals with irregular trailing words
- CAST-DIAL-A-002: utterance offsets must stay aligned with raw_text for
  indented paragraphs
- CAST-DIAL-A-003: documented line_count contract for compile_chapter

Each test is written to FAIL against the pre-fix behavior and PASS after.
"""

import pytest

from audiobooker.nlp.normalizer import _int_to_ordinal, normalize_numbers
from audiobooker.casting.dialogue import compile_chapter
from audiobooker.models import Chapter, CastingTable, UtteranceType


# ---------------------------------------------------------------------------
# NLP-NORM-A-001: compound ordinals with irregular trailing words
# ---------------------------------------------------------------------------

class TestCompoundOrdinals:
    """Compound numbers ending in an irregular cardinal must use the
    irregular ordinal form (e.g. 101 -> '... first', not '... oneth')."""

    @pytest.mark.parametrize(
        "n, expected",
        [
            (101, "one hundred first"),
            (108, "one hundred eighth"),
            (112, "one hundred twelfth"),
            (102, "one hundred second"),
            (103, "one hundred third"),
            (105, "one hundred fifth"),
            (109, "one hundred ninth"),
            (1009, "one thousand ninth"),
            (1001, "one thousand first"),
        ],
    )
    def test_irregular_trailing_word(self, n, expected):
        assert _int_to_ordinal(n) == expected

    def test_regular_compound_still_correct(self):
        # Sanity: regular trailing words unaffected by the fix.
        assert _int_to_ordinal(104) == "one hundred fourth"
        assert _int_to_ordinal(106) == "one hundred sixth"
        assert _int_to_ordinal(100) == "one hundredth"

    def test_hyphenated_trailing_word(self):
        # The hyphenated branch must also be table-driven.
        assert _int_to_ordinal(121) == "one hundred twenty-first"
        assert _int_to_ordinal(23) == "twenty-third"
        assert _int_to_ordinal(20) == "twentieth"

    def test_normalize_numbers_ordinal_in_sentence(self):
        assert (
            normalize_numbers("the 101st floor") == "the one hundred first floor"
        )
        assert (
            normalize_numbers("the 112th time") == "the one hundred twelfth time"
        )


# ---------------------------------------------------------------------------
# CAST-DIAL-A-002: offsets must align with raw_text for indented paragraphs
# ---------------------------------------------------------------------------

class TestIndentedParagraphOffsets:
    """The invariant raw_text[start_pos:end_pos] == utterance text must hold
    even when the source paragraph has leading whitespace (indentation)."""

    def test_indented_dialogue_offsets_align(self):
        raw = '    "Hello there," said Alice.'
        chapter = Chapter(index=0, title="Ch", raw_text=raw)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting)
        assert utterances, "expected at least one utterance"

        for u in utterances:
            # Old behavior shifted offsets left by len(leading whitespace),
            # so the slice did not contain the utterance text.
            sliced = raw[u.start_pos:u.end_pos]
            assert u.text in sliced or sliced == u.text, (
                f"offset slice {sliced!r} does not contain text {u.text!r}"
            )

    def test_indented_narration_exact_slice(self):
        raw = "        This is an indented narration paragraph."
        chapter = Chapter(index=0, title="Ch", raw_text=raw)
        casting = CastingTable()

        utterances = compile_chapter(chapter, casting)
        assert len(utterances) == 1
        u = utterances[0]
        assert u.utterance_type == UtteranceType.NARRATION
        assert raw[u.start_pos:u.end_pos] == u.text

    def test_second_indented_paragraph_offsets_align(self):
        # First paragraph at column 0, second one indented — checks the
        # running offset plus lead handling together.
        raw = (
            "Plain opening paragraph.\n\n"
            '    "Indented dialogue here," she whispered.'
        )
        chapter = Chapter(index=0, title="Ch", raw_text=raw)
        casting = CastingTable()
        casting.cast("narrator", "af_heart")

        utterances = compile_chapter(chapter, casting)
        assert utterances
        for u in utterances:
            sliced = raw[u.start_pos:u.end_pos]
            assert u.text in sliced or sliced == u.text, (
                f"offset slice {sliced!r} does not contain text {u.text!r}"
            )


# ---------------------------------------------------------------------------
# CAST-DIAL-A-003: documented line_count contract
# ---------------------------------------------------------------------------

class TestLineCountContract:
    """compile_chapter documents and applies a sequential-path line_count
    side effect; the docstring must no longer claim the function is pure."""

    def test_docstring_no_longer_claims_no_mutation(self):
        doc = compile_chapter.__doc__ or ""
        assert "does NOT mutate the CastingTable" not in doc, (
            "docstring still falsely claims purity"
        )
        # The docstring should describe the line_count side effect.
        assert "line_count" in doc

    def test_sequential_line_count_applied(self):
        raw = (
            '"First line," said Alice.\n\n'
            '"Second line," said Alice.'
        )
        chapter = Chapter(index=0, title="Ch", raw_text=raw)
        casting = CastingTable()
        casting.cast("Alice", "af_bella")

        compile_chapter(chapter, casting)
        # Sequential path: the mutation is observable on the passed table.
        assert casting.characters["alice"].line_count == 2

    def test_returned_utterances_allow_independent_tally(self):
        # The documented authoritative path: tally from returned utterances
        # rather than relying on the mutation. This must match the count.
        raw = (
            '"First line," said Alice.\n\n'
            '"Second line," said Alice.'
        )
        chapter = Chapter(index=0, title="Ch", raw_text=raw)
        casting = CastingTable()
        casting.cast("Alice", "af_bella")

        utterances = compile_chapter(chapter, casting)
        tally: dict[str, int] = {}
        for u in utterances:
            key = casting.normalize_key(u.speaker)
            tally[key] = tally.get(key, 0) + 1
        assert tally.get("alice") == casting.characters["alice"].line_count
