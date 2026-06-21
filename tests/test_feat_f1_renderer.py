"""
F1 renderer feature regression tests (v2.1).

Covers the renderer-side audiobook-professionalism + ACX features:

- FT-RENDER-M-001  Full metadata tagging (narrator/genre/year/series)
- FT-RENDER-M-002  Auto-cover from project.metadata.cover_art_path
- FT-RENDER-M-003  Bitrate threading (aac_bitrate / bitrate)
- FT-RENDER-M-006  Opus + FLAC assemblers
- FT-RENDER-M-007  Chapter-per-file AAC split + index playlist
- FT-RENDER-M-009  Retail sample (engine.render_sample)
- FT-ACX-001       ACX preset + master_check
- FT-CLI-007       export_chapter_metadata (ffmetadata / cue / json)

All tests are hermetic: no real ffmpeg, no voice-soundboard. FFmpeg is
faked via FakeFFmpegRunner and check_ffmpeg() is forced available by
setting the module-level cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import audiobooker.renderer.output as output_mod
from audiobooker.models import BookMetadata, Chapter, Utterance, UtteranceType
from audiobooker.project import AudiobookProject
from audiobooker.renderer import engine as engine_mod
from audiobooker.renderer.output import (
    AssemblyResult,
    assemble_m4b,
    assemble_mp3_chapters,
    assemble_opus,
    assemble_flac,
    assemble_m4a_split,
    master_check,
    export_chapter_metadata,
)
from audiobooker.renderer.protocols import RunResult
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class RecordingRunner:
    """FakeFFmpegRunner that records every command and always succeeds.

    When ``create_output`` is True, it writes a placeholder file at the last
    argument of each call (the conventional ffmpeg output path) so callers
    that assert the file exists see it materialize.
    """

    def __init__(self, create_output: bool = False) -> None:
        self.calls: list[list[str]] = []
        self._create_output = create_output

    def run(self, args: list[str]) -> RunResult:
        self.calls.append(list(args))
        if self._create_output and args:
            last = args[-1]
            if last not in ("-",) and not last.startswith("-"):
                try:
                    p = Path(last)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"FAKE")
                except OSError:
                    pass
        return RunResult(returncode=0, stdout="", stderr="")

    def flat(self) -> str:
        """All recorded args joined into one searchable string."""
        return " ".join(arg for call in self.calls for arg in call)


class ScriptedRunner:
    """Runner that returns scripted (returncode, stderr) per call index."""

    def __init__(self, results: list[RunResult]) -> None:
        self._results = results
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> RunResult:
        idx = len(self.calls)
        self.calls.append(list(args))
        if idx < len(self._results):
            return self._results[idx]
        return RunResult(returncode=0, stdout="", stderr="")


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
        wav = tmp_path / f"ch{i}.wav"
        write_silence_wav(wav, duration_s=0.25)
        files.append((wav, f"Chapter {i + 1}", 0.25))
    return files


def _full_metadata() -> BookMetadata:
    return BookMetadata(
        genre="Science Fiction",
        series="The Foundation",
        series_index=2,
        year=1952,
        narrator_name="Jane Narrator",
        publisher="Gnome Press",
    )


# ---------------------------------------------------------------------------
# FT-RENDER-M-001: full metadata tags (m4b)
# ---------------------------------------------------------------------------

class TestFullMetadataM4B:
    def test_metadata_written_to_ffmetadata_file(self, tmp_path: Path):
        runner = RecordingRunner()
        meta = _full_metadata()
        # Capture the metadata.txt content by intercepting writes is awkward;
        # instead assert the metadata lines are produced by the helper and that
        # the assembler runs to completion with metadata supplied.
        result = assemble_m4b(
            _chapter_files(tmp_path),
            tmp_path / "out.m4b",
            title="My Book",
            author="Author Name",
            runner=runner,
            metadata=meta,
        )
        assert isinstance(result, AssemblyResult)

    def test_ffmetadata_helper_emits_all_fields(self):
        meta = _full_metadata()
        lines = output_mod._metadata_ffmetadata_lines(meta)
        joined = "\n".join(lines)
        assert "album_artist=Jane Narrator" in joined
        assert "genre=Science Fiction" in joined
        assert "date=1952" in joined
        assert "publisher=Gnome Press" in joined
        # Series maps to album + SERIES atoms.
        assert "album=The Foundation" in joined
        assert "SERIES=The Foundation" in joined
        assert "SERIES-PART=2" in joined

    def test_none_metadata_yields_no_lines(self):
        assert output_mod._metadata_ffmetadata_lines(None) == []

    def test_mp3_metadata_args_include_genre_and_narrator(self):
        meta = _full_metadata()
        args = output_mod._metadata_mp3_args(meta)
        flat = " ".join(args)
        assert "genre=Science Fiction" in flat
        assert "album_artist=Jane Narrator" in flat
        assert "date=1952" in flat
        assert "SERIES-PART=2" in flat

    def test_mp3_chapters_thread_metadata(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_mp3_chapters(
            _chapter_files(tmp_path, 2),
            tmp_path / "mp3out",
            title="Album Title",
            author="Author",
            runner=runner,
            metadata=_full_metadata(),
        )
        flat = runner.flat()
        assert "genre=Science Fiction" in flat
        assert "album_artist=Jane Narrator" in flat


# ---------------------------------------------------------------------------
# FT-RENDER-M-003: bitrate threading
# ---------------------------------------------------------------------------

class TestBitrate:
    def test_m4b_uses_supplied_aac_bitrate(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4b(
            _chapter_files(tmp_path),
            tmp_path / "out.m4b",
            runner=runner,
            aac_bitrate="192k",
        )
        assert "192k" in runner.flat()

    def test_mp3_uses_supplied_bitrate(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_mp3_chapters(
            _chapter_files(tmp_path),
            tmp_path / "mp3out",
            runner=runner,
            bitrate="256k",
        )
        assert "256k" in runner.flat()

    def test_default_bitrate_is_128k(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4b(_chapter_files(tmp_path), tmp_path / "out.m4b", runner=runner)
        assert "128k" in runner.flat()


# ---------------------------------------------------------------------------
# FT-ACX-001: ACX loudnorm profile
# ---------------------------------------------------------------------------

class TestACXProfile:
    def test_acx_profile_forces_441k_sample_rate(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4b(
            _chapter_files(tmp_path),
            tmp_path / "out.m4b",
            runner=runner,
            loudnorm_profile="acx",
        )
        assert "44100" in runner.flat()
        assert "24000" not in runner.flat()

    def test_podcast_profile_keeps_24k(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4b(
            _chapter_files(tmp_path),
            tmp_path / "out.m4b",
            runner=runner,
            loudnorm_profile="podcast",
        )
        assert "24000" in runner.flat()

    def test_acx_normalize_uses_acx_loudnorm_filter(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4b(
            _chapter_files(tmp_path),
            tmp_path / "out.m4b",
            runner=runner,
            loudnorm_profile="acx",
            normalize=True,
        )
        flat = runner.flat()
        assert "loudnorm=I=-20:LRA=11:TP=-3" in flat

    def test_unknown_profile_falls_back_to_podcast(self, tmp_path: Path):
        prof = output_mod._resolve_loudnorm_profile("bogus")
        assert prof is output_mod.LOUDNORM_PROFILES["podcast"]


# ---------------------------------------------------------------------------
# FT-RENDER-M-006: Opus + FLAC assemblers
# ---------------------------------------------------------------------------

class TestOpusFlac:
    def test_opus_uses_libopus(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_opus(
            _chapter_files(tmp_path),
            tmp_path / "out.opus",
            runner=runner,
        )
        assert isinstance(result, AssemblyResult)
        assert "libopus" in runner.flat()

    def test_opus_default_bitrate_speech_tuned(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_opus(_chapter_files(tmp_path), tmp_path / "out.opus", runner=runner)
        assert "48k" in runner.flat()

    def test_flac_uses_flac_codec(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_flac(
            _chapter_files(tmp_path),
            tmp_path / "out.flac",
            runner=runner,
        )
        assert isinstance(result, AssemblyResult)
        assert "flac" in runner.flat()

    def test_opus_embeds_metadata(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_opus(
            _chapter_files(tmp_path),
            tmp_path / "out.opus",
            title="Opus Book",
            runner=runner,
            metadata=_full_metadata(),
        )
        # Metadata flows through the FFMETADATA mux file (map_metadata 1).
        assert "-map_metadata" in runner.flat()

    def test_opus_chapter_mux_failure_falls_back(self, tmp_path: Path):
        # First call = silence gen, second = encode (ok), third = mux (fail).
        results = [
            RunResult(returncode=0),  # silence
            RunResult(returncode=0),  # encode
            RunResult(returncode=1, stderr="mux boom"),  # mux fails
        ]
        runner = ScriptedRunner(results)
        result = assemble_flac(
            _chapter_files(tmp_path, 2),
            tmp_path / "out.flac",
            runner=runner,
        )
        assert result.chapters_embedded is False
        assert "boom" in result.chapter_error


# ---------------------------------------------------------------------------
# FT-RENDER-M-007: chapter-per-file AAC split + playlist
# ---------------------------------------------------------------------------

class TestM4ASplit:
    def test_emits_one_file_per_chapter_and_playlist(self, tmp_path: Path):
        runner = RecordingRunner()
        result = assemble_m4a_split(
            _chapter_files(tmp_path, 3),
            tmp_path / "book.m4b",
            title="Split Book",
            author="Author",
            runner=runner,
        )
        # Output is a directory named after the stem.
        out_dir = result.output_path
        assert out_dir.is_dir()
        playlist = out_dir / "_playlist.m3u"
        assert playlist.exists()
        names = playlist.read_text(encoding="utf-8").splitlines()
        assert len(names) == 3
        assert all(name.endswith(".m4a") for name in names)

    def test_split_tags_track_and_album(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4a_split(
            _chapter_files(tmp_path, 2),
            tmp_path / "book.m4b",
            title="Album X",
            runner=runner,
            metadata=_full_metadata(),
        )
        flat = runner.flat()
        assert "album=Album X" in flat
        assert "track=1" in flat
        assert "track=2" in flat
        assert "genre=Science Fiction" in flat

    def test_bitrate_alias_used_when_aac_bitrate_default(self, tmp_path: Path):
        runner = RecordingRunner()
        assemble_m4a_split(
            _chapter_files(tmp_path, 1),
            tmp_path / "book.m4b",
            runner=runner,
            bitrate="160k",
        )
        assert "160k" in runner.flat()


# ---------------------------------------------------------------------------
# FT-ACX-001: master_check
# ---------------------------------------------------------------------------

class TestMasterCheck:
    def _loudnorm_stderr(self, input_i: float, input_tp: float) -> str:
        return (
            "ffmpeg measuring...\n"
            + json.dumps({
                "input_i": str(input_i),
                "input_tp": str(input_tp),
                "input_lra": "7.0",
                "input_thresh": "-31.0",
            })
        )

    def test_passing_file(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = ScriptedRunner([
            RunResult(returncode=0, stderr=self._loudnorm_stderr(-20.0, -3.5)),
            RunResult(returncode=0, stderr="Noise floor dB: -70.0"),
        ])
        report = master_check(audio, profile="acx", runner=runner)
        assert report["profile"] == "acx"
        assert report["measured_rms_db"] == pytest.approx(-20.0)
        assert report["measured_peak_db"] == pytest.approx(-3.5)
        assert report["measured_noise_floor_db"] == pytest.approx(-70.0)
        assert report["passes"] is True
        assert report["failures"] == []

    def test_loudness_out_of_range_fails(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = ScriptedRunner([
            RunResult(returncode=0, stderr=self._loudnorm_stderr(-10.0, -3.5)),
            RunResult(returncode=0, stderr="Noise floor dB: -70.0"),
        ])
        report = master_check(audio, profile="acx", runner=runner)
        assert report["passes"] is False
        assert any("RMS" in f or "loudness" in f for f in report["failures"])

    def test_peak_too_hot_fails(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = ScriptedRunner([
            RunResult(returncode=0, stderr=self._loudnorm_stderr(-20.0, -1.0)),
            RunResult(returncode=0, stderr="Noise floor dB: -70.0"),
        ])
        report = master_check(audio, profile="acx", runner=runner)
        assert report["passes"] is False
        assert any("Peak" in f for f in report["failures"])

    def test_noisy_floor_fails(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = ScriptedRunner([
            RunResult(returncode=0, stderr=self._loudnorm_stderr(-20.0, -3.5)),
            RunResult(returncode=0, stderr="Noise floor dB: -40.0"),
        ])
        report = master_check(audio, profile="acx", runner=runner)
        assert report["passes"] is False
        assert any("Noise floor" in f for f in report["failures"])

    def test_missing_file_returns_error_dict(self, tmp_path: Path):
        report = master_check(tmp_path / "nope.m4a", profile="acx")
        assert report["passes"] is False
        assert any("not found" in f.lower() for f in report["failures"])

    def test_missing_ffmpeg_returns_error_dict(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        output_mod._ffmpeg_checked = False
        try:
            report = master_check(audio, profile="acx")
        finally:
            output_mod._ffmpeg_checked = True
        assert report["passes"] is False
        assert any("ffmpeg" in f.lower() for f in report["failures"])

    def test_unparseable_loudnorm_returns_error_not_crash(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"FAKE")
        runner = ScriptedRunner([
            RunResult(returncode=0, stderr="no json here"),
        ])
        report = master_check(audio, profile="acx", runner=runner)
        assert report["passes"] is False
        assert report["failures"]


# ---------------------------------------------------------------------------
# FT-CLI-007: export_chapter_metadata
# ---------------------------------------------------------------------------

class TestExportChapterMetadata:
    def _chapters(self):
        # (title, duration) pairs.
        return [
            ("Intro", 10.0),
            ("Chapter One", 60.0),
            ("Chapter Two", 30.0),
        ]

    def test_ffmetadata_format(self):
        out = export_chapter_metadata(self._chapters(), fmt="ffmetadata", chapter_pause_ms=2000)
        assert out.startswith(";FFMETADATA1")
        assert out.count("[CHAPTER]") == 3
        assert "START=0" in out
        assert "END=10000" in out
        # Second chapter starts after first + 2000ms pause.
        assert "START=12000" in out
        assert "title=Intro" in out

    def test_json_format(self):
        out = export_chapter_metadata(self._chapters(), fmt="json", chapter_pause_ms=0)
        data = json.loads(out)
        assert len(data) == 3
        assert data[0]["title"] == "Intro"
        assert data[0]["start"] == 0.0
        assert data[0]["end"] == 10.0
        # No pause: chapter two starts where chapter one ends.
        assert data[1]["start"] == 10.0
        # Internal keys are stripped.
        assert "_start_ms" not in data[0]

    def test_cue_format(self):
        out = export_chapter_metadata(
            self._chapters(), fmt="cue", chapter_pause_ms=0, title="My Book",
        )
        assert 'TITLE "My Book"' in out
        assert "TRACK 01 AUDIO" in out
        assert "TRACK 03 AUDIO" in out
        assert "INDEX 01 00:00:00" in out
        # CUE MM:SS:FF — 10s in = 00:10:00.
        assert "INDEX 01 00:10:00" in out

    def test_accepts_path_title_duration_triples(self, tmp_path: Path):
        triples = [(tmp_path / "a.wav", "Intro", 5.0), (tmp_path / "b.wav", "Two", 5.0)]
        out = export_chapter_metadata(triples, fmt="json", chapter_pause_ms=0)
        data = json.loads(out)
        assert data[0]["title"] == "Intro"
        assert data[1]["start"] == 5.0

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Unknown chapter metadata format"):
            export_chapter_metadata(self._chapters(), fmt="yaml")


# ---------------------------------------------------------------------------
# FT-RENDER-M-002: auto-cover via render_project
# ---------------------------------------------------------------------------

class RecordingAssembler:
    """Captures the kwargs render_project hands the assembler."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> AssemblyResult:
        self.calls.append(kwargs)
        out = Path(kwargs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE")
        return AssemblyResult(output_path=out, chapters_embedded=True)


def _make_project(num_chapters: int = 2, metadata: BookMetadata | None = None) -> AudiobookProject:
    project = AudiobookProject(title="Cover Book", author="Author")
    if metadata is not None:
        project.metadata = metadata
    project.cast("narrator", "af_heart")
    for i in range(num_chapters):
        ch = Chapter(index=i, title=f"Chapter {i + 1}", raw_text="Hello world " * 20)
        ch.utterances.append(
            Utterance(
                speaker="narrator",
                text="Some narration text here.",
                utterance_type=UtteranceType.NARRATION,
                chapter_index=i,
            )
        )
        project.chapters.append(ch)
    return project


class TestAutoCover:
    def test_metadata_cover_used_when_present(self, tmp_path: Path):
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8\xff")  # minimal JPEG-ish bytes
        meta = BookMetadata(cover_art_path=cover)
        project = _make_project(metadata=meta)

        assembler = RecordingAssembler()
        engine_mod.render_project(
            project, tmp_path / "out.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
        )
        assert assembler.calls
        assert assembler.calls[0].get("cover_art") == str(cover)

    def test_no_cover_when_metadata_path_missing(self, tmp_path: Path):
        meta = BookMetadata(cover_art_path=tmp_path / "missing.jpg")
        project = _make_project(metadata=meta)

        assembler = RecordingAssembler()
        engine_mod.render_project(
            project, tmp_path / "out.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
        )
        assert assembler.calls
        assert "cover_art" not in assembler.calls[0]

    def test_explicit_cover_overrides_metadata(self, tmp_path: Path):
        meta_cover = tmp_path / "meta.jpg"
        meta_cover.write_bytes(b"\xff\xd8\xff")
        explicit = tmp_path / "explicit.jpg"
        explicit.write_bytes(b"\xff\xd8\xff")
        project = _make_project(metadata=BookMetadata(cover_art_path=meta_cover))

        assembler = RecordingAssembler()
        engine_mod.render_project(
            project, tmp_path / "out.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cover_art=str(explicit),
            cache_root=tmp_path / "cache",
        )
        assert assembler.calls[0]["cover_art"] == str(explicit)


# ---------------------------------------------------------------------------
# render_project: profile / bitrate / metadata pass-through + format routing
# ---------------------------------------------------------------------------

class TestRenderProjectPassThrough:
    def test_acx_profile_and_bitrate_passed_to_assembler(self, tmp_path: Path):
        project = _make_project(metadata=_full_metadata())
        assembler = RecordingAssembler()
        engine_mod.render_project(
            project, tmp_path / "out.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
            output_profile="acx",
            bitrate="192k",
        )
        call = assembler.calls[0]
        assert call["loudnorm_profile"] == "acx"
        assert call["bitrate"] == "192k"
        assert call["metadata"] is project.metadata

    def test_default_profile_default_bitrate(self, tmp_path: Path):
        project = _make_project()
        assembler = RecordingAssembler()
        engine_mod.render_project(
            project, tmp_path / "out.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
        )
        call = assembler.calls[0]
        assert call["loudnorm_profile"] == "podcast"
        assert call["bitrate"] == "128k"

    def test_base_only_assembler_still_works(self, tmp_path: Path):
        """A legacy assembler that only takes the base 5 kwargs must not crash."""
        project = _make_project()

        class BaseAssembler:
            def __init__(self):
                self.calls = []

            def __call__(self, chapter_files, output_path, title="Audiobook",
                         author="", chapter_pause_ms=2000):
                self.calls.append((title, author))
                out = Path(output_path)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"FAKE")
                return AssemblyResult(output_path=out, chapters_embedded=True)

        assembler = BaseAssembler()
        result = engine_mod.render_project(
            project, tmp_path / "out.m4b",
            engine=FakeTTSEngine(),
            assembler=assembler,
            cache_root=tmp_path / "cache",
            output_profile="acx",
            bitrate="192k",
        )
        assert result.exists()
        assert assembler.calls  # called despite not accepting optional kwargs

    def test_opus_format_selects_opus_assembler(self, tmp_path: Path):
        project = _make_project()
        # No injected assembler — exercise the format-based selection. Use a
        # RecordingRunner via monkeypatched RealFFmpegRunner is heavy; instead
        # patch the opus assembler to record selection.
        called = {}

        import audiobooker.renderer.output as out_mod

        def fake_opus(**kwargs):
            called["opus"] = True
            out = Path(kwargs["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"FAKE")
            return AssemblyResult(output_path=out, chapters_embedded=True)

        orig = out_mod.assemble_opus
        out_mod.assemble_opus = fake_opus
        try:
            engine_mod.render_project(
                project, tmp_path / "out.opus",
                engine=FakeTTSEngine(),
                cache_root=tmp_path / "cache",
                output_format="opus",
            )
        finally:
            out_mod.assemble_opus = orig
        assert called.get("opus") is True

    def test_split_selects_m4a_split_assembler(self, tmp_path: Path):
        project = _make_project()
        called = {}

        import audiobooker.renderer.output as out_mod

        def fake_split(**kwargs):
            called["split"] = True
            out = Path(kwargs["output_path"]).parent / "split_dir"
            out.mkdir(parents=True, exist_ok=True)
            return AssemblyResult(output_path=out, chapters_embedded=True)

        orig = out_mod.assemble_m4a_split
        out_mod.assemble_m4a_split = fake_split
        try:
            engine_mod.render_project(
                project, tmp_path / "out.m4b",
                engine=FakeTTSEngine(),
                cache_root=tmp_path / "cache",
                output_format="m4b",
                split=True,
            )
        finally:
            out_mod.assemble_m4a_split = orig
        assert called.get("split") is True


# ---------------------------------------------------------------------------
# FT-RENDER-M-009: render_sample
# ---------------------------------------------------------------------------

class TestRenderSample:
    def test_renders_chapter_then_masters_sample(self, tmp_path: Path, monkeypatch):
        project = _make_project(num_chapters=2)
        # Compile so the chapter has utterances for the on-the-fly render path.
        project.compile()

        runner = RecordingRunner(create_output=True)
        # render_sample builds its own RealFFmpegRunner; patch it to record.
        monkeypatch.setattr(
            "audiobooker.renderer.ffmpeg_runner.RealFFmpegRunner",
            lambda: runner,
        )

        out = engine_mod.render_sample(
            project,
            from_chapter=0,
            start_seconds=0.0,
            duration=30.0,
            output_path=tmp_path / "sample.m4a",
            output_profile="acx",
            engine=FakeTTSEngine(),
            cache_root=tmp_path / "cache",
        )
        assert out == tmp_path / "sample.m4a"
        flat = " ".join(a for call in runner.calls for a in call)
        # Trim args + ACX master + retail-sample tag.
        assert "-ss" in flat
        assert "-t" in flat
        assert "44100" in flat
        assert "Retail Sample" in flat

    def test_reuses_cached_chapter_wav(self, tmp_path: Path, monkeypatch):
        project = _make_project(num_chapters=1)
        project.compile()

        cache_root = tmp_path / "cache"
        # First, render the project so the chapter WAV is cached.
        engine_mod.render_project(
            project, tmp_path / "book.m4b",
            engine=FakeTTSEngine(),
            assembler=RecordingAssembler(),
            cache_root=cache_root,
        )

        runner = RecordingRunner(create_output=True)
        monkeypatch.setattr(
            "audiobooker.renderer.ffmpeg_runner.RealFFmpegRunner",
            lambda: runner,
        )
        # A TTS engine that would fail if called — proving cache reuse.
        failing_engine = FakeTTSEngine(fail_on_call=0)

        out = engine_mod.render_sample(
            project,
            from_chapter=0,
            duration=20.0,
            output_path=tmp_path / "sample.m4a",
            engine=failing_engine,
            cache_root=cache_root,
        )
        assert out.exists()
        # Engine must NOT have been called (cache hit).
        assert len(failing_engine.calls) == 0

    def test_bad_chapter_index_raises(self, tmp_path: Path):
        project = _make_project(num_chapters=1)
        with pytest.raises(engine_mod.RenderError):
            engine_mod.render_sample(
                project, from_chapter=5, cache_root=tmp_path / "cache",
            )

    def test_zero_duration_raises(self, tmp_path: Path):
        project = _make_project(num_chapters=1)
        with pytest.raises(ValueError):
            engine_mod.render_sample(
                project, from_chapter=0, duration=0.0, cache_root=tmp_path / "cache",
            )
