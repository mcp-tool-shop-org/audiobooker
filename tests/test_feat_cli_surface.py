"""cli-surface (feature wave): consistency fixes across the 34-subcommand CLI.

The count of subcommands is not the problem — an audit agent drove the whole
pipeline on a 40-chapter novel without once failing to find a command. What
costs users is inconsistency INSIDE the surface, and that is what these tests
pin down:

- FEAT-IN-001: a non-ASCII book title crashed the CLI's own success message on
  a stock Windows console (cp1252). Third instance of the same encoding bug;
  fixed once at the output primitive instead of a fourth per-call-site guard.
- FEAT-UX-004: --json never covered the error path, and four commands that
  compute machine-readable numbers had no --json at all.
- FEAT-UX-002: a typo'd speaker in a review file shipped in the fallback voice.
- FEAT-UX-003: `make` narrated nothing and could not review.
- FEAT-UX-007: four chapter-numbering schemes in one CLI.
- Cheap correctness: cast-apply vs cast-suggest evidence parity, a pasteable
  review-import command, `voices` offline, real `speakers` line counts.

No TTS engine, no ffmpeg, no network.
"""

from __future__ import annotations

import io
import json
import os
import sys
from types import SimpleNamespace

import pytest

from audiobooker import AudiobookProject
from audiobooker import cli
from audiobooker.cli import create_parser, main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DIALOGUE_TEXT = (
    "Chapter 1: Arrival\n\n"
    "The room was quiet. \"We should go now,\" said Sarah.\n"
    "Tom shook his head. \"Not yet,\" he said.\n\n"
    "Chapter 2: The Wait\n\n"
    "Rain struck the glass. \"Then we wait,\" Sarah replied.\n"
    "Tom said nothing at all for a while.\n\n"
    "Chapter 3: The Archive\n\n"
    "Dust covered every shelf. \"Here,\" said Sarah.\n\n"
    "Chapter 4: Departure\n\n"
    "They left before dawn. \"Goodbye,\" said Tom.\n"
)


def _split_command(command: str) -> list[str]:
    """Split a printed command the way the LOCAL shell would.

    ``shlex.split`` is POSIX and eats Windows backslashes, so a Windows-style
    ``"C:\\x\\y.txt"`` has to be split in non-POSIX mode (and unwrapped).
    """
    import shlex as _shlex

    if os.name != "nt":
        return _shlex.split(command)
    return [tok.strip('"') for tok in _shlex.split(command, posix=False)]


def _make_project(tmp_path, *, title="Test Book", text=DIALOGUE_TEXT, compile_it=True):
    """Create + save a small multi-chapter project, returning its path."""
    project = AudiobookProject.from_string(text, title=title, author="Author")
    if compile_it:
        project.compile()
    path = tmp_path / "book.audiobooker"
    project.save(path)
    return path


# ---------------------------------------------------------------------------
# FEAT-IN-001 — one encoding fix, at the primitive
# ---------------------------------------------------------------------------

