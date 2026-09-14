"""
Stage B (proactive health) regression tests for the parse -> attribute -> cast
pipeline.

Every test here was written BEFORE its fix and observed failing against
``ccf35dd``. They cover one story in three acts plus three independent seams:

PH-B-001/002/003/004
    The tool's only signal of attribution quality moved in the WRONG direction.
    ``compile_chapter``'s >50%-unknown guard divided by ALL utterances including
    narration, so a chapter where 100% of dialogue was unattributed measured
    0.20-0.33 against a ``> 0.5`` test and never fired; ``compile_report``
    carried the same diluted number and no verdict; and two separate defects
    (TTS honorific expansion, ``re.IGNORECASE`` on the name fragment) each
    manufactured a WRONG speaker that was ACCEPTED, which LOWERS the unknown
    rate. Attribution getting worse made the metric look better.

PH-B-005
    Pronunciation overrides ran at parse time and rewrote the very text
    attribution runs against.

PH-B-006
    Chapter detection scored patterns in a fixed 200-line head window, so a
    Gutenberg-shaped table of contents beat the real headings.

PH-B-007
    ``CastingTable.normalize_key`` did ``casefold().strip()`` with no Unicode
    normalization, so NFC and NFD spellings of one name were different keys.

Shapes the existing fixtures cannot express and that are therefore explicit
here: SINGLE-newline-separated prose (one paragraph, interleaved narration and
quotes) and honorific-heavy classic literature ("said Mr. Holmes").
"""

from __future__ import annotations

import logging
import unicodedata

import pytest

from audiobooker.casting.dialogue import (
    compile_chapter,
    compile_report,
)
from audiobooker.language.profile import get_profile
from audiobooker.models import CastingTable, Chapter, UtteranceType
from audiobooker.nlp.normalizer import normalize
from audiobooker.parser.text import detect_chapter_pattern, split_into_chapters
from audiobooker.parser.text_cleaners import apply_pronunciation_overrides


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compile(text: str, casting: CastingTable | None = None):
    chapter = Chapter(index=0, title="T", raw_text=text)
    return compile_chapter(chapter, casting or CastingTable())


def _speakers(text: str, casting: CastingTable | None = None) -> list[str]:
    return [u.speaker for u in _compile(text, casting)]


def _dialogue_speakers(text: str, casting: CastingTable | None = None) -> list[str]:
    return [
        u.speaker
        for u in _compile(text, casting)
        if u.utterance_type == UtteranceType.DIALOGUE
    ]


def _report_for(text: str, casting: CastingTable | None = None) -> dict:
    casting = casting or CastingTable()
    chapter = Chapter(index=0, title="T", raw_text=text)
    chapter.utterances = compile_chapter(chapter, casting)
    return compile_report([chapter], casting)


# Real prose runs several narration paragraphs per quote. 100% of the dialogue
# below is unattributed; the old all-utterance denominator scored it 0.25.
DILUTED_BLANK_LINE_PROSE = "\n\n".join(
    "\n\n".join([
        "The corridor was empty again, and the lamps guttered in their brackets.",
        "Somewhere below, a door closed with the finality of a verdict.",
        "Nobody moved for a long moment after that.",
        f'"Line number {i}."',
    ])
    for i in range(4)
)

# SINGLE-newline-separated prose: one paragraph as far as the compiler is
# concerned, narration and quotes interleaved inside it. No existing fixture
# has this shape, and it is the common shape in OCR'd and EPUB-flattened text.
DILUTED_SINGLE_NEWLINE_PROSE = "\n".join([
    "The corridor was empty again, and the lamps guttered in their brackets.",
    "Somewhere below, a door closed with the finality of a verdict.",
    '"Line number one."',
    "The clock in the hall struck the half hour and then thought better of it.",
    "Rain worked its slow way down the tall windows.",
    '"Line number two."',
    "No one answered, because there was no one left in the house to answer.",
    "The fire had burned down to a red argument with itself.",
    '"Line number three."',
])


# ---------------------------------------------------------------------------
# PH-B-001 — the >50%-unknown guard cannot fire (diluted denominator)
# ---------------------------------------------------------------------------

