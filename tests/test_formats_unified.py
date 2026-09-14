"""F-7a3c91e2: one output-format table, and `--format wav` means WAV.

Six allowlists disagreed across three files. The consequences ran in both
directions at once: Opus and FLAC had working assemblers and were advertised
in the README but `--format` refused them, while `wav` -- one of only three
formats `--format` DID accept -- had no assembler branch and fell through the
dispatch's `else` to the M4B assembler.

These tests are drift guards. Each one fails if a format is added to the table
without the layer above learning about it, which is exactly how the six lists
came apart.
"""

from __future__ import annotations

import pathlib

import pytest

import audiobooker.renderer.output as output_mod
from audiobooker import formats as audio_formats
from audiobooker.models import ProjectConfig
from audiobooker.renderer import engine as engine_mod
from audiobooker.renderer.engine import RenderError, render_project_detailed
from audiobooker.renderer.output import AssemblyResult

from tests.test_stageb_renderer import FakeTTSEngine, _make_project


class TestTheAllowlistsAgree:
    """The four surviving allowlists must all derive from the one table."""

    def test_engine_valid_formats_is_the_table(self):
        assert engine_mod.VALID_OUTPUT_FORMATS == set(
            audio_formats.ALL_FORMAT_NAMES
        )

    def test_config_validator_is_the_table(self):
        assert set(ProjectConfig._VALID_OUTPUT_FORMATS) == set(
            audio_formats.ALL_FORMAT_NAMES
        )

    def test_cli_book_choices_are_the_table(self):
        """Every whole-book format `--format` offers is really assemblable."""
        for name in audio_formats.BOOK_FORMATS:
            spec = audio_formats.get(name)
            assert spec.whole_book
            assert hasattr(output_mod, spec.assembler)

    def test_podcast_choices_never_narrowed(self):
        """Unifying allowlists may widen a published choice list, never
        narrow it -- narrowing breaks commands that work today."""
        previously_accepted = {"m4b", "m4a", "mp3", "wav"}
        assert previously_accepted <= set(audio_formats.PODCAST_FORMATS)

    def test_readme_claims_are_reachable_from_the_cli(self):
        """README.md:18 advertises M4B / MP3 / Opus / FLAC. Opus and FLAC
        were rejected by `--format` for the life of that claim."""
        for advertised in ("m4b", "mp3", "opus", "flac"):
            assert advertised in audio_formats.BOOK_FORMATS


class TestFfmpegPreflightCoversEveryFormat:
    def test_wav_is_in_the_preflight_set(self):
        """`wav` was excluded with the comment "'wav' chapters are written
        directly by the TTS engine and need no ffmpeg step" -- true of a
        chapter, false of concatenating chapters into a book. It skipped the
        check that exists to fail BEFORE a full render rather than after it.
        """
        assert "wav" in engine_mod._FFMPEG_FORMATS

    def test_preflight_set_is_derived_not_handwritten(self):
        assert engine_mod._FFMPEG_FORMATS == set(audio_formats.FFMPEG_FORMATS)

    def test_unknown_format_is_assumed_to_need_ffmpeg(self):
        """Failing early on a guess costs a message; failing late costs the
        whole render."""
        assert audio_formats.needs_ffmpeg("something-new") is True


class TestDispatchRoutesEveryFormatToItsOwnAssembler:
    """The `else: _m4b_assembler` fallthrough is what made `--format wav`
    write AAC-in-MP4 bytes to a .wav path, silently."""

    @pytest.fixture
    def recording(self, monkeypatch):
        seen: dict[str, str] = {}

        def stub(label):
            def f(chapter_files, output_path, **kw):
                seen["who"] = label
                p = pathlib.Path(output_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"FAKE")
                return AssemblyResult(output_path=p, chapters_embedded=True)
            return f

        for attr, label in [
            ("assemble_m4b", "m4b"), ("assemble_mp3", "mp3"),
            ("assemble_opus", "opus"), ("assemble_flac", "flac"),
            ("assemble_wav", "wav"), ("assemble_m4a_split", "m4a_split"),
        ]:
            monkeypatch.setattr(output_mod, attr, stub(label))
        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: True)
        return seen

    def _render(self, tmp_path, fmt):
        return render_project_detailed(
            _make_project(num_chapters=1), tmp_path / f"book.{fmt}",
            engine=FakeTTSEngine(), cache_root=tmp_path / "cache",
            output_format=fmt,
        )

    @pytest.mark.parametrize("fmt,expected", [
        ("m4b", "m4b"),
        ("mp3", "mp3"),
        ("wav", "wav"),
        ("opus", "opus"),
        ("ogg", "opus"),
        ("flac", "flac"),
        ("m4a", "m4a_split"),
    ])
    def test_format_reaches_its_own_assembler(
        self, tmp_path, recording, fmt, expected
    ):
        self._render(tmp_path, fmt)
        assert recording["who"] == expected

    def test_unknown_format_raises_instead_of_writing_an_m4b(
        self, tmp_path, recording
    ):
        with pytest.raises(RenderError, match="Unknown output format"):
            self._render(tmp_path, "bogus")
        assert "who" not in recording


