"""
Wave-2 amend regression tests — renderer domain.

Wave 1 established that the existing renderer fixtures use shapes that CANNOT
express the defects they claim to cover (a fake runner that only ever returns
``str`` can never show the CJK-stderr crash; a cache-key test that only varies
sample_rate can never show a missing engine field). Every test in this file is
written in the FAILING shape: it reproduces the defect against the real code
path, so it goes red before the fix and green after.

Covered findings:
  renderer-crit-1-cjk-stderr      ffmpeg_runner decodes stderr with the locale
                                  codepage -> None stderr on CJK titles
  renderer-crit-2-cache-key       TTS engine + output profile absent from the
                                  render cache key
  renderer-crit-3-sample-stale    render_sample reuses a WAV its own hash check
                                  just rejected
  renderer-crit-4-partial-silent  a partial render is indistinguishable from a
                                  complete one
  renderer-crit-5-acx-rms         ACX "RMS" check measured EBU R128 LUFS
  renderer-high-6-render-lock     non-atomic, PID-only render lock
  renderer-high-7-cache-size      truncated WAV caches as ok
  renderer-high-9-cue-escape      unescaped quotes in CUE titles
  renderer-high-10-chapter-name   unbounded per-chapter filenames
  renderer-high-11-emotion-preset emotion_preset threaded by no caller
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

import pytest

import audiobooker.renderer.output as output_mod
from audiobooker.models import ProjectConfig
from audiobooker.project import AudiobookProject
from audiobooker.renderer import engine as engine_mod
from audiobooker.renderer import ffmpeg_runner as ffmpeg_runner_mod
from audiobooker.renderer.cache_manifest import (
    ChapterCacheEntry,
    get_chapter_wav_path,
    get_manifest_path,
    load_manifest,
)
from audiobooker.renderer.hash_utils import render_params_hash
from audiobooker.renderer.output import AssemblyResult, export_chapter_metadata, master_check
from audiobooker.renderer.protocols import RunResult
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav


# ---------------------------------------------------------------------------
# Shared doubles
# ---------------------------------------------------------------------------

BOOK_TEXT = (
    "Chapter 1: The Harbor\n\n"
    "The tide came in slowly. "
    '"We should go," said Alice.\n\n'
    "Chapter 2: The Lighthouse\n\n"
    "The lamp turned through the fog. "
    '"Not yet," Alice answered.\n\n'
    "Chapter 3: The Return\n\n"
    "Morning found the boat empty. "
    '"So it ends," said Alice.'
)


def _make_project(title: str = "Amend Book") -> AudiobookProject:
    project = AudiobookProject.from_string(BOOK_TEXT, title=title, author="Amend Author")
    project.cast("narrator", "af_heart", emotion="calm")
    project.cast("Alice", "af_bella", emotion="warm")
    project.compile()
    return project


class RecordingAssembler:
    """Assembler double that materializes the output file and records kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> AssemblyResult:
        self.calls.append(kwargs)
        out = Path(kwargs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE-AUDIO")
        return AssemblyResult(output_path=out, chapters_embedded=True)


class RecordingRunner:
    """FFmpegRunner double: always succeeds, optionally creates the output file."""

    def __init__(self, create_output: bool = True) -> None:
        self.calls: list[list[str]] = []
        self._create_output = create_output

    def run(self, args: list[str]) -> RunResult:
        self.calls.append(list(args))
        if self._create_output and args:
            last = args[-1]
            if last != "-" and not last.startswith("-"):
                try:
                    p = Path(last)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"FAKE")
                except OSError:
                    pass
        return RunResult(returncode=0, stdout="", stderr="")

    def flat(self) -> str:
        return " ".join(a for call in self.calls for a in call)


class ScriptedRunner:
    """Returns scripted RunResults per call index; empty success afterwards."""

    def __init__(self, results: list[RunResult]) -> None:
        self._results = results
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> RunResult:
        idx = len(self.calls)
        self.calls.append(list(args))
        if idx < len(self._results):
            return self._results[idx]
        return RunResult(returncode=0, stdout="", stderr="")


@pytest.fixture
def ffmpeg_available():
    """Force check_ffmpeg() True without spawning ffmpeg."""
    prev = output_mod._ffmpeg_checked
    output_mod._ffmpeg_checked = True
    yield
    output_mod._ffmpeg_checked = prev


