"""
Phase 7 (unwired features) — six things that were built, tested, sometimes
advertised, and wired to nothing.

  FEAT-PROD-009  the utterance-level incremental cache was never reachable
  FEAT-PROD-003  cache keys omitted intensity, emotion_preset and the
                 per-character voice params, so changing them served the
                 PREVIOUS audio and reported "Cached"
  FEAT-PROD-002  a pronunciation override added after compile was a no-op
  FEAT-OUT-001   recasting one character re-rendered the whole book
  FEAT-PROD-004  nothing checked the output destination before synthesizing
  FEAT-UX-006    a typo'd config key had no suggestion and no provenance

Every test here was written to fail against the pre-fix tree.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from audiobooker.models import (
    Chapter,
    CastingTable,
    ProjectConfig,
    Utterance,
    UtteranceType,
)
from audiobooker.project import AudiobookProject
from audiobooker.renderer.engine import RenderError, render_project
from audiobooker.renderer.hash_utils import (
    casting_hash,
    chapter_text_hash,
    render_params_hash,
)
from audiobooker.renderer.output import AssemblyResult
from audiobooker.renderer.protocols import RunResult
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

class StitchRunner:
    """ffmpeg stand-in for the utterance concat step (no ffmpeg on the box)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> RunResult:
        self.calls.append(list(args))
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        write_silence_wav(out, 0.1)
        return RunResult(returncode=0, stdout="", stderr="")