class TestWavAssemblerProducesWav:
    def test_it_encodes_pcm_not_aac(self, tmp_path, monkeypatch):
        captured: dict = {}

        def fake_concat(chapter_files, output_path, chapter_pause_ms,
                        codec_args, **kw):
            captured["codec_args"] = codec_args
            captured["embed_chapters"] = kw.get("embed_chapters")
            captured["embed_cover"] = kw.get("embed_cover")
            return AssemblyResult(output_path=pathlib.Path(output_path),
                                  chapters_embedded=False)

        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(output_mod, "_concat_to_single", fake_concat)
        output_mod.assemble_wav([], tmp_path / "book.wav", runner=object())

        assert captured["codec_args"] == ["-c:a", "pcm_s16le"]

    def test_it_does_not_attempt_a_chapter_mux(self, tmp_path, monkeypatch):
        """WAV has no chapter atom. Attempting the mux means an ffmpeg call
        that fails on every single render, then falls back to the same file
        while logging a stderr dump -- noise that reads like a defect."""
        captured: dict = {}

        def fake_concat(chapter_files, output_path, chapter_pause_ms,
                        codec_args, **kw):
            captured.update(kw)
            return AssemblyResult(output_path=pathlib.Path(output_path),
                                  chapters_embedded=False)

        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(output_mod, "_concat_to_single", fake_concat)
        output_mod.assemble_wav([], tmp_path / "book.wav", runner=object())

        assert captured["embed_chapters"] is False
        assert captured["embed_cover"] is False

    def test_missing_ffmpeg_is_a_clear_error_not_a_crash(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: False)
        with pytest.raises(RuntimeError, match="FFmpeg is required"):
            output_mod.assemble_wav([], tmp_path / "book.wav")

    def test_chapterless_result_carries_no_error(self, tmp_path, monkeypatch):
        """`chapters_embedded=False` with `chapter_error=None` is the honest
        report: nothing failed, the container simply has nowhere to put them.
        """
        def fake_concat(chapter_files, output_path, chapter_pause_ms,
                        codec_args, **kw):
            assert kw["embed_chapters"] is False
            return AssemblyResult(output_path=pathlib.Path(output_path),
                                  chapters_embedded=False)

        monkeypatch.setattr(output_mod, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(output_mod, "_concat_to_single", fake_concat)
        r = output_mod.assemble_wav([], tmp_path / "book.wav", runner=object())

        assert r.chapters_embedded is False
        # Falsy, not None: AssemblyResult.chapter_error defaults to "". What
        # matters is that nothing populated it -- a real mux failure fills it
        # with the last 20 lines of ffmpeg stderr.
        assert not r.chapter_error


class TestAliasResolution:
    def test_ogg_is_opus(self):
        assert audio_formats.canonical("ogg") == "opus"

    def test_canonical_is_idempotent(self):
        for name in audio_formats.ALL_FORMAT_NAMES:
            once = audio_formats.canonical(name)
            assert audio_formats.canonical(once) == once

    def test_case_and_whitespace_are_forgiven(self):
        assert audio_formats.canonical("  OGG ") == "opus"

    def test_every_alias_resolves_to_a_real_format(self):
        for name in audio_formats.ALL_FORMAT_NAMES:
            assert audio_formats.canonical(name) in audio_formats.FORMATS
