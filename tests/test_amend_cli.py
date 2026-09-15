"""Wave-2 amend regressions for audiobooker/cli.py + audiobooker/review.py.

Every test here is written in the SHAPE that the pre-existing suite could not
express, which is exactly why the defects survived wave 1:

* ``tests/test_review.py::TestRoundtrip`` uses strictly ALTERNATING speakers,
  so it can never observe consecutive same-speaker utterances collapsing into
  one on a zero-edit round trip (CLI-1).
* No test used a speaker name with a comma, so an appositive label like
  "Bob, the baker" silently became narrated body text (CLI-2).
* No test executed ``render -c N --dry-run``, so the dry-run guard sitting in
  the wrong branch performed a REAL render (CLI-3).

Nothing here touches TTS, ffmpeg, or voice-soundboard: every render entry
point is patched and asserted NOT to be called.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audiobooker.cli import main
from audiobooker.models import Chapter, Utterance, UtteranceType
from audiobooker.project import AudiobookProject
from audiobooker.review import SPEAKER_PATTERN, export_for_review, import_reviewed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_with(utterances: list[Utterance], title: str = "Amend Book"):
    """A one-chapter project holding exactly ``utterances``."""
    project = AudiobookProject(title=title, author="Amend Tester")
    project.chapters = [
        Chapter(index=0, title="Chapter 1", raw_text="", utterances=list(utterances))
    ]
    return project


def _write_compiled_project(tmp_path: Path, title: str = "Amend Render") -> Path:
    """A tiny compiled project saved to disk; returns its path."""
    # PH-B-002 (wave 5, out-of-grant declared edit): the dialogue line used
    # to be attributed only by a pronoun, which the attributor cannot resolve
    # to a name — this fixture's one utterance was 100% unattributed, which
    # is a genuinely 'failed' quality verdict, not a false positive. That was
    # incidental filler text for the render-plumbing tests below, not
    # something they meant to exercise, so it is reworded to attribute by
    # name rather than narrowing the new render gate to let a real
    # 100%-unknown book through.
    project = AudiobookProject.from_string(
        "Chapter 1\n\nHello world. This is narration.\n\n"
        '"I am Alice," said Alice.',
        title=title,
        author="Amend Tester",
    )
    project.cast("narrator", "af_heart")
    # FEAT-UX-002 (cli-surface wave, out-of-grant declared edit): `render`
    # now refuses when a NAMED speaker owns dialogue and has no voice, which
    # is what a typo'd speaker in a review file looks like. Alice was cast
    # nowhere and speaks one line, so these render-plumbing tests tripped the
    # new gate on incidental filler. Same remedy as the PH-B-002 note above:
    # fix the fixture so it exercises only what the test is named for,
    # rather than narrowing the gate.
    project.cast("Alice", "af_bella")
    project.compile()
    path = tmp_path / "amend.audiobooker"
    project.save(path)
    return path


def _no_render(*a, **kw):  # pragma: no cover - only runs when a fix regresses
    raise AssertionError("a real render was performed when it must not be")


# ===========================================================================
# CLI-1 — consecutive same-speaker utterances must survive a zero-edit trip
# ===========================================================================


class TestReviewConsecutiveSameSpeakerRoundTrip:
    """The failing SHAPE: consecutive same-speaker blocks, one non-NARRATION."""

    @staticmethod
    def _original() -> list[Utterance]:
        return [
            Utterance(speaker="narrator", text="The door creaked open.",
                      utterance_type=UtteranceType.NARRATION),
            Utterance(speaker="narrator", text="She stepped inside.",
                      utterance_type=UtteranceType.NARRATION),
            Utterance(speaker="narrator", text="[pause]",
                      utterance_type=UtteranceType.PAUSE),
            Utterance(speaker="narrator", text="The lamp guttered.",
                      utterance_type=UtteranceType.NARRATION),
        ]

    def test_zero_edit_roundtrip_preserves_count_order_and_type(self, tmp_path):
        """4 consecutive narrator utterances must come back as 4, in order."""
        original = self._original()
        project = _project_with(original)

        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)
        import_reviewed(project, review_path)

        result = project.chapters[0].utterances
        assert len(result) == len(original), (
            f"zero-edit round trip changed the utterance count: "
            f"{len(original)} -> {len(result)}; texts={[u.text for u in result]!r}"
        )
        assert [u.text for u in result] == [u.text for u in original]
        assert [u.utterance_type for u in result] == [
            u.utterance_type for u in original
        ]

    def test_pause_marker_is_not_merged_into_narration(self, tmp_path):
        """The PAUSE marker must not become narrated prose."""
        project = _project_with(self._original())
        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)
        import_reviewed(project, review_path)

        pauses = [
            u for u in project.chapters[0].utterances
            if u.utterance_type is UtteranceType.PAUSE
        ]
        assert len(pauses) == 1, (
            "the PAUSE utterance was destroyed by the round trip; got "
            f"{[(u.text, u.utterance_type) for u in project.chapters[0].utterances]!r}"
        )
        assert pauses[0].text == "[pause]"

    def test_emotion_change_is_still_applied_per_block(self, tmp_path):
        """One tag per utterance must not break per-block emotion edits."""
        project = _project_with(self._original())
        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)

        content = review_path.read_text(encoding="utf-8")
        content = content.replace("@narrator\n", "@narrator (somber)\n", 1)
        review_path.write_text(content, encoding="utf-8")

        import_reviewed(project, review_path)
        emotions = [u.emotion for u in project.chapters[0].utterances]
        assert emotions[0] == "somber"


# ===========================================================================
# CLI-2 — an @-leading line must never be absorbed as body text
# ===========================================================================


class TestReviewSpeakerNameParsing:
    def test_speaker_pattern_accepts_appositive_comma(self):
        """'Bob, the baker' is an ordinary speaker label, not body text."""
        match = SPEAKER_PATTERN.match("@Bob, the baker")
        assert match is not None, "a comma in a speaker name must parse"
        assert match.group(1) == "Bob, the baker"
        assert match.group(2) is None

    def test_speaker_pattern_accepts_comma_plus_emotion(self):
        match = SPEAKER_PATTERN.match("@Mrs. Hale, the housekeeper (weary)")
        assert match is not None
        assert match.group(1) == "Mrs. Hale, the housekeeper"
        assert match.group(2) == "weary"

    def test_roundtrip_preserves_comma_speaker(self, tmp_path):
        """Zero-edit round trip must keep the character, not narrate the tag."""
        original = [
            Utterance(speaker="narrator", text="The shop was warm.",
                      utterance_type=UtteranceType.NARRATION),
            Utterance(speaker="Bob, the baker", text='"Fresh bread!"',
                      utterance_type=UtteranceType.DIALOGUE),
        ]
        project = _project_with(original)
        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)
        import_reviewed(project, review_path)

        result = project.chapters[0].utterances
        assert len(result) == 2, (
            "the @-tag was absorbed as body text; got "
            f"{[(u.speaker, u.text) for u in result]!r}"
        )
        assert result[1].speaker == "Bob, the baker"
        assert "@Bob" not in result[0].text
        assert "@Bob" not in result[1].text

    def test_ambiguous_double_emotion_is_flagged_not_narrated(self, tmp_path):
        """'@Bob (terrified) (fearful)' — what the file's own 'change @Name
        (old) to @Name (new)' instruction produces when a user APPENDS rather
        than replaces — is ambiguous. It must be reported, never spoken."""
        ambiguous = "@Bob (terrified) (fearful)"
        assert SPEAKER_PATTERN.match(ambiguous) is None

        project = _project_with(
            [Utterance(speaker="narrator", text="The night was cold.")]
        )
        review = tmp_path / "review.txt"
        review.write_text(
            "=== Chapter 1 ===\n\n@narrator\nThe night was cold.\n\n"
            f"{ambiguous}\n\"Help!\"\n",
            encoding="utf-8",
        )
        stats = import_reviewed(project, review)

        assert stats["malformed_lines"], "the ambiguous tag was swallowed"
        assert ambiguous in stats["malformed_lines"][0]["text"]
        texts = " ".join(u.text for u in project.chapters[0].utterances)
        assert "@Bob" not in texts


class TestReviewMalformedLines:
    MALFORMED = "@Bob <the baker>"

    def _review_file(self, tmp_path: Path) -> Path:
        review = tmp_path / "review.txt"
        review.write_text(
            "=== Chapter 1 ===\n"
            "\n"
            "@narrator\n"
            "The shop was warm.\n"
            "\n"
            f"{self.MALFORMED}\n"
            "Fresh bread!\n",
            encoding="utf-8",
        )
        return review

    def test_unmatched_at_line_is_never_body_text(self, tmp_path):
        """An unparseable @-line must be reported, never narrated aloud."""
        project = _project_with(
            [Utterance(speaker="narrator", text="The shop was warm.")]
        )
        stats = import_reviewed(project, self._review_file(tmp_path))

        malformed = stats.get("malformed_lines")
        assert malformed, (
            "an unmatched @-line was swallowed instead of reported; stats="
            f"{ {k: v for k, v in stats.items() if k != 'speakers_found'} !r}"
        )
        entry = malformed[0]
        assert self.MALFORMED in entry["text"]
        assert entry["line"] > 0

        texts = " ".join(u.text for u in project.chapters[0].utterances)
        assert self.MALFORMED not in texts, (
            "the malformed tag leaked into narrated body text"
        )

    def test_cli_review_import_reports_and_fails(self, tmp_path, monkeypatch, capsys):
        """`review-import` must not print 'Ready to render' and exit 0."""
        monkeypatch.chdir(tmp_path)
        project = _project_with(
            [Utterance(speaker="narrator", text="The shop was warm.")]
        )
        proj_path = tmp_path / "amend.audiobooker"
        project.save(proj_path)
        review = self._review_file(tmp_path)

        code = main(["review-import", str(review), "-p", str(proj_path)])
        captured = capsys.readouterr()

        assert code != 0, "a malformed review file must not exit 0"
        assert "Ready to render" not in captured.out
        # Residual 4: the malformed-line report goes through _err -> stderr.
        assert self.MALFORMED in captured.err

    def test_emptied_chapter_is_reported(self, tmp_path):
        """A matched chapter whose utterances drop to 0 must be flagged."""
        project = _project_with(
            [Utterance(speaker="narrator", text="Something."),
             Utterance(speaker="narrator", text="Anything.")]
        )
        review = tmp_path / "review.txt"
        review.write_text("=== Chapter 1 ===\n\n", encoding="utf-8")

        stats = import_reviewed(project, review)
        assert stats.get("emptied_chapters"), (
            "a chapter emptied by the import was not reported; stats="
            f"{ {k: v for k, v in stats.items() if k != 'speakers_found'} !r}"
        )


class TestReviewVerseIndentation:
    def test_leading_whitespace_survives_roundtrip(self, tmp_path):
        """Verse/epigraph indentation must not be flattened to prose."""
        verse = "Roses are red,\n    Violets are blue,\n    So say we all."
        project = _project_with(
            [Utterance(speaker="narrator", text=verse,
                       utterance_type=UtteranceType.NARRATION)]
        )
        review_path = tmp_path / "review.txt"
        export_for_review(project, review_path)
        import_reviewed(project, review_path)

        text = project.chapters[0].utterances[0].text
        assert text == verse, f"verse lost its shape on round trip: {text!r}"


# ===========================================================================
# CLI-3 / CLI-5 — the single-chapter render branch
# ===========================================================================


class TestRenderSingleChapter:
    def test_dry_run_with_chapter_writes_nothing(self, tmp_path, monkeypatch, capsys):
        """`render -c 0 --dry-run` must preview, never synthesize."""
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)

        monkeypatch.setattr(AudiobookProject, "render_chapter", _no_render)
        with patch("audiobooker.renderer.engine.render_chapter", _no_render):
            code = main(["render", "-p", str(proj), "-c", "0", "--dry-run"])

        assert code == 0
        assert not list(tmp_path.glob("chapter_*.wav")), (
            "--dry-run wrote a chapter WAV"
        )
        out = capsys.readouterr().out.lower()
        assert "dry run" in out or "would render" in out

    def test_dry_run_with_chapter_and_engine_writes_nothing(
        self, tmp_path, monkeypatch
    ):
        """The --engine sub-path must honor --dry-run too."""
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)

        monkeypatch.setattr(AudiobookProject, "render_chapter", _no_render)
        with patch(
            "audiobooker.renderer.engine.get_default_engine",
            return_value=MagicMock(name="engine"),
        ), patch("audiobooker.renderer.engine.render_chapter", _no_render):
            code = main([
                "render", "-p", str(proj), "-c", "0",
                "--dry-run", "--engine", "my-tts",
            ])

        assert code == 0
        assert not list(tmp_path.glob("chapter_*.wav"))

    def test_plain_single_chapter_render_still_works(self, tmp_path, monkeypatch):
        """The new guard must not block the ordinary `render -c N`."""
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)
        out = tmp_path / "chapter_000.wav"

        def _fake(self, chapter_index, output=None, *a, **kw):
            Path(output).write_bytes(b"wav")
            return Path(output)

        monkeypatch.setattr(AudiobookProject, "render_chapter", _fake)
        code = main(["render", "-p", str(proj), "-c", "0"])

        assert code == 0
        assert out.exists()

    @pytest.mark.parametrize("bad", ["-1", "99"])
    def test_out_of_range_chapter_rejected(self, tmp_path, monkeypatch, bad):
        """`render -c -1` must not silently render the last chapter."""
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)

        monkeypatch.setattr(AudiobookProject, "render_chapter", _no_render)
        with patch("audiobooker.renderer.engine.render_chapter", _no_render):
            code = main(["render", "-p", str(proj), "-c", bad])

        assert code == 1
        assert not list(tmp_path.glob("chapter_*.wav"))

    def test_chapter_with_mastering_flags_rejected(self, tmp_path, monkeypatch, capsys):
        """`render -c 0 --acx --format mp3` must fail fast, not lie."""
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"jpg")

        monkeypatch.setattr(AudiobookProject, "render_chapter", _no_render)
        with patch("audiobooker.renderer.engine.render_chapter", _no_render):
            code = main([
                "render", "-p", str(proj), "-c", "0",
                "--acx", "--format", "mp3", "--cover", str(cover),
            ])

        assert code == 1
        combined = capsys.readouterr()
        text = combined.out + combined.err
        assert "--acx" in text and "--format" in text and "--cover" in text

    def test_chapter_with_chapters_filter_rejected(self, tmp_path, monkeypatch, capsys):
        """-c and --chapters mean different things; refuse the combination."""
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)

        monkeypatch.setattr(AudiobookProject, "render_chapter", _no_render)
        with patch("audiobooker.renderer.engine.render_chapter", _no_render):
            code = main(["render", "-p", str(proj), "-c", "0", "--chapters", "0"])

        assert code == 1
        combined = capsys.readouterr()
        assert "--chapters" in combined.out + combined.err


# ===========================================================================
# CLI-4 — make must honor --chapter-delimiter / --force-text
# ===========================================================================


class TestMakeThreadsInputFlags:
    def test_chapter_delimiter_reaches_from_text(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "notes.txt"
        src.write_text("Scene 1\n\nA.\n\nScene 2\n\nB.\n", encoding="utf-8")

        real_from_text = AudiobookProject.from_text
        seen: dict = {}

        def _spy(path, **kwargs):
            seen.update(kwargs)
            return real_from_text(path, **kwargs)

        monkeypatch.setattr(AudiobookProject, "from_text", staticmethod(_spy))
        with patch(
            "audiobooker.renderer.engine.render_project",
            return_value=tmp_path / "out.m4b",
        ):
            main(["make", str(src), "--chapter-delimiter", "^Scene [0-9]+"])

        assert seen.get("chapter_delimiter") == "^Scene [0-9]+", (
            f"--chapter-delimiter never reached from_text; saw {seen!r}"
        )

    def test_force_text_reaches_from_pdf(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        seen: dict = {}

        def _fake_from_pdf(path, **kwargs):
            seen.update(kwargs)
            return AudiobookProject.from_string("Chapter 1\n\nText.", title="Scan")

        monkeypatch.setattr(
            AudiobookProject, "from_pdf", staticmethod(_fake_from_pdf)
        )
        with patch(
            "audiobooker.renderer.engine.render_project",
            return_value=tmp_path / "out.m4b",
        ):
            main(["make", str(src), "--force-text"])

        assert seen.get("force_text") is True, (
            f"--force-text never reached from_pdf; saw {seen!r}"
        )


# ===========================================================================
# CLI-6 — config-file values must beat argparse DEFAULTS
# ===========================================================================


class TestConfigPrecedence:
    def test_config_format_wins_over_argparse_default(self, tmp_path, monkeypatch):
        """A config saying mp3, with no --format typed, must produce mp3."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".audiobookerrc").write_text(
            'format = "mp3"\n', encoding="utf-8"
        )
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello.\n", encoding="utf-8")

        with patch(
            "audiobooker.renderer.engine.render_project",
            return_value=tmp_path / "out.mp3",
        ) as mock_rp:
            code = main(["make", str(src)])

        assert code == 0
        assert mock_rp.call_args.kwargs.get("output_format") == "mp3", (
            "argparse's m4b default clobbered the config file"
        )

    def test_explicit_format_flag_still_wins(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".audiobookerrc").write_text(
            'format = "mp3"\n', encoding="utf-8"
        )
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello.\n", encoding="utf-8")

        with patch(
            "audiobooker.renderer.engine.render_project",
            return_value=tmp_path / "out.wav",
        ) as mock_rp:
            code = main(["make", str(src), "--format", "wav"])

        assert code == 0
        assert mock_rp.call_args.kwargs.get("output_format") == "wav"

    def test_config_booknlp_wins_over_argparse_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".audiobookerrc").write_text(
            'booknlp_mode = "off"\n', encoding="utf-8"
        )
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello.\n", encoding="utf-8")

        code = main(["new", str(src)])
        assert code == 0

        project = AudiobookProject.load(src.with_suffix(".audiobooker"))
        assert project.config.booknlp_mode == "off", (
            "argparse's 'auto' default clobbered the config file"
        )

    def test_explicit_booknlp_flag_still_wins(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".audiobookerrc").write_text(
            'booknlp_mode = "off"\n', encoding="utf-8"
        )
        src = tmp_path / "book.txt"
        src.write_text("Chapter 1\n\nHello.\n", encoding="utf-8")

        code = main(["new", str(src), "--booknlp", "on"])
        assert code == 0

        project = AudiobookProject.load(src.with_suffix(".audiobooker"))
        assert project.config.booknlp_mode == "on"


