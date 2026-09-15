"""Attribution confidence, provenance, speaker merge, raya and split quotes.

FEAT-CAST-001 / -003 / -004 / -006 (dogfood-swarm Phase 7, F1).

The keystone defect these tests pin down: **the product could not tell the
truth about its own output.** ``_infer_next_speaker`` fills every attribution
gap by alternation and each guess was recorded as a SUCCESSFUL attribution, so
guessing LOWERED the unknown rate. Measured before the fix, on the eight-line
Petrov/Kessler passage below, six of eight dialogue lines were pure alternation
guesses and ``compile_report`` still returned::

    unknown_rate = 0.0   dialogue_unknown_rate = 0.0   quality = 'ok'

The quality signal improved as attribution degraded. Confidence + provenance
exist so a guess is visibly a guess, and ``dialogue_unverified_rate`` exists so
the number cannot be gamed by guessing harder: an alternation guess moves a
line from ``unknown`` to ``low_confidence`` and the combined rate does not
move.
"""

from __future__ import annotations

import pytest

from audiobooker.casting.dialogue import (
    LOW_CONFIDENCE_THRESHOLD,
    compile_chapter,
    compile_report,
    extract_speaker_from_context,
    extract_speaker_with_confidence,
)
from audiobooker.language import get_profile
from audiobooker.models import ATTRIBUTION_SOURCES, CastingTable, Chapter, Utterance

RAYA = "—"


def _compile(text: str, lang: str = "en", casting: CastingTable | None = None):
    casting = casting if casting is not None else CastingTable()
    chapter = Chapter(index=0, title="Ch", raw_text=text)
    chapter.utterances = compile_chapter(
        chapter, casting, profile=get_profile(lang),
    )
    return chapter


def _dialogue(chapter: Chapter) -> list[Utterance]:
    return [u for u in chapter.utterances if u.utterance_type.value == "dialogue"]


# Real prose shape: two speakers, only the first two lines carry a tag. This is
# the ordinary Hemingway-style exchange every novel contains, and it is where
# the old metric read 'ok' while 75% of the attributions were manufactured.
LEDGER_SCENE = (
    '"You brought the ledger," Petrov said.\n\n'
    '"I brought what was left of it," Kessler answered.\n\n'
    '"Then read me the second column."\n\n'
    '"It is not a column. It is a list of names."\n\n'
    '"Read it."\n\n'
    '"Yours is on it."\n\n'
    'The lamp guttered and neither of them moved.\n\n'
    '"That is not possible."\n\n'
    '"It is the third name."\n'
)


# ---------------------------------------------------------------------------
# FEAT-CAST-001 — confidence and provenance on every attribution
# ---------------------------------------------------------------------------

class TestUtteranceCarriesProvenance:
    """The signal already existed in ``_collect_candidates`` as a tier and was
    thrown away by ``extract_speaker_from_context`` after sorting."""

    def test_utterance_defaults_are_none_so_every_old_call_site_still_works(self):
        utt = Utterance(speaker="Alice", text="Hello")
        assert utt.attribution_source is None
        assert utt.confidence is None

    def test_a_directly_attached_tag_is_high_confidence(self):
        chapter = _compile('"Hello there," said Alice.')
        first = _dialogue(chapter)[0]
        assert first.speaker == "Alice"
        assert first.attribution_source == "tag"
        assert first.confidence > LOW_CONFIDENCE_THRESHOLD

    def test_an_alternation_guess_is_turn_and_low_confidence(self):
        """A guess must be visibly a guess. This is the whole point."""
        chapter = _compile(LEDGER_SCENE)
        guessed = [u for u in _dialogue(chapter) if u.attribution_source == "turn"]
        assert len(guessed) == 6, [
            (u.speaker, u.attribution_source, u.text[:30]) for u in _dialogue(chapter)
        ]
        for utt in guessed:
            assert utt.confidence < LOW_CONFIDENCE_THRESHOLD
            assert utt.speaker != "unknown"

    def test_an_inline_override_is_user_authored_and_certain(self):
        chapter = _compile('[Alice] "Whatever you say."')
        first = _dialogue(chapter)[0]
        assert first.speaker == "Alice"
        assert first.attribution_source == "inline"
        assert first.confidence == 1.0

    def test_unknown_carries_zero_confidence_not_none(self):
        chapter = _compile('"Nobody here is named."')
        first = _dialogue(chapter)[0]
        assert first.speaker == "unknown"
        assert first.confidence == 0.0

    def test_narration_is_not_an_attribution_and_stays_unannotated(self):
        chapter = _compile("The lamp guttered and neither of them moved.")
        narration = chapter.utterances[0]
        assert narration.speaker == "narrator"
        assert narration.attribution_source is None
        assert narration.confidence is None

    @pytest.mark.parametrize("source", sorted(ATTRIBUTION_SOURCES))
    def test_every_declared_source_is_accepted(self, source):
        Utterance(speaker="Alice", text="x", attribution_source=source)

    def test_an_undeclared_source_is_refused(self):
        with pytest.raises(ValueError, match="attribution_source"):
            Utterance(speaker="Alice", text="x", attribution_source="vibes")

    @pytest.mark.parametrize("bad", [-0.1, 1.5, "high", True])
    def test_confidence_is_range_checked_like_intensity(self, bad):
        with pytest.raises(ValueError, match="confidence"):
            Utterance(speaker="Alice", text="x", confidence=bad)