# Captured before any fixture stubs it out, so the encoding test can reach the
# real implementation.
_REAL_GET_AUDIO_DURATION = output_mod.get_audio_duration


@pytest.fixture(autouse=True)
def _no_real_ffprobe(monkeypatch):
    """Post-render validation must never spawn a real ffprobe in these tests."""
    monkeypatch.setattr(output_mod, "get_audio_duration", lambda p: 0.0)


# ---------------------------------------------------------------------------
# renderer-crit-1-cjk-stderr
# ---------------------------------------------------------------------------

# "I Am a Cat" — its UTF-8 bytes contain 0x81 and 0x90, both undefined in
# cp1252, so a locale-codepage decode of this really does blow up.
CJK_TITLE = "吾輩は猫である"

FFMPEG_STDERR_BYTES = (
    "ffmpeg version 7.1 Copyright (c) 2000-2024 the FFmpeg developers\n"
    "  Metadata:\n"
    f"    title           : {CJK_TITLE}\n"
    "Conversion failed!\n"
).encode("utf-8")


def _locale_decoding_subprocess_run(recorded: list[dict]) -> Callable:
    """Build a subprocess.run double that models CPython's text-mode decode.

    In text mode with no ``encoding=``, CPython decodes the child's pipes with
    the locale codepage. On a Windows box that is cp1252, which has *undefined*
    bytes at 0x81/0x8D/0x8F/0x90/0x9D — every one of which shows up in the
    UTF-8 ffmpeg echoes back for a CJK title. The decode blows up inside
    subprocess's reader thread, which does not re-raise: the attribute simply
    arrives as None.
    """

    def _run(args, **kwargs):
        recorded.append(dict(kwargs))
        encoding = kwargs.get("encoding")
        errors = kwargs.get("errors")
        if kwargs.get("text") and not encoding:
            try:
                decoded = FFMPEG_STDERR_BYTES.decode("cp1252")
            except UnicodeDecodeError:
                decoded = None
        else:
            decoded = FFMPEG_STDERR_BYTES.decode(encoding or "utf-8", errors or "strict")
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr=decoded
        )

    return _run


class TestCJKStderr:
    def test_cjk_title_on_stderr_comes_back_as_str(self, monkeypatch):
        """A Japanese book title must not turn stderr into None."""
        recorded: list[dict] = []
        monkeypatch.setattr(
            ffmpeg_runner_mod.subprocess,
            "run",
            _locale_decoding_subprocess_run(recorded),
        )

        result = ffmpeg_runner_mod.RealFFmpegRunner().run(
            ["ffmpeg", "-y", "-i", "in.wav", "out.m4a"]
        )

        assert isinstance(result.stderr, str), (
            "stderr came back as None — RunResult declares stderr: str and every "
            "downstream consumer calls .strip() on it"
        )
        assert CJK_TITLE in result.stderr
        assert result.returncode == 1
        assert recorded and recorded[0].get("encoding") == "utf-8"
        assert recorded[0].get("errors") == "replace"

    def test_none_streams_are_coerced_to_str(self, monkeypatch):
        """Defensive: even a None from the child yields RunResult's declared str."""

        def _run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout=None, stderr=None
            )

        monkeypatch.setattr(ffmpeg_runner_mod.subprocess, "run", _run)
        result = ffmpeg_runner_mod.RealFFmpegRunner().run(["ffmpeg", "-version"])
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)

    def test_non_executable_ffmpeg_returns_structured_result(self, monkeypatch):
        """A non-executable ffmpeg is an OSError, not FileNotFoundError."""

        def _run(args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(ffmpeg_runner_mod.subprocess, "run", _run)
        result = ffmpeg_runner_mod.RealFFmpegRunner().run(["ffmpeg", "-version"])
        assert result.returncode == -1
        assert isinstance(result.stderr, str)
        assert result.stderr

    def test_check_ffmpeg_survives_cjk_stderr(self, monkeypatch):
        """check_ffmpeg() has the same decode bug and the same fix."""
        output_mod.reset_ffmpeg_cache()
        recorded: list[dict] = []
        monkeypatch.setattr(
            output_mod.subprocess, "run", _locale_decoding_subprocess_run(recorded)
        )
        try:
            output_mod.check_ffmpeg()
        finally:
            output_mod.reset_ffmpeg_cache()
        assert recorded and recorded[0].get("encoding") == "utf-8"

    def test_get_audio_duration_passes_encoding(self, monkeypatch, tmp_path: Path):
        recorded: list[dict] = []

        def _run(args, **kwargs):
            recorded.append(dict(kwargs))
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="12.5", stderr=""
            )

        monkeypatch.setattr(output_mod.subprocess, "run", _run)
        # The autouse fixture stubs get_audio_duration; reach the real one.
        assert _REAL_GET_AUDIO_DURATION(tmp_path / "x.m4a") == pytest.approx(12.5)
        assert recorded and recorded[0].get("encoding") == "utf-8"


