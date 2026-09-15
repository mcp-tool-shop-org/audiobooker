"""Planted-RED gates for wave-2 Health A production contracts.

Written against the INTENDED contract. Production fixes land in sibling
worktrees (renderer-cache, cli-surface, project-core, parsers); until
those merge, these tests are expected RED. Do not xfail them.

Contracts:
  - utterance_hash / chapter_text_hash include utterance_type
  - utterance_hash includes Character speed / pitch_shift / emphasis
    (mutate, demand a sub-cache miss)
  - make / batch / podcast refuse guessed attribution without --force
    (render_project / project.render uncalled)
  - filter_chapters_by_selection include_ranges keys on chapter.index
  - render_sample keys cache identity on chapter.index
  - import_lexicon busts chapter_text_hash on already-compiled text
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiobooker.models import (
    CastingTable,
    Chapter,
    Character,
    ProjectConfig,
    Utterance,
    UtteranceType,
)
from audiobooker.project import AudiobookProject
from audiobooker.renderer.cache_manifest import get_chapter_wav_path
from audiobooker.renderer.engine import (
    filter_chapters_by_selection,
    render_project,
    render_sample,
)
from audiobooker.renderer.hash_utils import chapter_text_hash, utterance_hash
from audiobooker.renderer.output import AssemblyResult
from audiobooker.renderer.protocols import RunResult
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav
from tests.test_render_gates_on_attribution_quality import LEDGER


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

class StitchRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> RunResult:
        self.calls.append(list(args))
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        write_silence_wav(out, 0.1)
        return RunResult(returncode=0, stdout="", stderr="")


class RecordingFfmpeg:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> RunResult:
        self.calls.append(list(args))
        if args:
            last = args[-1]
            if last != "-" and not str(last).startswith("-"):
                p = Path(last)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"FAKE-SAMPLE")
        return RunResult(returncode=0, stdout="", stderr="")


def _tolerant_assembler(chapter_files, output_path, title="", author="",
                        chapter_pause_ms=2000, **_kwargs):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"FAKE")
    return AssemblyResult(output_path=output_path, chapters_embedded=True)


def _casting() -> CastingTable:
    table = CastingTable()
    table.cast("narrator", "af_heart")
    table.cast("Alice", "af_bella")
    return table


def _utterance_project(tmp_path: Path) -> AudiobookProject:
    p = AudiobookProject.from_chapters(
        [("One", "placeholder")], title="Hash"
    )
    p.project_path = tmp_path / "book.abp"
    p.config = ProjectConfig(validate_voices_on_render=False, utterance_cache=True)
    p.casting = _casting()
    ch = Chapter(index=0, title="One", raw_text="x")
    ch.utterances = [
        Utterance(speaker="narrator", text="The hall was cold.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker="Alice", text="Hello there.", emotion="angry",
                  utterance_type=UtteranceType.DIALOGUE),
    ]
    p.chapters = [ch]
    return p


def _guessed_source(tmp_path: Path, name: str = "ledger.txt") -> Path:
    src = tmp_path / name
    src.write_text("Chapter 1: The Scale\n\n" + LEDGER, encoding="utf-8")
    return src


def _cast_everyone(project, speakers, *, max_suggestions=1):
    """Auto-cast stub so the uncast gate cannot steal this test."""
    return [
        SimpleNamespace(speaker=s, top=SimpleNamespace(voice_id="af_heart"))
        for s in speakers
    ]


# ===========================================================================
# utterance_hash / chapter_text_hash — renderer-cache F-0da2d3a9, F-14251d01
# ===========================================================================

class TestUtteranceHashIncludesSynthesizerInputs:
    def test_utterance_type_pause_vs_narration_changes_the_hash(self):
        spoken = Utterance(
            speaker="narrator", text="pause:1000ms",
            utterance_type=UtteranceType.NARRATION,
        )
        pause = Utterance(
            speaker="narrator", text="pause:1000ms",
            utterance_type=UtteranceType.PAUSE,
        )
        assert utterance_hash(spoken, "af_heart", "p") != utterance_hash(
            pause, "af_heart", "p"
        ), (
            "utterance_hash ignores utterance_type — PAUSE and NARRATION "
            "with the same text collide (renderer-cache F-0da2d3a9)"
        )

    def test_utterance_type_is_in_the_chapter_text_hash(self):
        def _ch(kind: UtteranceType) -> Chapter:
            ch = Chapter(index=0, title="One", raw_text="x")
            ch.utterances = [
                Utterance(speaker="narrator", text="pause:1000ms",
                          utterance_type=kind),
            ]
            return ch

        assert chapter_text_hash(_ch(UtteranceType.NARRATION)) != chapter_text_hash(
            _ch(UtteranceType.PAUSE)
        ), (
            "chapter_text_hash ignores utterance_type — a review that "
            "turns a pause into speech still cache-hits"
        )

    def test_character_speed_pitch_emphasis_are_in_utterance_hash(self):
        u = Utterance(
            speaker="Alice", text="Hello there.", emotion="angry",
            utterance_type=UtteranceType.DIALOGUE,
        )
        h_default = utterance_hash(u, "af_bella", "params")
        params = inspect.signature(utterance_hash).parameters
        kwargs: dict = {}
        if "speed" in params:
            kwargs.update(speed=1.4, pitch_shift=-0.3, emphasis=1.7)
        elif "character" in params:
            kwargs["character"] = Character(
                name="Alice", voice="af_bella", speed=1.4,
                pitch_shift=-0.3, emphasis=1.7,
            )
        elif "casting" in params:
            table = CastingTable()
            table.cast("Alice", "af_bella")
            table.characters[CastingTable.normalize_key("Alice")].speed = 1.4
            kwargs["casting"] = table
        else:
            pytest.fail(
                "utterance_hash does not accept speed/pitch/emphasis, "
                "character=, or casting= (renderer-cache F-14251d01) — "
                "awaits sibling merge"
            )
        h_retuned = utterance_hash(u, "af_bella", "params", **kwargs)
        assert h_retuned != h_default, (
            "passing retuned delivery knobs did not change utterance_hash"
        )

    def test_retuning_character_speed_misses_the_utterance_subcache(
        self, tmp_path
    ):
        """Read side. casting_hash already keys speed, so the CHAPTER cache
        misses and render_chapter_incremental runs; each utterance then
        HITS the sub-cache unless utterance_hash sees the knob too."""
        p = _utterance_project(tmp_path)
        cache = tmp_path / "cache"
        render_project(
            p, tmp_path / "out.m4b", engine=FakeTTSEngine(),
            assembler=_tolerant_assembler, cache_root=cache,
            stitch_runner=StitchRunner(),
        )
        alice = p.casting.characters[CastingTable.normalize_key("Alice")]
        alice.speed = 1.4
        engine2 = FakeTTSEngine()
        render_project(
            p, tmp_path / "out2.m4b", engine=engine2,
            assembler=_tolerant_assembler, cache_root=cache,
            stitch_runner=StitchRunner(),
        )
        assert engine2.calls, (
            "retuning Character.speed served the old-speed utterance WAVs "
            "from the sub-cache (renderer-cache F-14251d01)"
        )
        scripts = " ".join(c.script for c in engine2.calls)
        assert "{speed:1.4}" in scripts, scripts


# ===========================================================================
# make / batch / podcast spend gates — cli-surface F-bf22f423, F-86a66bc0
# ===========================================================================

class TestSpendPathsRefuseGuessedAttribution:
    def test_fixture_still_diverges(self):
        from audiobooker.casting import compile_report
        from audiobooker.casting.dialogue import compile_chapter
        from audiobooker.parser.text import split_into_chapters

        title, raw = split_into_chapters("Chapter 1: The Scale\n\n" + LEDGER)[0]
        ch = Chapter(index=0, title=title, raw_text=raw)
        ch.utterances = compile_chapter(ch, CastingTable())
        report = compile_report([ch], CastingTable())
        assert report["quality"] == "ok"
        assert report["attribution_quality"] == "failed", report

    def test_make_does_not_call_render_project(self, tmp_path, monkeypatch):
        from audiobooker.cli import main

        src = _guessed_source(tmp_path)
        calls: list = []

        def _capture(*_a, **_k):
            calls.append(_k)
            out = Path(_k.get("output_path") or (_a[1] if len(_a) > 1 else tmp_path / "x"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"FAKE")
            return out

        monkeypatch.setattr(
            "audiobooker.renderer.engine.render_project", _capture
        )
        monkeypatch.setattr("audiobooker.cli._suggest_voices", _cast_everyone)
        code = main(["make", str(src), "-o", str(tmp_path / "out.m4b")])
        assert not calls, (
            "make spent TTS on a guessed-attribution book without --force "
            f"(cli-surface F-bf22f423); kwargs={calls!r}"
        )
        assert code != 0

    def test_batch_does_not_call_render_project(self, tmp_path, monkeypatch):
        from audiobooker.cli import main

        src = _guessed_source(tmp_path, "book.txt")
        calls: list = []

        def _capture(*_a, **_k):
            calls.append(_k)
            return tmp_path / "out.m4b"

        monkeypatch.setattr(
            "audiobooker.renderer.engine.render_project", _capture
        )
        monkeypatch.setattr("audiobooker.cli._suggest_voices", _cast_everyone)
        code = main(["batch", str(src)])
        assert not calls, (
            "batch spent TTS on a guessed-attribution book without --force "
            f"(cli-surface F-bf22f423); kwargs={calls!r}"
        )
        assert code != 0

    def test_podcast_does_not_call_project_render(self, tmp_path, monkeypatch):
        from audiobooker.cli import main

        project = AudiobookProject.from_string(
            "Chapter 1: The Scale\n\n" + LEDGER,
            title="Ledger", author="A",
        )
        project.compile()
        for speaker in sorted(project.get_uncast_speakers()):
            project.cast(speaker, "af_heart")
        path = tmp_path / "p.audiobooker"
        project.save(path)

        calls: list = []

        def _capture(self, **kwargs):
            calls.append(kwargs)
            return path

        monkeypatch.setattr(AudiobookProject, "render", _capture)
        code = main([
            "podcast", "-p", str(path),
            "--base-url", "https://example.test/",
            "-o", str(tmp_path / "podcast.xml"),
        ])
        assert not calls, (
            "podcast rendered guessed-speaker audio without --force "
            f"(cli-surface F-86a66bc0); kwargs={calls!r}"
        )
        assert code != 0


# ===========================================================================
# chapter.index identity — renderer-cache F-0b11d4e5, F-813e9865
# ===========================================================================

class TestSelectionAndSampleKeyOnChapterIndex:
    def test_include_ranges_selects_by_chapter_index_not_enumerate(self):
        chapters = [
            Chapter(index=0, title="A", raw_text="x"),
            Chapter(index=1, title="B", raw_text="x"),
            Chapter(index=3, title="D", raw_text="x"),
            Chapter(index=4, title="E", raw_text="x"),
        ]
        got = filter_chapters_by_selection(chapters, include_ranges="4")
        assert [c.index for c in got] == [3], (
            "--chapters 4 on a gapped list [0,1,3,4] must keep the chapter "
            f"whose .index is 3 (title D); got {[c.title for c in got]} "
            f"index={[c.index for c in got]} (renderer-cache F-0b11d4e5)"
        )
        assert [c.title for c in got] == ["D"]

    def test_render_sample_writes_chapter_index_wav_not_loop_position(
        self, tmp_path, monkeypatch
    ):
        import audiobooker.renderer.output as output_mod

        monkeypatch.setattr(output_mod, "_ffmpeg_checked", True)
        monkeypatch.setattr(
            "audiobooker.renderer.ffmpeg_runner.RealFFmpegRunner",
            RecordingFfmpeg,
        )

        book = "\n\n".join(
            f"Chapter {n}: Section {n}\n\n"
            f"The hall was cold and nobody spoke about lamp {n}."
            for n in range(1, 5)
        )
        project = AudiobookProject.from_string(book, title="Sel", author="A")
        project.cast("narrator", "af_heart")
        project.compile()
        project.chapters = [c for c in project.chapters if c.index == 3]
        assert [c.index for c in project.chapters] == [3]

        cache = tmp_path / "cache"
        render_sample(
            project,
            from_chapter=3,
            duration=5.0,
            output_path=tmp_path / "sample.m4a",
            engine=FakeTTSEngine(),
            cache_root=cache,
        )
        assert get_chapter_wav_path(cache, 3).exists(), (
            "render_sample keyed the WAV on list position, not chapter.index "
            f"— files: {sorted(p.name for p in cache.rglob('chapter_*.wav'))} "
            "(renderer-cache F-813e9865)"
        )
        assert not get_chapter_wav_path(cache, 0).exists(), (
            "chapter 4's sample wrote chapter_0000.wav"
        )


# ===========================================================================
# import_lexicon — project-core F-33865e9b
# ===========================================================================

class TestImportLexiconBustsCompiledTextHash:
    def test_import_rewrites_compiled_utterances_and_the_hash(self, tmp_path):
        p = AudiobookProject.from_chapters(
            [("One", "Siobhan waited by the gate."),
             ("Two", "The road was empty.")],
            title="Lex",
        )
        p.project_path = tmp_path / "book.abp"
        p.config.validate_voices_on_render = False
        p.compile()
        p.cast("narrator", "af_heart")
        before = chapter_text_hash(p.chapters[0])
        untouched = chapter_text_hash(p.chapters[1])

        lex = tmp_path / "lex.json"
        lex.write_text(json.dumps({"Siobhan": "shiv-AWN"}), encoding="utf-8")
        p.import_lexicon(lex)

        joined = " ".join(u.text for u in p.chapters[0].utterances)
        assert "shiv-AWN" in joined, (
            "import_lexicon merged the override into config but left "
            f"compiled utterance text untouched: {joined!r} "
            "(project-core F-33865e9b)"
        )
        assert chapter_text_hash(p.chapters[0]) != before, (
            "chapter_text_hash was unchanged after import_lexicon — the "
            "next render will cache-hit the old pronunciation"
        )
        assert chapter_text_hash(p.chapters[1]) == untouched