class TestProvenanceSurvivesSerialization:
    """``Utterance`` is widely serialized — every persisted project must still
    load, and a project written before this feature must round-trip byte-for-
    byte unchanged."""

    def test_legacy_payload_without_the_new_keys_still_loads(self):
        legacy = {
            "id": "abc",
            "speaker": "Alice",
            "text": "Hello",
            "type": "dialogue",
            "emotion": None,
            "chapter_index": 0,
            "line_index": 3,
            "start_pos": 0,
            "end_pos": 5,
        }
        utt = Utterance.from_dict(legacy)
        assert utt.attribution_source is None
        assert utt.confidence is None

    def test_an_unannotated_utterance_serializes_exactly_as_before(self):
        utt = Utterance(speaker="Alice", text="Hello")
        data = utt.to_dict()
        assert "attribution_source" not in data
        assert "confidence" not in data

    def test_round_trip_preserves_source_and_confidence(self):
        utt = Utterance(
            speaker="Alice", text="Hello",
            attribution_source="turn", confidence=0.25,
        )
        again = Utterance.from_dict(utt.to_dict())
        assert again.attribution_source == "turn"
        assert again.confidence == 0.25

    def test_zero_confidence_round_trips_and_is_not_dropped_as_falsy(self):
        utt = Utterance(speaker="unknown", text="Hello", confidence=0.0)
        data = utt.to_dict()
        assert data["confidence"] == 0.0
        assert Utterance.from_dict(data).confidence == 0.0


class TestExtractorExposesTheTierItAlreadyComputed:

    def test_the_two_tuple_signature_is_unchanged_for_existing_callers(self):
        assert extract_speaker_from_context(
            '"Watch out!" whispered Bob urgently.', 0, 13,
        ) == ("Bob", "whisper")

    def test_the_confidence_variant_reports_tag_provenance(self):
        speaker, emotion, source, confidence = extract_speaker_with_confidence(
            '"Watch out!" whispered Bob urgently.', 0, 13,
        )
        assert (speaker, emotion, source) == ("Bob", "whisper", "tag")
        assert confidence > LOW_CONFIDENCE_THRESHOLD

    def test_a_cross_line_tag_scores_lower_than_an_attached_one(self):
        """Tier 2 — the tag is on a DIFFERENT line — is a weaker claim than a
        tag welded to the quote, and the number must say so."""
        attached = extract_speaker_with_confidence(
            '"Hello there," said Alice.', 0, 14,
        )
        cross_line = extract_speaker_with_confidence(
            '"Hello there,"\nsaid Alice.', 0, 14,
        )
        assert attached[0] == cross_line[0] == "Alice"
        assert cross_line[3] < attached[3]
        assert cross_line[3] < LOW_CONFIDENCE_THRESHOLD < attached[3]

    def test_no_attribution_yields_no_source(self):
        assert extract_speaker_with_confidence('"Hello there."', 0, 14) == (
            None, None, None, 0.0,
        )