class TestUnknownGuardDenominator:
    """compile_chapter must measure unattributed DIALOGUE, not all utterances."""

    @pytest.mark.parametrize(
        "prose,label",
        [
            (DILUTED_BLANK_LINE_PROSE, "blank-line-separated"),
            (DILUTED_SINGLE_NEWLINE_PROSE, "single-newline-separated"),
        ],
    )
    def test_all_dialogue_unknown_is_flagged(self, prose, label, caplog):
        """100% unattributed dialogue must be reported, whatever the narration ratio."""
        with caplog.at_level(logging.WARNING, logger="audiobooker.casting"):
            utterances = _compile(prose)

        dialogue = [u for u in utterances if u.utterance_type == UtteranceType.DIALOGUE]
        assert dialogue, f"{label} fixture produced no dialogue at all"
        assert all(u.speaker == "unknown" for u in dialogue)

        # The old guard divided by len(utterances) and stayed under 0.5.
        assert len([u for u in utterances if u.speaker == "unknown"]) <= len(utterances) * 0.5

        loud = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "dialogue" in r.message.lower()
        ]
        assert loud, (
            f"{label}: no warning names the dialogue-only unattributed rate; "
            f"records={[r.message for r in caplog.records]}"
        )

    def test_total_collapse_is_escalated_above_error(self, caplog):
        """A book that would render as a single voice must halt loudly, not whisper."""
        with caplog.at_level(logging.WARNING, logger="audiobooker.casting"):
            _compile(DILUTED_BLANK_LINE_PROSE)
        assert any(r.levelno >= logging.ERROR for r in caplog.records), (
            "100% unattributed dialogue only produced WARNING-or-lower records"
        )

    def test_healthy_chapter_stays_quiet(self, caplog):
        prose = (
            '"Good evening," said Alice.\n\n'
            "She set the lamp on the table and waited.\n\n"
            '"And to you," said Bob.\n\n'
            "The room settled around them.\n\n"
            '"We should begin," said Alice.'
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.casting"):
            _compile(prose)
        assert not [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "unattributed" in r.message.lower()
        ]


# ---------------------------------------------------------------------------
# PH-B-002 — compile_report has no verdict
# ---------------------------------------------------------------------------

class TestCompileReportVerdict:

    def test_report_exposes_dialogue_unknown_rate(self):
        report = _report_for(DILUTED_BLANK_LINE_PROSE)
        assert "dialogue_unknown_rate" in report
        assert report["dialogue_unknown_rate"] == pytest.approx(1.0)
        assert report["total_dialogue_unknown"] == report["total_dialogue"]

    def test_report_keeps_all_utterance_rate_as_secondary(self):
        """unknown_rate stays the all-utterance figure — it is a published key."""
        report = _report_for(DILUTED_BLANK_LINE_PROSE)
        assert report["unknown_rate"] == pytest.approx(
            report["total_dialogue_unknown"] / report["total_utterances"]
        )
        assert report["unknown_rate"] < report["dialogue_unknown_rate"]

    def test_quality_verdict_failed(self):
        assert _report_for(DILUTED_BLANK_LINE_PROSE)["quality"] == "failed"

    def test_quality_verdict_ok(self):
        prose = (
            '"Good evening," said Alice.\n\n'
            "She set the lamp on the table.\n\n"
            '"And to you," said Bob.'
        )
        assert _report_for(prose)["quality"] == "ok"

    def test_quality_verdict_degraded(self):
        # One named speaker, so turn-tracking has nothing to alternate with
        # and the three bare quotes stay unattributed: 3 of 4 -> 0.75.
        prose = (
            '"One," said Alice.\n\n'
            "The hall was cold.\n\n"
            '"Two."\n\n'
            "Nothing stirred.\n\n"
            '"Three."\n\n'
            "Nothing stirred again.\n\n"
            '"Four."'
        )
        report = _report_for(prose)
        assert report["dialogue_unknown_rate"] == pytest.approx(0.75)
        assert report["quality"] == "degraded"

    def test_empty_report_is_ok(self):
        report = compile_report([], CastingTable())
        assert report["dialogue_unknown_rate"] == 0.0
        assert report["quality"] == "ok"


# ---------------------------------------------------------------------------
# PH-B-003 — default TTS normalization creates phantom cast members
# ---------------------------------------------------------------------------

class TestHonorificsSurviveNormalization:
    """The target corpus is honorific-heavy classic literature."""

    @pytest.mark.parametrize(
        "raw,surname",
        [
            ('"Elementary," said Mr. Holmes.', "Holmes"),
            ('"Obviously," said Dr. Watson.', "Watson"),
            ('"Indeed," said Prof. Lindqvist.', "Lindqvist"),
            ('"Quite so," said Mrs. Hudson.', "Hudson"),
        ],
    )
    def test_speaker_identical_with_and_without_normalize_text(self, raw, surname):
        raw_speaker = _dialogue_speakers(raw)[0]
        normalized_speaker = _dialogue_speakers(normalize(raw))[0]

        # The honorific alone is never a person.
        for bad in ("Mister", "Missus", "Doctor", "Professor", "Mr", "Dr", "Prof"):
            assert raw_speaker != bad, f"raw attribution collapsed to honorific {bad!r}"
            assert normalized_speaker != bad, (
                f"normalized attribution collapsed to honorific {bad!r}"
            )

        assert surname in raw_speaker
        assert surname in normalized_speaker
        assert raw_speaker == normalized_speaker, (
            "normalize_text=True (the default) must not change who is speaking: "
            f"{raw_speaker!r} != {normalized_speaker!r}"
        )

    def test_prof_is_recognized_before_normalization(self):
        """A second, independent gap: the title list never covered Prof."""
        assert _dialogue_speakers('"Indeed," said Prof. Lindqvist.')[0] != "Prof"

    def test_title_table_is_one_source_of_truth(self):
        """name_titles must cover every abbreviation the TTS normalizer expands."""
        from audiobooker.nlp.normalizer import TITLE_EXPANSIONS

        profile = get_profile("en")
        fragment = profile.name_pattern_fragment()
        for abbrev, expansion in TITLE_EXPANSIONS.items():
            assert abbrev.replace(".", r"\.") in fragment, (
                f"{abbrev!r} is expanded by the TTS normalizer but is not a name title"
            )
            assert expansion in fragment, (
                f"{expansion!r} is what the TTS normalizer writes but is not a name title"
            )

    def test_honorific_speaker_does_not_split_the_cast(self):
        """One character, not two, across a normalized and un-normalized pass."""
        raw = '"Elementary," said Mr. Holmes.\n\nHe lit his pipe.\n\n"Obviously," said Dr. Watson.'
        keys_raw = {CastingTable.normalize_key(s) for s in _dialogue_speakers(raw)}
        keys_norm = {CastingTable.normalize_key(s) for s in _dialogue_speakers(normalize(raw))}
        assert keys_raw == keys_norm
        assert len(keys_raw) == 2


# ---------------------------------------------------------------------------
# PH-B-004 — re.IGNORECASE manufactures speakers
# ---------------------------------------------------------------------------

class TestIgnorecasePhantomSpeakers:

    @pytest.mark.parametrize(
        "prose,phantom",
        [
            ('"Hello?" asked nobody in particular.', "Nobody"),
            ('"Listen," said something in the dark.', "Something"),
            ('"Quiet now," said nothing at all.', "Nothing"),
            ('"Wait," said someone behind the door.', "Someone"),
        ],
    )
    def test_lowercase_words_are_not_speakers(self, prose, phantom):
        speaker = _dialogue_speakers(prose)[0]
        assert speaker != phantom, (
            f"{phantom!r} was manufactured from a lowercase word and ACCEPTED, "
            "which also lowers the unknown rate"
        )
        assert speaker == "unknown"

    def test_real_capitalized_names_still_attribute(self):
        assert _dialogue_speakers('"Hello!" said Alice cheerfully.')[0] == "Alice"
        assert _dialogue_speakers('"Hello!" Alice said.')[0] == "Alice"

    def test_verb_case_insensitivity_is_preserved(self):
        """IGNORECASE was there for the VERB alternation — that must still work."""
        assert _dialogue_speakers('"Hello!" SAID Alice.')[0] == "Alice"
        assert _dialogue_speakers('"Hello!" Said Alice.')[0] == "Alice"

    def test_definite_article_attribution_still_works(self):
        assert "Doctor" in _dialogue_speakers('"Hello," said the Doctor.')[0]

    def test_indefinite_pronouns_are_blacklisted(self):
        profile = get_profile("en")
        for word in ("nobody", "somebody", "anybody", "everybody",
                     "someone", "anyone", "everyone", "no one",
                     "nothing", "something", "anything", "everything"):
            assert word in profile.speaker_blacklist, f"{word!r} missing from blacklist"

    def test_phantoms_do_not_deflate_the_unknown_rate(self):
        prose = (
            '"Hello?" asked nobody in particular.\n\n'
            "The hallway swallowed the sound.\n\n"
            '"Listen," said something in the dark.'
        )
        assert _report_for(prose)["dialogue_unknown_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# PH-B-005 — pronunciation overrides destroy attribution
# ---------------------------------------------------------------------------

class TestPronunciationOverridesVsAttribution:

    SRC = '"We go north," said Siobhan, folding the map.'

    def test_unprotected_override_destroys_attribution(self):
        """The defect itself, pinned so a regression is visible."""
        assert _dialogue_speakers(self.SRC)[0] == "Siobhan"
        rewritten = apply_pronunciation_overrides(self.SRC, {"Siobhan": "shiv-AWN"})
        assert _dialogue_speakers(rewritten)[0] == "unknown"

    def test_protected_cast_name_is_refused(self, caplog):
        casting = CastingTable()
        casting.cast("Siobhan", "af_heart")
        with caplog.at_level(logging.ERROR, logger="audiobooker.parser"):
            out = apply_pronunciation_overrides(
                self.SRC,
                {"Siobhan": "shiv-AWN"},
                protected_names=casting.protected_names(),
            )
        assert out == self.SRC, "a cast member's name must not be rewritten at parse time"
        assert _dialogue_speakers(out, casting)[0] == "Siobhan"
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_protection_covers_aliases(self):
        casting = CastingTable()
        character = casting.cast("Siobhan Nolan", "af_heart")
        character.aliases = ["Siobhan"]
        out = apply_pronunciation_overrides(
            self.SRC,
            {"Siobhan": "shiv-AWN"},
            protected_names=casting.protected_names(),
        )
        assert out == self.SRC

    def test_unprotected_terms_still_apply(self):
        text = "The kalimba sounded across the water."
        out = apply_pronunciation_overrides(
            text,
            {"kalimba": "kuh-LIM-buh"},
            protected_names=CastingTable().protected_names(),
        )
        assert "kuh-LIM-buh" in out

    def test_proper_noun_override_warns_even_without_a_casting_table(self, caplog):
        """The lexicon's documented use case is proper nouns; say so loudly."""
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            apply_pronunciation_overrides(self.SRC, {"Siobhan": "shiv-AWN"})
        assert any(
            "attribution" in r.message.lower() for r in caplog.records
        ), [r.message for r in caplog.records]

    def test_protected_names_includes_narrator_and_aliases(self):
        casting = CastingTable()
        char = casting.cast("Alice", "af_heart")
        char.aliases = ["Ally", "Miss A"]
        names = casting.protected_names()
        assert "alice" in names
        assert "ally" in names
        assert "miss a" in names


# ---------------------------------------------------------------------------
# PH-B-006 — chapter detection reads only the first 200 lines
# ---------------------------------------------------------------------------

def _gutenberg_shaped_document(n_chapters: int = 40) -> str:
    """Title page + numbered contents list + boilerplate, then the real body."""
    lines = ["THE GREAT BOOK", "by Somebody", ""]
    for i in range(1, n_chapters + 1):
        lines.append(f"{i}. The Title Of Chapter {i}")
    lines += [f"boilerplate line {i}" for i in range(160)]
    for i in range(1, n_chapters + 1):
        lines += ["", f"Chapter {i}", "", f"Body text for chapter {i}."]
    return "\n".join(lines)


class TestChapterDetectionWholeDocument:

    def test_toc_pattern_does_not_beat_the_real_headings(self):
        doc = _gutenberg_shaped_document()
        pattern = detect_chapter_pattern(doc)
        assert pattern is not None
        assert pattern.match("Chapter 7"), (
            f"the contents list won detection: {pattern.pattern!r}"
        )

    def test_forty_chapter_book_parses_to_forty_chapters(self):
        chapters = split_into_chapters(_gutenberg_shaped_document())
        assert len(chapters) >= 40, (
            f"a 40-chapter book parsed to {len(chapters)} chapters"
        )

    def test_clustered_match_run_is_warned_about(self, caplog):
        """Matches confined to a contents list must not pass silently."""
        lines = ["THE GREAT BOOK", ""]
        for i in range(1, 21):
            lines.append(f"{i}. The Title Of Chapter {i}")
        lines += [f"plain prose line {i}" for i in range(400)]
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            split_into_chapters("\n".join(lines))
        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "a 20-match contents list produced no warning at any level"
        )

    def test_short_document_detection_unchanged(self):
        text = "Chapter 1\nbody\nChapter 2\nbody\nChapter 3\nbody"
        pattern = detect_chapter_pattern(text)
        assert pattern is not None
        assert pattern.match("Chapter 2")

    def test_markdown_h1_detection_unchanged(self):
        text = "# One\n\nbody\n\n# Two\n\nbody\n\n# Three\n\nbody"
        pattern = detect_chapter_pattern(text)
        assert pattern is not None
        assert pattern.match("# Two")


# ---------------------------------------------------------------------------
# PH-B-007 — CastingTable.normalize_key has no Unicode normalization
# ---------------------------------------------------------------------------

NFC_JOSE = unicodedata.normalize("NFC", "José")
NFD_JOSE = unicodedata.normalize("NFD", "José")


class TestNormalizeKeyUnicode:

    def test_fixture_really_is_two_encodings(self):
        assert NFC_JOSE != NFD_JOSE
        assert len(NFC_JOSE) != len(NFD_JOSE)

    def test_nfc_and_nfd_are_the_same_key(self):
        assert CastingTable.normalize_key(NFC_JOSE) == CastingTable.normalize_key(NFD_JOSE)

    def test_get_voice_finds_the_other_encoding(self):
        casting = CastingTable()
        casting.cast(NFC_JOSE, "voice_jose")
        assert casting.get_voice(NFD_JOSE)[0] == "voice_jose", (
            "macOS-authored text and several EPUB toolchains emit NFD routinely"
        )

    def test_interior_nbsp_matches_a_plain_space(self):
        assert (
            CastingTable.normalize_key("María José")
            == CastingTable.normalize_key("María José")
        )

    def test_zero_width_characters_are_stripped(self):
        assert CastingTable.normalize_key("Jo‍se") == "jose"
        assert CastingTable.normalize_key("﻿Jose") == "jose"
        assert CastingTable.normalize_key("Jose​") == "jose"

    def test_language_profile_key_agrees_with_casting_key(self):
        profile = get_profile("en")
        assert profile.normalize_name(NFD_JOSE) == CastingTable.normalize_key(NFC_JOSE)

    def test_from_dict_rekeys_legacy_project_files(self):
        """The fix changes existing project-file keys, so load must migrate."""
        legacy_key = NFD_JOSE.casefold().strip()
        table = CastingTable.from_dict({
            "characters": {
                legacy_key: {"name": NFD_JOSE, "voice": "voice_jose"},
            },
        })
        assert CastingTable.normalize_key(NFC_JOSE) in table.characters
        assert table.get_voice(NFC_JOSE)[0] == "voice_jose"

    def test_from_dict_rekey_is_idempotent(self):
        table = CastingTable()
        table.cast("Alice", "af_heart")
        table.cast(NFC_JOSE, "voice_jose")
        round_tripped = CastingTable.from_dict(table.to_dict())
        assert set(round_tripped.characters) == set(table.characters)

    def test_from_dict_collision_keeps_one_entry_and_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="audiobooker.models"):
            table = CastingTable.from_dict({
                "characters": {
                    NFC_JOSE.casefold(): {"name": NFC_JOSE, "voice": "voice_a"},
                    NFD_JOSE.casefold(): {"name": NFD_JOSE, "voice": "voice_b"},
                },
            })
        assert len(table.characters) == 1
        assert any(r.levelno >= logging.WARNING for r in caplog.records)
