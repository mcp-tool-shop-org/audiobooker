"""
FEATURE pass — v2.1 CASTING-DEPTH (FT-CAST-020..026 + FT-NLP-025).

Covers the casting-side feature work:

- FT-CAST-020: named cast preset library (presets.py)
- FT-CAST-021: bulk cast-fill (VoiceSuggester.bulk_assign)
- FT-CAST-023: emotion intensity — emotion.py sets utterance.intensity from
  graded confidence; engine.py maps (emotion, intensity) -> SSML emphasis;
  dialogue.py serializes/parses '(emotion:intensity)'. REGRESSION-CRITICAL:
  bare emotion (intensity None) renders byte-identically to today.
- FT-CAST-024: scene emotion spans ([scene:<emotion>]...[/scene]) as a fallback
- FT-CAST-026: emotion preset packs (neutral/literary/dramatic/children)
- FT-NLP-025: alias discovery (proposal only, never auto-applied)

No network / ffmpeg / voice-soundboard — registries and NLP adapters faked.
"""

from __future__ import annotations

import pytest

from audiobooker.casting import presets as presets_mod
from audiobooker.casting.dialogue import (
    _format_emotion_tag,
    compile_chapter,
    parse_emotion_tag,
    utterances_to_script,
)
from audiobooker.casting.voice_suggester import VoiceSuggester
from audiobooker.models import (
    CastingTable,
    Chapter,
    Character,
    Utterance,
    UtteranceType,
)
from audiobooker.nlp.emotion import (
    VALID_EMOTION_PRESETS,
    EmotionInferencer,
    get_emotion_preset,
)
from audiobooker.nlp.speaker_resolver import AliasProposal, suggest_aliases
from audiobooker.renderer.engine import (
    _EMOTION_EMPHASIS,
    _emphasis_for,
    preprocess_ssml,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FixedRegistry:
    """Voice registry returning a fixed list (no voice-soundboard)."""

    def __init__(self, voices: list[str]) -> None:
        self._voices = voices

    def list_voices(self) -> list[str]:
        return self._voices


@pytest.fixture
def isolated_presets(tmp_path, monkeypatch):
    """Point the preset library at a temp config dir for the test."""
    monkeypatch.setattr(presets_mod, "_config_root", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# FT-CAST-020 — named cast preset library
# ---------------------------------------------------------------------------

class TestCastPresets:
    def _sample(self) -> list[dict]:
        return [
            {"name": "Alice", "voice": "af_heart", "emotion": None,
             "speed": 1.0, "aliases": ["Ali"], "description": "lead"},
            {"name": "Bob", "voice": "am_eric", "emotion": "gruff",
             "speed": 1.1, "aliases": [], "description": None},
        ]

    def test_save_then_load_round_trips(self, isolated_presets):
        presets_mod.save_preset("Fantasy Ensemble", self._sample())
        loaded = presets_mod.load_preset("Fantasy Ensemble")
        assert loaded == self._sample()

    def test_list_presets_returns_display_names(self, isolated_presets):
        presets_mod.save_preset("Fantasy Ensemble", self._sample())
        presets_mod.save_preset("Noir Cast", self._sample())
        assert presets_mod.list_presets() == ["Fantasy Ensemble", "Noir Cast"]

    def test_list_empty_when_none_saved(self, isolated_presets):
        assert presets_mod.list_presets() == []

    def test_delete_preset(self, isolated_presets):
        presets_mod.save_preset("Temp", self._sample())
        assert presets_mod.delete_preset("Temp") is True
        assert presets_mod.list_presets() == []
        # Deleting again is a no-op returning False.
        assert presets_mod.delete_preset("Temp") is False

    def test_preset_dir_exists_under_config(self, isolated_presets):
        d = presets_mod.preset_dir()
        assert d.exists()
        assert d.parent == isolated_presets

    def test_load_missing_raises(self, isolated_presets):
        with pytest.raises(presets_mod.PresetError):
            presets_mod.load_preset("nope")

    def test_save_rejects_non_list(self, isolated_presets):
        with pytest.raises(presets_mod.PresetError):
            presets_mod.save_preset("bad", {"not": "a list"})  # type: ignore[arg-type]

    def test_save_rejects_entry_without_name_or_voice(self, isolated_presets):
        with pytest.raises(presets_mod.PresetError):
            presets_mod.save_preset("bad", [{"name": "Alice"}])

    def test_save_rejects_empty_name(self, isolated_presets):
        with pytest.raises(presets_mod.PresetError):
            presets_mod.save_preset("  ", self._sample())

    def test_preset_shape_matches_export_casting(self, isolated_presets):
        """A preset entry feeds straight into Character.from_dict / import."""
        presets_mod.save_preset("X", self._sample())
        loaded = presets_mod.load_preset("X")
        casting = CastingTable()
        for entry in loaded:
            char = Character.from_dict(entry)
            casting.characters[casting.normalize_key(char.name)] = char
        assert "alice" in casting.characters
        assert casting.characters["bob"].emotion == "gruff"


# ---------------------------------------------------------------------------
# FT-CAST-021 — bulk cast-fill
# ---------------------------------------------------------------------------

class TestBulkAssign:
    def _suggester(self) -> VoiceSuggester:
        return VoiceSuggester(registry=_FixedRegistry([
            "af_heart", "af_jessica", "am_eric", "am_liam", "bm_george", "bf_emma",
        ]))

    def test_assigns_every_speaker(self):
        s = self._suggester()
        result = s.bulk_assign(
            ["Mary", "John", "Elizabeth"],
            line_counts={"Mary": 50, "John": 50, "Elizabeth": 50},
        )
        assert set(result) == {"Mary", "John", "Elizabeth"}

    def test_diversity_no_duplicate_voices_with_pool(self):
        s = self._suggester()
        result = s.bulk_assign(
            ["Mary", "Elizabeth"],
            line_counts={"Mary": 50, "Elizabeth": 50},
            voice_pools={"female_major": ["af_heart", "af_jessica"]},
        )
        assert result["Mary"] != result["Elizabeth"]

    def test_gender_bucket_uses_correct_pool(self):
        s = self._suggester()
        result = s.bulk_assign(
            ["Mary", "John"],
            line_counts={"Mary": 50, "John": 50},
            voice_pools={
                "female_major": ["af_heart"],
                "male_major": ["am_eric"],
            },
        )
        assert result["Mary"] == "af_heart"
        assert result["John"] == "am_eric"

    def test_major_vs_minor_threshold_splits_buckets(self):
        s = self._suggester()
        # John has 3 lines (minor), so he draws from the minor pool only.
        result = s.bulk_assign(
            ["John", "James"],
            line_counts={"John": 3, "James": 50},
            major_line_threshold=10,
            voice_pools={
                "male_minor": ["am_liam"],
                "male_major": ["am_eric"],
            },
        )
        assert result["John"] == "am_liam"
        assert result["James"] == "am_eric"

    def test_no_pool_defers_to_suggester(self):
        s = self._suggester()
        result = s.bulk_assign(
            ["Mary", "John"], line_counts={"Mary": 50, "John": 50},
        )
        # Both assigned and distinct (diversity penalty in suggest_for_speaker).
        assert result["Mary"] != result["John"]

    def test_already_cast_is_honored(self):
        s = self._suggester()
        result = s.bulk_assign(
            ["Mary"],
            line_counts={"Mary": 50},
            already_cast={"Mary": "bf_emma"},
        )
        assert result["Mary"] == "bf_emma"

    def test_deterministic(self):
        s = self._suggester()
        pools = {"female_major": ["af_heart", "af_jessica"]}
        a = s.bulk_assign(["Mary", "Elizabeth"],
                          line_counts={"Mary": 50, "Elizabeth": 50},
                          voice_pools=pools)
        b = s.bulk_assign(["Mary", "Elizabeth"],
                          line_counts={"Mary": 50, "Elizabeth": 50},
                          voice_pools=pools)
        assert a == b


# ---------------------------------------------------------------------------
# FT-CAST-023 — emotion intensity (engine SSML + dialogue serialization)
# ---------------------------------------------------------------------------

class TestEmotionIntensityEngine:
    def test_bare_emotion_is_historical_strong(self):
        """REGRESSION: angry with no intensity -> 'strong' (today's behavior)."""
        u = Utterance(speaker="Alice", text="I am furious",
                      utterance_type=UtteranceType.DIALOGUE, emotion="angry")
        ssml = preprocess_ssml([u])
        assert '<emphasis level="strong">' in ssml

    def test_bare_emotion_byte_identical_regression(self):
        """The full SSML string must equal the pre-intensity output."""
        u = Utterance(speaker="narrator", text="Hello world",
                      utterance_type=UtteranceType.NARRATION, emotion="sad")
        expected = (
            '<speak>\n<prosody rate="medium">'
            '<emphasis level="moderate">Hello world</emphasis>'
            '</prosody>\n</speak>'
        )
        assert preprocess_ssml([u]) == expected

    def test_no_emotion_no_emphasis_wrapper(self):
        u = Utterance(speaker="Alice", text="Plain line",
                      utterance_type=UtteranceType.DIALOGUE)
        ssml = preprocess_ssml([u])
        assert "<emphasis" not in ssml

    def test_intensity_none_matches_default_map(self):
        for emotion, level in _EMOTION_EMPHASIS.items():
            assert _emphasis_for(emotion, None, "neutral") == level

    def test_low_intensity_reduced(self):
        assert _emphasis_for("angry", 0.1, "neutral") == "reduced"

    def test_mid_intensity_moderate(self):
        assert _emphasis_for("angry", 0.5, "neutral") == "moderate"

    def test_high_intensity_full_level(self):
        assert _emphasis_for("angry", 0.95, "neutral") == "strong"

    def test_intensity_flows_into_ssml(self):
        u = Utterance(speaker="Alice", text="Quietly now",
                      utterance_type=UtteranceType.DIALOGUE, emotion="angry")
        u.intensity = 0.1  # type: ignore[attr-defined]
        ssml = preprocess_ssml([u])
        assert '<emphasis level="reduced">' in ssml


class TestEmotionIntensityScript:
    def test_format_bare_emotion_unchanged(self):
        assert _format_emotion_tag("angry", None) == "(angry) "

    def test_format_with_intensity(self):
        assert _format_emotion_tag("angry", 0.7) == "(angry:0.7) "

    def test_format_no_emotion(self):
        assert _format_emotion_tag(None, 0.5) == ""

    def test_parse_bare(self):
        assert parse_emotion_tag("(angry) hello") == ("angry", None, "hello")

    def test_parse_with_intensity(self):
        assert parse_emotion_tag("(angry:0.7) hi") == ("angry", 0.7, "hi")

    def test_parse_no_tag(self):
        assert parse_emotion_tag("no tag here") == (None, None, "no tag here")

    def test_parse_clamps_out_of_range(self):
        emotion, intensity, _ = parse_emotion_tag("(angry:9.0) x")
        assert intensity == 1.0

    def test_script_serializes_intensity(self):
        u = Utterance(speaker="Alice", text="Stop!",
                      utterance_type=UtteranceType.DIALOGUE, emotion="angry")
        u.intensity = 0.7  # type: ignore[attr-defined]
        script = utterances_to_script([u])
        assert "(angry:0.7)" in script

    def test_script_bare_emotion_historical(self):
        u = Utterance(speaker="Bob", text="Hi",
                      utterance_type=UtteranceType.DIALOGUE, emotion="happy")
        script = utterances_to_script([u])
        assert "(happy)" in script
        assert "(happy:" not in script

    def test_round_trip(self):
        tag = _format_emotion_tag("sad", 0.4)
        emotion, intensity, rest = parse_emotion_tag(tag + "body")
        assert emotion == "sad"
        assert intensity == 0.4
        assert rest == "body"


class TestEmotionInferencerIntensity:
    def test_intensity_set_from_confidence(self):
        utts = [Utterance(speaker="Alice",
                          text="I am absolutely furious right now",
                          utterance_type=UtteranceType.DIALOGUE)]
        inf = EmotionInferencer()
        applied = inf.apply_to_utterances(
            utts, chapter_text="I am absolutely furious right now")
        assert applied == 1
        assert utts[0].emotion == "angry"
        assert getattr(utts[0], "intensity", None) is not None
        assert 0.0 <= utts[0].intensity <= 1.0

    def test_no_emotion_no_intensity(self):
        utts = [Utterance(speaker="Alice", text="The table was brown.",
                          utterance_type=UtteranceType.NARRATION)]
        inf = EmotionInferencer()
        inf.apply_to_utterances(utts, chapter_text="The table was brown.")
        assert utts[0].emotion is None
        assert getattr(utts[0], "intensity", None) is None


# ---------------------------------------------------------------------------
# FT-CAST-024 — scene emotion spans
# ---------------------------------------------------------------------------

class TestSceneEmotion:
    def _casting(self) -> CastingTable:
        casting = CastingTable()
        casting.characters["alice"] = Character(name="Alice", voice="af_heart")
        casting.characters["bob"] = Character(name="Bob", voice="am_eric")
        return casting

    def test_scene_emotion_applied_as_fallback(self):
        text = (
            "[scene:tense]\n\n"
            '"We need to go," said Alice.\n\n'
            '"Not yet," Bob replied.\n\n'
            "[/scene]\n\n"
            '"All clear now," said Alice.'
        )
        ch = Chapter(index=0, title="T", raw_text=text)
        utts = compile_chapter(ch, self._casting())
        dia = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        inside = [u for u in dia if "need to go" in u.text or "Not yet" in u.text]
        after = [u for u in dia if "All clear" in u.text]
        assert all(u.emotion == "tense" for u in inside)
        assert all(u.emotion is None for u in after)

    def test_scene_does_not_override_attribution(self):
        # 'screamed' carries a 'fearful' attribution hint that must beat scene.
        text = '[scene:calm]\n\n"Get out!" screamed Alice.'
        ch = Chapter(index=0, title="T", raw_text=text)
        utts = compile_chapter(ch, self._casting())
        dia = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        assert dia[0].emotion == "fearful"

    def test_scene_beats_chapter_mood(self):
        text = '[scene:tense]\n\n"Where are we?" said Alice.'
        ch = Chapter(index=0, title="T", raw_text=text)
        ch.mood = "somber"  # type: ignore[attr-defined]
        utts = compile_chapter(ch, self._casting())
        dia = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        assert dia[0].emotion == "tense"

    def test_scene_tags_stripped_from_text(self):
        text = '[scene:tense]\n\n"Hello," said Alice.\n\n[/scene]'
        ch = Chapter(index=0, title="T", raw_text=text)
        utts = compile_chapter(ch, self._casting())
        assert all("[scene" not in u.text and "[/scene" not in u.text
                   for u in utts)

    def test_no_scene_tag_is_unchanged(self):
        text = '"Hello," said Alice.'
        ch = Chapter(index=0, title="T", raw_text=text)
        utts = compile_chapter(ch, self._casting())
        dia = [u for u in utts if u.utterance_type == UtteranceType.DIALOGUE]
        assert dia[0].emotion is None


# ---------------------------------------------------------------------------
# FT-CAST-026 — emotion preset packs
# ---------------------------------------------------------------------------

class TestEmotionPresets:
    def test_valid_presets(self):
        assert set(VALID_EMOTION_PRESETS) == {
            "neutral", "literary", "dramatic", "children"}

    def test_neutral_threshold_is_historical(self):
        assert EmotionInferencer().threshold == 0.75
        assert EmotionInferencer(preset="neutral").threshold == 0.75

    def test_preset_thresholds(self):
        assert EmotionInferencer(preset="dramatic").threshold == 0.65
        assert EmotionInferencer(preset="literary").threshold == 0.85
        assert EmotionInferencer(preset="children").threshold == 0.70

    def test_explicit_threshold_overrides_preset(self):
        assert EmotionInferencer(preset="dramatic", threshold=0.9).threshold == 0.9

    def test_unknown_preset_falls_back_to_neutral(self):
        assert get_emotion_preset("bogus").name == "neutral"

    def test_children_preset_suppresses_angry(self):
        utts = [Utterance(speaker="Alice",
                          text="I am absolutely furious right now",
                          utterance_type=UtteranceType.DIALOGUE)]
        inf = EmotionInferencer(preset="children")
        inf.apply_to_utterances(
            utts, chapter_text="I am absolutely furious right now")
        assert utts[0].emotion is None  # angry not in children label set

    def test_neutral_preset_allows_angry(self):
        utts = [Utterance(speaker="Alice",
                          text="I am absolutely furious right now",
                          utterance_type=UtteranceType.DIALOGUE)]
        inf = EmotionInferencer(preset="neutral")
        inf.apply_to_utterances(
            utts, chapter_text="I am absolutely furious right now")
        assert utts[0].emotion == "angry"

    def test_engine_neutral_preset_is_historical(self):
        u = Utterance(speaker="Alice", text="x",
                      utterance_type=UtteranceType.DIALOGUE, emotion="angry")
        assert preprocess_ssml([u], "neutral") == preprocess_ssml([u])

    def test_engine_literary_pulls_angry_down(self):
        # literary maps angry -> moderate at full intensity.
        assert _emphasis_for("angry", None, "literary") == "moderate"

    def test_engine_dramatic_keeps_sad_strong(self):
        assert _emphasis_for("sad", None, "dramatic") == "strong"


# ---------------------------------------------------------------------------
# FT-NLP-025 — alias discovery (proposal only)
# ---------------------------------------------------------------------------

class TestAliasDiscovery:
    def _casting(self) -> CastingTable:
        casting = CastingTable()
        casting.characters["holmes"] = Character(name="Holmes", voice="am_eric")
        casting.characters["watson"] = Character(name="Watson", voice="am_liam")
        return casting

    def _text(self) -> str:
        return (
            "Watson examined the patient. The Doctor frowned. Watson sighed and "
            "the Doctor nodded. Watson left, but the Doctor lingered near Watson "
            'and watched.\n\nHolmes returned home. "Remarkable," said Mr. Holmes '
            "to Holmes himself."
        )

    def test_proposes_alias_for_descriptor(self):
        casting = self._casting()
        ch = Chapter(index=0, title="T", raw_text=self._text())
        proposals = suggest_aliases([ch], casting, use_booknlp=False, min_score=0.1)
        labels = {p.candidate: p.speaker for p in proposals}
        assert labels.get("the Doctor") == "Watson"
        assert labels.get("Mr. Holmes") == "Holmes"

    def test_never_auto_applied(self):
        casting = self._casting()
        ch = Chapter(index=0, title="T", raw_text=self._text())
        suggest_aliases([ch], casting, use_booknlp=False, min_score=0.1)
        # The cast is unchanged — no 'the doctor' / 'mr. holmes' entries added,
        # and no aliases attached to the confirmed characters.
        assert "the doctor" not in casting.characters
        assert "mr. holmes" not in casting.characters
        assert casting.characters["watson"].aliases == []
        assert casting.characters["holmes"].aliases == []

    def test_returns_alias_proposal_objects(self):
        casting = self._casting()
        ch = Chapter(index=0, title="T", raw_text=self._text())
        proposals = suggest_aliases([ch], casting, use_booknlp=False, min_score=0.1)
        assert proposals
        assert all(isinstance(p, AliasProposal) for p in proposals)
        assert all(0.0 <= p.score <= 1.0 for p in proposals)

    def test_sorted_by_score_desc(self):
        casting = self._casting()
        ch = Chapter(index=0, title="T", raw_text=self._text())
        proposals = suggest_aliases([ch], casting, use_booknlp=False, min_score=0.1)
        scores = [p.score for p in proposals]
        assert scores == sorted(scores, reverse=True)

    def test_no_confirmed_speakers_no_proposals(self):
        casting = CastingTable()  # empty cast
        ch = Chapter(index=0, title="T", raw_text=self._text())
        assert suggest_aliases([ch], casting, use_booknlp=False) == []

    def test_min_score_filters(self):
        casting = self._casting()
        ch = Chapter(index=0, title="T", raw_text=self._text())
        high = suggest_aliases([ch], casting, use_booknlp=False, min_score=0.99)
        assert high == []

    def test_coref_source_when_booknlp_corroborates(self):
        from audiobooker.nlp.booknlp_adapter import BookNLPResult, Entity

        class _FakeAdapter:
            def is_available(self):
                return True

            def analyze(self, text):
                return BookNLPResult(
                    entities=[
                        Entity(name="Holmes", start=0, end=6),
                        Entity(name="Watson", start=0, end=6),
                    ],
                    success=True,
                )

        casting = self._casting()
        ch = Chapter(index=0, title="T", raw_text=self._text())
        proposals = suggest_aliases(
            [ch], casting, adapter=_FakeAdapter(), use_booknlp=True,
            min_score=0.1,
        )
        # 'Mr. Holmes' shares the surname 'Holmes' with a confirmed entity, so
        # its proposal is corroborated by coref.
        by_cand = {p.candidate: p for p in proposals}
        assert by_cand["Mr. Holmes"].source == "coref"
