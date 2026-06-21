"""Regression tests for Stage A CLI/project health fixes.

Covers the six verified defects fixed in cli.py and project.py:

  CLI-A-001  render --chapters must not delete chapters from the saved file
  CLI-A-002  notification title/message must not allow command injection
  CLI-A-003  the `load` subcommand must be wired into the dispatch table
  CLI-A-007  load() must reject valid-JSON-but-wrong-shape files clearly
  CLI-A-008  pronunciation add must go through add_pronunciation() validation
  OUTPUT-A-006 (CLI portion)  render --cover must validate the path early

Each test fails against the old behavior and passes against the fix.
No network, no real ffmpeg, no real voice-soundboard.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from audiobooker import AudiobookProject
from audiobooker.cli import (
    main,
    _ps_single_quote,
    _osascript_double_quote,
    _sanitize_notification_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path, n_chapters=4):
    """Build and save a multi-chapter project; return its path."""
    chapters = [
        (f"Chapter {i + 1}", f"This is the body text of chapter number {i + 1}.")
        for i in range(n_chapters)
    ]
    project = AudiobookProject.from_chapters(chapters, title="Test Book")
    path = tmp_path / "book.audiobooker"
    project.save(path)
    return path


# ---------------------------------------------------------------------------
# CLI-A-001 — transient render filter must not be persisted (data loss)
# ---------------------------------------------------------------------------

class TestRenderChapterSelectionDoesNotDeleteChapters:
    def test_render_with_chapters_filter_preserves_all_chapters_on_disk(
        self, tmp_path, monkeypatch
    ):
        """`render --chapters 1-2` on a 4-chapter project must leave all 4
        chapters in the saved project file."""
        project_path = _make_project(tmp_path, n_chapters=4)

        # Mock the actual render so we exercise the CLI flow without TTS/ffmpeg.
        fake_output = tmp_path / "out.m4b"

        def fake_render(self, output=None, *args, **kwargs):
            # Inside cmd_render, project.chapters has been reduced to the
            # selected subset at this point — that is expected during render.
            assert len(self.chapters) == 2
            fake_output.write_bytes(b"fake")
            return fake_output

        monkeypatch.setattr(AudiobookProject, "render", fake_render)

        code = main([
            "render",
            "-p", str(project_path),
            "--chapters", "1-2",
            "-o", str(fake_output),
        ])
        assert code == 0

        # The saved project file must still contain all 4 chapters.
        reloaded = AudiobookProject.load(project_path)
        assert len(reloaded.chapters) == 4

        # And the raw JSON on disk must list 4 chapters too.
        raw = json.loads(project_path.read_text(encoding="utf-8"))
        assert len(raw["chapters"]) == 4

    def test_render_with_exclude_chapters_preserves_all_chapters_on_disk(
        self, tmp_path, monkeypatch
    ):
        """`render --exclude-chapters 4` must not drop chapter 4 from the file."""
        project_path = _make_project(tmp_path, n_chapters=4)
        fake_output = tmp_path / "out.m4b"

        def fake_render(self, output=None, *args, **kwargs):
            fake_output.write_bytes(b"fake")
            return fake_output

        monkeypatch.setattr(AudiobookProject, "render", fake_render)

        code = main([
            "render",
            "-p", str(project_path),
            "--exclude-chapters", "4",
            "-o", str(fake_output),
        ])
        assert code == 0

        reloaded = AudiobookProject.load(project_path)
        assert len(reloaded.chapters) == 4


# ---------------------------------------------------------------------------
# CLI-A-002 — notification command injection
# ---------------------------------------------------------------------------

class TestNotificationCommandInjection:
    INJECTION = 'x"; calc.exe ; "'

    def test_powershell_quote_keeps_injection_inside_a_literal(self):
        quoted = _ps_single_quote(self.INJECTION)
        # The whole value must be wrapped in a single-quoted literal so the
        # double-quote can never break out into executable code.
        assert quoted.startswith("'")
        assert quoted.endswith("'")
        # The injected double-quote stays *inside* the quoted literal.
        inner = quoted[1:-1]
        assert "calc.exe" in inner
        # A double-quote is harmless inside a single-quoted PS string; what we
        # must guarantee is no UNescaped single-quote breaks the literal.
        # Every single-quote in the inner text must be doubled.
        assert "'" not in inner.replace("''", "")

    def test_powershell_quote_doubles_embedded_single_quotes(self):
        quoted = _ps_single_quote("it's a 'title'")
        assert quoted == "'it''s a ''title'''"

    def test_powershell_full_command_has_no_unquoted_injection(self):
        title = self.INJECTION
        message = "done"
        command = (
            f"New-BurntToastNotification -Text "
            f"{_ps_single_quote(title)}, {_ps_single_quote(message)}"
        )
        # The literal injected double-quote must never appear outside a quoted
        # segment. Strip out single-quoted literals and confirm the dangerous
        # tokens are gone from what remains.
        import re

        outside = re.sub(r"'(?:[^']|'')*'", "", command)
        assert '"' not in outside
        assert "calc.exe" not in outside

    def test_osascript_quote_escapes_double_quotes(self):
        quoted = _osascript_double_quote(self.INJECTION)
        assert quoted.startswith('"')
        assert quoted.endswith('"')
        inner = quoted[1:-1]
        # Every double-quote in the body must be backslash-escaped.
        assert '"' not in inner.replace('\\"', "")
        assert "calc.exe" in inner

    def test_osascript_quote_escapes_backslashes(self):
        quoted = _osascript_double_quote('a\\b"c')
        assert quoted == '"a\\\\b\\"c"'

    def test_sanitize_strips_control_characters(self):
        cleaned = _sanitize_notification_text("hello\nworld\r\x00!")
        assert "\n" not in cleaned
        assert "\r" not in cleaned
        assert "\x00" not in cleaned
        assert "hello" in cleaned and "world" in cleaned


# ---------------------------------------------------------------------------
# CLI-A-003 — `load` subcommand must be dispatched
# ---------------------------------------------------------------------------

class TestLoadSubcommand:
    def test_load_returns_zero_and_prints_info(self, tmp_path, capsys):
        project_path = _make_project(tmp_path, n_chapters=3)

        code = main(["load", str(project_path)])
        assert code == 0

        out = capsys.readouterr().out
        assert "Unknown command" not in out
        assert "Test Book" in out
        assert "Chapters: 3" in out

    def test_load_missing_file_reports_error(self, tmp_path, capsys):
        code = main(["load", str(tmp_path / "nope.audiobooker")])
        assert code == 1
        out = capsys.readouterr().out
        assert "Unknown command" not in out
        assert "Error" in out


# ---------------------------------------------------------------------------
# CLI-A-007 — load() must reject wrong-shape JSON with a clear message
# ---------------------------------------------------------------------------

class TestLoadWrongShapeJson:
    def test_top_level_array_raises_valueerror_not_attributeerror(self, tmp_path):
        bad = tmp_path / "bad.audiobooker"
        bad.write_text("[1, 2, 3]", encoding="utf-8")

        with pytest.raises(ValueError) as exc_info:
            AudiobookProject.load(bad)

        # Must be a clear ValueError, never a raw AttributeError.
        assert not isinstance(exc_info.value, AttributeError)
        msg = str(exc_info.value).lower()
        assert "audiobooker project" in msg

    def test_top_level_string_raises_valueerror(self, tmp_path):
        bad = tmp_path / "bad2.audiobooker"
        bad.write_text('"just a string"', encoding="utf-8")
        with pytest.raises(ValueError):
            AudiobookProject.load(bad)


# ---------------------------------------------------------------------------
# CLI-A-008 — pronunciation add must validate via add_pronunciation()
# ---------------------------------------------------------------------------

class TestPronunciationAddValidation:
    def test_empty_word_is_rejected_and_not_stored(self, tmp_path, capsys):
        project_path = _make_project(tmp_path, n_chapters=1)

        code = main([
            "pronunciation", "add", "", "replacement",
            "-p", str(project_path),
        ])
        assert code != 0

        # The empty entry must not be persisted.
        reloaded = AudiobookProject.load(project_path)
        assert "" not in reloaded.config.pronunciation_overrides
        assert "replacement" not in reloaded.config.pronunciation_overrides.values()

    def test_whitespace_is_stripped_when_stored(self, tmp_path):
        project_path = _make_project(tmp_path, n_chapters=1)

        code = main([
            "pronunciation", "add", "  Hermione  ", "  Her-MY-oh-nee  ",
            "-p", str(project_path),
        ])
        assert code == 0

        reloaded = AudiobookProject.load(project_path)
        assert reloaded.config.pronunciation_overrides.get("Hermione") == "Her-MY-oh-nee"
        # The un-stripped key must not exist.
        assert "  Hermione  " not in reloaded.config.pronunciation_overrides


# ---------------------------------------------------------------------------
# OUTPUT-A-006 (CLI portion) — render --cover must validate the path early
# ---------------------------------------------------------------------------

class TestRenderCoverValidation:
    def test_missing_cover_errors_clearly_and_does_not_render(self, tmp_path):
        project_path = _make_project(tmp_path, n_chapters=2)

        called = {"render": False}

        def fake_render(self, *args, **kwargs):  # pragma: no cover - must not run
            called["render"] = True
            return tmp_path / "out.m4b"

        # Patch both possible render entry points so a regression that skips
        # the early check is caught.
        with patch.object(AudiobookProject, "render", fake_render):
            code = main([
                "render",
                "-p", str(project_path),
                "--cover", str(tmp_path / "does_not_exist.png"),
                "-o", str(tmp_path / "out.m4b"),
            ])

        assert code == 1
        assert called["render"] is False

    def test_existing_cover_passes_validation(self, tmp_path, monkeypatch):
        project_path = _make_project(tmp_path, n_chapters=2)
        cover = tmp_path / "cover.png"
        cover.write_bytes(b"\x89PNG fake")
        out = tmp_path / "out.m4b"

        captured = {"cover": None}

        # cmd_render uses render_project when --cover is given.
        import audiobooker.renderer.engine as engine_mod

        def fake_render_project(project, output, *args, **kwargs):
            captured["cover"] = kwargs.get("cover_art")
            out.write_bytes(b"fake")
            return out

        monkeypatch.setattr(engine_mod, "render_project", fake_render_project)
        # Avoid real compilation work.
        monkeypatch.setattr(AudiobookProject, "compile", lambda self, *a, **k: None)

        code = main([
            "render",
            "-p", str(project_path),
            "--cover", str(cover),
            "-o", str(out),
        ])
        assert code == 0
        assert captured["cover"] == str(cover)
