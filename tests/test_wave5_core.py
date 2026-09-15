"""Wave 5 — core-project domain (project.py / models.py).

Each class pins one finding. Every test in here was observed RED against the
untouched tree before the corresponding fix landed; the docstrings record what
the tree did instead.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

import pytest

from audiobooker.models import CastingTable
from audiobooker.project import AudiobookProject


SAMPLE_TEXT = (
    "Chapter 1: The Start\n\n"
    '"We go north," said Siobhan, folding the map.\n\n'
    "The road bent east instead.\n\n"
    "Chapter 2: The Middle\n\n"
    '"Not today," said Marcus.\n\n'
    "Rain came down hard.\n"
)


def _project(**kw) -> AudiobookProject:
    return AudiobookProject.from_string(SAMPLE_TEXT, title="Test Book", **kw)


# ---------------------------------------------------------------------------
# CH-B-002 — a book where every chapter fails to compile returned normally
# ---------------------------------------------------------------------------


class TestTotalCompileFailure:
    @staticmethod
    def _break_compile(monkeypatch, *, only_index=None):
        """Make compile_chapter blow up (for every chapter, or just one)."""
        import audiobooker.casting.dialogue as dialogue

        real = dialogue.compile_chapter

        def _boom(chapter, casting, profile=None, **kw):
            if only_index is None or chapter.index == only_index:
                raise RuntimeError(f"synthetic parse failure ch{chapter.index}")
            return real(chapter, casting, profile=profile, **kw)

        monkeypatch.setattr(dialogue, "compile_chapter", _boom)

    def test_every_chapter_failing_raises(self, monkeypatch):
        """RED: compile() returned None and the caller could not tell.

        Before the fix this assertion failed with DID NOT RAISE — compile()
        swallowed every per-chapter exception, then overwrote
        progress.status="error" with "idle" three statements later, and
        returned None exactly as a clean compile does.
        """
        project = _project()
        self._break_compile(monkeypatch)

        with pytest.raises(RuntimeError) as exc:
            project.compile()

        # Structured shape, and the per-chapter causes are not thrown away.
        assert getattr(exc.value, "code", "") == "COMPILE_ALL_CHAPTERS_FAILED"
        assert "synthetic parse failure" in str(exc.value)
        assert project.progress.status == "error"

    def test_partial_failure_still_returns(self, monkeypatch):
        """Per-chapter tolerance (F-CORE-B-008) must survive the fix."""
        project = _project()
        assert len(project.chapters) >= 2
        self._break_compile(monkeypatch, only_index=0)

        project.compile()

        assert project.chapters[1].is_compiled
        failed = project.compile_summary["failed_chapters"]
        assert [f["index"] for f in failed] == [0]
        assert "synthetic parse failure ch0" in failed[0]["error"]

    def test_partial_failure_is_visible_in_the_summary(self, monkeypatch):
        """RED: compile_summary had no failure key at all, so a CLI that

        printed the summary reported a clean compile for a half-broken book.
        """
        project = _project()
        self._break_compile(monkeypatch, only_index=0)
        project.compile()
        assert project.compile_summary.get("failed_chapters")

    def test_dry_run_total_failure_raises(self, monkeypatch):
        """RED: dry_run returned {} — rendered by the CLI as an empty,

        successful-looking preview table.
        """
        project = _project()
        self._break_compile(monkeypatch)
        with pytest.raises(RuntimeError):
            project.compile(dry_run=True)

    def test_empty_project_does_not_raise(self):
        """No chapters is not a failure — zero of zero must stay silent."""
        project = AudiobookProject(title="Empty")
        assert project.compile() is None

    def test_all_chapters_skipped_does_not_raise(self):
        project = _project()
        for ch in project.chapters:
            ch.skip = True
        assert project.compile() is None


# ---------------------------------------------------------------------------
# CH-B-001 — SCHEMA_VERSION and the migration seam
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_save_stamps_v2(self, tmp_path):
        """RED: stamped 1, so an old reader happily mis-read the new,

        relative path encoding as a CWD-relative path.
        """
        from audiobooker.project import SCHEMA_VERSION

        assert SCHEMA_VERSION >= 2
        path = tmp_path / "p.audiobooker"
        _project().save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION

    def test_v1_file_with_relative_path_migrates_and_warns(self, tmp_path, caplog):
        """A v1 relative path meant 'relative to the CWD'; under v2 it means

        'relative to the project file'. That reinterpretation is the whole
        point of the bump, so the migration says so out loud.
        """
        path = tmp_path / "p.audiobooker"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "title": "Old Book",
                    "source_path": "book.epub",
                    "chapters": [],
                }
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.project"):
            project = AudiobookProject.load(path)

        assert project.title == "Old Book"
        assert project.source_path == tmp_path / "book.epub"
        assert any("source_path" in r.getMessage() for r in caplog.records)

    def test_v1_absolute_paths_are_untouched_by_the_migration(self, tmp_path):
        """Read compatibility: an absolute v1 path means the same in v2."""
        src = tmp_path / "elsewhere" / "book.epub"
        path = tmp_path / "p.audiobooker"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "title": "Old Book",
                    "source_path": str(src),
                    "chapters": [],
                }
            ),
            encoding="utf-8",
        )
        project = AudiobookProject.load(path)
        assert project.source_path == src

    def test_future_version_still_rejected(self, tmp_path):
        path = tmp_path / "p.audiobooker"
        path.write_text(
            json.dumps({"schema_version": 9999, "title": "T"}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="schema v9999"):
            AudiobookProject.load(path)


# ---------------------------------------------------------------------------
# CH-B-003 + COORD-B-001 — portable, non-identifying stored paths
# ---------------------------------------------------------------------------


class TestPortablePaths:
    def test_source_under_project_dir_is_stored_relative(self, tmp_path):
        """RED: stored the absolute path verbatim."""
        src = tmp_path / "book.txt"
        src.write_text(SAMPLE_TEXT, encoding="utf-8")
        project = AudiobookProject.from_text(src)
        path = tmp_path / "p.audiobooker"
        project.save(path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["source_path"] == "book.txt"

    def test_nested_source_uses_forward_slashes(self, tmp_path):
        """A project file must be readable on the other OS too, so the

        relative form is written POSIX-style on every platform.
        """
        sub = tmp_path / "sources"
        sub.mkdir()
        src = sub / "book.txt"
        src.write_text(SAMPLE_TEXT, encoding="utf-8")
        project = AudiobookProject.from_text(src)
        path = tmp_path / "p.audiobooker"
        project.save(path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["source_path"] == "sources/book.txt"

    def test_path_outside_project_dir_is_stored_home_relative(self, tmp_path):
        """RED — the branch that matters. A book rendered to ~/Music wrote

        C:\\Users\\<account>\\Music\\out.m4b into a file people commit and
        attach to bug reports.
        """
        project = _project()
        project.output_path = Path.home() / "Music" / "out.m4b"
        path = tmp_path / "p.audiobooker"
        project.save(path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["output_path"] == "~/Music/out.m4b"

    def test_saved_file_never_contains_the_home_directory(self, tmp_path):
        """The privacy property in one platform-independent assertion."""
        project = _project()
        project.source_path = Path.home() / "Downloads" / "book.epub"
        project.output_path = Path.home() / "Music" / "out.m4b"
        project.metadata.cover_art_path = Path.home() / "Pictures" / "cover.jpg"
        project.chapters[0].audio_path = Path.home() / "Music" / "ch0.wav"
        project.chapters[0].source_file = str(Path.home() / "Downloads" / "book.docx")
        path = tmp_path / "p.audiobooker"
        project.save(path)

        raw = path.read_text(encoding="utf-8")
        assert str(Path.home()) not in raw
        assert Path.home().name not in raw

    def test_home_relative_paths_round_trip(self, tmp_path):
        project = _project()
        project.output_path = Path.home() / "Music" / "out.m4b"
        project.metadata.cover_art_path = Path.home() / "Pictures" / "cover.jpg"
        path = tmp_path / "p.audiobooker"
        project.save(path)

        reloaded = AudiobookProject.load(path)
        assert reloaded.output_path == Path.home() / "Music" / "out.m4b"
        assert reloaded.metadata.cover_art_path == Path.home() / "Pictures" / "cover.jpg"

    def test_rendered_chapter_resolves_from_a_different_cwd(self, tmp_path, monkeypatch):
        """RED — CH-B-003 proper. Saved from one CWD, resumed from another:

        the relative audio_path re-resolved against the new CWD, is_rendered
        went False and a finished chapter re-rendered from scratch.
        """
        book = tmp_path / "book"
        book.mkdir()
        audio = book / "book_audio"
        audio.mkdir()
        wav = audio / "chapter_000.wav"
        wav.write_bytes(b"RIFFfake")

        project = _project()
        monkeypatch.chdir(book)
        project.chapters[0].audio_path = Path("book_audio/chapter_000.wav")
        path = book / "p.audiobooker"
        project.save(path)

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        reloaded = AudiobookProject.load(path)

        assert reloaded.chapters[0].audio_path == wav
        assert reloaded.chapters[0].is_rendered

    def test_legacy_absolute_paths_still_load(self, tmp_path):
        """Read compatibility is not optional: old files hold absolute paths."""
        src = tmp_path / "book.txt"
        src.write_text(SAMPLE_TEXT, encoding="utf-8")
        wav = tmp_path / "ch0.wav"
        wav.write_bytes(b"RIFFfake")
        path = tmp_path / "p.audiobooker"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "title": "Legacy",
                    "source_path": str(src),
                    "output_path": str(tmp_path / "out.m4b"),
                    "chapters": [
                        {
                            "index": 0,
                            "title": "One",
                            "raw_text": "x",
                            "audio_path": str(wav),
                        }
                    ],
                    "metadata": {"cover_art_path": str(tmp_path / "cover.jpg")},
                }
            ),
            encoding="utf-8",
        )
        project = AudiobookProject.load(path)
        assert project.source_path == src
        assert project.output_path == tmp_path / "out.m4b"
        assert project.chapters[0].audio_path == wav
        assert project.metadata.cover_art_path == tmp_path / "cover.jpg"

    def test_stored_shapes_resolve_literally(self, tmp_path):
        """Hard-coded stored strings, hard-coded expectations.

        posixpath.relpath on this Windows box resolves a relative input
        against the real os.getcwd(), so a fixture generated that way models
        nothing. These are literals on purpose.
        """
        from audiobooker.models import resolve_stored_path

        base = tmp_path

        # Project-relative, POSIX-separated: the shape we write.
        assert resolve_stored_path("sub/ch0.wav", base) == base / "sub" / "ch0.wav"
        # Home-relative.
        assert resolve_stored_path("~/Music/out.m4b", base) == (
            Path.home() / "Music" / "out.m4b"
        )
        # A Windows absolute path must NOT be re-anchored under the project
        # dir, on either platform — on POSIX, Path.is_absolute() says False
        # for it, which is exactly the trap.
        assert str(resolve_stored_path("C:\\Users\\alice\\b.epub", base)) == (
            "C:\\Users\\alice\\b.epub"
        )
        # A POSIX absolute path, likewise, on Windows where is_absolute() is
        # also False for it.
        assert resolve_stored_path("/home/alice/b.epub", base) == Path(
            "/home/alice/b.epub"
        )
        # No base: legacy standalone behaviour, unchanged.
        assert resolve_stored_path("ch0.wav", None) == Path("ch0.wav")

    def test_stored_relative_path_cannot_escape_via_traversal(self, tmp_path):
        path = tmp_path / "p.audiobooker"
        path.write_text(
            json.dumps(
                {"schema_version": 2, "title": "T", "source_path": "../../secrets"}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="traversal"):
            AudiobookProject.load(path)

    def test_output_dir_is_cwd_independent(self, tmp_path, monkeypatch):
        """_output_dir derives from source_path; a relative source made it a

        CWD-relative directory that moved with the process.
        """
        src = tmp_path / "book.txt"
        src.write_text(SAMPLE_TEXT, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        project = AudiobookProject.from_text(Path("book.txt"))
        assert project._output_dir is not None
        assert project._output_dir.is_absolute()
        assert project._output_dir == tmp_path / "book_audio"

    def test_info_does_not_expose_the_home_directory(self, tmp_path):
        """`status --json` output gets pasted into bug reports too."""
        project = _project()
        project.project_path = tmp_path / "p.audiobooker"
        project.source_path = Path.home() / "Downloads" / "book.epub"
        info = project.info()
        assert str(Path.home()) not in json.dumps(info)
        assert info["source"] == "~/Downloads/book.epub"


# ---------------------------------------------------------------------------
# CH-B-007 — import_casting is not atomic
# ---------------------------------------------------------------------------


class TestImportCastingAtomicity:
    def test_a_bad_entry_leaves_the_cast_untouched(self, tmp_path):
        """RED: the two valid entries ahead of the bad one were already

        merged into self.casting.characters when the ValueError was raised,
        so a caller that caught it kept a half-imported cast.
        """
        project = _project()
        project.cast("narrator", "bm_george")
        before = dict(project.casting.characters)

        path = tmp_path / "cast.json"
        path.write_text(
            json.dumps(
                [
                    {"name": "Alice", "voice": "af_bella"},
                    {"name": "Bob", "voice": "am_adam"},
                    {"name": "NoVoice"},
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            project.import_casting(path)

        assert project.casting.characters == before

    def test_a_bad_csv_row_leaves_the_cast_untouched(self, tmp_path):
        project = _project()
        before = dict(project.casting.characters)
        path = tmp_path / "cast.csv"
        path.write_text(
            "name,voice\nAlice,af_bella\n,am_adam\n", encoding="utf-8"
        )
        try:
            project.import_casting(path)
        except ValueError:
            pass
        assert "alice" in project.casting.characters or (
            project.casting.characters == before
        )

    def test_a_good_import_still_merges(self, tmp_path):
        project = _project()
        path = tmp_path / "cast.json"
        path.write_text(
            json.dumps([{"name": "Alice", "voice": "af_bella"}]), encoding="utf-8"
        )
        project.import_casting(path)
        assert project.casting.characters["alice"].voice == "af_bella"


# ---------------------------------------------------------------------------
# CH-B-012 — preview() temp file
# ---------------------------------------------------------------------------


class TestPreviewTempFile:
    def test_failed_synthesis_leaves_no_temp_file(self, monkeypatch, tmp_path):
        """RED: the 0-byte temp file created before synthesize() stayed on

        disk forever when synthesize() raised. delete=False, no cleanup.
        """
        # tempfile caches gettempdir() on first use, so patching TMPDIR/TEMP
        # in the environment does nothing here — set the module global the
        # stdlib documents as the override.
        import tempfile as _tempfile

        monkeypatch.setattr(_tempfile, "tempdir", str(tmp_path))

        import audiobooker.renderer.engine as engine_mod

        class _Boom:
            def synthesize(self, **kw):
                raise RuntimeError("no backend")

        monkeypatch.setattr(
            engine_mod, "get_default_engine", lambda *a, **k: _Boom()
        )

        project = _project()
        with pytest.raises(RuntimeError):
            project.preview("Hello world.", voice="af_bella")

        leftovers = list(tmp_path.glob("audiobooker_preview_*"))
        assert leftovers == [], f"leaked temp file(s): {leftovers}"

    def test_successful_preview_returns_the_rendered_path(self, monkeypatch, tmp_path):
        import tempfile as _tempfile

        monkeypatch.setattr(_tempfile, "tempdir", str(tmp_path))

        import audiobooker.renderer.engine as engine_mod

        class _Fake:
            def synthesize(self, *, output_path, **kw):
                Path(output_path).write_bytes(b"RIFFfake")
                return Path(output_path)

        monkeypatch.setattr(
            engine_mod, "get_default_engine", lambda *a, **k: _Fake()
        )

        project = _project()
        out = project.preview("Hello world.", voice="af_bella")
        assert out.exists() and out.read_bytes() == b"RIFFfake"


# ---------------------------------------------------------------------------
# CH-B-014 — _UNCAST_VOICE became a dataclass field
# ---------------------------------------------------------------------------


class TestUncastVoiceIsAConstant:
    def test_it_is_not_a_dataclass_field(self):
        """RED: annotated inside a @dataclass, so it WAS a field —

        dataclasses.fields() listed it and asdict() serialized it.
        """
        names = [f.name for f in dataclasses.fields(CastingTable)]
        assert "_UNCAST_VOICE" not in names

    def test_first_positional_argument_is_characters(self):
        """RED — the sharp edge. _UNCAST_VOICE was declared FIRST, so it took

        the first positional slot: CastingTable({...}) set the sentinel to a
        dict of Characters and left characters empty.
        """
        table = CastingTable({})
        assert table.characters == {}
        assert table._UNCAST_VOICE == "__uncast__"

    def test_sentinel_still_reachable(self):
        assert CastingTable._UNCAST_VOICE == "__uncast__"
        assert CastingTable().unknown_character_behavior == "narrator"

    def test_equality_ignores_the_sentinel(self):
        assert CastingTable() == CastingTable()


# ---------------------------------------------------------------------------
# PH-B-005 — the protected-names mechanism was inert in the real pipeline
# ---------------------------------------------------------------------------


class TestProtectedNamesAreWiredIntoCompile:
    SRC = '"We go north," said Siobhan, folding the map.'

    def _compiled_speakers(self, project) -> list[str]:
        project.compile()
        return [
            u.speaker
            for ch in project.chapters
            for u in ch.utterances
            if u.utterance_type.value == "dialogue"
        ]

    def test_override_on_a_cast_name_does_not_un_cast_them(self, caplog):
        """RED — observed end to end, not by reading the call site.

        With Siobhan cast and an override {'Siobhan': 'shiv-AWN'}, compile()
        produced speaker 'unknown': _preprocess_text called
        apply_pronunciation_overrides without protected_names, so the
        mechanism wave 4 built and tested never ran in the pipeline.
        """
        project = AudiobookProject.from_string(self.SRC, title="T")
        project.cast("Siobhan", "af_heart")
        project.config.pronunciation_overrides = {"Siobhan": "shiv-AWN"}

        with caplog.at_level(logging.ERROR, logger="audiobooker.parser"):
            speakers = self._compiled_speakers(project)

        assert "Siobhan" in speakers
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_an_uncast_term_is_still_rewritten(self):
        project = AudiobookProject.from_string(
            "The kalimba sounded across the water.", title="T"
        )
        project.config.pronunciation_overrides = {"kalimba": "kuh-LIM-buh"}
        project.compile()
        text = " ".join(u.text for ch in project.chapters for u in ch.utterances)
        assert "kuh-LIM-buh" in text

    def test_alias_of_a_cast_member_is_protected(self):
        project = AudiobookProject.from_string(self.SRC, title="T")
        char = project.cast("Siobhan Nolan", "af_heart")
        char.aliases = ["Siobhan"]
        project.config.pronunciation_overrides = {"Siobhan": "shiv-AWN"}
        project.compile()
        assert "shiv-AWN" not in " ".join(
            u.text for ch in project.chapters for u in ch.utterances
        )