class TestNonAsciiTitlesNeverKillTheCommand:
    """`new` saved a valid project and then died printing its own success line.

    The traceback landed on ``_out(f"  Title: {project.title}")``. The
    ``.audiobooker`` file on disk was completely fine; only the report of it
    crashed, with exit 1/2. This is the third instance of the same bug in this
    codebase (``_encodable_spinner`` for rich's braille glyph, the CJK
    ffmpeg-stderr decode) and the first two fixes were local to their call
    sites, so neither protected ``_out``/``_err`` — the most-used output path
    in cli.py, with 60+ sites echoing titles.
    """

    def test_new_survives_a_title_the_console_cannot_encode(
        self, tmp_path, monkeypatch
    ):
        source = tmp_path / "真夜中の庭.txt"
        source.write_text(
            "Chapter 1\n\nThe wind moved.\n\nChapter 2\n\nIt moved again.\n",
            encoding="utf-8",
        )
        out_path = tmp_path / "jp.audiobooker"

        # A stock Windows console: cp1252, which cannot encode any of those
        # five characters.
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")
        stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)

        code = main(["new", str(source), "-o", str(out_path)])

        assert code == 0
        assert out_path.exists()
        # And the title really was non-ASCII — i.e. the test exercised the bug.
        assert AudiobookProject.load(out_path).title == "真夜中の庭"

    def test_the_undisplayable_characters_degrade_rather_than_vanish(
        self, tmp_path, monkeypatch
    ):
        """The line still prints; only the glyphs the console lacks are lost."""
        source = tmp_path / "Москва.txt"
        source.write_text("Chapter 1\n\nText.\n", encoding="utf-8")

        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="cp1252", newline="")
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(
            sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        )

        assert main(["new", str(source), "-o", str(tmp_path / "p.audiobooker")]) == 0

        stdout.flush()
        printed = buffer.getvalue().decode("cp1252")
        assert "Title: " in printed
        assert "?" in printed

    def test_the_fix_is_at_the_primitive_not_the_call_site(self, monkeypatch):
        """``_configure_output_encoding`` is what makes every _out()/_err() safe."""
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)

        cli._configure_output_encoding()

        assert sys.stdout.errors == "replace"
        assert sys.stderr.errors == "replace"
        cli._out("真夜中の庭")
        cli._err("真夜中の庭")

    def test_a_stream_that_cannot_be_reconfigured_is_not_an_error(self, monkeypatch):
        """pytest captures, pipes and pythonw all hand us odd stdout objects."""

        class Odd:
            encoding = "cp1252"

        monkeypatch.setattr(sys, "stdout", Odd())
        monkeypatch.setattr(sys, "stderr", Odd())
        cli._configure_output_encoding()  # must not raise


# ---------------------------------------------------------------------------
# FEAT-UX-004 — --json covers the error path, and the commands that matter
# ---------------------------------------------------------------------------

class TestJsonCoversTheErrorPath:
    """``json.loads`` of a failing --json run used to hit English prose.

    errors.py has carried a structured code/message/hint/retryable shape from
    the start and cli.py never emitted it.
    """

    def test_error_is_machine_readable_under_json(self, tmp_path, capsys):
        missing = tmp_path / "nope.audiobooker"
        code = main(["status", "--json", "-p", str(missing)])

        assert code == 1
        captured = capsys.readouterr()
        # stderr, deliberately: stdout is the payload stream, so an error must
        # never land in a redirected `status --json > status.json`.
        payload = json.loads(captured.err)
        assert payload["code"]
        assert payload["message"]
        assert "hint" in payload
        assert payload["retryable"] is False

    def test_a_structured_error_keeps_its_own_code(self, capsys):
        from audiobooker.errors import CompilationFailedError

        _report_error = cli._report_error
        _report_error(
            CompilationFailedError("all failed", chapter_count=3),
            SimpleNamespace(json_output=True, debug=False),
        )
        payload = json.loads(capsys.readouterr().err)
        assert payload["code"] == "COMPILE_ALL_CHAPTERS_FAILED"
        assert payload["hint"]

    def test_plain_python_errors_still_get_a_stable_code(self, capsys):
        cli._report_error(
            FileNotFoundError("no such book"),
            SimpleNamespace(json_output=True, debug=False),
        )
        assert json.loads(capsys.readouterr().err)["code"] == "FILE_NOT_FOUND"

    def test_prose_is_unchanged_without_json(self, capsys):
        cli._report_error(ValueError("boom"), SimpleNamespace(json_output=False, debug=False))
        err = capsys.readouterr().err
        assert "Error: boom" in err
        with pytest.raises(json.JSONDecodeError):
            json.loads(err)