# ---------------------------------------------------------------------------
# renderer-crit-2-cache-key
# ---------------------------------------------------------------------------

class TestRenderCacheKey:
    def test_two_engines_produce_two_cache_keys(self):
        """The engine is the single largest determinant of the audio."""
        default = ProjectConfig(tts_engine="voice-soundboard")
        other = ProjectConfig(tts_engine="piper")
        assert render_params_hash(default) != render_params_hash(other), (
            "switching --engine served the previous engine's cached audio"
        )

    def test_env_var_engine_changes_cache_key(self, monkeypatch):
        config = ProjectConfig()
        monkeypatch.delenv(engine_mod.ENGINE_ENV_VAR, raising=False)
        baseline = render_params_hash(config)
        monkeypatch.setenv(engine_mod.ENGINE_ENV_VAR, "piper")
        assert render_params_hash(config) != baseline

    def test_injected_engine_instance_changes_cache_key(self, monkeypatch):
        monkeypatch.delenv(engine_mod.ENGINE_ENV_VAR, raising=False)
        config = ProjectConfig()
        baseline = render_params_hash(config)
        assert render_params_hash(config, engine=FakeTTSEngine()) != baseline

    def test_engine_version_changes_cache_key(self, monkeypatch):
        monkeypatch.delenv(engine_mod.ENGINE_ENV_VAR, raising=False)
        config = ProjectConfig()
        import audiobooker.renderer.hash_utils as hash_mod

        monkeypatch.setattr(hash_mod, "_engine_distribution_version", lambda name: "1.0.0")
        first = render_params_hash(config)
        monkeypatch.setattr(hash_mod, "_engine_distribution_version", lambda name: "2.0.0")
        assert render_params_hash(config) != first

    def test_output_profile_changes_cache_key(self):
        podcast = ProjectConfig(output_profile="podcast")
        acx = ProjectConfig(output_profile="acx")
        assert render_params_hash(podcast) != render_params_hash(acx), (
            "switching to --acx re-served unmastered audio from the cache"
        )

    def test_output_profile_override_changes_cache_key(self):
        config = ProjectConfig(output_profile="podcast")
        assert render_params_hash(config, output_profile="acx") != render_params_hash(config)

    def test_manifest_version_bumped_so_old_entries_invalidate_once(self):
        from audiobooker.renderer import cache_manifest as cm

        assert cm.MANIFEST_VERSION >= 2, (
            "MANIFEST_VERSION must be bumped so pre-fix manifests (whose keys "
            "omit the engine) invalidate rather than serve cross-engine audio"
        )


# ---------------------------------------------------------------------------
# renderer-crit-3-sample-stale
# ---------------------------------------------------------------------------

