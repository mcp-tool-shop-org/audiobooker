"""
Wave-2 amend regression tests for the casting-nlp domain.

Every test here is written in the SHAPE that the pre-existing fixtures could
not express.  Wave 1 established that the dialogue fixtures are all
blank-line-separated paragraphs, which is exactly the shape in which the
leftmost-wins attribution bug is invisible; and that the two ``audition_voices``
tests wrap the call in ``except (AttributeError, TypeError): pytest.skip(...)``,
which turns a live production crash into an inert skip.  So:

* attribution is exercised with SINGLE-NEWLINE separated multi-speaker dialogue
  (plain .txt / PDF-extracted / many EPUB sources) as well as the blank-line
  shape, to prove the blank-line shape is unaffected;
* ``audition_voices`` is called with a non-empty casting table and NO
  try/except at all;
* dependency drift is simulated by registering a ``voice_soundboard`` package
  that has no ``config`` submodule (the exact traceback from GitHub issue #1)
  and a ``booknlp`` package whose ``__init__`` imports something absent.
"""

from __future__ import annotations

import logging
import sys
import types
from unittest.mock import patch

import pytest

from audiobooker.casting.dialogue import (
    compile_chapter,
    detect_dialogue,
    extract_speaker_from_context,
)
from audiobooker.casting.voice_registry import (
    VoiceBackendIncompatibleError,
    VoiceBackendUnavailableError,
    get_available_voices,
    validate_voices,
)
from audiobooker.casting.voice_suggester import DefaultVoiceRegistry, audition_voices
from audiobooker.language.profile import get_profile
from audiobooker.models import Chapter, CastingTable, Utterance, UtteranceType
from audiobooker.nlp.emotion import EmotionInferencer, _punctuation_emotion
from audiobooker.nlp.normalizer import expand_abbreviations, normalize_numbers


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _compile(text: str, casting: CastingTable | None = None) -> list[Utterance]:
    chapter = Chapter(index=0, title="Amend", raw_text=text)
    return compile_chapter(chapter, casting if casting is not None else CastingTable())


def _dialogue_speakers(utterances: list[Utterance]) -> list[str]:
    return [
        u.speaker for u in utterances
        if u.utterance_type == UtteranceType.DIALOGUE
    ]


# ---------------------------------------------------------------------------
# casting-1-leftmost-attribution
# ---------------------------------------------------------------------------