class TestJsonOnTheCommandsThatComputeNumbers:
    def test_compile_has_json(self, tmp_path, capsys):
        path = _make_project(tmp_path, compile_it=False)
        assert main(["compile", "-p", str(path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        # The unattributed rate that decides whether to proceed has to be
        # reachable from the command that computes it.
        assert "dialogue_unattributed_rate" in payload
        assert payload["quality"] in ("ok", "degraded", "failed")
        assert payload["utterances"] > 0
        assert isinstance(payload["uncast_speakers"], list)

    def test_compile_dry_run_has_json(self, tmp_path, capsys):
        path = _make_project(tmp_path, compile_it=False)
        assert main(["compile", "-p", str(path), "--dry-run", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["speakers"]

    def test_chapters_has_json(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        assert main(["chapters", "-p", str(path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["chapters"]) == 4

    def test_cast_suggest_has_json(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        assert main(["cast-suggest", "-p", str(path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["suggestions"]
        first = payload["suggestions"][0]
        assert "speaker" in first and "candidates" in first

    def test_render_dry_run_has_json(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        assert main(["render", "-p", str(path), "--dry-run", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["chapters"]
        assert "cast" in payload

    def test_render_result_is_json_and_stdout_carries_nothing_else(
        self, tmp_path, capsys, monkeypatch
    ):
        """Progress chatter and the rich bar both write to stdout — under
        --json neither may run, or the payload is unparseable."""
        path = _make_project(tmp_path)
        out_file = tmp_path / "out.m4b"
        out_file.write_bytes(b"fake")
        monkeypatch.setattr(
            AudiobookProject, "render", lambda self, out, **kw: out_file
        )

        code = main(["render", "-p", str(path), "--force", "-o", str(out_file), "--json"])

        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["complete"] is True
        assert payload["output"] == str(out_file)

    def test_render_failure_is_json_too(self, tmp_path, capsys, monkeypatch):
        path = _make_project(tmp_path)
        from audiobooker.renderer.engine import RenderError

        def _boom(self, out, **kw):
            raise RenderError("ffmpeg is not on PATH")

        monkeypatch.setattr(AudiobookProject, "render", _boom)

        code = main(["render", "-p", str(path), "--force", "--json"])

        assert code == 1
        captured = capsys.readouterr()
        assert captured.out.strip() == "", captured.out
        payload = json.loads(captured.err)
        assert payload["code"]
        assert "ffmpeg" in payload["message"]

    def test_render_json_ffmpeg_missing_without_force(
        self, tmp_path, capsys, monkeypatch
    ):
        """F-2d778457: ``render --json`` (no --force) ffmpeg miss is JSON.

        Renderer API preflights exist; the CLI operator copy used to be only
        the --force RenderError plant. Demand DEP_FFMPEG_MISSING on stderr.
        """
        import audiobooker.renderer.output as output_mod

        project = AudiobookProject.from_string(
            DIALOGUE_TEXT, title="Cast Book", author="Author"
        )
        project.compile()
        for speaker in list(project.get_uncast_speakers()):
            project.cast(speaker, "af_bella")
        project.config.validate_voices_on_render = False
        path = tmp_path / "book.audiobooker"
        project.save(path)

        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: False)
        monkeypatch.setattr(output_mod, "_ffmpeg_checked", False)

        code = main([
            "render", "-p", str(path), "--json",
            "-o", str(tmp_path / "out.m4b"),
        ])
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out.strip() == "", captured.out
        payload = json.loads(captured.err)
        assert payload["code"] == "DEP_FFMPEG_MISSING"
        assert payload["message"]
        assert "hint" in payload

    def test_render_json_engine_down_without_force(
        self, tmp_path, capsys, monkeypatch
    ):
        """F-2d778457: ``render --json`` engine ImportError is JSON.

        get_default_engine raising ImportError must surface
        RENDER_BACKEND_UNAVAILABLE (not UNEXPECTED_ERROR / English).
        """
        import audiobooker.renderer.output as output_mod

        project = AudiobookProject.from_string(
            DIALOGUE_TEXT, title="Cast Book", author="Author"
        )
        project.compile()
        for speaker in list(project.get_uncast_speakers()):
            project.cast(speaker, "af_bella")
        project.config.validate_voices_on_render = False
        path = tmp_path / "book.audiobooker"
        project.save(path)

        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(output_mod, "_ffmpeg_checked", True)

        def _boom(name=None):
            raise ImportError("voice-soundboard is required for rendering")

        monkeypatch.setattr(
            "audiobooker.renderer.engine.get_default_engine", _boom
        )

        code = main([
            "render", "-p", str(path), "--json",
            "-o", str(tmp_path / "out.m4b"),
        ])
        assert code != 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "", captured.out
        payload = json.loads(captured.err)
        assert payload["code"] == "RENDER_BACKEND_UNAVAILABLE", payload
        assert payload["message"]
        assert "hint" in payload


# ---------------------------------------------------------------------------
# FEAT-UX-002 — a typo'd speaker must not reach the TTS bill
# ---------------------------------------------------------------------------

def _uncast_named_speaker_project(tmp_path):
    """Sarah is cast under a typo'd key, so the real 'sarah' owns dialogue uncast."""
    project = AudiobookProject.from_string(DIALOGUE_TEXT, title="Typo Book")
    project.compile()
    project.cast("narrator", "af_heart")
    project.cast("Tom", "am_onyx")
    project.cast("Sarrah", "bm_george")  # the typo: real speaker is Sarah
    project.cast("unknown", "bf_emma")
    path = tmp_path / "typo.audiobooker"
    project.save(path)
    return path


class TestRenderRefusesAnUncastSpeakerWithDialogue:
    """`--force`'s help promised casting-completeness validation.

    One existed, in the renderer, but only above a 30%-of-all-utterances
    threshold and only after the CLI had announced the render and started the
    progress bar. A typo on a secondary character sat under the threshold and
    shipped in the fallback voice for the price of a full TTS run.
    """

    def test_render_refuses_before_spending_anything(self, tmp_path, capsys, monkeypatch):
        path = _uncast_named_speaker_project(tmp_path)

        from audiobooker.renderer import engine as engine_mod

        def _must_not_render(*a, **k):
            raise AssertionError("render must be refused before synthesis")

        monkeypatch.setattr(engine_mod, "render_project", _must_not_render)

        code = main(["render", "-p", str(path)])

        assert code == 1
        err = capsys.readouterr().err
        assert "sarah" in err.lower()
        assert "--force" in err

    def test_force_still_renders(self, tmp_path, monkeypatch):
        path = _uncast_named_speaker_project(tmp_path)
        calls = []

        from audiobooker.renderer import engine as engine_mod

        def _fake_render(project, out_path, **kwargs):
            calls.append(out_path)
            return out_path

        monkeypatch.setattr(engine_mod, "render_project", _fake_render)
        monkeypatch.setattr(
            AudiobookProject, "render", lambda self, out, **kw: calls.append(out) or out
        )

        assert main(["render", "-p", str(path), "--force"]) == 0
        assert calls

    def test_unknown_alone_does_not_trip_the_gate(self, tmp_path, monkeypatch):
        """'unknown' has its own gate; it must not be double-reported here."""
        project = AudiobookProject.from_string(DIALOGUE_TEXT, title="Fine Book")
        project.compile()
        for speaker in project.get_detected_speakers():
            if project.casting.normalize_key(speaker) != "unknown":
                project.cast(speaker, "af_heart")
        path = tmp_path / "fine.audiobooker"
        project.save(path)

        offenders = cli._uncast_dialogue_speakers(project, project.chapters)
        assert offenders == {}

    def test_dry_run_reports_the_cast(self, tmp_path, capsys):
        path = _uncast_named_speaker_project(tmp_path)
        assert main(["render", "-p", str(path), "--dry-run"]) == 0
        captured = capsys.readouterr()
        # Who reads the book is on stdout with the rest of the plan...
        assert "Cast (" in captured.out
        assert "bm_george" in captured.out
        # ...and the thing that will make a real render refuse is a warning.
        assert "Sarah" in captured.err
        assert "--force" in captured.err

    def test_force_help_names_the_gate_it_bypasses(self):
        parser = create_parser()
        help_text = parser.parse_args(["render", "--help"]) if False else None
        del help_text
        for action in parser._subparsers._group_actions[0].choices["render"]._actions:
            if "--force" in getattr(action, "option_strings", []):
                assert "uncast" in action.help.lower()
                break
        else:  # pragma: no cover - the flag exists
            pytest.fail("render has no --force flag")


# ---------------------------------------------------------------------------
# FEAT-UX-003 — `make` narrates its phases and can review
# ---------------------------------------------------------------------------

class TestMakeNarratesAndCanReview:
    def test_make_reports_each_phase(self, tmp_path, capsys, monkeypatch):
        source = tmp_path / "book.txt"
        source.write_text(DIALOGUE_TEXT, encoding="utf-8")

        from audiobooker.renderer import engine as engine_mod

        monkeypatch.setattr(
            engine_mod, "render_project", lambda p, out, **kw: out
        )

        assert main(["make", str(source), "-o", str(tmp_path / "out.m4b")]) == 0
        out = capsys.readouterr().out
        assert "Parsed" in out
        assert "Compiled" in out
        assert "attribution" in out.lower()
        assert "Cast" in out
        assert "4 chapter" in out

    def test_make_review_stops_after_compile(self, tmp_path, capsys, monkeypatch):
        source = tmp_path / "book.txt"
        source.write_text(DIALOGUE_TEXT, encoding="utf-8")

        from audiobooker.renderer import engine as engine_mod

        def _must_not_render(*a, **k):
            raise AssertionError("--review must not render")

        monkeypatch.setattr(engine_mod, "render_project", _must_not_render)

        assert main(["make", str(source), "--review"]) == 0
        out = capsys.readouterr().out
        assert "review-import" in out
        review_files = list(tmp_path.glob("*_review.txt"))
        assert review_files, "make --review must write a review file"
        assert (tmp_path / "book.audiobooker").exists()


# ---------------------------------------------------------------------------
# FEAT-UX-007 — one chapter number is never enough
# ---------------------------------------------------------------------------

class TestChapterNumbersAreUnambiguous:
    def test_chapters_prints_both_numbers(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        assert main(["chapters", "-p", str(path)]) == 0
        out = capsys.readouterr().out
        assert "[idx 0]" in out
        assert "ch.1" in out
        assert "[idx 3]" in out
        assert "ch.4" in out

    def test_chapters_json_carries_both_numbers(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        assert main(["chapters", "-p", str(path), "--json"]) == 0
        rows = json.loads(capsys.readouterr().out)["chapters"]
        assert rows[3]["index"] == 3
        assert rows[3]["number"] == 4

    def test_render_selection_names_the_real_chapters(self, tmp_path, capsys):
        """`--chapters 1-2,4` used to print [0] [1] [2] against titles 1, 2, 4."""
        path = _make_project(tmp_path)
        assert main(["render", "-p", str(path), "--dry-run", "--chapters", "1-2,4"]) == 0
        out = capsys.readouterr().out
        assert "[idx 3] ch.4" in out
        assert "[idx 2]" not in out  # chapter 3 was excluded by the selection

    def test_single_chapter_dry_run_prints_both(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        assert main(["render", "-p", str(path), "-c", "2", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "[idx 2]" in out
        assert "ch.3" in out


# ---------------------------------------------------------------------------
# Cheap correctness
# ---------------------------------------------------------------------------

class TestCastApplyActsOnTheEvidenceCastSuggestShows:
    """cmd_cast_suggest passed speaker_utterances; cmd_cast_apply did not.

    So the command that ACTS ranked on strictly less evidence than the command
    that EXPLAINS — for a male-cued speaker they chose different voices.
    """

    def test_apply_matches_suggest(self, tmp_path, capsys):
        text = (
            "Chapter 1\n\n"
            "The ward was cold. \"He will not last the night,\" said Doctor.\n"
            "He wiped his hands. \"His fever has broken,\" Doctor added.\n"
            "His voice was low when he spoke of his own father.\n"
        )
        project = AudiobookProject.from_string(text, title="Ward")
        project.compile()
        path = tmp_path / "ward.audiobooker"
        project.save(path)

        assert main(["cast-suggest", "-p", str(path), "--json", "-n", "1"]) == 0
        rows = json.loads(capsys.readouterr().out)["suggestions"]
        # Only the speakers cast-apply --auto will actually touch: the ones
        # cast-suggest reports as uncast.
        suggested = {
            row["speaker"]: row["candidates"][0]
            for row in rows
            if row["candidates"] and row["cast"] is None
        }
        assert "Doctor" in suggested, rows

        # The evidence itself, not just agreement: "he/his/father" in the
        # sample lines is the ONLY thing that can produce a male match, so
        # this pins that the samples reached the suggester at all. Two
        # commands agreeing on an evidence-free answer is not the fix.
        doctor = suggested["Doctor"]
        assert "gender match (male)" in doctor["reason"], doctor
        assert doctor["voice_id"].startswith(("am_", "bm_")), doctor

        assert main(["cast-apply", "-p", str(path), "--auto"]) == 0
        applied = AudiobookProject.load(path).casting.get_voice_mapping()

        for speaker, candidate in suggested.items():
            key = project.casting.normalize_key(speaker)
            assert applied[key] == candidate["voice_id"], (
                f"cast-apply chose {applied[key]} for {speaker} but "
                f"cast-suggest showed {candidate['voice_id']}"
            )

    def test_cast_apply_dry_run_changes_nothing(self, tmp_path, capsys):
        path = _make_project(tmp_path)
        before = AudiobookProject.load(path).casting.get_voice_mapping()

        assert main(["cast-apply", "-p", str(path), "--auto", "--dry-run"]) == 0
        after = AudiobookProject.load(path).casting.get_voice_mapping()

        assert after == before
        assert "DRY RUN" in capsys.readouterr().out


class TestPrintedCommandsArePasteable:
    def test_review_export_quotes_a_spaced_name(self, tmp_path, capsys):
        """The printed command must survive being pasted.

        The old one read ``audiobooker review-import The Midnight
        Garden_review.txt`` — three bare tokens, which argparse rejects with
        a dump of all 34 subcommands.
        """
        project = AudiobookProject.from_string(DIALOGUE_TEXT, title="The Midnight Garden")
        project.compile()
        path = tmp_path / "mg.audiobooker"
        project.save(path)
        spaced = tmp_path / "The Midnight Garden_review.txt"

        assert main(["review-export", "-p", str(path), "-o", str(spaced)]) == 0
        out = capsys.readouterr().out
        printed = [ln for ln in out.splitlines() if "review-import" in ln]
        assert printed, out
        command = printed[-1].split("audiobooker ", 1)[1].strip()

        # The name has a space, so it MUST come back as a single token.
        tokens = _split_command(command)
        assert tokens[0] == "review-import"
        assert len(tokens) == 2, f"argparse would reject: {command!r}"
        assert tokens[1] == spaced.name

    def test_a_name_needing_no_quotes_is_left_alone(self):
        """POSIX single-quoting every Windows path would be its own defect."""
        assert cli._quote_arg("mg_review.txt") == "mg_review.txt"
        assert " " not in cli._quote_arg("plain.txt")

    def test_review_file_defaults_to_the_project_stem(self, tmp_path):
        project = AudiobookProject.from_string(DIALOGUE_TEXT, title="The Midnight Garden")
        project.compile()
        path = tmp_path / "mg.audiobooker"
        project.save(path)

        assert main(["review-export", "-p", str(path)]) == 0
        assert (tmp_path / "mg_review.txt").exists()


class TestVoicesWorksOffline:
    def test_voices_lists_the_curated_catalog_without_the_backend(
        self, tmp_path, capsys, monkeypatch
    ):
        """cast-suggest and audition return voice ids with no backend installed;
        `voices` refused, so you could accept the machine's casting but never
        override it."""
        from audiobooker.casting import voice_registry

        def _unavailable(*a, **k):
            raise voice_registry.VoiceBackendUnavailableError()

        monkeypatch.setattr(voice_registry, "get_available_voices", _unavailable)

        assert main(["voices"]) == 0
        out = capsys.readouterr().out
        assert "af_heart" in out

    def test_offline_voices_say_so(self, capsys, monkeypatch):
        from audiobooker.casting import voice_registry

        monkeypatch.setattr(
            voice_registry,
            "get_available_voices",
            lambda *a, **k: (_ for _ in ()).throw(
                voice_registry.VoiceBackendUnavailableError()
            ),
        )
        assert main(["voices"]) == 0
        assert "built-in" in capsys.readouterr().err.lower()


class TestSpeakersReportsRealLineCounts:
    def test_counts_match_the_report_command(self, tmp_path, capsys):
        """`speakers` read Character.line_count, which is assigned per chapter
        (so the last chapter wins) and never at all for a speaker cast after
        compile. Everyone showed (0 lines) or one chapter's worth."""
        project = AudiobookProject.from_string(DIALOGUE_TEXT, title="Counts")
        project.compile()
        project.cast("Sarah", "af_heart")
        project.cast("narrator", "am_onyx")
        path = tmp_path / "counts.audiobooker"
        project.save(path)

        from audiobooker.casting import compile_report

        expected = compile_report(project.chapters, project.casting)["speaker_line_counts"]

        assert main(["speakers", "-p", str(path)]) == 0
        out = capsys.readouterr().out
        assert f"({expected['sarah']} lines)" in out
        assert expected["sarah"] > 0