def tolerant_assembler(chapter_files, output_path, title="", author="",
                       chapter_pause_ms=2000):
    """Creates its parent directory, like tests/fakes FakeAssembler does."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"FAKE")
    return AssemblyResult(output_path=output_path, chapters_embedded=True)


def honest_assembler(chapter_files, output_path, title="", author="",
                     chapter_pause_ms=2000):
    """Writes where it is told and nowhere else — what ffmpeg actually does."""
    output_path = Path(output_path)
    output_path.write_bytes(b"FAKE")
    return AssemblyResult(output_path=output_path, chapters_embedded=True)


def _casting() -> CastingTable:
    c = CastingTable()
    c.cast("narrator", "af_heart")
    c.cast("Alice", "af_bella")
    c.cast("Bob", "bm_george")
    return c


def _chapter(index: int = 0, speaker: str = "Alice") -> Chapter:
    ch = Chapter(index=index, title=f"Chapter {index + 1}", raw_text="x y z")
    ch.utterances = [
        Utterance(speaker="narrator", text="The sun rose.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker=speaker, text="Good morning.", emotion="happy",
                  utterance_type=UtteranceType.DIALOGUE),
        Utterance(speaker="narrator", text="Nobody answered.",
                  utterance_type=UtteranceType.NARRATION),
    ]
    return ch


def _project(tmp_path: Path, n_chapters: int = 2, **config_kwargs):
    """A compiled, fully cast project whose chapter N uses speaker N."""
    speakers = ["Alice", "Bob", "Alice", "Bob"]
    p = AudiobookProject.from_chapters(
        [(f"Chapter {i + 1}", "placeholder") for i in range(n_chapters)],
        title="Wired",
    )
    p.project_path = tmp_path / "book.abp"
    p.config = ProjectConfig(validate_voices_on_render=False, **config_kwargs)
    p.casting = _casting()
    for i in range(n_chapters):
        p.chapters[i] = _chapter(i, speakers[i % len(speakers)])
        p.chapters[i].index = i
    return p


# ===========================================================================
# FEAT-PROD-009 — the utterance-level incremental cache reaches the renderer
# ===========================================================================

class TestUtteranceCacheWiring:
    """ProjectConfig.utterance_cache actually routes the render."""

    def test_flag_on_synthesizes_per_utterance_not_per_chapter(self, tmp_path):
        p = _project(tmp_path, n_chapters=1, utterance_cache=True)
        engine = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine,
            assembler=tolerant_assembler, cache_root=tmp_path / "cache",
            stitch_runner=StitchRunner(),
        )
        # Three utterances in the chapter → three synthesize() calls.
        assert len(engine.calls) == 3

    def test_flag_off_keeps_one_call_per_chapter(self, tmp_path):
        p = _project(tmp_path, n_chapters=1)  # utterance_cache defaults False
        engine = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine,
            assembler=tolerant_assembler, cache_root=tmp_path / "cache",
        )
        assert len(engine.calls) == 1

    def test_flag_on_writes_the_namespaced_utterance_manifest(self, tmp_path):
        from audiobooker.renderer.cache_manifest import (
            get_utterance_manifest_path,
        )
        cache = tmp_path / "cache"
        p = _project(tmp_path, n_chapters=1, utterance_cache=True)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
            stitch_runner=StitchRunner(),
        )
        assert get_utterance_manifest_path(cache, 0).exists()

    def test_opting_in_does_not_silently_change_the_markup(self, tmp_path):
        """The opt-in path must speak the same language as the default one.

        render_chapter picks SSML for an SSML-capable engine and the
        tagged-line script otherwise; render_chapter_incremental always chose
        the tagged-line script. Turning the cache on therefore changed the
        markup handed to the engine — and dropped the emotion preset and
        intensity grading, which only exist in the SSML branch.
        """
        class SsmlEngine(FakeTTSEngine):
            def capabilities(self):
                return {"ssml": True}

        p = _project(tmp_path, n_chapters=1, utterance_cache=True,
                     emotion_preset="literary")
        engine = SsmlEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine,
            assembler=tolerant_assembler, cache_root=tmp_path / "cache",
            stitch_runner=StitchRunner(),
        )
        dialogue = next(c.script for c in engine.calls if "Good morning" in c.script)
        assert dialogue.startswith("<speak>")
        # 'happy' is "strong" under neutral and "moderate" under literary —
        # the preset has to reach this path or it is silently ignored.
        assert 'level="moderate"' in dialogue

    def test_toggling_the_flag_invalidates_the_chapter_cache(self, tmp_path):
        """Per-utterance synthesis + concat is not the same waveform.

        The chapter SSML puts a <break time="750ms"/> at speaker changes;
        a concat of separately-synthesized utterances has no equivalent. So
        the flag has to be part of the render-params key, or flipping it
        re-serves the other strategy's audio and reports "Cached".
        """
        cache = tmp_path / "cache"
        p = _project(tmp_path, n_chapters=1)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
        )
        p.config.utterance_cache = True
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine2,
            assembler=tolerant_assembler, cache_root=cache,
            stitch_runner=StitchRunner(),
        )
        assert len(engine2.calls) == 3  # re-rendered, per utterance

    def test_stitch_names_the_output_format_explicitly(self, tmp_path):
        """The render path hands the stitcher a ".wav.tmp" scratch name.

        ffmpeg infers the output format from the extension, and ".tmp" is not
        one it knows — so without an explicit -f every real stitch would die
        on "Unable to find a suitable output format". Invisible until now
        because nothing called the incremental path, and the tests inject a
        runner that writes the file itself.
        """
        runner = StitchRunner()
        p = _project(tmp_path, n_chapters=1, utterance_cache=True)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=tmp_path / "cache",
            stitch_runner=runner,
        )
        assert runner.calls, "the concat step never ran"
        args = runner.calls[0]
        assert args[-1].endswith(".wav.tmp")
        assert args[-3:-1] == ["-f", "wav"]

    def test_editing_one_line_resynthesizes_only_that_line(self, tmp_path):
        """The whole point: one edited line costs one utterance, not a chapter."""
        cache = tmp_path / "cache"
        p = _project(tmp_path, n_chapters=1, utterance_cache=True)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
            stitch_runner=StitchRunner(),
        )

        p.chapters[0].utterances[1].text = "Good morning, friend."
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine2,
            assembler=tolerant_assembler, cache_root=cache,
            stitch_runner=StitchRunner(),
        )
        assert len(engine2.calls) == 1, (
            "editing one utterance re-synthesized "
            f"{len(engine2.calls)} utterances, not 1"
        )
        # A single call is ALSO what the chapter-level path does, so the count
        # alone proves nothing. What distinguishes the two is the payload: the
        # one call must carry ONLY the edited line, not the whole chapter.
        script = engine2.calls[0].script
        assert "Good morning, friend." in script
        assert "The sun rose." not in script
        assert "Nobody answered." not in script


# ===========================================================================
# FEAT-PROD-003 — cache keys that served the wrong audio
# ===========================================================================

class TestCacheKeyOmissions:

    def test_intensity_is_in_the_chapter_text_hash(self):
        bare = _chapter()
        bare.utterances[1].intensity = None
        graded = _chapter()
        graded.utterances[1].intensity = 0.1
        # The two render to <emphasis level="strong"> vs "reduced".
        assert chapter_text_hash(bare) != chapter_text_hash(graded)

    def test_emotion_preset_is_in_the_render_params_hash(self):
        digests = {
            preset: render_params_hash(ProjectConfig(emotion_preset=preset))
            for preset in ("neutral", "literary", "dramatic", "children")
        }
        # 'literary' resolves a different emphasis level for 5 of 9 emotions.
        assert digests["neutral"] != digests["literary"]
        assert len(set(digests.values())) > 1

    def test_switching_preset_rerenders_instead_of_reporting_cached(self, tmp_path):
        cache = tmp_path / "cache"
        p = _project(tmp_path, n_chapters=2)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
        )
        p.config.emotion_preset = "literary"
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine2,
            assembler=tolerant_assembler, cache_root=cache,
        )
        assert len(engine2.calls) == 2, (
            "switching to the literary preset served the neutral audio"
        )

    def test_character_voice_params_are_in_the_casting_hash(self):
        """speed / pitch_shift / emphasis reach the script, so they must key it."""
        base = _casting()
        for attr, value in (("speed", 1.4), ("pitch_shift", -0.3), ("emphasis", 1.7)):
            changed = _casting()
            setattr(changed.characters[CastingTable.normalize_key("Alice")],
                    attr, value)
            assert casting_hash(base) != casting_hash(changed), (
                f"changing Character.{attr} did not invalidate the cache"
            )

    def test_manifest_version_bumped_so_legacy_entries_rerender_once(self):
        from audiobooker.renderer.cache_manifest import MANIFEST_VERSION
        assert MANIFEST_VERSION >= 3


# ===========================================================================
# FEAT-PROD-002 — a pronunciation override added after compile
# ===========================================================================

class TestPronunciationAfterCompile:

    def _book(self, tmp_path):
        p = AudiobookProject.from_chapters(
            [("One", "Siobhan waited by the gate."),
             ("Two", "The road was empty.")],
            title="Pron",
        )
        p.project_path = tmp_path / "book.abp"
        p.config.validate_voices_on_render = False
        p.compile()
        p.cast("narrator", "af_heart")
        for spk in sorted(p.get_uncast_speakers()):
            p.cast(spk, "af_heart")
        return p

    def test_add_reports_which_chapters_it_touched(self, tmp_path):
        p = self._book(tmp_path)
        affected = p.add_pronunciation("Siobhan", "shiv-AWN")
        assert affected == [0], (
            "add_pronunciation must report the chapters it changed so the CLI "
            f"can say a re-render is needed; got {affected!r}"
        )

    def test_add_rewrites_already_compiled_utterances(self, tmp_path):
        p = self._book(tmp_path)
        p.add_pronunciation("Siobhan", "shiv-AWN")
        joined = " ".join(u.text for u in p.chapters[0].utterances)
        assert "shiv-AWN" in joined
        assert "Siobhan" not in joined

    def test_render_after_add_actually_respeaks_the_name(self, tmp_path):
        cache = tmp_path / "cache"
        p = self._book(tmp_path)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
        )
        p.add_pronunciation("Siobhan", "shiv-AWN")
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine2,
            assembler=tolerant_assembler, cache_root=cache,
        )
        assert len(engine2.calls) == 1, (
            "the corrected chapter cache-hit instead of re-rendering"
        )
        assert "shiv-AWN" in engine2.calls[0].script

    def test_unaffected_chapters_are_not_re_rendered(self, tmp_path):
        cache = tmp_path / "cache"
        p = self._book(tmp_path)
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
        )
        p.add_pronunciation("Siobhan", "shiv-AWN")
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine2,
            assembler=tolerant_assembler, cache_root=cache,
        )
        # Count first: "nothing was re-rendered" would satisfy the negative
        # assertion below for entirely the wrong reason.
        assert len(engine2.calls) == 1
        scripts = " ".join(c.script for c in engine2.calls)
        assert "The road was empty" not in scripts

    def test_add_refuses_to_rewrite_a_cast_character_name(self, tmp_path):
        """PH-B-005: an override over a cast name must not silently un-cast."""
        p = self._book(tmp_path)
        p.cast("Siobhan", "af_bella")
        affected = p.add_pronunciation("Siobhan", "shiv-AWN")
        assert affected == []
        joined = " ".join(u.text for u in p.chapters[0].utterances)
        assert "Siobhan" in joined

    def test_add_does_not_spam_never_matched_warnings(self, tmp_path, caplog):
        """apply_pronunciation_overrides warns per CALL, not per document.

        Applying one override utterance-by-utterance made it warn "override
        never matched" for every utterance that simply does not contain the
        word — measured at 8 spurious warnings on this two-chapter book,
        which at the CLI's default WARNING level buries the real ones.
        """
        p = self._book(tmp_path)
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            p.add_pronunciation("Siobhan", "shiv-AWN")
        assert "never matched" not in caplog.text
        assert "looks like a proper noun" not in caplog.text

    def test_remove_marks_affected_chapters_for_recompile(self, tmp_path, caplog):
        p = self._book(tmp_path)
        p.add_pronunciation("Siobhan", "shiv-AWN")
        with caplog.at_level(logging.WARNING, logger="audiobooker.project"):
            affected = p.remove_pronunciation("Siobhan")
        assert affected == [0]
        # Cleared so render()'s compile gate picks it up from raw_text again.
        assert not p.chapters[0].is_compiled
        assert p.chapters[1].is_compiled
        # Clearing a chapter discards review edits that live on its
        # utterances. Unavoidable here, but it must not be silent.
        assert "PRONUNCIATION_REMOVED" in caplog.text

    def test_add_preserves_review_edits_in_the_same_chapter(self, tmp_path):
        """The add path rewrites in place rather than recompiling.

        A recompile would re-derive every utterance from raw text and throw
        away imported review edits, emotion overrides and mood spans across
        the whole book — for a one-word pronunciation change.
        """
        p = self._book(tmp_path)
        p.chapters[0].utterances[0].emotion = "somber"
        p.chapters[0].utterances[0].speaker = "Reviewer"
        p.add_pronunciation("Siobhan", "shiv-AWN")
        assert p.chapters[0].utterances[0].emotion == "somber"
        assert p.chapters[0].utterances[0].speaker == "Reviewer"
        assert "shiv-AWN" in p.chapters[0].utterances[0].text


# ===========================================================================
# FEAT-OUT-001 — per-chapter casting scope
# ===========================================================================

class TestPerChapterCastingScope:

    def test_casting_hash_accepts_a_chapter(self):
        ch = _chapter(0, "Alice")
        # Must not raise — the whole finding is that it had no chapter scope.
        casting_hash(_casting(), chapter=ch)

    def test_recasting_an_absent_character_does_not_change_the_hash(self):
        ch = _chapter(0, "Alice")  # narrator + Alice only
        before = casting_hash(_casting(), chapter=ch)
        recast = _casting()
        recast.cast("Bob", "bm_lewis")
        assert casting_hash(recast, chapter=ch) == before

    def test_recasting_a_present_character_does_change_the_hash(self):
        ch = _chapter(0, "Alice")
        before = casting_hash(_casting(), chapter=ch)
        recast = _casting()
        recast.cast("Alice", "af_sky")
        assert casting_hash(recast, chapter=ch) != before

    def test_uncompiled_chapter_falls_back_to_the_whole_table(self):
        empty = Chapter(index=0, title="Not compiled", raw_text="x")
        assert casting_hash(_casting(), chapter=empty) == casting_hash(_casting())

    def test_fallback_voice_change_invalidates_every_chapter(self):
        ch = _chapter(0, "Alice")
        before = casting_hash(_casting(), chapter=ch)
        changed = _casting()
        changed.fallback_voice_id = "am_onyx"
        assert casting_hash(changed, chapter=ch) != before

    def test_recasting_one_character_rerenders_only_their_chapters(self, tmp_path):
        cache = tmp_path / "cache"
        p = _project(tmp_path, n_chapters=2)  # ch0 Alice, ch1 Bob
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=tolerant_assembler, cache_root=cache,
        )
        p.casting.cast("Bob", "bm_lewis")
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out.m4b", engine=engine2,
            assembler=tolerant_assembler, cache_root=cache,
        )
        assert len(engine2.calls) == 1, (
            f"recasting Bob re-rendered {len(engine2.calls)} chapters; "
            "Bob appears in exactly one"
        )


# ===========================================================================
# FEAT-PROD-004 — output-destination preflight
# ===========================================================================

class TestOutputDestinationPreflight:

    @pytest.mark.parametrize("case", ["dest_is_dir", "parent_is_file"])
    def test_unwritable_destination_fails_before_any_synthesis(self, tmp_path, case):
        if case == "dest_is_dir":
            dest = tmp_path / "out.m4b"
            dest.mkdir()
        else:
            afile = tmp_path / "afile"
            afile.write_bytes(b"x")
            dest = afile / "out.m4b"

        p = _project(tmp_path, n_chapters=4)
        engine = FakeTTSEngine()
        with pytest.raises(RenderError) as exc:
            render_project(
                p, dest, engine=engine, assembler=honest_assembler,
                cache_root=tmp_path / "cache",
            )
        assert len(engine.calls) == 0, (
            f"{case}: synthesized {len(engine.calls)} chapters before noticing "
            "the destination was unwritable"
        )
        assert exc.value.code == "OUTPUT_UNWRITABLE"
        assert exc.value.hint

    def test_missing_parent_directory_is_created_and_announced(
        self, tmp_path, caplog
    ):
        """A missing output directory is made, not rejected — but said out loud.

        No assembler in renderer/output.py creates it, so this used to be a
        FileNotFoundError after the whole book had been synthesized. Creating
        it is the forgiving answer; the WARNING is what makes a typo'd path
        recoverable instead of silent.
        """
        dest = tmp_path / "no_such_dir" / "deeper" / "out.m4b"
        p = _project(tmp_path, n_chapters=1)
        with caplog.at_level(logging.WARNING, logger="audiobooker.renderer"):
            render_project(
                p, dest, engine=FakeTTSEngine(), assembler=honest_assembler,
                cache_root=tmp_path / "cache",
            )
        assert dest.exists()
        assert "RENDER_OUTPUT_DIR_CREATED" in caplog.text

    def test_a_writable_destination_still_renders(self, tmp_path):
        p = _project(tmp_path, n_chapters=1)
        out = tmp_path / "fine.m4b"
        render_project(
            p, out, engine=FakeTTSEngine(), assembler=honest_assembler,
            cache_root=tmp_path / "cache",
        )
        assert out.exists()

    def test_preflight_does_not_clobber_an_existing_output(self, tmp_path):
        out = tmp_path / "existing.m4b"
        out.write_bytes(b"PRECIOUS")
        from audiobooker.renderer.engine import _preflight_output_destination
        _preflight_output_destination(out, split=False)
        assert out.read_bytes() == b"PRECIOUS"


# ===========================================================================
# FEAT-UX-006 — config provenance + unknown-key suggestions
# ===========================================================================

class TestConfigUnknownKeys:

    def _rc(self, tmp_path: Path, body: str) -> Path:
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nText.\n", encoding="utf-8")
        (tmp_path / ".audiobookerrc").write_text(body, encoding="utf-8")
        return src

    def test_report_names_the_typo_and_the_nearest_valid_key(self, tmp_path):
        from audiobooker.config_file import load_config_report
        src = self._rc(tmp_path, 'output_fromat = "mp3"\n')
        report = load_config_report(src)
        unknown = {u["key"]: u for u in report.unknown_keys}
        assert "output_fromat" in unknown
        assert unknown["output_fromat"]["suggestion"] == "output_format"
        assert ".audiobookerrc" in unknown["output_fromat"]["origin"]

    def test_acx_gets_the_flag_specific_hint(self, tmp_path):
        """`acx = true` is the dangerous one: --acx is a real flag."""
        from audiobooker.config_file import load_config_report
        src = self._rc(tmp_path, "acx = true\n")
        report = load_config_report(src)
        entry = next(u for u in report.unknown_keys if u["key"] == "acx")
        assert "profile" in entry["message"]
        assert "acx" in entry["message"]

    def test_report_carries_the_provenance_find_config_files_computes(self, tmp_path):
        from audiobooker.config_file import load_config_report
        src = self._rc(tmp_path, 'format = "mp3"\n')
        report = load_config_report(src)
        assert report.sources["project_rc"] == str(tmp_path / ".audiobookerrc")
        assert report.values["output_format"] == "mp3"
        assert report.unknown_keys == []

    def test_unknown_key_with_no_near_match_still_reported(self, tmp_path):
        from audiobooker.config_file import load_config_report
        src = self._rc(tmp_path, "jobz = 4\n")
        report = load_config_report(src)
        entry = next(u for u in report.unknown_keys if u["key"] == "jobz")
        assert entry["message"]

    def test_warning_text_includes_the_suggestion(self, tmp_path, caplog):
        from audiobooker.config_file import load_config
        src = self._rc(tmp_path, 'output_fromat = "mp3"\n')
        with caplog.at_level(logging.WARNING, logger="audiobooker.config_file"):
            load_config(src)
        assert "output_format" in caplog.text