class TestNearestWinsAttribution:
    """
    dialogue.py: attribution must score candidates by DISTANCE to the quote,
    not by position in ``window_before + ' ' + window_after``.
    """

    def test_second_quote_does_not_inherit_first_quotes_tag(self):
        """'Then Bob replied' owns the second quote — not the earlier 'Alice said'."""
        utts = _compile('Alice said, "Hello." Then Bob replied, "Goodbye."')
        speakers = _dialogue_speakers(utts)
        assert speakers == ["Alice", "Bob"]

    def test_action_beat_blocks_a_previous_speakers_tag(self):
        """
        An intervening action beat ('Bob shook his head.') severs the link to
        the previous quote's trailing tag.  The honest answer is 'unknown' —
        which lets turn-tracking and the >50%-unknown warning actually fire —
        not a confident, silent, wrong 'Alice'.
        """
        utts = _compile('"Get out," Alice whispered. Bob shook his head. "No."')
        dialogue = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        assert dialogue[0].speaker == "Alice"
        assert dialogue[0].emotion == "whisper"
        assert dialogue[1].speaker != "Alice"
        # And the emotion must not leak across either.
        assert dialogue[1].emotion != "whisper"

    def test_single_newline_separated_dialogue_keeps_distinct_speakers(self):
        """
        THE failing shape.  compile_chapter splits paragraphs on BLANK lines
        only, so a plain .txt / PDF-extracted source is ONE paragraph and the
        first speaker used to take every quote in the chapter.
        """
        text = (
            'Alice said, "One."\n'
            'Bob said, "Two."\n'
            'Carol said, "Three."'
        )
        utts = _compile(text)
        assert _dialogue_speakers(utts) == ["Alice", "Bob", "Carol"]

    def test_blank_line_separated_dialogue_is_unaffected(self):
        """The shape the existing fixtures use must keep behaving identically."""
        text = (
            'Alice said, "One."\n\n'
            'Bob said, "Two."\n\n'
            'Carol said, "Three."'
        )
        utts = _compile(text)
        assert _dialogue_speakers(utts) == ["Alice", "Bob", "Carol"]

    def test_same_speaker_continuation_still_carries_over(self):
        """
        '"Hi," Alice said. "How are you?"' is the same speaker continuing.
        Nearest-wins must not over-correct and drop this to unknown.
        """
        utts = _compile('"Hello there," Alice said. "How are you?"')
        assert _dialogue_speakers(utts) == ["Alice", "Alice"]

    def test_trailing_tag_beats_a_distant_leading_tag(self):
        speaker, _ = extract_speaker_from_context(
            'Alice said, "Hello." Then Bob replied, "Goodbye."',
            39, 49,
        )
        assert speaker == "Bob"

    def test_emotion_verb_is_taken_from_the_winning_tag_only(self):
        """
        The emotion search had the identical leftmost-wins flaw: a distant
        'whispered' used to colour an unrelated quote.
        """
        speaker, emotion = extract_speaker_from_context(
            '"Get out," Alice whispered. Bob shook his head. "No."',
            47, 52,
        )
        assert emotion is None
        assert speaker != "Alice"

    def test_classic_shapes_preserved(self):
        assert extract_speaker_from_context('"Hello!" said Alice cheerfully.', 0, 9)[0] == "Alice"
        assert extract_speaker_from_context('Alice said "Hello!" with a smile.', 12, 20)[0] == "Alice"
        assert extract_speaker_from_context('"Watch out!" whispered Bob urgently.', 0, 13) == ("Bob", "whisper")
        assert extract_speaker_from_context('"Hello there."', 0, 14)[0] is None


# ---------------------------------------------------------------------------
# casting-2-audition-crash
# ---------------------------------------------------------------------------

class _StubRegistry:
    def list_voices(self) -> list[str]:
        return ["af_heart", "af_bella", "bm_george", "am_adam", "bf_emma", "af_sarah"]


class TestAuditionVoices:
    """voice_suggester.audition_voices read ``char.voice_id``; the field is ``voice``."""

    def test_audition_with_an_already_cast_character(self):
        """
        NO try/except.  This is the ordinary workflow — auditioning a new voice
        while at least one character is already cast — and it used to raise
        AttributeError straight out of the shipped ``audiobooker audition``
        command.
        """
        casting = CastingTable()
        casting.cast("Alice", "af_heart")

        result = audition_voices(
            "Bob",
            casting,
            ["I will not go quietly.", "You have no idea what you have done."],
            registry=_StubRegistry(),
        )

        assert isinstance(result, list)
        assert result, "audition_voices returned no suggestions"
        for row in result:
            assert set(row) >= {"voice_id", "gender", "style", "sample_text", "score"}

    def test_already_cast_voices_are_deprioritised(self):
        """Proves the already-cast map is actually populated (it was always empty)."""
        casting = CastingTable()
        casting.cast("Alice", "af_heart")
        casting.cast("Carol", "af_bella")

        result = audition_voices("Bob", casting, ["Hello."], registry=_StubRegistry())
        ranked = [row["voice_id"] for row in result]
        assert ranked, "no suggestions returned"
        # Voices already spoken for should not lead the ranking.
        assert ranked[0] not in {"af_heart", "af_bella"}


# ---------------------------------------------------------------------------
# casting-3-import-swallow  (GitHub issue #1)
# ---------------------------------------------------------------------------

def _drifted_voice_soundboard() -> types.ModuleType:
    """A voice_soundboard package that is INSTALLED but has no .config submodule."""
    pkg = types.ModuleType("voice_soundboard")
    pkg.__path__ = []  # a package with nowhere to find submodules
    return pkg