class TestTheMetricIsHonest:
    """Right now a manufactured guess IMPROVES the number."""

    def test_the_published_unknown_rate_keys_keep_their_meaning(self):
        report = compile_report([_compile(LEDGER_SCENE)], CastingTable())
        # Unchanged: these are asserted on elsewhere in the suite.
        assert report["unknown_rate"] == 0.0
        assert report["dialogue_unknown_rate"] == 0.0
        assert report["quality"] == "ok"

    def test_low_confidence_lines_are_listed_beside_top_unattributed(self):
        report = compile_report([_compile(LEDGER_SCENE)], CastingTable())
        assert report["top_unattributed"] == []
        assert report["low_confidence"], "six of eight lines were guessed"
        entry = report["low_confidence"][0]
        assert set(entry) >= {
            "text", "speaker", "confidence", "attribution_source",
            "chapter_index", "line_index", "context",
        }
        assert entry["attribution_source"] == "turn"

    def test_the_count_is_surfaced_not_only_the_sample(self):
        report = compile_report([_compile(LEDGER_SCENE)], CastingTable())
        assert report["total_low_confidence"] == 6
        assert report["dialogue_low_confidence_rate"] == pytest.approx(6 / 8)

    def test_guessing_harder_cannot_improve_the_unverified_rate(self):
        """The anti-gaming property, stated as an equality rather than a hope.

        Every one of the six guessed lines would be ``unknown`` if turn-
        tracking were switched off, so the unverified rate must equal the
        unknown rate that honest abstention would have produced."""
        report = compile_report([_compile(LEDGER_SCENE)], CastingTable())
        guessed_or_unknown = (
            report["total_low_confidence"] + report["total_dialogue_unknown"]
        )
        assert guessed_or_unknown == 6
        assert report["dialogue_unverified_rate"] == pytest.approx(6 / 8)
        # The two verdicts diverge, which is the entire point: the published
        # one still says the chapter is fine.
        #
        # attribution_quality reads "failed", not "degraded": the coordinator
        # gave it its own thresholds (UNVERIFIED_WARN_RATE 0.30 /
        # UNVERIFIED_FAIL_RATE 0.60) rather than inheriting the unknown-rate
        # ones. A guess is worse for the user than an admission — an unknown
        # line is visible in the report and the review export, a guess is
        # not — so unverified has to fail earlier than unknown. Three
        # quarters guesswork is not degraded, it is unusable, and this
        # passage measured 52% hand-scored speaker accuracy.
        assert report["quality"] == "ok"
        assert report["attribution_quality"] == "failed"

    def test_a_genuinely_well_attributed_chapter_still_reads_clean(self):
        text = (
            '"The council will decide," King Aldric declared.\n\n'
            '"The Shadow advances," said Lady Morgaine.\n\n'
            '"I have seen it," Theron muttered.\n'
        )
        report = compile_report([_compile(text)], CastingTable())
        assert report["total_low_confidence"] == 0
        assert report["dialogue_unverified_rate"] == 0.0
        assert report["attribution_quality"] == "ok"

    def test_source_distribution_is_reported(self):
        report = compile_report([_compile(LEDGER_SCENE)], CastingTable())
        assert report["attribution_source_distribution"] == {"tag": 2, "turn": 6}

    def test_an_empty_book_does_not_divide_by_zero(self):
        report = compile_report([], CastingTable())
        assert report["total_low_confidence"] == 0
        assert report["dialogue_unverified_rate"] == 0.0
        assert report["attribution_quality"] == "ok"
        assert report["low_confidence"] == []


# ---------------------------------------------------------------------------
# FEAT-CAST-003 — speaker merge
# ---------------------------------------------------------------------------

CLINIC_SCENE = (
    '"The cultures are clean," Dr. Merrin said, setting down the tray.\n\n'
    '"You are certain?" the technician asked.\n\n'
    '"Merrin is never certain," said Halloway from the doorway.\n\n'
    '"I am certain enough," Merrin replied.\n\n'
    'The Doctor turned back to the bench.\n\n'
    '"Log it," the Doctor said.\n'
)


