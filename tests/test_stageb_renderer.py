"""
Stage B (proactive health) regression tests for the renderer.

Every test in this file was written to FAIL against the pre-fix renderer and
pass against the fix. Hermetic: no real ffmpeg, no voice-soundboard, no
network.

Covered findings:

- RH-B-001  loudness mastering was silently discarded for every format except
            m4b (``normalize`` was appended LAST to ``optional_kwargs`` and
            ``_call_assembler`` stripped optional kwargs from the END on
            TypeError, so it was always the first thing dropped). An
            ``--acx`` "retail master" in mp3/opus/flac/--split therefore
            shipped with zero loudness normalization and zero user-visible
            signal, because ``AssemblyResult.mastering_applied`` kept its
            ``True`` default and the ``ACX_MASTER_NOT_APPLIED`` path could
            not fire.
- RH-B-002  ``AssemblyResult.chapters_embedded`` / ``mastering_applied`` /
            ``mastering_error`` reached no caller. A chapterless .m4b (the
            chapter-marker mux failed and the chapterless AAC was copied to
            the .m4b) came back as a summary whose ``is_complete`` was True,
            with the only evidence a stderr WARNING.
- RH-B-003  ``--jobs N`` drove ONE engine instance from N threads with no
            documented thread-safety contract, so a stateful third-party
            engine registered through the ``audiobooker.tts_engines`` entry
            point was entered concurrently by construction.
- RH-B-004  ``dry_run_render`` computed ``render_params_hash(project.config)``
            with no ``engine=`` and no ``output_profile=`` while the real
            render passed both, so ``render --acx --dry-run`` reported every
            chapter cached and the real ``--acx`` render then re-rendered the
            whole book.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import pytest

import audiobooker.renderer.output as output_mod
from audiobooker.models import Chapter, Utterance, UtteranceType
from audiobooker.project import AudiobookProject
from audiobooker.renderer import engine as engine_mod
from audiobooker.renderer.engine import (
    RenderSummary,
    dry_run_render,
    render_project_detailed,
)
from audiobooker.renderer.output import (
    AssemblyResult,
    assemble_flac,
    assemble_m4a_split,
    assemble_mp3,
    assemble_mp3_chapters,
    assemble_opus,
)
from audiobooker.renderer.protocols import SynthesisResult, TTSEngine
from tests.fakes.fake_ffmpeg import FakeAssembler
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav


# ---------------------------------------------------------------------------
# Test doubles / helpers
# ---------------------------------------------------------------------------

class RecordingRunner:
    """FFmpegRunner double that records every command and always succeeds."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        from audiobooker.renderer.protocols import RunResult

        self.calls.append(list(args))
        return RunResult(returncode=0, stdout="", stderr="")

    def flat(self) -> str:
        return " ".join(arg for call in self.calls for arg in call)

    def has_loudnorm(self) -> bool:
        """True when a real loudnorm FILTER was passed (not a path match)."""
        return any("loudnorm=I=" in arg for call in self.calls for arg in call)


@pytest.fixture(autouse=True)
def _ffmpeg_available():
    """Force check_ffmpeg() available without spawning ffmpeg."""
    prev = output_mod._ffmpeg_checked
    output_mod._ffmpeg_checked = True
    yield
    output_mod._ffmpeg_checked = prev


def _chapter_files(tmp_path: Path, n: int = 2) -> list[tuple[Path, str, float]]:
    files = []
    for i in range(n):
        wav = tmp_path / f"sbr_ch{i}.wav"
        write_silence_wav(wav, duration_s=0.25)
        files.append((wav, f"Chapter {i + 1}", 0.25))
    return files


def _make_chapter(index: int, utterances: int = 2) -> Chapter:
    ch = Chapter(index=index, title=f"Chapter {index + 1}", raw_text="Hello world " * 20)
    for i in range(utterances):
        ch.utterances.append(
            Utterance(
                speaker="narrator" if i % 2 == 0 else "Alice",
                text=f"Utterance {i} of chapter {index}.",
                utterance_type=(
                    UtteranceType.NARRATION if i % 2 == 0 else UtteranceType.DIALOGUE
                ),
                chapter_index=index,
                line_index=i,
            )
        )
    return ch