class TestSampleStaleWav:
    def _prime_cache(self, tmp_path: Path) -> tuple[AudiobookProject, Path]:
        project = _make_project()
        cache_root = tmp_path / "cache"
        engine_mod.render_project(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=RecordingAssembler(),
            cache_root=cache_root,
        )
        return project, cache_root

    def test_rejected_hash_forces_a_rerender(
        self, tmp_path: Path, monkeypatch, ffmpeg_available
    ):
        """The retail sample must never be mastered from pre-edit audio."""
        project, cache_root = self._prime_cache(tmp_path)

        # The user edits chapter 1 — the manifest entry is now invalid.
        project.chapters[0].utterances[0].text = "A completely rewritten opening line."

        runner = RecordingRunner(create_output=True)
        monkeypatch.setattr(
            "audiobooker.renderer.ffmpeg_runner.RealFFmpegRunner", lambda: runner
        )
        fresh_engine = FakeTTSEngine()
        engine_mod.render_sample(
            project,
            from_chapter=0,
            duration=30.0,
            output_path=tmp_path / "sample.m4a",
            engine=fresh_engine,
            cache_root=cache_root,
        )

        assert fresh_engine.calls, (
            "render_sample reused the WAV its own hash check had just rejected — "
            "the retail sample was mastered from pre-edit audio"
        )

    def test_unverified_disk_fallback_warns(
        self, tmp_path: Path, monkeypatch, caplog, ffmpeg_available
    ):
        """A WAV with no manifest entry may be reused, but never silently."""
        project = _make_project()
        cache_root = tmp_path / "cache"
        wav = get_chapter_wav_path(cache_root, 0)
        wav.parent.mkdir(parents=True, exist_ok=True)
        write_silence_wav(wav, duration_s=1.0)

        runner = RecordingRunner(create_output=True)
        monkeypatch.setattr(
            "audiobooker.renderer.ffmpeg_runner.RealFFmpegRunner", lambda: runner
        )
        engine = FakeTTSEngine()
        with caplog.at_level(logging.WARNING, logger="audiobooker.renderer"):
            engine_mod.render_sample(
                project,
                from_chapter=0,
                duration=30.0,
                output_path=tmp_path / "sample.m4a",
                engine=engine,
                cache_root=cache_root,
            )

        assert not engine.calls, "an unverified but present WAV should still be reused"
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("verif" in r.getMessage().lower() for r in warnings), (
            "the unverified fallback was logged at INFO — the user never sees it"
        )


# ---------------------------------------------------------------------------
# renderer-crit-4-partial-silent
# ---------------------------------------------------------------------------

class TestPartialRenderVisibility:
    def _render_with_one_failure(self, tmp_path: Path, caplog):
        project = _make_project()
        assembler = RecordingAssembler()
        # Second chapter's synthesize() call raises.
        engine = FakeTTSEngine(fail_on_call=1)
        with caplog.at_level(logging.WARNING, logger="audiobooker.renderer"):
            result = engine_mod.render_project(
                project,
                tmp_path / "book.m4b",
                engine=engine,
                assembler=assembler,
                cache_root=tmp_path / "cache",
                allow_partial=True,
            )
        return project, result

    def test_partial_render_exposes_its_summary(self, tmp_path: Path, caplog):
        """A 2-of-3-chapter book must not look like a complete one."""
        project, result = self._render_with_one_failure(tmp_path, caplog)

        summary = getattr(result, "render_summary", None)
        assert summary is not None, (
            "render_project returned a bare Path — a caller cannot tell a partial "
            "render from a complete one"
        )
        assert summary.failed == 1
        assert [f["index"] for f in summary.failed_chapters] == [1]
        assert summary.total == len(project.chapters)

    def test_partial_render_warns_with_chapter_indices(self, tmp_path: Path, caplog):
        self._render_with_one_failure(tmp_path, caplog)
        warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert any("RENDER_PARTIAL" in m for m in warnings), (
            "allow_partial suppressed a chapter failure with no WARNING"
        )
        assert any("1" in m for m in warnings if "RENDER_PARTIAL" in m)

    def test_render_project_detailed_returns_summary(self, tmp_path: Path):
        project = _make_project()
        summary = engine_mod.render_project_detailed(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=RecordingAssembler(),
            cache_root=tmp_path / "cache",
        )
        assert isinstance(summary, engine_mod.RenderSummary)
        assert summary.failed == 0
        assert summary.rendered == len(project.chapters)

    def test_returned_path_still_behaves_like_a_path(self, tmp_path: Path):
        """Backwards compatibility: callers treat the return value as a Path."""
        project = _make_project()
        out = tmp_path / "book.m4b"
        result = engine_mod.render_project(
            project,
            out,
            engine=FakeTTSEngine(),
            assembler=RecordingAssembler(),
            cache_root=tmp_path / "cache",
        )
        assert isinstance(result, Path)
        assert result == out
        assert result.exists()
        assert str(result) == str(out)

    def test_post_render_validate_expects_the_full_book(self, tmp_path: Path, caplog):
        """The expected duration must come from ALL chapters, not the short book.

        Summing only the chapters that survived makes the ratio 1.0 by
        construction, so a dropped chapter can never be detected.
        """
        seen: list[float] = []
        original = engine_mod._post_render_validate

        def _spy(output_path, expected_duration, *args, **kwargs):
            seen.append(expected_duration)
            return original(output_path, expected_duration, *args, **kwargs)

        engine_mod._post_render_validate = _spy
        try:
            project = _make_project()
            engine = FakeTTSEngine(fail_on_call=1)
            with caplog.at_level(logging.WARNING, logger="audiobooker.renderer"):
                engine_mod.render_project(
                    project,
                    tmp_path / "book.m4b",
                    engine=engine,
                    assembler=RecordingAssembler(),
                    cache_root=tmp_path / "cache",
                    allow_partial=True,
                )
        finally:
            engine_mod._post_render_validate = original

        ok_total = sum(
            ch.duration_seconds
            for ch in project.chapters
            if ch.audio_path and Path(ch.audio_path).exists()
        )
        assert seen, "_post_render_validate was never called"
        assert seen[0] > ok_total, (
            "expected duration was summed from the surviving chapters, so a "
            "dropped chapter can never move the ratio"
        )