class TestVoiceBackendImportDiagnosis:

    def test_absent_package_says_not_installed(self):
        with patch.dict(sys.modules, {"voice_soundboard": None, "voice_soundboard.config": None}):
            with pytest.raises(VoiceBackendUnavailableError) as exc:
                get_available_voices()
        assert "voice-soundboard" in str(exc.value)
        assert isinstance(exc.value, ImportError)  # back-compatible with old callers

    def test_drifted_submodule_does_not_say_not_installed(self):
        """
        The reporter's traceback was ModuleNotFoundError for the SUBMODULE
        'voice_soundboard.config'.  ModuleNotFoundError subclasses ImportError,
        so the old handler told a user who already HAD the package to install it.
        """
        with patch.dict(sys.modules, {"voice_soundboard": _drifted_voice_soundboard()}):
            sys.modules.pop("voice_soundboard.config", None)
            with pytest.raises(VoiceBackendIncompatibleError) as exc:
                get_available_voices()

        message = str(exc.value)
        assert "voice_soundboard.config" in message
        assert "pip install voice-soundboard" not in message, (
            "advice is a no-op for a user who already has the package"
        )
        assert exc.value.__cause__ is not None, "original cause was dropped"
        assert exc.value.code != VoiceBackendUnavailableError("x").code

    def test_validate_voices_does_not_silently_pass_on_drift(self):
        """
        validate_voices returned [] on any ImportError, so an unknown voice id
        validated clean against a broken backend.
        """
        with patch.dict(sys.modules, {"voice_soundboard": _drifted_voice_soundboard()}):
            sys.modules.pop("voice_soundboard.config", None)
            with pytest.raises(VoiceBackendIncompatibleError):
                validate_voices({"definitely_not_a_real_voice"})

    def test_validate_voices_still_skips_when_genuinely_absent(self, caplog):
        with patch.dict(sys.modules, {"voice_soundboard": None, "voice_soundboard.config": None}):
            with caplog.at_level(logging.WARNING, logger="audiobooker.casting"):
                assert validate_voices({"anything"}) == []
        assert any("not installed" in r.message for r in caplog.records)

    def test_default_registry_warns_loudly_on_drift(self, caplog):
        """
        DefaultVoiceRegistry fell back to a frozen curated table on ANY
        ImportError, and downstream suggestions then recommended voices the
        real backend may not have.
        """
        registry = DefaultVoiceRegistry()
        with patch.dict(sys.modules, {"voice_soundboard": _drifted_voice_soundboard()}):
            sys.modules.pop("voice_soundboard.config", None)
            with caplog.at_level(logging.WARNING, logger="audiobooker.casting"):
                voices = registry.list_voices()

        assert voices, "registry must still return something usable"
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "drift was swallowed silently"
        assert any("voice_soundboard.config" in r.getMessage() for r in warnings)

    def test_booknlp_check_distinguishes_broken_install(self, tmp_path, caplog):
        """
        _check_booknlp_available discarded the exception entirely, so a BROKEN
        booknlp install was reported as absent and the user told to pip install
        a package they already had.
        """
        from audiobooker.nlp import booknlp_adapter

        pkg = tmp_path / "booknlp"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "import audiobooker_missing_dep_xyz\n", encoding="utf-8"
        )

        with patch.dict(sys.modules, {}):
            sys.modules.pop("booknlp", None)
            sys.path.insert(0, str(tmp_path))
            try:
                import importlib
                importlib.invalidate_caches()
                with caplog.at_level(logging.WARNING, logger="audiobooker.nlp"):
                    assert booknlp_adapter._check_booknlp_available() is False
            finally:
                sys.path.remove(str(tmp_path))
                sys.modules.pop("booknlp", None)
                import importlib
                importlib.invalidate_caches()

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "a broken booknlp install was swallowed silently"
        joined = " ".join(r.getMessage() for r in warnings)
        assert "audiobooker_missing_dep_xyz" in joined


# ---------------------------------------------------------------------------
# casting-4-validate-gate
# ---------------------------------------------------------------------------