def _make_project(num_chapters: int = 2) -> AudiobookProject:
    project = AudiobookProject(title="Stage B Book", author="Tester")
    project.cast("narrator", "af_heart")
    project.cast("Alice", "af_bella")
    for i in range(num_chapters):
        project.chapters.append(_make_chapter(i))
    return project


class PartialKwargAssembler:
    """An assembler that DECLARES ``normalize`` but not the other optionals.

    This is the exact shape the old TypeError-stripping loop got wrong: it
    dropped optional kwargs from the END, and ``normalize`` was appended last,
    so an assembler missing any earlier optional kwarg lost ``normalize``
    first — and then kept losing kwargs until the call type-checked, ending
    with every optional kwarg dropped including the one it could honour.
    """

    def __init__(self) -> None:
        self.received: dict = {}

    def __call__(
        self,
        chapter_files,
        output_path,
        title: str = "Audiobook",
        author: str = "",
        chapter_pause_ms: int = 2000,
        *,
        normalize: bool = False,
        loudnorm_profile: str = "podcast",
    ) -> AssemblyResult:
        self.received = {
            "normalize": normalize,
            "loudnorm_profile": loudnorm_profile,
        }
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"FAKE")
        return AssemblyResult(
            output_path=output_path,
            chapters_embedded=True,
            mastering_applied=bool(normalize),
        )


class VarKwargsAssembler:
    """Declares ``**kwargs`` but rejects ``normalize`` at call time.

    A signature alone cannot prove support here, so the residual TypeError
    path must still reopen the "mastering did not happen" verdict.
    """

    def __call__(
        self,
        chapter_files,
        output_path,
        title: str = "Audiobook",
        author: str = "",
        chapter_pause_ms: int = 2000,
        **kwargs,
    ) -> AssemblyResult:
        if "normalize" in kwargs:
            raise TypeError("__call__() got an unexpected keyword 'normalize'")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"FAKE")
        return AssemblyResult(output_path=output_path, chapters_embedded=True)


class BodyRaisesTypeErrorAssembler:
    """Fully signature-readable, and raises TypeError from its own BODY.

    F-e29a147c. Every optional kwarg is declared, so a BINDING TypeError is
    impossible here -- any TypeError is a real internal error (the message is
    the one a real `", ".join()` over a None field produces). The render must
    not reinterpret it as "that kwarg is unsupported".
    """

    def __init__(self) -> None:
        self.attempts = 0

    def __call__(self, chapter_files, output_path, title="Audiobook", author="",
                 chapter_pause_ms=2000, metadata=None, cover_art=None,
                 normalize=False, loudnorm_profile=None, aac_bitrate=None,
                 bitrate=None):
        self.attempts += 1
        if metadata is not None:
            raise TypeError("sequence item 0: expected str instance, NoneType found")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"FAKE")
        return AssemblyResult(output_path=output_path, chapters_embedded=True,
                              mastering_applied=bool(normalize))


class ConcurrencyProbeEngine:
    """Records the maximum number of threads inside synthesize() at once."""

    def __init__(self, thread_safe: Optional[bool] = None, hold: float = 0.05) -> None:
        self._thread_safe = thread_safe
        self._hold = hold
        self._lock = threading.Lock()
        self._inside = 0
        self.max_concurrent = 0
        self.calls = 0

    def capabilities(self) -> dict[str, bool]:
        caps = {
            "streaming": False,
            "emotions": False,
            "ssml": False,
            "multi_speaker": False,
        }
        if self._thread_safe is not None:
            caps["thread_safe"] = self._thread_safe
        return caps

    def synthesize(
        self,
        script: str,
        voices: dict[str, str],
        output_path: Path,
        progress_callback: Optional[Callable] = None,
    ) -> SynthesisResult:
        with self._lock:
            self._inside += 1
            self.calls += 1
            self.max_concurrent = max(self.max_concurrent, self._inside)
        try:
            time.sleep(self._hold)
            output_path = Path(output_path)
            write_silence_wav(output_path, 0.25)
            return SynthesisResult(audio_path=output_path, duration_seconds=0.25)
        finally:
            with self._lock:
                self._inside -= 1