class TestAttributionCanonicalizesThroughTheAliasTable:
    """Audio was already right because ``get_voice`` resolves aliases. The
    damage was a permanently dirty uncast warning and split report rows."""

    def test_an_alias_attributes_to_the_primary_name(self):
        casting = CastingTable()
        casting.cast("Merrin", "voice_a")
        casting.characters[casting.normalize_key("Merrin")].aliases = [
            "Dr. Merrin", "the Doctor",
        ]
        chapter = _compile(CLINIC_SCENE, casting=casting)
        speakers = {u.speaker for u in _dialogue(chapter)}
        assert "Dr. Merrin" not in speakers
        assert "The Doctor" not in speakers
        assert "Merrin" in speakers

    def test_line_counts_stop_splitting_across_the_same_character(self):
        casting = CastingTable()
        casting.cast("Merrin", "voice_a")
        casting.characters[casting.normalize_key("Merrin")].aliases = [
            "Dr. Merrin", "the Doctor",
        ]
        chapter = _compile(CLINIC_SCENE, casting=casting)
        report = compile_report([chapter], casting)
        assert report["speaker_line_counts"].get("merrin") == 3

    def test_a_name_that_is_nobody_s_alias_is_left_alone(self):
        casting = CastingTable()
        casting.cast("Merrin", "voice_a")
        chapter = _compile(CLINIC_SCENE, casting=casting)
        assert "Halloway" in {u.speaker for u in _dialogue(chapter)}


class TestMergesAmongConfirmedSpeakersAreProposed:
    """``_collect_alias_candidates`` skipped any descriptor that is already a
    confirmed speaker — which is exactly the case that matters."""

    @staticmethod
    def _cast_three() -> CastingTable:
        casting = CastingTable()
        casting.cast("Dr. Merrin", "voice_a")
        casting.cast("Merrin", "voice_b")
        casting.cast("The Doctor", "voice_c")
        casting.cast("Halloway", "voice_d")
        return casting

    def test_title_plus_surname_merges_into_the_bare_surname(self):
        from audiobooker.nlp.speaker_resolver import suggest_aliases

        casting = self._cast_three()
        chapter = Chapter(index=0, title="Ch", raw_text=CLINIC_SCENE)
        proposals = suggest_aliases([chapter], casting, use_booknlp=False)
        pairs = {(p.candidate, p.speaker) for p in proposals}
        assert ("Dr. Merrin", "Merrin") in pairs, pairs

    def test_the_merge_proposal_says_why_it_fired(self):
        from audiobooker.nlp.speaker_resolver import suggest_aliases

        casting = self._cast_three()
        chapter = Chapter(index=0, title="Ch", raw_text=CLINIC_SCENE)
        merge = next(
            p for p in suggest_aliases([chapter], casting, use_booknlp=False)
            if p.candidate == "Dr. Merrin"
        )
        assert merge.source == "name-overlap"

    def test_a_the_x_descriptor_that_became_a_cast_slot_is_still_proposed(self):
        from audiobooker.nlp.speaker_resolver import suggest_aliases

        casting = self._cast_three()
        chapter = Chapter(index=0, title="Ch", raw_text=CLINIC_SCENE)
        proposals = suggest_aliases([chapter], casting, use_booknlp=False)
        assert any(p.candidate == "The Doctor" for p in proposals), [
            (p.candidate, p.speaker, p.source) for p in proposals
        ]

    def test_two_genuinely_different_people_are_not_merged(self):
        from audiobooker.nlp.speaker_resolver import suggest_aliases

        casting = self._cast_three()
        chapter = Chapter(index=0, title="Ch", raw_text=CLINIC_SCENE)
        proposals = suggest_aliases([chapter], casting, use_booknlp=False)
        assert not any(p.candidate == "Halloway" for p in proposals), [
            (p.candidate, p.speaker, p.source) for p in proposals
        ]

    def test_nothing_is_proposed_as_an_alias_of_itself(self):
        from audiobooker.nlp.speaker_resolver import suggest_aliases

        casting = self._cast_three()
        chapter = Chapter(index=0, title="Ch", raw_text=CLINIC_SCENE)
        for proposal in suggest_aliases([chapter], casting, use_booknlp=False):
            assert proposal.candidate.casefold() != proposal.speaker.casefold()

    def test_proposals_never_mutate_the_cast(self):
        from audiobooker.nlp.speaker_resolver import suggest_aliases

        casting = self._cast_three()
        before = sorted(casting.characters)
        chapter = Chapter(index=0, title="Ch", raw_text=CLINIC_SCENE)
        suggest_aliases([chapter], casting, use_booknlp=False)
        assert sorted(casting.characters) == before
        assert all(not c.aliases for c in casting.characters.values())