class TestValidateVoicesGate:
    """
    The casting-side half of the render gate: validate_voices must be correct
    and callable with a supplied catalog, and its skip path must be loud.
    Wiring the call site lives in project.py / renderer/ — not this domain.
    """

    def test_missing_ids_are_reported(self):
        assert validate_voices({"af_heart", "nope"}, {"af_heart"}) == ["nope"]

    def test_supplied_catalog_never_touches_the_backend(self):
        with patch.dict(sys.modules, {"voice_soundboard": None, "voice_soundboard.config": None}):
            assert validate_voices({"af_heart"}, {"af_heart"}) == []


# ---------------------------------------------------------------------------
# casting-5-emdash
# ---------------------------------------------------------------------------

class TestRayaDialogue:
    """
    Detection is driven purely by open/close quote PAIRS; a dash that OPENS a
    line of speech was never detected.  es.py documents the convention in a
    comment while shipping no marker for it.
    """

    def test_line_initial_raya_is_dialogue_spanish(self):
        text = "—¿Adónde vas? preguntó Ana.\n—A casa, dijo Luis."
        segments = detect_dialogue(text, profile=get_profile("es"))
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) == 2, segments
        assert "Adónde vas" in dialogue[0][0]
        assert "A casa" in dialogue[1][0]

    def test_raya_on_the_final_line_is_detected(self):
        """
        pt models the raya as the quote pair ('—', '\\n'), so the LAST line of
        a paragraph — which has no trailing newline — was never matched.
        """
        text = "—Aonde vais? perguntou Ana.\n—Para casa, disse Luis."
        segments = detect_dialogue(text, profile=get_profile("pt"))
        dialogue = [s for s in segments if s[1]]
        assert len(dialogue) == 2, segments
        assert "Para casa" in dialogue[1][0]

    def test_raya_speakers_are_attributed(self):
        chapter = Chapter(
            index=0,
            title="Capitulo",
            raw_text="—¿Adónde vas? preguntó Ana.\n—A casa, dijo Luis.",
        )
        utts = compile_chapter(chapter, CastingTable(), profile=get_profile("es"))
        speakers = _dialogue_speakers(utts)
        assert speakers == ["Ana", "Luis"], [(u.speaker, u.text) for u in utts]

    def test_english_is_not_given_the_raya_rule(self):
        """English does not use the raya; enabling it there would be a regression."""
        segments = detect_dialogue("—I was going to say— he began.")
        assert not [s for s in segments if s[1]]

    def test_zero_dialogue_with_markers_present_warns(self, caplog):
        """
        A chapter that yields no dialogue at all while the text is full of
        dialogue-ish markers is the symptom that would have surfaced this.
        """
        chapter = Chapter(
            index=3,
            title="Capitulo",
            raw_text="—Where are you going? asked Ana.\n—Home, said Luis.",
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.casting.dialogue"):
            compile_chapter(chapter, CastingTable())
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("no dialogue" in w.lower() for w in warnings), warnings

    def test_no_spurious_warning_for_plain_narration(self, caplog):
        chapter = Chapter(index=0, title="t", raw_text="The room was empty and cold.")
        with caplog.at_level(logging.WARNING, logger="audiobooker.casting.dialogue"):
            compile_chapter(chapter, CastingTable())
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ---------------------------------------------------------------------------
# casting-6-emotion-position
# ---------------------------------------------------------------------------

class TestEmotionContextPosition:
    """
    emotion.py located context with chapter_text.find(utt.text) — the FIRST
    occurrence — though Utterance.start_pos is already populated.  Every
    repeated short line ('No.', 'Yes.') inferred emotion from the wrong passage.
    """

    def test_repeated_line_uses_its_own_position(self):
        # The context window is 200 chars each side, so the two copies of the
        # repeated line are separated by more than that. Each sits next to a
        # different emotional passage; only position can tell them apart.
        padding = "The road went on past the mile markers. " * 12  # ~480 chars
        chapter_text = (
            "She was furious and enraged and absolutely livid. "
            'He said, "No." '
            + padding +
            "It was a joyful, delighted, cheerful morning. "
            'She said, "No." '
        )
        first = chapter_text.index('"No."') + 1
        second = chapter_text.index('"No."', first + 1) + 1

        utt_a = Utterance(speaker="He", text="No.", start_pos=first, end_pos=first + 3)
        utt_b = Utterance(speaker="She", text="No.", start_pos=second, end_pos=second + 3)

        inf = EmotionInferencer(mode="rule", threshold=0.5)
        inf.apply_to_utterances([utt_a, utt_b], chapter_text=chapter_text)

        assert utt_a.emotion != utt_b.emotion, (
            "both repeats read the SAME (first) passage for context"
        )

    def test_pause_and_direction_utterances_are_skipped(self):
        chapter_text = "She was furious and enraged and absolutely livid."
        pause = Utterance(
            speaker="narrator",
            text="pause:500ms",
            utterance_type=UtteranceType.PAUSE,
        )
        direction = Utterance(
            speaker="narrator",
            text="a door slams",
            utterance_type=UtteranceType.DIRECTION,
        )
        inf = EmotionInferencer(mode="rule", threshold=0.5)
        inf.apply_to_utterances([pause, direction], chapter_text=chapter_text)
        assert pause.emotion is None
        assert direction.emotion is None


# ---------------------------------------------------------------------------
# casting-7-punctuation-threshold
# ---------------------------------------------------------------------------

class TestPunctuationCuesCanFire:
    """
    Punctuation cues maxed out at 0.6 while every shipped preset threshold is
    >= 0.65, so the documented inference source could never fire.
    """

    def test_strong_cues_reach_the_lowest_shipped_preset(self):
        from audiobooker.nlp.emotion import _EMOTION_PRESETS

        lowest = min(p.threshold for p in _EMOTION_PRESETS.values())
        shout = _punctuation_emotion("Stop it!!")
        assert shout is not None
        assert shout.confidence >= lowest, (
            f"strongest punctuation cue {shout.confidence} < lowest preset {lowest}"
        )

    def test_dramatic_preset_actually_tags_a_shout(self):
        inf = EmotionInferencer(mode="rule", preset="dramatic")
        result = inf.infer("Get out of my house!!")
        assert result.source == "punctuation"
        assert result.label != "neutral"

    def test_weak_ellipsis_cue_stays_weak(self):
        result = _punctuation_emotion("Well... maybe.")
        assert result is not None
        assert result.confidence < 0.65


# ---------------------------------------------------------------------------
# casting-8 / casting-9 — normalizer
# ---------------------------------------------------------------------------

class TestNormalizerYears:
    """normalize_numbers mangled 19th-century years and orphaned decade suffixes."""

    def test_nineteenth_century_year(self):
        assert normalize_numbers("In 1812 the war began.") == (
            "In eighteen twelve the war began."
        )

    def test_decade_suffix(self):
        assert normalize_numbers("The 1980s were loud.") == (
            "The nineteen eighties were loud."
        )

    def test_twentieth_century_year_unchanged(self):
        assert normalize_numbers("In 1984") == "In nineteen eighty-four"

    def test_two_thousands_unchanged(self):
        assert normalize_numbers("In 2024") == "In twenty twenty-four"


class TestNormalizerAbbreviations:
    """expand_abbreviations deleted the sentence-final period after any abbreviation."""

    def test_sentence_final_period_survives(self):
        assert expand_abbreviations("He worked at Acme Inc.").endswith(
            "Incorporated."
        )

    def test_mid_sentence_abbreviation_still_expands(self):
        assert expand_abbreviations("Dr. Watson looked up.") == "Doctor Watson looked up."

    def test_ambiguous_street_abbreviation_is_left_alone(self):
        """'Baker St.' is Street, not Saint — and the period is the sentence's."""
        result = expand_abbreviations("He lived on Baker St.")
        assert "Saint" not in result
        assert result.endswith(".")

    def test_etcetera_keeps_its_stop(self):
        assert expand_abbreviations("Apples, pears, etc.").endswith("etcetera.")