class BarrierEngine:
    """Engine that advertises thread safety and proves real parallelism.

    Two workers must meet at the barrier; if the renderer serialized the
    calls the barrier times out and ``parallel`` stays False.
    """

    def __init__(self, parties: int = 2, timeout: float = 5.0) -> None:
        self._barrier = threading.Barrier(parties)
        self._timeout = timeout
        self.parallel = False

    def capabilities(self) -> dict[str, bool]:
        return {
            "streaming": False,
            "emotions": False,
            "ssml": False,
            "multi_speaker": False,
            "thread_safe": True,
        }

    def synthesize(
        self,
        script: str,
        voices: dict[str, str],
        output_path: Path,
        progress_callback: Optional[Callable] = None,
    ) -> SynthesisResult:
        try:
            self._barrier.wait(timeout=self._timeout)
            self.parallel = True
        except threading.BrokenBarrierError:
            pass
        output_path = Path(output_path)
        write_silence_wav(output_path, 0.25)
        return SynthesisResult(audio_path=output_path, duration_seconds=0.25)


# ---------------------------------------------------------------------------
# RH-B-001 — loudness mastering must reach every assembler, or say so loudly
# ---------------------------------------------------------------------------

class TestNormalizeReachesEveryAssembler:
    """Only assemble_m4b accepted ``normalize``; the rest silently produced
    un-normalized audio for --normalize and for every --acx retail master."""

    def test_mp3_chapters_accepts_and_applies_normalize(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_mp3_chapters(
            _chapter_files(tmp_path),
            tmp_path / "mp3out",
            runner=runner,
            normalize=True,
            loudnorm_profile="acx",
        )
        assert runner.has_loudnorm()

    def test_mp3_reports_mastering_applied(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_mp3(
            _chapter_files(tmp_path),
            tmp_path / "book.mp3",
            runner=runner,
            normalize=True,
            loudnorm_profile="acx",
        )
        assert result.mastering_applied is True
        assert runner.has_loudnorm()

    def test_opus_accepts_and_applies_normalize(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_opus(
            _chapter_files(tmp_path),
            tmp_path / "book.opus",
            runner=runner,
            normalize=True,
        )
        assert runner.has_loudnorm()
        assert result.mastering_applied is True

    def test_flac_accepts_and_applies_normalize(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_flac(
            _chapter_files(tmp_path),
            tmp_path / "book.flac",
            runner=runner,
            normalize=True,
        )
        assert runner.has_loudnorm()
        assert result.mastering_applied is True

    def test_m4a_split_accepts_and_applies_normalize(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_m4a_split(
            _chapter_files(tmp_path),
            tmp_path / "book.m4b",
            runner=runner,
            normalize=True,
            loudnorm_profile="acx",
        )
        assert runner.has_loudnorm()
        assert result.mastering_applied is True

    def test_no_loudnorm_when_not_requested(self, tmp_path: Path):
        """Regression guard: the default path must not gain an ffmpeg call."""
        runner = RecordingRunner()
        result = assemble_opus(
            _chapter_files(tmp_path), tmp_path / "book.opus", runner=runner,
        )
        assert not runner.has_loudnorm()
        assert result.mastering_applied is True


class TestAssemblerKwargBindingBySignature:
    """Kwargs must be bound by inspecting the signature, not discovered by
    catching TypeError and stripping from the end."""

    def test_partial_assembler_still_receives_normalize(self, tmp_path: Path):
        project = _make_project(num_chapters=1)
        assembler = PartialKwargAssembler()

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
            normalize=True,
            output_profile="acx",
        )

        assert assembler.received.get("normalize") is True
        assert assembler.received.get("loudnorm_profile") == "acx"

    def test_unsupported_normalize_is_not_a_silent_success(
        self, tmp_path: Path, caplog
    ):
        """The headline assertion for RH-B-001: requesting ``normalize``
        against an assembler that cannot honour it must NOT come back as a
        success carrying ``mastering_applied=True``."""
        project = _make_project(num_chapters=1)
        # FakeAssembler takes only the base five kwargs — it cannot normalize.
        assembler = FakeAssembler()

        with caplog.at_level(logging.ERROR, logger="audiobooker.renderer"):
            summary = render_project_detailed(
                project,
                tmp_path / "book.mp3",
                engine=FakeTTSEngine(),
                assembler=assembler,
                cache_root=tmp_path / "cache",
                normalize=True,
                output_format="mp3",
            )

        assert summary.mastering_applied is False
        assert summary.mastering_error
        assert summary.is_retail_ready is False
        # The ERROR must name the format the user actually asked for.
        assert "mp3" in caplog.text.lower()

    def test_acx_forces_normalize_and_reports_the_gap(self, tmp_path: Path, caplog):
        """--acx forces effective_normalize=True; an assembler that cannot
        honour it must not yield a silently un-normalized 'retail master'."""
        project = _make_project(num_chapters=1)

        with caplog.at_level(logging.ERROR, logger="audiobooker.renderer"):
            summary = render_project_detailed(
                project,
                tmp_path / "book.mp3",
                engine=FakeTTSEngine(),
                assembler=FakeAssembler(),
                cache_root=tmp_path / "cache",
                output_profile="acx",
                output_format="mp3",
            )

        assert summary.mastering_applied is False
        assert summary.is_retail_ready is False

    def test_var_kwargs_assembler_rejecting_normalize_is_reported(
        self, tmp_path: Path, caplog
    ):
        """A ``**kwargs`` assembler hides its real shape, so the residual
        TypeError drop must still flip the mastering verdict — and say so."""
        project = _make_project(num_chapters=1)

        with caplog.at_level(logging.WARNING, logger="audiobooker.renderer"):
            summary = render_project_detailed(
                project,
                tmp_path / "book.m4b",
                engine=FakeTTSEngine(),
                assembler=VarKwargsAssembler(),
                cache_root=tmp_path / "cache",
                normalize=True,
            )

        assert summary.mastering_applied is False
        assert summary.is_retail_ready is False
        assert "normalize" in caplog.text

    def test_supported_normalize_reports_applied(self, tmp_path: Path):
        project = _make_project(num_chapters=1)
        summary = render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=PartialKwargAssembler(),
            cache_root=tmp_path / "cache",
            normalize=True,
        )
        assert summary.mastering_applied is True
        assert summary.mastering_error == ""
        assert summary.is_retail_ready is True


class TestBodyRaisedTypeErrorIsNotAKwargVerdict:
    """F-e29a147c: a TypeError from inside a signature-readable assembler is a
    real error, not evidence that a kwarg is unsupported.

    Signature binding (RH-B-001) fixed `normalize` always being dropped, but
    left the retry loop running for assemblers whose signature IS readable --
    where a binding TypeError cannot occur, so the loop could only ever be
    eating a genuine internal failure.
    """

    def test_body_typeerror_propagates_instead_of_stripping_kwargs(
        self, tmp_path: Path
    ):
        project = _make_project(num_chapters=1)
        assembler = BodyRaisesTypeErrorAssembler()

        with pytest.raises(TypeError, match="expected str instance"):
            render_project_detailed(
                project,
                tmp_path / "book.m4b",
                engine=FakeTTSEngine(),
                assembler=assembler,
                cache_root=tmp_path / "cache",
                normalize=True,
                output_profile="acx",
            )

        # Called ONCE. Before the fix it was called five times, stripping
        # normalize -> aac_bitrate -> loudnorm_profile -> metadata and then
        # returning a "successful" render of a book with no metadata.
        assert assembler.attempts == 1

    def test_body_typeerror_does_not_produce_a_false_kwarg_diagnosis(
        self, tmp_path: Path, caplog
    ):
        """The regression that made this worse than silence.

        The old loop logged RENDER_ASSEMBLER_KWARG_DROPPED naming 'normalize'
        as rejected by an assembler whose signature declares it -- a specific,
        checkable, WRONG cause that sends the reader to audit the signature.
        """
        project = _make_project(num_chapters=1)
        assembler = BodyRaisesTypeErrorAssembler()

        with caplog.at_level(logging.WARNING):
            with pytest.raises(TypeError):
                render_project_detailed(
                    project,
                    tmp_path / "book.m4b",
                    engine=FakeTTSEngine(),
                    assembler=assembler,
                    cache_root=tmp_path / "cache",
                    normalize=True,
                    output_profile="acx",
                )

        assert "RENDER_ASSEMBLER_KWARG_DROPPED" not in caplog.text
        assert "does not accept" not in caplog.text

    def test_var_kwargs_assembler_keeps_the_retry_path(self, tmp_path: Path):
        """The loop is narrowed, not removed.

        `**kwargs` hides the real shape, so the signature cannot prove support
        and drop-and-retry is still the only way to find out. Guards against
        "fixing" this by deleting the loop outright.
        """
        project = _make_project(num_chapters=1)
        assembler = VarKwargsAssembler()

        summary = render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
            normalize=True,
            output_profile="acx",
        )

        assert summary is not None


class TestAcxMasterVerificationOnDirectoryOutput:
    """``_verify_acx_master`` returned at its ``is_file()`` guard for mp3 /
    --split output, so a directory-shaped ACX master that skipped mastering
    was never reported."""

    def test_directory_output_still_reports_mastering_not_applied(
        self, tmp_path: Path, caplog
    ):
        out_dir = tmp_path / "book_mp3s"
        out_dir.mkdir()
        assembly = AssemblyResult(
            output_path=out_dir,
            chapters_embedded=True,
            mastering_applied=False,
            mastering_error="loudnorm pass failed (rc=1)",
        )
        summary = RenderSummary(output_path=out_dir)

        with caplog.at_level(logging.ERROR, logger="audiobooker.renderer"):
            engine_mod._verify_acx_master(assembly, summary)

        assert summary.acx_check is not None
        assert summary.acx_check["passes"] is False
        assert "ACX_MASTER_NOT_APPLIED" in caplog.text


# ---------------------------------------------------------------------------
# RH-B-002 — degradation flags must reach the caller
# ---------------------------------------------------------------------------

class TestDegradationFlagsReachTheSummary:
    def test_chapterless_output_is_recorded_on_the_summary(self, tmp_path: Path):
        project = _make_project(num_chapters=2)
        summary = render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=FakeAssembler(chapters_embedded=False),
            cache_root=tmp_path / "cache",
        )

        assert summary.chapters_embedded is False
        assert "fake chapter error" in summary.chapter_error
        # An audiobook with no chapter navigation is retail-blocking.
        assert summary.is_retail_ready is False

    def test_chapterless_output_warns_through_progress_callback(self, tmp_path: Path):
        """A stderr WARNING scrolls away; the renderer's own progress channel
        is the one a terminal-only session actually keeps."""
        project = _make_project(num_chapters=2)
        messages: list[str] = []

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            progress_callback=lambda c, t, s: messages.append(s),
            engine=FakeTTSEngine(),
            assembler=FakeAssembler(chapters_embedded=False),
            cache_root=tmp_path / "cache",
        )

        joined = " ".join(messages).lower()
        assert "chapter" in joined
        assert "warning" in joined

    def test_complete_render_is_retail_ready(self, tmp_path: Path):
        project = _make_project(num_chapters=2)
        summary = render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=FakeAssembler(),
            cache_root=tmp_path / "cache",
        )
        assert summary.chapters_embedded is True
        assert summary.chapter_error == ""
        assert summary.mastering_applied is True
        assert summary.is_complete is True
        assert summary.is_retail_ready is True

    def test_render_summary_defaults_are_non_degraded(self):
        summary = RenderSummary(output_path=Path("x.m4b"))
        assert summary.chapters_embedded is True
        assert summary.chapter_error == ""
        assert summary.mastering_applied is True
        assert summary.mastering_error == ""
        assert summary.is_retail_ready is True