# ---------------------------------------------------------------------------
# renderer-crit-5-acx-rms
# ---------------------------------------------------------------------------

class TestAcxRmsMeasurement:
    """ACX gates on unweighted RMS, not on EBU R128 integrated loudness.

    help.acx.com states the requirement verbatim as an RMS window; ffmpeg's
    loudnorm reports ``input_i`` in LUFS (K-weighted, gated). They are
    different quantities and disagree by several dB on speech.
    """

    def _loudnorm_stderr(self, input_i: float, input_tp: float) -> str:
        return "measuring\n" + json.dumps(
            {
                "input_i": str(input_i),
                "input_tp": str(input_tp),
                "input_lra": "7.0",
                "input_thresh": "-31.0",
            }
        )

    def _volumedetect_stderr(self, mean_db: float) -> str:
        return (
            "[Parsed_volumedetect_0 @ 000] n_samples: 4410000\n"
            f"[Parsed_volumedetect_0 @ 000] mean_volume: {mean_db} dB\n"
            "[Parsed_volumedetect_0 @ 000] max_volume: -1.2 dB\n"
        )

    def _runner(self, input_i: float, mean_db: Optional[float]) -> ScriptedRunner:
        results = [
            RunResult(returncode=0, stderr=self._loudnorm_stderr(input_i, -3.5)),
            RunResult(returncode=0, stderr="Noise floor dB: -70.0"),
        ]
        if mean_db is not None:
            results.append(
                RunResult(returncode=0, stderr=self._volumedetect_stderr(mean_db))
            )
        return ScriptedRunner(results)

    def test_rms_comes_from_volumedetect_not_loudnorm(
        self, tmp_path: Path, ffmpeg_available
    ):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        # LUFS sits inside the ACX window; the true RMS does not.
        runner = self._runner(input_i=-20.0, mean_db=-12.0)
        report = master_check(audio, profile="acx", runner=runner)

        assert report["measured_rms_db"] == pytest.approx(-12.0), (
            "measured_rms_db still carries loudnorm's LUFS value"
        )
        assert report["passes"] is False, (
            "a file 6 dB hotter than the ACX ceiling was reported as PASS because "
            "the check compared LUFS against an RMS window"
        )
        assert any("RMS" in f for f in report["failures"])
        flat = " ".join(a for call in runner.calls for a in call)
        assert "volumedetect" in flat

    def test_integrated_loudness_is_reported_under_its_own_name(
        self, tmp_path: Path, ffmpeg_available
    ):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = self._runner(input_i=-20.0, mean_db=-20.5)
        report = master_check(audio, profile="acx", runner=runner)
        assert report["measured_lufs"] == pytest.approx(-20.0)
        assert report["rms_source"] == "volumedetect"
        assert report["passes"] is True

    def test_rms_source_is_labelled_when_volumedetect_is_unavailable(
        self, tmp_path: Path, ffmpeg_available
    ):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = self._runner(input_i=-20.0, mean_db=None)
        report = master_check(audio, profile="acx", runner=runner)
        assert report["rms_source"] != "volumedetect"
        assert report["warnings"], "a LUFS fallback must say so"

    def test_acx_render_reports_unapplied_mastering(
        self, tmp_path: Path, ffmpeg_available
    ):
        """A failed loudnorm pass under acx must not ship as a finished master."""
        from audiobooker.renderer.output import assemble_m4b

        class LoudnormHatingRunner(RecordingRunner):
            """Every command carrying a loudnorm filter fails."""

            def run(self, args: list[str]) -> RunResult:
                if any("loudnorm" in a for a in args):
                    self.calls.append(list(args))
                    return RunResult(returncode=1, stderr="Invalid argument")
                return super().run(args)

        runner = LoudnormHatingRunner(create_output=True)
        chapter_files = []
        for i in range(2):
            wav = tmp_path / f"ch{i}.wav"
            write_silence_wav(wav, duration_s=0.5)
            chapter_files.append((wav, f"Chapter {i + 1}", 0.5))

        result = assemble_m4b(
            chapter_files,
            tmp_path / "out.m4b",
            runner=runner,
            loudnorm_profile="acx",
            normalize=True,
        )
        assert result.mastering_applied is False
        assert result.mastering_error
        # And the book still shipped rather than dying at assembly.
        assert Path(result.output_path).exists()

    def test_mastering_is_applied_in_the_encode_pass(
        self, tmp_path: Path, ffmpeg_available
    ):
        """No AAC->AAC second generation: the filter runs on the lossless WAVs."""
        from audiobooker.renderer.output import assemble_m4b

        runner = RecordingRunner(create_output=True)
        wav = tmp_path / "ch0.wav"
        write_silence_wav(wav, duration_s=0.5)
        assemble_m4b(
            [(wav, "Chapter 1", 0.5)],
            tmp_path / "out.m4b",
            runner=runner,
            loudnorm_profile="acx",
            normalize=True,
        )
        loudnorm_encodes = [
            call
            for call in runner.calls
            if any("loudnorm" in a for a in call) and "null" not in call
        ]
        assert loudnorm_encodes, "loudnorm never ran"
        for call in loudnorm_encodes:
            inputs = [call[i + 1] for i, a in enumerate(call) if a == "-i"]
            assert not any(str(i).endswith(".m4a") for i in inputs), (
                "loudnorm was applied to an already-encoded AAC file — a second "
                f"lossy generation: {call}"
            )