class TestTheMergeCanActuallyBeApplied:
    """A proposal nobody can act on is not a fix. ``speakers merge`` lives in
    cli.py (another agent's file this wave), so the operation itself belongs
    on the CastingTable where both the CLI and the resolver can reach it."""

    @staticmethod
    def _cast_pair() -> CastingTable:
        casting = CastingTable()
        casting.cast("Dr. Merrin", "voice_a")
        casting.cast("Merrin", "voice_b")
        casting.characters[casting.normalize_key("Dr. Merrin")].line_count = 4
        casting.characters[casting.normalize_key("Merrin")].line_count = 7
        return casting

    def test_the_source_slot_disappears(self):
        casting = self._cast_pair()
        casting.merge_speaker("Dr. Merrin", "Merrin")
        assert casting.normalize_key("Dr. Merrin") not in casting.characters
        assert casting.normalize_key("Merrin") in casting.characters

    def test_the_source_name_becomes_an_alias_so_attribution_folds(self):
        casting = self._cast_pair()
        merged = casting.merge_speaker("Dr. Merrin", "Merrin")
        assert casting.resolve_alias("Dr. Merrin") is merged
        chapter = _compile(CLINIC_SCENE, casting=casting)
        assert "Dr. Merrin" not in {u.speaker for u in _dialogue(chapter)}

    def test_line_counts_add_up_rather_than_being_lost(self):
        casting = self._cast_pair()
        merged = casting.merge_speaker("Dr. Merrin", "Merrin")
        assert merged.line_count == 11

    def test_the_source_s_own_aliases_come_along(self):
        casting = self._cast_pair()
        casting.characters[casting.normalize_key("Dr. Merrin")].aliases = ["Doc"]
        merged = casting.merge_speaker("Dr. Merrin", "Merrin")
        assert casting.resolve_alias("Doc") is merged

    def test_merging_a_slot_into_itself_is_refused(self):
        casting = self._cast_pair()
        with pytest.raises(ValueError, match="itself"):
            casting.merge_speaker("Merrin", "merrin")

    def test_an_unknown_slot_is_refused_by_name(self):
        casting = self._cast_pair()
        with pytest.raises(ValueError, match="Halloway"):
            casting.merge_speaker("Halloway", "Merrin")

    def test_the_narrator_cannot_be_merged_away(self):
        casting = self._cast_pair()
        casting.cast("narrator", "voice_n")
        with pytest.raises(ValueError, match="narrator"):
            casting.merge_speaker("narrator", "Merrin")

    def test_the_merge_survives_a_project_round_trip(self):
        casting = self._cast_pair()
        casting.merge_speaker("Dr. Merrin", "Merrin")
        again = CastingTable.from_dict(casting.to_dict())
        assert again.resolve_alias("Dr. Merrin") is not None
        assert again.normalize_key("Dr. Merrin") not in again.characters


# ---------------------------------------------------------------------------
# FEAT-CAST-006 — Spanish/Portuguese raya DETECTION mid-paragraph
# ---------------------------------------------------------------------------