# ===========================================================================
# CLI-7 — cast must not accept a typo'd voice id in silence
# ===========================================================================


class TestCastVoiceValidation:
    VOICES = {"af_bella", "af_heart", "am_liam", "bm_george"}

    def _project(self, tmp_path: Path) -> Path:
        project = AudiobookProject.from_string("Hello world.", title="Cast Test")
        path = tmp_path / "cast.audiobooker"
        project.save(path)
        return path

    def test_typo_voice_warns_with_suggestion(self, tmp_path, monkeypatch, capsys):
        path = self._project(tmp_path)
        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices",
            lambda *a, **kw: set(self.VOICES),
        )

        code = main(["cast", "narrator", "af_bela", "-p", str(path)])
        combined = capsys.readouterr()
        text = combined.out + combined.err

        assert "af_bela" in text
        assert "af_bella" in text, (
            f"no close-match suggestion for the typo; got {text!r}"
        )
        # Warn, don't hard-fail: a pluggable engine may expose other ids.
        assert code == 0

    def test_known_voice_is_silent(self, tmp_path, monkeypatch, capsys):
        path = self._project(tmp_path)
        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices",
            lambda *a, **kw: set(self.VOICES),
        )

        code = main(["cast", "narrator", "af_bella", "-p", str(path)])
        combined = capsys.readouterr()
        assert code == 0
        assert "WARNING" not in (combined.out + combined.err)

    def test_force_suppresses_the_warning(self, tmp_path, monkeypatch, capsys):
        path = self._project(tmp_path)
        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices",
            lambda *a, **kw: set(self.VOICES),
        )

        code = main(["cast", "narrator", "zz_custom", "-p", str(path), "--force"])
        combined = capsys.readouterr()
        assert code == 0
        assert "zz_custom" not in (combined.out + combined.err).replace(
            "Cast narrator as zz_custom", ""
        )

    def test_unavailable_registry_is_not_fatal(self, tmp_path, monkeypatch):
        """No voice-soundboard installed => validation is skipped, not fatal."""
        path = self._project(tmp_path)

        def _boom(*a, **kw):
            raise ImportError("voice-soundboard is required")

        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices", _boom
        )
        code = main(["cast", "narrator", "af_bella", "-p", str(path)])
        assert code == 0