# ---------------------------------------------------------------------------
# renderer-high-6-render-lock
# ---------------------------------------------------------------------------

class TestRenderLock:
    def test_lock_is_created_atomically(self, tmp_path: Path, monkeypatch):
        """O_CREAT|O_EXCL, not exists()-then-write."""
        cache_root = tmp_path / "cache"
        cache_root.mkdir(parents=True)

        opened: list[int] = []
        real_open = os.open

        def _spy(path, flags, *args, **kwargs):
            opened.append(flags)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(engine_mod.os, "open", _spy)
        lock = engine_mod._acquire_render_lock(cache_root)
        try:
            assert any(
                f & os.O_EXCL and f & os.O_CREAT for f in opened
            ), "the lockfile was created with a TOCTOU exists()/write_text() pair"
        finally:
            engine_mod._release_render_lock(lock)

    def test_second_acquire_in_the_same_process_is_refused(self, tmp_path: Path):
        """A same-PID lock is not automatically stale — it is usually live."""
        cache_root = tmp_path / "cache"
        cache_root.mkdir(parents=True)
        lock = engine_mod._acquire_render_lock(cache_root)
        try:
            with pytest.raises(engine_mod.RenderError):
                engine_mod._acquire_render_lock(cache_root)
        finally:
            engine_mod._release_render_lock(lock)

    def test_stale_lock_from_a_dead_process_is_reclaimed(self, tmp_path: Path):
        cache_root = tmp_path / "cache"
        cache_root.mkdir(parents=True)
        (cache_root / engine_mod.LOCKFILE_NAME).write_text(
            json.dumps({"pid": 999999, "started_at": "2020-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )
        lock = engine_mod._acquire_render_lock(cache_root)
        engine_mod._release_render_lock(lock)

    def test_lock_carries_a_process_identity_token(self, tmp_path: Path):
        cache_root = tmp_path / "cache"
        cache_root.mkdir(parents=True)
        lock = engine_mod._acquire_render_lock(cache_root)
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            assert data.get("token"), "PID alone cannot survive PID reuse"
            assert data["pid"] == os.getpid()
        finally:
            engine_mod._release_render_lock(lock)

    def test_chapter_tmp_name_is_unique_per_process(self, tmp_path: Path):
        project = _make_project()
        engine_mod.render_project(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=RecordingAssembler(),
            cache_root=tmp_path / "cache",
        )
        name = engine_mod._chapter_tmp_path(get_chapter_wav_path(tmp_path / "cache", 0)).name
        assert str(os.getpid()) in name, (
            "two processes rendering the same cache collide on chapter_0000.wav.tmp"
        )


# ---------------------------------------------------------------------------
# renderer-high-7-cache-size
# ---------------------------------------------------------------------------

class TestCacheEntryIntegrity:
    def _entry(self, wav: Path, **overrides) -> ChapterCacheEntry:
        data = dict(
            chapter_index=0,
            text_hash="t",
            casting_hash="c",
            render_params_hash="p",
            wav_path=str(wav),
            status="ok",
        )
        data.update(overrides)
        return ChapterCacheEntry(**data)

    def test_truncated_wav_is_not_valid(self, tmp_path: Path):
        wav = tmp_path / "chapter.wav"
        write_silence_wav(wav, duration_s=1.0)
        entry = self._entry(wav, size_bytes=wav.stat().st_size)
        assert entry.is_valid("t", "c", "p")

        # Disk filled mid-write: the file exists and is non-empty, but short.
        wav.write_bytes(b"RIFF" + b"\x00" * 64)
        assert not entry.is_valid("t", "c", "p"), (
            "a truncated WAV passed validation because the only check was "
            "'file is non-empty'"
        )

    def test_legacy_entry_without_size_still_validates(self, tmp_path: Path):
        wav = tmp_path / "chapter.wav"
        write_silence_wav(wav, duration_s=1.0)
        entry = self._entry(wav)  # size_bytes defaults to 0 (pre-fix manifest)
        assert entry.is_valid("t", "c", "p")

    def test_unstatable_wav_is_not_valid(self, tmp_path: Path, monkeypatch):
        wav = tmp_path / "chapter.wav"
        write_silence_wav(wav, duration_s=1.0)
        entry = self._entry(wav, size_bytes=wav.stat().st_size)

        def _boom(self, *args, **kwargs):
            raise OSError(5, "I/O error")

        monkeypatch.setattr(Path, "stat", _boom)
        assert not entry.is_valid("t", "c", "p")

    def test_render_records_the_byte_size(self, tmp_path: Path):
        project = _make_project()
        cache_root = tmp_path / "cache"
        engine_mod.render_project(
            project,
            tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=RecordingAssembler(),
            cache_root=cache_root,
        )
        manifest = load_manifest(get_manifest_path(cache_root))
        assert manifest is not None
        entry = manifest.get_entry(0)
        assert entry is not None and entry.size_bytes > 0


# ---------------------------------------------------------------------------
# renderer-high-9-cue-escape
# ---------------------------------------------------------------------------

class TestCueEscaping:
    def test_quotes_in_chapter_titles_are_escaped(self):
        chapters = [
            ('The "Quiet" Room', 10.0),
            ("Plain Chapter", 10.0),
        ]
        cue = export_chapter_metadata(
            chapters, fmt="cue", chapter_pause_ms=0, title='A "Loud" Book'
        )
        for line in cue.splitlines():
            stripped = line.strip()
            if stripped.startswith("TITLE "):
                value = stripped[len("TITLE "):]
                assert value.startswith('"') and value.endswith('"')
                assert '"' not in value[1:-1], (
                    f"unescaped quote breaks the CUE sheet: {line!r}"
                )


# ---------------------------------------------------------------------------
# renderer-high-10-chapter-name
# ---------------------------------------------------------------------------

class TestPerChapterFilenames:
    def test_long_title_is_truncated(self, tmp_path: Path, ffmpeg_available):
        from audiobooker.renderer.output import assemble_m4a_split

        long_title = "A " + ("very " * 120) + "long chapter title"
        wav = tmp_path / "ch0.wav"
        write_silence_wav(wav, duration_s=0.5)
        runner = RecordingRunner(create_output=True)
        result = assemble_m4a_split(
            [(wav, long_title, 0.5)],
            tmp_path / "book.m4b",
            runner=runner,
        )
        produced = [p for p in Path(result.output_path).iterdir() if p.suffix == ".m4a"]
        assert produced
        assert len(produced[0].stem) <= 70, (
            f"filename stem is {len(produced[0].stem)} chars — an unbounded EPUB "
            f"TOC title blows the path limit"
        )

    def test_punctuation_only_title_falls_back(self, tmp_path: Path, ffmpeg_available):
        from audiobooker.renderer.output import assemble_m4a_split

        wav = tmp_path / "ch0.wav"
        write_silence_wav(wav, duration_s=0.5)
        runner = RecordingRunner(create_output=True)
        result = assemble_m4a_split(
            [(wav, "***", 0.5)],
            tmp_path / "book.m4b",
            runner=runner,
        )
        produced = [p for p in Path(result.output_path).iterdir() if p.suffix == ".m4a"]
        assert produced
        assert "chapter" in produced[0].stem.lower()

    def test_trailing_dot_is_stripped(self, tmp_path: Path, ffmpeg_available):
        from audiobooker.renderer.output import assemble_m4a_split

        wav = tmp_path / "ch0.wav"
        write_silence_wav(wav, duration_s=0.5)
        runner = RecordingRunner(create_output=True)
        result = assemble_m4a_split(
            [(wav, "Chapter One.", 0.5)],
            tmp_path / "book.m4b",
            runner=runner,
        )
        produced = [p for p in Path(result.output_path).iterdir() if p.suffix == ".m4a"]
        assert produced
        assert not produced[0].stem.endswith((".", " "))


# ---------------------------------------------------------------------------
# renderer-high-11-emotion-preset
# ---------------------------------------------------------------------------

class SSMLFakeTTSEngine(FakeTTSEngine):
    """FakeTTSEngine that advertises SSML support so the preset path runs."""

    def capabilities(self) -> dict[str, bool]:
        return {
            "streaming": False,
            "emotions": True,
            "ssml": True,
            "multi_speaker": True,
        }


class TestEmotionPresetThreading:
    def _project_with_sad_line(self, preset: str) -> AudiobookProject:
        project = AudiobookProject.from_string(
            BOOK_TEXT, title="Preset Book", author="A"
        )
        project.config.emotion_preset = preset
        project.cast("narrator", "af_heart")
        project.cast("Alice", "af_bella")
        project.compile()
        for chapter in project.chapters:
            for utt in chapter.utterances:
                utt.emotion = "sad"
                utt.intensity = None
        return project

    def test_render_project_threads_the_preset(self, tmp_path: Path):
        """'sad' is moderate under neutral and strong under dramatic."""
        project = self._project_with_sad_line("dramatic")
        engine = SSMLFakeTTSEngine()
        engine_mod.render_project(
            project,
            tmp_path / "book.m4b",
            engine=engine,
            assembler=RecordingAssembler(),
            cache_root=tmp_path / "cache",
        )
        scripts = "\n".join(call.script for call in engine.calls)
        assert 'level="strong"' in scripts, (
            "render_project ignored project.config.emotion_preset — the "
            "literary/dramatic/children maps are dead code"
        )
        assert 'level="moderate"' not in scripts

    def test_neutral_preset_is_unchanged(self, tmp_path: Path):
        project = self._project_with_sad_line("neutral")
        engine = SSMLFakeTTSEngine()
        engine_mod.render_project(
            project,
            tmp_path / "book.m4b",
            engine=engine,
            assembler=RecordingAssembler(),
            cache_root=tmp_path / "cache",
        )
        scripts = "\n".join(call.script for call in engine.calls)
        assert 'level="moderate"' in scripts
        assert 'level="strong"' not in scripts

    def test_render_sample_threads_the_preset(
        self, tmp_path: Path, monkeypatch, ffmpeg_available
    ):
        project = self._project_with_sad_line("dramatic")
        runner = RecordingRunner(create_output=True)
        monkeypatch.setattr(
            "audiobooker.renderer.ffmpeg_runner.RealFFmpegRunner", lambda: runner
        )
        engine = SSMLFakeTTSEngine()
        engine_mod.render_sample(
            project,
            from_chapter=0,
            duration=30.0,
            output_path=tmp_path / "sample.m4a",
            engine=engine,
            cache_root=tmp_path / "cache",
        )
        scripts = "\n".join(call.script for call in engine.calls)
        assert 'level="strong"' in scripts