# ---------------------------------------------------------------------------
# RH-B-003 — --jobs N must not enter a stateful engine concurrently
# ---------------------------------------------------------------------------

class TestEngineThreadSafetyContract:
    def test_capabilities_default_declares_thread_safe_false(self):
        caps = TTSEngine.capabilities(None)  # type: ignore[arg-type]
        assert caps["thread_safe"] is False

    def test_protocol_documents_the_thread_safety_contract(self):
        doc = TTSEngine.capabilities.__doc__ or ""
        assert "thread_safe" in doc

    def test_engine_without_capabilities_is_treated_as_unsafe(self):
        assert engine_mod.engine_is_thread_safe(FakeTTSEngine()) is False

    def test_engine_advertising_thread_safe_is_trusted(self):
        assert engine_mod.engine_is_thread_safe(BarrierEngine()) is True

    def test_parallel_render_serializes_an_unsafe_engine(self, tmp_path: Path, caplog):
        project = _make_project(num_chapters=4)
        probe = ConcurrencyProbeEngine(thread_safe=None)

        with caplog.at_level(logging.WARNING, logger="audiobooker.renderer"):
            render_project_detailed(
                project,
                tmp_path / "book.m4b",
                engine=probe,
                assembler=FakeAssembler(),
                cache_root=tmp_path / "cache",
                jobs=4,
            )

        assert probe.calls == 4
        assert probe.max_concurrent == 1, (
            "synthesize() was entered concurrently on an engine that never "
            "advertised thread safety"
        )
        assert "thread" in caplog.text.lower()

    def test_engine_declaring_thread_safe_false_is_serialized(self, tmp_path: Path):
        project = _make_project(num_chapters=4)
        probe = ConcurrencyProbeEngine(thread_safe=False)

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=probe,
            assembler=FakeAssembler(),
            cache_root=tmp_path / "cache",
            jobs=4,
        )
        assert probe.max_concurrent == 1

    def test_thread_safe_engine_still_runs_in_parallel(self, tmp_path: Path):
        project = _make_project(num_chapters=4)
        eng = BarrierEngine(parties=2, timeout=5.0)

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=eng,
            assembler=FakeAssembler(),
            cache_root=tmp_path / "cache",
            jobs=4,
        )
        assert eng.parallel is True, (
            "an engine advertising thread_safe=True must not be serialized"
        )

    def test_serializing_does_not_change_the_cache_key(self, tmp_path: Path):
        """The lock wrapper must not become part of the engine identity —
        that would invalidate every cached chapter on a --jobs render."""
        from audiobooker.renderer.hash_utils import render_params_hash

        project = _make_project(num_chapters=4)
        probe = ConcurrencyProbeEngine(thread_safe=None)
        expected = render_params_hash(
            project.config, engine=probe, output_profile="podcast"
        )

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=probe,
            assembler=FakeAssembler(),
            cache_root=tmp_path / "cache",
            jobs=4,
        )

        from audiobooker.renderer.cache_manifest import (
            get_manifest_path, load_manifest,
        )

        manifest = load_manifest(get_manifest_path(tmp_path / "cache"))
        assert manifest is not None
        entry = manifest.get_entry(0)
        assert entry is not None
        assert entry.render_params_hash == expected


