"""`utterance_cache = true` silently removed every pause in the book.

`preprocess_ssml` emits the inter-speaker `<break time="750ms"/>` only when
`prev_speaker is not None` — i.e. only *between* two utterances in one call.
The incremental path calls it with a one-element list per utterance, so
`prev_speaker` is None on the only iteration, every time, and no break is
ever emitted. The stitch then concatenates with `-c copy`, which inserts
nothing.

Net effect of opting in: every speaker change across the whole book loses its
750 ms of air. Dialogue runs together. Nothing warns, the durations look
plausible, and the utterance cache reports a hit rate it has genuinely
earned — on audio that is not the audio the chapter path produces.

The pause belongs *between* two utterances, so it is inserted at stitch time
rather than baked into either neighbour's cached WAV. Baking it in would make
an utterance's bytes depend on its neighbour, which is the coupling the
per-utterance cache exists to avoid.
"""

from __future__ import annotations

import wave
from pathlib import Path

from audiobooker.models import CastingTable, Chapter, Utterance, UtteranceType
from audiobooker.renderer.engine import (
    SPEAKER_CHANGE_BREAK_MS,
    preprocess_ssml,
    render_chapter_incremental,
)
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav


class _ConcatRecordingRunner:
    """Fake ffmpeg runner that reads the concat list *during* the call.

    `_stitch_utterance_wavs` deletes the concat file in a `finally`, so the
    list has to be captured while the call is in flight — recording argv
    alone would only preserve a path that no longer exists.

    The output WAV duration is the SUM of the listed files, not a fixed
    0.1s clip. A duration assertion can therefore fail if the stitch
    omitted the speaker-change gaps.
    """

    def __init__(self) -> None:
        self.concat_entries: list[Path] = []

    def run(self, args: list[str]):
        from audiobooker.renderer.protocols import RunResult

        concat_file = Path(args[args.index("-i") + 1])
        listed: list[Path] = []
        for line in concat_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("file "):
                p = Path(line[6:-1])
                self.concat_entries.append(p)
                listed.append(p)

        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        total = sum(_wav_duration(p) for p in listed if p.exists())
        write_silence_wav(out, total if total > 0 else 0.1)
        return RunResult(returncode=0, stdout="", stderr="")


def _casting() -> CastingTable:
    casting = CastingTable()
    casting.cast("narrator", "af_heart")
    casting.cast("Alice", "af_bella")
    casting.cast("Bob", "bm_george")
    return casting


def _chapter() -> Chapter:
    """Four utterances, three speaker changes — so the chapter path emits
    exactly three breaks and the difference is countable."""
    ch = Chapter(index=0, title="Chapter 1", raw_text="x")
    ch.utterances = [
        Utterance(speaker="narrator", text="The hall was cold.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker="Alice", text="Two ounces light.",
                  utterance_type=UtteranceType.DIALOGUE),
        Utterance(speaker="Bob", text="The scale is wrong.",
                  utterance_type=UtteranceType.DIALOGUE),
        Utterance(speaker="narrator", text="Nobody moved.",
                  utterance_type=UtteranceType.NARRATION),
    ]
    return ch


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


class TestThePremise:
    def test_single_utterance_ssml_carries_no_break(self):
        """Why the bug exists, asserted rather than assumed. If this ever
        stops being true the fix below is solving nothing."""
        utts = _chapter().utterances
        whole = preprocess_ssml(utts)
        per_utterance = [preprocess_ssml([u]) for u in utts]

        assert whole.count("<break") == 3
        assert sum(p.count("<break") for p in per_utterance) == 0


