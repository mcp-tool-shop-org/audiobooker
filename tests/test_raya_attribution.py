"""F-9f2e0c74-A: raya dialogue must attribute, not shift the whole chapter.

Found because a vacuous assertion was standing over it —
``assert "dijo" in profile.speaker_verbs or len(profile.speaker_verbs) > 0``,
whose right operand is unconditionally true. The Spanish profile had exactly
one substantive test and it could not fail, so a two-language
voice-misassignment bug shipped underneath it.

The defect: ``es`` declares ``("—", "\\n")`` in ``dialogue_quotes``, so the
raya opener was harvested by ``_attribution_quote_chars`` as a quote
character, and ``_gap_is_attributive(..., allow_quotes=False)`` then rejected
any candidate whose gap contained the attributive raya of ``—dijo María`` —
while ``_ATTRIB_GAP_RE`` explicitly whitelists ``—`` as an attributive
separator. Two mechanisms, opposite conclusions.

It failed silently and shifted every line: attribution returned None,
turn-tracking filled the hole with the PREVIOUS speaker, so only the FIRST
line was ``unknown`` and every subsequent line carried the wrong voice.
"""

from __future__ import annotations

import pytest

from audiobooker.casting.dialogue import (
    _attribution_quote_chars,
    compile_chapter,
)
from audiobooker.language import get_profile
from audiobooker.models import CastingTable, Chapter

RAYA = "—"
EN_DASH = "–"


def _speakers(text: str, lang: str) -> list[str]:
    profile = get_profile(lang)
    chapter = Chapter(index=0, title="Ch", raw_text=text)
    utterances = compile_chapter(chapter, CastingTable(), profile=profile)
    return [u.speaker for u in utterances
            if u.speaker and u.speaker.lower() != "narrator"]


class TestRayaIsNotADelimiter:
    """A character cannot be a quote delimiter and an attributive separator
    at the same time. `_ATTRIB_GAP_RE` already claimed it as the latter."""

    @pytest.mark.parametrize("lang", ["es", "pt"])
    def test_raya_is_excluded_from_the_quote_chars(self, lang):
        assert RAYA not in _attribution_quote_chars(get_profile(lang))

    @pytest.mark.parametrize("lang", ["es", "pt"])
    def test_en_dash_is_excluded_too(self, lang):
        assert EN_DASH not in _attribution_quote_chars(get_profile(lang))

    def test_real_quote_marks_are_still_delimiters(self):
        """The fix must not empty the set — guillemets and double quotes are
        genuine delimiters and the gap check depends on them."""
        chars = _attribution_quote_chars(get_profile("es"))
        assert '"' in chars
        assert "«" in chars  # «
        assert "»" in chars  # »


class TestRayaDialogueAttributes:
    """The behaviour, measured through compile_chapter — the production path,
    not the attribution helper in isolation."""

    def test_spanish_three_turns_each_to_its_own_speaker(self):
        text = "\n".join([
            f"{RAYA}Ven aquí {RAYA}dijo María.",
            f"{RAYA}No quiero {RAYA}respondió Pedro.",
            f"{RAYA}Es importante {RAYA}insistió María.",
        ])
        assert _speakers(text, "es") == ["María", "Pedro", "María"]

    def test_portuguese_is_not_broken_the_same_way(self):
        """pt declares the same pair and was broken identically. fr and it
        never declare it and reach the raya path via _RAYA_LANGUAGES, which
        is why they were fine — so this is about the DECLARATION, not the
        language."""
        text = "\n".join([
            f"{RAYA}Vem cá {RAYA}disse Maria.",
            f"{RAYA}Não quero {RAYA}respondeu Pedro.",
        ])
        assert _speakers(text, "pt") == ["Maria", "Pedro"]

    @pytest.mark.parametrize("lang,cases", [
        ("fr", [("Viens ici", "dit", "Marie"), ("Je refuse", "répondit", "Pierre")]),
        ("it", [("Vieni qui", "disse", "Maria"), ("Non voglio", "rispose", "Pietro")]),
    ])
    def test_languages_that_were_already_correct_stay_correct(self, lang, cases):
        text = "\n".join(
            f"{RAYA}{line} {RAYA}{verb} {who}." for line, verb, who in cases
        )
        assert _speakers(text, lang) == [who for _, _, who in cases]

    def test_no_line_is_attributed_to_the_previous_speaker(self):
        """The shape of the failure, pinned directly.

        Before the fix this chapter produced [unknown, María, Pedro] for
        [María, Pedro, María] — every line carrying the previous line's
        speaker. A regression would reintroduce exactly that offset, so
        assert against it rather than only against the correct answer.
        """
        text = "\n".join([
            f"{RAYA}Uno {RAYA}dijo María.",
            f"{RAYA}Dos {RAYA}respondió Pedro.",
            f"{RAYA}Tres {RAYA}insistió María.",
        ])
        got = _speakers(text, "es")
        assert "unknown" not in [s.lower() for s in got]
        assert got[0] == "María"


class TestTheQualitySignalNoLongerLies:
    """Why this was HIGH and not MEDIUM.

    The defect converted a would-be `unknown` into an ACCEPTED WRONG speaker
    on every line but the first — the fourth defect of that class in this
    module. The unattributed rate therefore approached zero as a chapter grew,
    so the >50% guard could not fire on a book where every voice was wrong.
    """

    def test_a_long_raya_chapter_reports_zero_unattributed_because_it_is(self):
        lines = []
        for i in range(12):
            who = "María" if i % 2 == 0 else "Pedro"
            lines.append(f"{RAYA}Línea {i} {RAYA}dijo {who}.")
        chapter = Chapter(index=0, title="Ch", raw_text="\n".join(lines))
        utterances = compile_chapter(
            chapter, CastingTable(), profile=get_profile("es")
        )
        named = [u.speaker for u in utterances
                 if u.speaker and u.speaker.lower() != "narrator"]
        assert len(named) == 12
        assert all(s.lower() != "unknown" for s in named)
        # Correct alternation, not a shifted one.
        assert named == ["María" if i % 2 == 0 else "Pedro"
                         for i in range(12)]