# ===========================================================================
# CLI-8 — audition --render must not claim success when everything failed
# ===========================================================================


class TestAuditionRenderFailures:
    CANDIDATES = [
        {"voice_id": "af_heart", "gender": "female", "style": "warm", "score": 0.9},
        {"voice_id": "bm_george", "gender": "male", "style": "deep", "score": 0.8},
    ]

    def test_all_failed_returns_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)

        def _fail(*a, **kw):
            raise RuntimeError("engine exploded")

        with patch(
            "audiobooker.casting.voice_suggester.audition_voices",
            return_value=list(self.CANDIDATES),
        ), patch("audiobooker.renderer.engine.render_chapter", _fail):
            code = main([
                "audition", "narrator", "-p", str(proj), "--render",
                "-o", str(tmp_path / "aud"),
            ])

        combined = capsys.readouterr()
        assert code != 0, "every sample render failed but audition exited 0"
        assert "engine exploded" in combined.out + combined.err

    def test_json_payload_lists_failures(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        proj = _write_compiled_project(tmp_path)

        def _half(chapter, casting, output_path, **kw):
            if "bm_george" in str(output_path):
                raise RuntimeError("no such voice")
            Path(output_path).write_bytes(b"wav")
            return Path(output_path)

        with patch(
            "audiobooker.casting.voice_suggester.audition_voices",
            return_value=list(self.CANDIDATES),
        ), patch("audiobooker.renderer.engine.render_chapter", _half):
            code = main([
                "audition", "narrator", "-p", str(proj), "--render", "--json",
                "-o", str(tmp_path / "aud"),
            ])

        payload = json.loads(capsys.readouterr().out)
        assert code == 0, "a partial success must still exit 0"
        assert [r["voice_id"] for r in payload["rendered"]] == ["af_heart"]
        assert payload.get("failed"), "the --json payload hid the failure"
        assert payload["failed"][0]["voice_id"] == "bm_george"


# ===========================================================================
# Cross-cutting — a --json payload must never carry an error line
# ===========================================================================


class TestJsonPayloadNotCorruptedByErrors:
    def test_status_json_error_goes_to_stderr(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        missing = tmp_path / "nope.audiobooker"

        code = main(["status", "--json", "-p", str(missing)])
        captured = capsys.readouterr()

        assert code == 1
        assert "Error" not in captured.out, (
            f"the error line corrupted the JSON payload on stdout: {captured.out!r}"
        )
        # FEAT-UX-004 (cli-surface wave) amended this assertion. It read
        # `"Error" in captured.err`, which pinned the PROSE format; under
        # --json the failure is now reported as the same structured
        # code/message/hint/retryable object errors.py has always carried, so
        # `json.loads(stderr)` works when something goes wrong. The behaviour
        # this test is named for — the error is on stderr and not in the
        # stdout payload — is unchanged and still asserted, above and below.
        import json as _json

        payload = _json.loads(captured.err)
        assert payload["code"] == "FILE_NOT_FOUND"
        assert "not found" in payload["message"].lower()

    def test_plain_status_error_also_on_stderr(self, tmp_path, monkeypatch, capsys):
        """Residual 4: stderr routing is unconditional, not gated on --json.

        This test used to assert the opposite ("the historical stdout behavior
        is unchanged"), which is precisely the behavior wave 2 wanted to flip
        and could not, because eight assertions in other domains' files read
        error text off stdout.
        """
        monkeypatch.chdir(tmp_path)
        missing = tmp_path / "nope.audiobooker"

        code = main(["status", "-p", str(missing)])
        captured = capsys.readouterr()
        assert code == 1
        assert "Error" not in captured.out
        assert "Error" in captured.err


class TestStructuredErrorSurfacing:
    def test_report_error_surfaces_code_and_retryable(self, capsys):
        from audiobooker.cli import _report_error
        from audiobooker.errors import AudiobookerError, ErrorDetail

        err = AudiobookerError(
            ErrorDetail(
                code="RENDER_BACKEND_UNAVAILABLE",
                message="TTS backend is down",
                hint="Retry in a moment",
                retryable=True,
            )
        )
        _report_error(err)
        captured = capsys.readouterr()
        # Residual 4: _report_error goes through _err, which is stderr-only.
        assert captured.out == ""
        err_text = captured.err

        assert "RENDER_BACKEND_UNAVAILABLE" in err_text
        assert "retryable" in err_text.lower()
        assert "Retry in a moment" in err_text