class TestStitchRestoresThePauses:
    def test_silence_is_concatenated_at_every_speaker_change(self, tmp_path):
        runner = _ConcatRecordingRunner()

        render_chapter_incremental(
            _chapter(), _casting(), tmp_path / "chapter_0000.wav",
            engine=FakeTTSEngine(),
            cache_root=tmp_path / "cache",
            render_params_hash="paramhash",
            runner=runner,
        )

        # 4 utterances + 3 speaker-change gaps.
        assert len(runner.concat_entries) == 7, (
            "the chapter was stitched from "
            f"{len(runner.concat_entries)} parts — every speaker change "
            "should contribute a silence segment between the two voices"
        )

        gaps = [p for p in runner.concat_entries if "gap" in p.name]
        assert len(gaps) == 3
        for gap in gaps:
            assert abs(
                _wav_duration(gap) - SPEAKER_CHANGE_BREAK_MS / 1000.0
            ) < 0.01, f"{gap.name} is {_wav_duration(gap):.3f}s"

    def test_gaps_land_between_the_speakers_that_changed(self, tmp_path):
        runner = _ConcatRecordingRunner()

        render_chapter_incremental(
            _chapter(), _casting(), tmp_path / "chapter_0000.wav",
            engine=FakeTTSEngine(),
            cache_root=tmp_path / "cache",
            render_params_hash="paramhash",
            runner=runner,
        )

        shape = ["gap" if "gap" in p.name else "utt"
                 for p in runner.concat_entries]
        assert shape == ["utt", "gap", "utt", "gap", "utt", "gap", "utt"]

    def test_no_gap_when_the_speaker_does_not_change(self, tmp_path):
        ch = _chapter()
        ch.utterances = [
            Utterance(speaker="narrator", text="One.",
                      utterance_type=UtteranceType.NARRATION),
            Utterance(speaker="narrator", text="Two.",
                      utterance_type=UtteranceType.NARRATION),
        ]
        runner = _ConcatRecordingRunner()

        render_chapter_incremental(
            ch, _casting(), tmp_path / "chapter_0000.wav",
            engine=FakeTTSEngine(),
            cache_root=tmp_path / "cache",
            render_params_hash="paramhash",
            runner=runner,
        )

        assert [p for p in runner.concat_entries if "gap" in p.name] == []
        assert len(runner.concat_entries) == 2

    def test_reported_duration_includes_the_pauses(self, tmp_path):
        """The gaps are real audio in the chapter file, so a duration that
        omits them under-reports the book and desynchronises chapter marks."""
        runner = _ConcatRecordingRunner()

        result = render_chapter_incremental(
            _chapter(), _casting(), tmp_path / "chapter_0000.wav",
            engine=FakeTTSEngine(),
            cache_root=tmp_path / "cache",
            render_params_hash="paramhash",
            runner=runner,
        )

        speech = sum(
            _wav_duration(p)
            for p in runner.concat_entries
            if "gap" not in p.name
        )
        expected = speech + 3 * (SPEAKER_CHANGE_BREAK_MS / 1000.0)
        assert abs(result.duration_seconds - expected) < 0.05, (
            f"reported {result.duration_seconds:.3f}s, "
            f"stitched {expected:.3f}s"
        )
        # The runner now writes a WAV whose duration is the sum of the
        # concat list, so omitting the gaps would shrink the file even if
        # duration_seconds was computed from gap_before.
        assert abs(_wav_duration(result.audio_path) - expected) < 0.05, (
            f"assembled file is {_wav_duration(result.audio_path):.3f}s, "
            f"stitched {expected:.3f}s"
        )

    def test_a_cached_utterance_wav_holds_no_pause(self, tmp_path):
        """The pause is a *between* thing. Baking it into a neighbour's
        cached WAV would make that WAV depend on its neighbour, which is
        exactly the coupling a per-utterance cache exists to avoid.

        FakeTTSEngine now grows the WAV when the script contains
        ``<break time="750ms"/>``. Comparing utterance durations to each
        other used to pass against that bake: every call wrote the same
        0.25s silence regardless of SSML. This asserts each cached WAV
        matches speech-only duration (breaks stripped).
        """
        cache_root = tmp_path / "cache"
        runner = _ConcatRecordingRunner()
        engine = FakeTTSEngine()

        render_chapter_incremental(
            _chapter(), _casting(), tmp_path / "chapter_0000.wav",
            engine=engine,
            cache_root=cache_root,
            render_params_hash="paramhash",
            runner=runner,
        )

        utt_wavs = [p for p in runner.concat_entries if "gap" not in p.name]
        assert utt_wavs, "nothing was cached"
        assert len(engine.calls) == len(utt_wavs), (
            f"{len(engine.calls)} synthesize() calls for "
            f"{len(utt_wavs)} cached utterance WAVs"
        )
        for wav, call in zip(utt_wavs, engine.calls):
            assert cache_root in wav.parents, (
                f"{wav} is not in the utterance cache"
            )
            assert "<break" not in call.script, (
                "the speaker-change pause was baked into the cached "
                f"utterance script: {call.script!r}"
            )
            speech_only = FakeTTSEngine.duration_for(
                FakeTTSEngine.strip_breaks(call.script),
                call.voices,
                duration_per_call=engine.duration_per_call,
            )
            got = _wav_duration(wav)
            assert abs(got - speech_only) < 0.02, (
                f"{wav.name} is {got:.3f}s; speech-only FakeTTS duration "
                f"is {speech_only:.3f}s — a baked "
                f"{SPEAKER_CHANGE_BREAK_MS}ms break would add "
                f"{SPEAKER_CHANGE_BREAK_MS / 1000.0:.3f}s"
            )