# ---------------------------------------------------------------------------
# RH-B-004 — dry-run must key the cache exactly like the real render
# ---------------------------------------------------------------------------

class TestDryRunHashParity:
    def _record_hashes(self, monkeypatch) -> list[dict]:
        import audiobooker.renderer.hash_utils as hash_mod

        real = hash_mod.render_params_hash
        seen: list[dict] = []

        def spy(config, *, engine=None, output_profile=None):
            value = real(config, engine=engine, output_profile=output_profile)
            seen.append({
                "engine": engine,
                "output_profile": output_profile,
                "hash": value,
            })
            return value

        monkeypatch.setattr(hash_mod, "render_params_hash", spy)
        return seen

    def test_dry_run_and_render_agree_on_the_params_hash(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        seen = self._record_hashes(monkeypatch)
        project = _make_project(num_chapters=1)
        eng = FakeTTSEngine()

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=eng,
            assembler=FakeAssembler(),
            cache_root=tmp_path / "cache",
            output_profile="acx",
        )
        render_hash = seen[-1]["hash"]

        seen.clear()
        dry_run_render(project, resume=False, engine=eng, output_profile="acx")
        capsys.readouterr()
        dry_hash = seen[-1]["hash"]

        assert dry_hash == render_hash

    def test_dry_run_defaults_match_render_defaults(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        seen = self._record_hashes(monkeypatch)
        project = _make_project(num_chapters=1)
        eng = FakeTTSEngine()

        render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=eng,
            assembler=FakeAssembler(),
            cache_root=tmp_path / "cache",
        )
        render_hash = seen[-1]["hash"]

        seen.clear()
        dry_run_render(project, resume=False, engine=eng)
        capsys.readouterr()
        assert seen[-1]["hash"] == render_hash

    def test_acx_dry_run_does_not_reuse_the_podcast_profile_hash(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """The user-visible symptom: ``render --acx --dry-run`` reported every
        chapter cached (it hashed the stored config profile), and then the
        real ``--acx`` render re-rendered the whole book."""
        seen = self._record_hashes(monkeypatch)
        project = _make_project(num_chapters=1)
        eng = FakeTTSEngine()

        dry_run_render(project, resume=False, engine=eng, output_profile="podcast")
        capsys.readouterr()
        podcast_hash = seen[-1]["hash"]

        seen.clear()
        dry_run_render(project, resume=False, engine=eng, output_profile="acx")
        capsys.readouterr()
        acx_hash = seen[-1]["hash"]

        assert acx_hash != podcast_hash
