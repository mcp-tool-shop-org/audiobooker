"""Wave-3 cross-domain residuals — the seams between domain owners.

Each test here pins a defect that a wave-2 domain agent correctly REFUSED to
fix because the remedy lived outside its owned files:

* residual 1 — a partial render is reported to the user as a success
  (renderer produced the evidence; ``cli.py`` threw it away).
* residual 2 — the voice-ID gate is bypassed on exactly the *elaborate*
  renders, because those take a direct ``render_project`` path that skips
  ``Project.render()``.
* residual 5 — ``RenderError`` / ``PresetError`` / ``VoiceNotFoundError`` are
  cited by SHIP_GATE.md Gate B as evidence the structured error shape ships,
  but none of them belonged to the ``AudiobookerError`` family.

Residual 3 (a broad ``except`` in ``test_wave3_feature_execution.py``),
residual 4 (``_err`` → stderr) and residual 6 (CSV cast-sheet tuning columns)
are about *existing* assertions and are amended in place in their own files.

Everything here is hermetic: no voice-soundboard, no ffmpeg, no real TTS.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from audiobooker.models import (
    Chapter,
    ProjectConfig,
    Utterance,
    UtteranceType,
)
from audiobooker.project import AudiobookProject
from audiobooker.renderer.engine import (
    RenderSummary,
    _attach_summary,
    render_project,
)

from tests.fakes.fake_ffmpeg import FakeAssembler
from tests.fakes.fake_tts import FakeTTSEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _incomplete_render_path(tmp_path: Path, missing: list[int]) -> Path:
    """A render_project return value that says 'this book is INCOMPLETE'."""
    out = tmp_path / "book.m4b"
    out.write_bytes(b"not really audio")
    summary = RenderSummary(
        output_path=out,
        rendered=2,
        failed=0,
        total=3,
        missing_chapters=list(missing),
    )
    assert not summary.is_complete
    return _attach_summary(out, summary)


def _project_with_voice(voice: str, *, chapters: int = 1) -> AudiobookProject:
    """A compiled, fully-cast project whose narrator uses ``voice``."""
    project = AudiobookProject(title="Residual Book")
    project.cast("narrator", voice)
    for i in range(chapters):
        ch = Chapter(index=i, title=f"Chapter {i + 1}", raw_text="Hello world " * 20)
        ch.utterances.append(
            Utterance(
                speaker="narrator",
                text="Hello world, this is narration.",
                utterance_type=UtteranceType.NARRATION,
                chapter_index=i,
                line_index=0,
            )
        )
        project.chapters.append(ch)
    return project


def _seed_project_file(tmp_path: Path, *, validate_voices: bool = False) -> Path:
    """Write a tiny compiled project to disk and return its path."""
    project = AudiobookProject.from_string(
        "Chapter 1\n\nHello world. This is a test sentence for narration.\n\n"
        "Chapter 2\n\nAnd a second chapter of narration text.\n",
        title="Residual CLI Book",
        author="Tester",
    )
    project.config.validate_voices_on_render = validate_voices
    project.compile()
    path = tmp_path / "residual.audiobooker"
    project.save(path)
    return path


# ===========================================================================
# Residual 1 — a partial render must never be reported as a success
# ===========================================================================


class TestPartialRenderIsNotSuccess:
    def test_process_book_records_partial_status(self, tmp_path, monkeypatch):
        """_process_book recorded status 'success' regardless of the summary.

        29-of-30 chapters under --allow-partial looked byte-identical to a
        finished book at this call site.
        """
        from audiobooker.cli import _process_book

        monkeypatch.chdir(tmp_path)
        src = tmp_path / "book.txt"
        src.write_text(
            "Chapter 1\n\nHello world narration.\n\n"
            "Chapter 2\n\nMore narration here.\n\n"
            "Chapter 3\n\nAnd the last one.\n",
            encoding="utf-8",
        )

        enriched = _incomplete_render_path(tmp_path, missing=[2])
        with patch(
            "audiobooker.renderer.engine.render_project", return_value=enriched
        ):
            result = _process_book(src, fmt="m4b", jobs=1, lang="en")

        assert result["status"] == "partial", (
            f"an incomplete render was reported as {result['status']!r}"
        )
        assert "2" in result["error"], (
            f"the missing chapter was not named: {result['error']!r}"
        )
        assert result["output"], "a partial render still produced a file"

    def test_batch_exits_with_partial_success_code(self, tmp_path, capsys):
        """cmd_batch must use its documented partial-success exit code (3)."""
        from audiobooker.cli import main

        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello.\n", encoding="utf-8")

        partial_result = {
            "file": str(src),
            "name": "Residual Book",
            "status": "partial",
            "output": str(tmp_path / "book.m4b"),
            "error": "incomplete: 1 chapter missing (indices: [2])",
            "duration_s": 0.5,
        }
        with patch("audiobooker.cli._process_book", return_value=partial_result):
            code = main(["batch", str(src)])

        assert code == 3, f"a partial batch exited {code}, not the partial code 3"
        out = capsys.readouterr().out
        assert "PARTIAL" in out.upper()

    def test_render_command_reports_partial_and_exits_three(self, tmp_path, capsys):
        """`render --allow-partial` announced 'Audiobook created' and exited 0."""
        from audiobooker.cli import main

        proj = _seed_project_file(tmp_path)
        enriched = _incomplete_render_path(tmp_path, missing=[1])

        with patch(
            "audiobooker.renderer.engine.render_project", return_value=enriched
        ):
            code = main(
                [
                    "render",
                    "-p",
                    str(proj),
                    "--allow-partial",
                    "-o",
                    str(tmp_path / "book.m4b"),
                ]
            )

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert code == 3, f"a partial render exited {code}, not the partial code 3"
        assert "partial" in combined.lower(), combined
        assert "1" in combined


# ===========================================================================
# Residual 2 — the voice gate must run on EVERY render path
# ===========================================================================


class TestVoiceGateOnDirectRenderPaths:
    def test_render_project_runs_the_voice_gate(self, tmp_path):
        """render_project skipped voice validation entirely.

        cli.py calls it directly for --cover/--normalize/--profile/--bitrate/
        --split/--engine, so a typo'd voice was caught only on the simplest
        renders and discovered hours in on the elaborate ones.
        """
        from audiobooker.casting.voice_registry import VoiceNotFoundError

        project = _project_with_voice("nonexistent_voice")

        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart", "bm_george"},
        ):
            with pytest.raises(VoiceNotFoundError) as exc:
                render_project(
                    project,
                    tmp_path / "book.m4b",
                    engine=FakeTTSEngine(),
                    assembler=FakeAssembler(),
                    cache_root=tmp_path / "cache",
                )

        assert "nonexistent_voice" in str(exc.value)

    def test_force_does_not_bypass_the_voice_gate(self, tmp_path):
        """batch/make pass force=True to skip *casting completeness*.

        force is about uncast speakers, not about typo'd voice IDs — a voice
        that does not exist is fatal on every path.
        """
        from audiobooker.casting.voice_registry import VoiceNotFoundError

        project = _project_with_voice("nonexistent_voice")

        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart"},
        ):
            with pytest.raises(VoiceNotFoundError):
                render_project(
                    project,
                    tmp_path / "book.m4b",
                    engine=FakeTTSEngine(),
                    assembler=FakeAssembler(),
                    cache_root=tmp_path / "cache",
                    force=True,
                )

    def test_cli_normalize_path_validates_voices(self, tmp_path, capsys):
        """--normalize sets needs_direct, which used to skip Project.render()."""
        from audiobooker.cli import main

        project = AudiobookProject.from_string(
            "Chapter 1\n\nHello world. This is narration.\n",
            title="Direct Path Book",
        )
        project.cast("narrator", "nonexistent_voice")
        project.config.fallback_voice_id = "nonexistent_voice"
        project.compile()
        proj = tmp_path / "direct.audiobooker"
        project.save(proj)

        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart", "bm_george"},
        ):
            code = main(
                [
                    "render",
                    "-p",
                    str(proj),
                    "--normalize",
                    "-o",
                    str(tmp_path / "out.m4b"),
                ]
            )

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert code != 0
        assert "nonexistent_voice" in combined, (
            "the direct (needs_direct) render path never checked the voice IDs: "
            f"{combined!r}"
        )

    def test_project_render_validates_exactly_once(self, tmp_path):
        """Guard: moving the gate into the renderer must not double-validate.

        Project.render() keeps its own fail-fast check (it runs BEFORE
        compile); the renderer must not query the registry a second time.
        """
        project = _project_with_voice("af_heart")
        project.project_path = tmp_path / "p.audiobooker"
        project.config = ProjectConfig(validate_voices_on_render=True)

        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            return_value={"af_heart"},
        ) as mock_get:
            project.render(
                tmp_path / "book.m4b",
                engine=FakeTTSEngine(),
                assembler=FakeAssembler(),
            )

        assert mock_get.call_count == 1, (
            f"the voice registry was queried {mock_get.call_count} times"
        )

    def test_missing_voice_backend_does_not_break_the_render(self, tmp_path):
        """The gate must warn-and-skip when voice-soundboard is absent.

        A gate that hard-fails on an absent optional dependency would turn
        every render into an ImportError on machines without the backend.
        """
        from audiobooker.casting.voice_registry import VoiceBackendUnavailableError

        project = _project_with_voice("af_heart")

        with patch(
            "audiobooker.casting.voice_registry.get_available_voices",
            side_effect=VoiceBackendUnavailableError(),
        ):
            out = render_project(
                project,
                tmp_path / "book.m4b",
                engine=FakeTTSEngine(),
                assembler=FakeAssembler(),
                cache_root=tmp_path / "cache",
            )

        assert Path(out).exists()


# ===========================================================================
# Residual 5 — the structured-error family SHIP_GATE.md Gate B claims
# ===========================================================================


class TestStructuredErrorFamily:
    def test_render_error_is_an_audiobooker_error(self):
        from audiobooker.errors import AudiobookerError
        from audiobooker.renderer.engine import RenderError

        err = RenderError("chapter 3 failed")
        assert isinstance(err, AudiobookerError)
        # Existing `except RuntimeError` call sites must keep catching it.
        assert isinstance(err, RuntimeError)
        assert str(err) == "chapter 3 failed"
        assert err.code == "RUNTIME_RENDER"
        assert err.retryable is True
        assert err.hint
        assert err.structured()["code"] == "RUNTIME_RENDER"
        assert err.structured()["message"] == "chapter 3 failed"

    def test_render_error_keeps_summary_and_overrides(self, tmp_path):
        from audiobooker.renderer.engine import RenderError

        summary = RenderSummary(output_path=tmp_path / "b.m4b", total=2)
        err = RenderError(
            "boom",
            summary,
            code="DEP_FFMPEG_MISSING",
            hint="install ffmpeg",
            cause="FileNotFoundError",
            retryable=False,
        )
        assert err.summary is summary
        assert err.code == "DEP_FFMPEG_MISSING"
        assert err.hint == "install ffmpeg"
        assert err.retryable is False
        assert err.structured()["cause"] == "FileNotFoundError"
        assert str(err) == "boom"

    def test_preset_error_is_an_audiobooker_error(self):
        from audiobooker.casting.presets import PresetError
        from audiobooker.errors import AudiobookerError

        err = PresetError("Preset name must be a non-empty string.")
        assert isinstance(err, AudiobookerError)
        # Existing `except ValueError` call sites must keep catching it.
        assert isinstance(err, ValueError)
        assert str(err) == "Preset name must be a non-empty string."
        assert err.code
        assert err.hint
        assert err.structured()["message"] == str(err)

    def test_voice_not_found_error_is_an_audiobooker_error(self):
        from audiobooker.casting.voice_registry import VoiceNotFoundError
        from audiobooker.errors import AudiobookerError

        err = VoiceNotFoundError(missing=["fake_voice"], available_count=20)
        assert isinstance(err, AudiobookerError)
        assert isinstance(err, Exception)
        # str(exc) is asserted verbatim across the suite — it must not drift.
        assert str(err) == (
            "Voice IDs not found: fake_voice\n"
            "  20 voices available. Run 'audiobooker voices' to list them.\n"
            "  To skip validation, set validate_voices_on_render=false in "
            "project config."
        )
        assert err.code == "INPUT_VOICE_NOT_FOUND"
        assert err.missing == ["fake_voice"]
        assert err.available_count == 20
        assert err.retryable is False
        assert err.structured() == {
            "code": "INPUT_VOICE_NOT_FOUND",
            "message": str(err),
            "hint": err.hint,
            "retryable": False,
        }

    def test_every_gate_b_error_reports_the_canonical_shape(self, tmp_path):
        """Gate B cites these by name; the shape must actually be there."""
        from audiobooker.casting.presets import PresetError
        from audiobooker.casting.voice_registry import VoiceNotFoundError
        from audiobooker.errors import AudiobookerError, ConfigValidationError
        from audiobooker.renderer.engine import RenderError

        errors = [
            RenderError("x"),
            PresetError("y"),
            VoiceNotFoundError(missing=["z"], available_count=1),
            ConfigValidationError("w"),
        ]
        for err in errors:
            assert isinstance(err, AudiobookerError), type(err).__name__
            shape = err.structured()
            assert set(shape) >= {"code", "message", "hint", "retryable"}, (
                f"{type(err).__name__} is missing part of the canonical shape"
            )
            assert isinstance(shape["code"], str) and shape["code"]
            assert isinstance(shape["retryable"], bool)


# ===========================================================================
# Residual 4 — errors go to stderr on EVERY path, not only --json
# ===========================================================================


class TestErrorsGoToStderr:
    def test_err_routes_to_stderr_without_json(self, capsys):
        from audiobooker.cli import _err

        _err("Error: something broke")
        captured = capsys.readouterr()
        assert captured.out == "", (
            f"the error line landed on stdout: {captured.out!r}"
        )
        assert "Error: something broke" in captured.err

    def test_plain_command_error_is_on_stderr(self, tmp_path, monkeypatch, capsys):
        from audiobooker.cli import main

        monkeypatch.chdir(tmp_path)
        code = main(["status", "-p", str(tmp_path / "nope.audiobooker")])
        captured = capsys.readouterr()

        assert code == 1
        assert "Error" not in captured.out
        assert "Error" in captured.err

    def test_piping_stdout_keeps_errors_visible(self, tmp_path, monkeypatch, capsys):
        """`audiobooker info -p missing > out.txt` must not write the error
        into out.txt — that is the whole point of the stderr routing."""
        from audiobooker.cli import main

        monkeypatch.chdir(tmp_path)
        code = main(["info", "-p", str(tmp_path / "nope.audiobooker"), "--silent"])
        captured = capsys.readouterr()

        assert code == 1
        assert captured.out == ""
        assert "Error" in captured.err