class TestRayaIsDetectedMidParagraph:
    """``line_open_re`` anchored the raya to line start, so mid-paragraph
    speech became NARRATION — invisible to every quality metric, because
    narration counts as correctly attributed and pulls the rate DOWN."""

    def test_speech_after_an_action_beat_on_the_same_line_is_dialogue(self):
        chapter = _compile(
            "Ella dejó la pluma. —La balanza está mal —dijo Marta.\n",
            "es",
        )
        dialogue = _dialogue(chapter)
        assert [u.text for u in dialogue] == ["La balanza está mal"]
        assert dialogue[0].speaker == "Marta"

    def test_the_action_beat_itself_stays_narration(self):
        chapter = _compile(
            "Ella dejó la pluma. —La balanza está mal —dijo Marta.\n",
            "es",
        )
        narration = [u.text for u in chapter.utterances
                     if u.utterance_type.value == "narration"]
        assert "Ella dejó la pluma." in narration[0]

    def test_the_line_initial_case_is_not_regressed(self):
        chapter = _compile(
            "—La balanza está mal —dijo Marta.\n", "es",
        )
        assert [u.speaker for u in _dialogue(chapter)] == ["Marta"]

    def test_a_tag_raya_after_a_full_stop_is_not_a_new_speech_opener(self):
        """``—Vete. —dijo ella.`` — some editions close the speech with a
        period before the attributive raya. That raya opens no speech."""
        chapter = _compile("—Vete. —dijo ella.\n", "es")
        assert [u.text for u in _dialogue(chapter)] == ["Vete."]

    def test_the_closing_raya_of_an_inline_tag_is_not_a_speech_opener(self):
        chapter = _compile(
            "—Kessler —dijo Petrov con cuidado—, no lo sé.\n", "es",
        )
        assert not any(u.text.lstrip().startswith(",") for u in _dialogue(chapter))

    def test_portuguese_gets_the_same_treatment(self):
        chapter = _compile(
            "Ela pousou a pena. —A balança está errada —disse Marta.\n",
            "pt",
        )
        assert [u.text for u in _dialogue(chapter)] == ["A balança está errada"]

    def test_english_em_dashes_are_still_not_speech_markers(self):
        """An em dash mid-sentence in English is an aside, never a raya."""
        chapter = _compile(
            "She set the pen down. — an odd gesture — and said nothing.",
        )
        assert _dialogue(chapter) == []

    def test_real_spanish_prose_with_several_beats(self):
        text = (
            "El inspector cerró la carpeta. —No hay nada aquí "
            "—dijo Orduña.\n"
            "Marta se levantó. —Entonces busque mejor —replicó Marta.\n"
        )
        chapter = _compile(text, "es")
        assert [u.speaker for u in _dialogue(chapter)] == ["Orduña", "Marta"]


# ---------------------------------------------------------------------------
# FEAT-CAST-004 — split quotes get ONE speaker
# ---------------------------------------------------------------------------

class TestSplitQuotesShareOneSpeaker:
    """``"Kessler," Petrov said carefully, "is on the manifest."`` became two
    utterances with two different speakers — audibly two voices mid-sentence."""

    SPLIT = '"Kessler," Petrov said carefully, "is on the manifest."'

    def test_both_halves_carry_the_same_speaker(self):
        chapter = _compile(self.SPLIT)
        dialogue = _dialogue(chapter)
        assert len(dialogue) == 2
        assert [u.speaker for u in dialogue] == ["Petrov", "Petrov"]

    def test_the_second_half_is_not_a_guess(self):
        chapter = _compile(self.SPLIT)
        second = _dialogue(chapter)[1]
        assert second.attribution_source == "tag"
        assert second.confidence > LOW_CONFIDENCE_THRESHOLD

    def test_the_interior_tag_is_still_read_by_the_narrator(self):
        chapter = _compile(self.SPLIT)
        narration = [u for u in chapter.utterances
                     if u.utterance_type.value == "narration"]
        assert any("Petrov said carefully" in u.text for u in narration)

    def test_a_split_quote_does_not_poison_the_turn_stack(self):
        """Both halves are one turn. Pushing the speaker twice would make the
        alternation guess return the SAME speaker for the next line."""
        text = (
            '"Kessler," Petrov said carefully, "is on the manifest."\n\n'
            '"I know," Rhodes answered.\n\n'
            '"Then say so."\n'
        )
        chapter = _compile(text)
        assert [u.speaker for u in _dialogue(chapter)] == [
            "Petrov", "Petrov", "Rhodes", "Petrov",
        ]

    def test_two_separate_sentences_by_one_speaker_are_not_merged(self):
        """``said Alice.`` ends the tag. The next quote is a new utterance,
        not the back half of a split one — do not narrow the fix into it."""
        chapter = _compile('"Hello," said Alice. "How are you?"')
        assert len(_dialogue(chapter)) == 2

    def test_a_genuine_two_speaker_exchange_is_not_collapsed(self):
        chapter = _compile('"Run!" Sarah screamed.\n\n"Down!" Jake shouted.')
        assert [u.speaker for u in _dialogue(chapter)] == ["Sarah", "Jake"]

    def test_the_classic_register_splits_the_same_way(self):
        chapter = _compile(
            '"You are mistaken," said Mr. Darcy, "if you suppose that I '
            'intended any slight."'
        )
        assert [u.speaker for u in _dialogue(chapter)] == ["Mr. Darcy", "Mr. Darcy"]

    def test_the_tags_own_full_stop_demotes_it_to_a_carry_over(self):
        """``name_boundary`` CONSUMES the tag's terminal punctuation, so a tag
        that plainly closed the previous sentence reached the tier test with
        an EMPTY gap and scored tier 0 — "directly attached to this quote".
        Measured: on the two-turn line below the previous speaker beat the tag
        actually attached to the line, at full confidence."""
        chapter = _compile(
            "—Vete —dijo Elena. —No quiero —respondió Marcos.\n",
            "es",
        )
        assert [u.speaker for u in _dialogue(chapter)] == ["Elena", "Marcos"]

    def test_a_dash_closed_tag_is_a_name_boundary(self):
        """``respondió Marcos—.`` matched no attribution pattern at all: the
        profile's name_boundary listed ``,.!?`` and whitespace, never the
        raya, which is the mark that CLOSES an interposed Spanish comment."""
        chapter = _compile(
            "—Sí —respondió Marcos—. Vamos ahora mismo.\n", "es",
        )
        assert [u.speaker for u in _dialogue(chapter)] == ["Marcos", "Marcos"]

    def test_a_parenthetical_inside_speech_keeps_one_voice(self):
        """No speech verb in the interposition at all — the dashes alone say
        the same person is still talking. The tag is on the BACK half here,
        which is why attribution cannot simply flow front-to-back."""
        chapter = _compile(
            "—Ese hombre —el que viste ayer— vino otra vez "
            "—dijo Elena.\n",
            "es",
        )
        dialogue = _dialogue(chapter)
        assert [u.speaker for u in dialogue] == ["Elena", "Elena"]
        assert [u.text for u in dialogue] == ["Ese hombre", "vino otra vez"]

    def test_the_trailing_tag_is_not_swallowed_into_the_resumed_speech(self):
        chapter = _compile(
            "—Ese hombre —el que viste ayer— vino otra vez "
            "—dijo Elena.\n",
            "es",
        )
        assert not any("dijo" in u.text for u in _dialogue(chapter))

    def test_an_unclosed_comment_leaves_its_tail_as_narration(self):
        """``—Vamos —insistió Marta, y salió de la habitación.`` has no
        closing raya, so the tail really is narration — do not over-fit the
        resumption rule into it."""
        chapter = _compile(
            "—Vamos —insistió Marta, y salió de la habitación.\n",
            "es",
        )
        assert [u.text for u in _dialogue(chapter)] == ["Vamos"]

    def test_spanish_resumes_after_the_closing_raya_of_the_tag(self):
        chapter = _compile(
            "—Kessler —dijo Petrov con cuidado—, está en el "
            "manifiesto.\n",
            "es",
        )
        dialogue = _dialogue(chapter)
        assert len(dialogue) == 2, [u.text for u in dialogue]
        assert [u.speaker for u in dialogue] == ["Petrov", "Petrov"]
        assert "manifiesto" in dialogue[1].text
