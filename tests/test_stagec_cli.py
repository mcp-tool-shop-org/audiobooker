"""Stage C (humanization) regression tests for the CLI / review layer — wave 4.

Every test in this file was written BEFORE its fix and observed FAILING against
``ccf35dd``. The three HIGH/CRITICAL defects this repo shipped before were all
invisible to the existing fixtures — a project that had never been hand-edited,
a directory that never contained a render cache, a title that never contained a
colon — so each test here deliberately builds the shape that can express the
defect.

Findings covered:

* CLIUX-C-001  ``make``/``batch`` silently destroy an existing project, and the
  destructive save happens BEFORE the render that can fail.
* CLIUX-H-002  ``find_project_file`` counts the ``.audiobooker`` render-cache
  DIRECTORY as a project file.
* CLIUX-H-003  ``render --clean-cache`` deletes before every guard, including
  both ``--dry-run`` short-circuits.
* CLIUX-H-004  ``diagnose`` says "All checks passed." on a box with no TTS
  engine and no ffmpeg.
* CLIUX-H-005  ``cast`` accepts a character that appears nowhere in the book.
* CLIUX-H-006  the review header recommends the edit that destroys utterance
  types, and the import never says it happened.
* CLIUX-H-007  the malformed-tag hint cannot fix its own most common cause.
* CLIUX-H-008  ``review-export``'s default filename skips the sanitizer.
* CLIUX-H-009  ``export-chapters`` emits markers from unrendered chapters.
* CLIUX-H-010  ``cache clean`` deletes hours of audio with no confirmation.

No network, no ffmpeg, no voice-soundboard: everything is text-only or mocked.
"""

from __future__ import annotations

import json
import logging
import sys
from types import SimpleNamespace

import pytest

from audiobooker import AudiobookProject
from audiobooker.cli import find_project_file, main
from audiobooker.models import Utterance, UtteranceType
from audiobooker.review import export_for_review, import_reviewed


SAMPLE_TEXT = (
    "Chapter 1: The Beginning\n\n"
    "The morning sun rose over the hills. "
    '"Good morning," said Alice cheerfully. '
    '"Hello there," Bob replied with a smile.\n\n'
    "Chapter 2: The Middle\n\n"
    "Later that afternoon they met again. "
    '"Did you finish?" Alice asked. '
    '"Almost," said Bob.'
)


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------


def _text_source(tmp_path, name: str = "book.txt"):
    src = tmp_path / name
    src.write_text(SAMPLE_TEXT, encoding="utf-8")
    return src


def _hand_tuned_project(source):
    """The project shape the CRITICAL finding is about.

    A project the user has actually invested work in: two hand-cast voices, a
    pronunciation override and an edited chapter title. A fresh auto-cast parse
    has none of those, so a silent overwrite is detectable without inspecting
    timestamps.
    """
    project = AudiobookProject.from_string(
        SAMPLE_TEXT, title="Hand Tuned Book", author="Author"
    )
    project.cast("Alice", "af_bella")
    project.cast("Bob", "bm_george")
    project.add_pronunciation("Ada", "AY-duh")
    project.chapters[0].title = "Renamed By Hand"
    path = source.with_suffix(".audiobooker")
    project.save(path)
    return path


def _saved_compiled_project(tmp_path, title: str = "Test Book", name: str = "p.audiobooker"):
    project = AudiobookProject.from_string(SAMPLE_TEXT, title=title, author="Author")
    # FEAT-UX-002 (cli-surface wave, out-of-grant declared edit): `render`
    # now refuses when a NAMED speaker owns dialogue and has no voice — that
    # is what a typo'd speaker in an imported review file looks like, and it
    # used to ship in the fallback voice for the price of a full TTS run.
    # SAMPLE_TEXT's Alice and Bob were never cast, so the --clean-cache
    # ordering test below tripped the gate on incidental filler. Cast the
    # book so the test exercises only the cache ordering it is named for.
    for speaker, voice in (
        ("narrator", "af_heart"), ("Alice", "af_bella"), ("Bob", "bm_george"),
    ):
        project.cast(speaker, voice)
    project.compile()
    return project.save(tmp_path / name)


def _cache_with_chapters(project_dir, count: int = 2, size: int = 4096):
    """Create a render cache that looks like real rendered audio."""
    from audiobooker.renderer.cache_manifest import get_cache_root, get_chapters_dir

    root = get_cache_root(project_dir)
    chapters = get_chapters_dir(root)
    chapters.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (chapters / f"chapter_{i:04d}.wav").write_bytes(b"\0" * size)
    return root


def _no_voice_engine(monkeypatch):
    def raise_import():
        raise ImportError("voice-soundboard is not installed")

    monkeypatch.setattr(
        "audiobooker.casting.voice_registry.get_available_voices", raise_import
    )


# ===========================================================================
# CLIUX-C-001 — make/batch destroy an existing project, and do it before the
# render that can fail.
# ===========================================================================


class TestMakeDoesNotDestroyExistingProjects:
    def test_make_refuses_when_the_project_file_already_exists(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)
        project_path = _hand_tuned_project(source)
        before = project_path.read_bytes()

        code = main(["make", str(source)])
        combined = "".join(capsys.readouterr())

        assert project_path.read_bytes() == before, (
            "make replaced an existing project file without asking"
        )
        assert code != 0
        assert project_path.name in combined
        # It must say what is at risk and offer both real paths forward.
        assert "--overwrite-project" in combined
        assert "audiobooker render -p" in combined

    def test_refusal_names_the_cast_and_lexicon_at_risk(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)
        _hand_tuned_project(source)

        main(["make", str(source)])
        combined = "".join(capsys.readouterr())

        assert "cast" in combined.lower()
        assert "pronunciation" in combined.lower()
        # narrator + Alice + Bob = 3 cast voices, 1 lexicon entry.
        assert "3" in combined and "1" in combined

    def test_overwrite_keeps_the_old_project_when_the_render_fails(
        self, tmp_path, monkeypatch, capsys
    ):
        """The ordering IS the finding: save is step 4, render is step 5.

        With --overwrite-project the user accepted a replacement, but only of a
        run that actually produced an audiobook. A render that dies at ffmpeg
        must leave the original project on disk.
        """
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)
        project_path = _hand_tuned_project(source)

        from audiobooker.renderer import engine as render_engine

        def boom(*args, **kwargs):
            raise render_engine.RenderError("ffmpeg not found")

        monkeypatch.setattr(render_engine, "render_project", boom)

        code = main(["make", str(source), "--overwrite-project"])
        capsys.readouterr()

        assert code != 0
        reloaded = AudiobookProject.load(project_path)
        assert reloaded.config.pronunciation_overrides.get("Ada") == "AY-duh", (
            "the render failed and the hand-tuned project was destroyed anyway"
        )
        assert reloaded.chapters[0].title == "Renamed By Hand"
        # No staging debris left beside it.
        strays = [
            p for p in tmp_path.iterdir()
            if p.is_file() and p.name.startswith("book.audiobooker") and p != project_path
        ]
        assert strays == []

    def test_overwrite_promotes_the_new_project_when_the_render_succeeds(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)
        project_path = _hand_tuned_project(source)

        from audiobooker.renderer import engine as render_engine

        rendered = tmp_path / "out.m4b"
        rendered.write_bytes(b"\0")

        monkeypatch.setattr(
            render_engine, "render_project", lambda *a, **k: rendered
        )

        code = main(["make", str(source), "--overwrite-project"])
        capsys.readouterr()

        assert code == 0
        reloaded = AudiobookProject.load(project_path)
        # The fresh parse has the parsed title back, not the hand edit.
        assert reloaded.chapters[0].title != "Renamed By Hand"
        strays = [
            p for p in tmp_path.iterdir()
            if p.is_file() and p.name.startswith("book.audiobooker") and p != project_path
        ]
        assert strays == []

    def test_make_dry_run_reports_the_plan_and_writes_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)

        code = main(["make", str(source), "--dry-run"])
        out = capsys.readouterr().out

        assert code == 0
        assert "DRY RUN" in out
        assert "book.audiobooker" in out
        assert "does not exist" in out.lower()
        # The cast that would be applied, and the output path.
        assert "narrator" in out.lower()
        assert ".m4b" in out or ".mp3" in out or ".wav" in out
        assert not (tmp_path / "book.audiobooker").exists()

    def test_make_dry_run_says_when_the_project_already_exists(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)
        project_path = _hand_tuned_project(source)
        before = project_path.read_bytes()

        code = main(["make", str(source), "--dry-run"])
        out = capsys.readouterr().out

        assert code == 0
        assert "exists" in out.lower()
        assert project_path.read_bytes() == before

    def test_batch_refuses_to_overwrite_every_project_in_the_directory(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        source = _text_source(tmp_path)
        project_path = _hand_tuned_project(source)
        before = project_path.read_bytes()

        code = main(["batch", str(source)])
        combined = "".join(capsys.readouterr())

        assert project_path.read_bytes() == before
        assert code != 0, "batch reported success after refusing every book"
        assert "--overwrite-project" in combined


# ===========================================================================
# CLIUX-H-002 — project auto-detection breaks after the first render.
# ===========================================================================


class TestFindProjectFileIgnoresDirectories:
    def test_render_cache_directory_is_not_a_project_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        real = _saved_compiled_project(tmp_path, name="book.audiobooker")
        # This is exactly what the renderer creates beside the project.
        (tmp_path / ".audiobooker" / "cache" / "chapters").mkdir(parents=True)

        found = find_project_file(None)

        assert found.name == real.name

    def test_multiple_real_projects_still_ask_but_say_which_is_which(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        _saved_compiled_project(tmp_path, title="Alpha", name="alpha.audiobooker")
        _saved_compiled_project(tmp_path, title="Beta", name="beta.audiobooker")

        with pytest.raises(ValueError) as excinfo:
            find_project_file(None)

        message = str(excinfo.value)
        assert "alpha.audiobooker" in message and "beta.audiobooker" in message
        # An informed -p choice needs more than two filenames.
        assert "Alpha" in message and "Beta" in message


# ===========================================================================
# CLIUX-H-003 — render --clean-cache runs before every guard.
# ===========================================================================


class TestRenderCleanCacheOrdering:
    def test_dry_run_does_not_delete_the_cache(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)

        code = main(["render", "-p", str(project_path), "--clean-cache", "--dry-run"])
        out = capsys.readouterr().out

        assert cache_root.exists(), "--dry-run destroyed the cache it claimed to preview"
        assert code == 0
        assert "would delete" in out.lower()
        assert "2" in out  # two cached chapters

    def test_single_chapter_dry_run_does_not_delete_the_cache(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)

        code = main(
            ["render", "-p", str(project_path), "--clean-cache", "-c", "0", "--dry-run"]
        )
        capsys.readouterr()

        assert cache_root.exists()
        assert code == 0

    def test_bad_chapter_index_does_not_delete_the_cache(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)

        code = main(["render", "-p", str(project_path), "--clean-cache", "-c", "99"])
        capsys.readouterr()

        assert code == 1
        assert cache_root.exists(), "a mistyped -c index destroyed the cache"

    def test_missing_cover_does_not_delete_the_cache(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)

        code = main(
            ["render", "-p", str(project_path), "--clean-cache", "--cover", "nope.jpg"]
        )
        capsys.readouterr()

        assert code == 1
        assert cache_root.exists(), "a mistyped --cover destroyed the cache"

    def test_incompatible_flag_does_not_delete_the_cache(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)

        code = main(
            ["render", "-p", str(project_path), "--clean-cache", "-c", "0", "--acx"]
        )
        capsys.readouterr()

        assert code == 1
        assert cache_root.exists()

    def test_real_deletion_reports_chapter_count_and_size(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path, count=3)

        monkeypatch.setattr(
            AudiobookProject,
            "render_chapter",
            lambda self, index, output: tmp_path / "chapter_000.wav",
        )

        code = main(["render", "-p", str(project_path), "--clean-cache", "-c", "0"])
        out = capsys.readouterr().out

        assert code == 0
        assert not cache_root.exists()
        assert "3" in out
        assert "KB" in out or "MB" in out


# ===========================================================================
# CLIUX-H-004 — diagnose says "All checks passed" on a box that cannot render.
# ===========================================================================


class TestDiagnoseReadinessVerdict:
    def test_not_ready_without_voice_engine_or_ffmpeg(self, monkeypatch, capsys):
        import shutil as shutil_mod

        monkeypatch.setattr(shutil_mod, "which", lambda name: None)
        _no_voice_engine(monkeypatch)

        code = main(["diagnose"])
        out = capsys.readouterr().out

        assert "All checks passed." not in out
        assert "NOT ready to render" in out
        assert "ffmpeg" in out
        assert code != 0

    def test_ready_when_both_are_present(self, monkeypatch, capsys):
        import shutil as shutil_mod

        monkeypatch.setattr(shutil_mod, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices",
            lambda: [SimpleNamespace(id="af_heart", name="af_heart")],
        )

        code = main(["diagnose"])
        out = capsys.readouterr().out

        assert "Ready to render." in out
        assert code == 0

    def test_json_names_the_missing_required_components(self, monkeypatch, capsys):
        import shutil as shutil_mod

        monkeypatch.setattr(shutil_mod, "which", lambda name: None)
        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices",
            lambda: [SimpleNamespace(id="af_heart", name="af_heart")],
        )

        code = main(["diagnose", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["ready"] is False
        assert "ffmpeg" in data["missing_required"]
        assert code != 0

    def test_reports_which_output_formats_are_reachable(self, monkeypatch, capsys):
        import shutil as shutil_mod

        monkeypatch.setattr(shutil_mod, "which", lambda name: None)
        monkeypatch.setattr(
            "audiobooker.casting.voice_registry.get_available_voices",
            lambda: [SimpleNamespace(id="af_heart", name="af_heart")],
        )

        main(["diagnose", "--json"])
        data = json.loads(capsys.readouterr().out)

        # ffmpeg assembles every book format, including a multi-chapter WAV.
        assert data["reachable_formats"] == []

        capsys.readouterr()
        monkeypatch.setattr(shutil_mod, "which", lambda name: f"/usr/bin/{name}")
        main(["diagnose", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert "m4b" in data["reachable_formats"]


# ===========================================================================
# CLIUX-H-005 — cast accepts a character that appears nowhere in the book.
# ===========================================================================


class TestCastValidatesTheCharacter:
    def test_unknown_character_warns_with_close_matches(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)

        code = main(["cast", "Alicia", "af_bella", "-p", str(project_path)])
        err = capsys.readouterr().err

        assert "Alicia" in err
        assert "Did you mean" in err
        assert "Alice" in err
        assert code == 0  # non-fatal, same shape as the unknown-voice warning

    def test_known_speaker_is_not_warned_about(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)

        main(["cast", "Alice", "af_bella", "-p", str(project_path)])
        err = capsys.readouterr().err

        assert "unknown character" not in err.lower()

    def test_check_is_skipped_when_the_project_is_not_compiled(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project = AudiobookProject.from_string(SAMPLE_TEXT, title="T", author="A")
        project_path = project.save(tmp_path / "uncompiled.audiobooker")

        code = main(["cast", "Whoever", "af_bella", "-p", str(project_path)])
        err = capsys.readouterr().err

        assert code == 0
        assert "unknown character" not in err.lower()

    def test_force_skips_the_character_check(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)

        code = main(["cast", "Alicia", "af_bella", "--force", "-p", str(project_path)])
        err = capsys.readouterr().err

        assert code == 0
        assert "unknown character" not in err.lower()


# ===========================================================================
# CLIUX-H-006 — the review file instructs the edit that destroys types.
# ===========================================================================


def _typed_review_project(tmp_path):
    """A compiled project whose first chapter carries non-narration types."""
    project = AudiobookProject.from_string(SAMPLE_TEXT, title="Typed Book", author="A")
    project.compile()
    chapter = project.chapters[0]
    chapter.utterances = [
        Utterance(
            speaker="narrator",
            text="The door creaked open.",
            utterance_type=UtteranceType.NARRATION,
            chapter_index=0,
            line_index=0,
        ),
        Utterance(
            speaker="narrator",
            text="[PAUSE 2s]",
            utterance_type=UtteranceType.PAUSE,
            chapter_index=0,
            line_index=1,
        ),
        Utterance(
            speaker="narrator",
            text="[SFX: thunder]",
            utterance_type=UtteranceType.DIRECTION,
            chapter_index=0,
            line_index=2,
        ),
        Utterance(
            speaker="Alice",
            text='"Hello?"',
            utterance_type=UtteranceType.DIALOGUE,
            chapter_index=0,
            line_index=3,
        ),
    ]
    return project


def _review_text_with_one_block_deleted(project) -> str:
    chapter = project.chapters[0]
    header = f"=== {chapter.title} === [id:{chapter.id}]" if chapter.id else (
        f"=== {chapter.title} ==="
    )
    blocks = []
    # Drop the first block — the shape a user produces when they follow
    # "Delete entire speaker blocks to remove them".
    for utterance in chapter.utterances[1:]:
        blocks.append(f"@{utterance.speaker}\n{utterance.text}")
    return header + "\n\n" + "\n\n".join(blocks) + "\n"


class TestReviewTypeDestruction:
    def test_export_header_says_what_deleting_a_block_costs(self, tmp_path):
        project = _typed_review_project(tmp_path)
        path = export_for_review(project, tmp_path / "review.txt")
        header = path.read_text(encoding="utf-8")

        assert "Delete entire speaker blocks" in header
        # It must not stop there.
        lowered = header.lower()
        assert "utterance type" in lowered or "re-derive" in lowered
        assert "pause" in lowered and "direction" in lowered

    def test_import_reports_chapters_whose_types_were_re_derived(self, tmp_path):
        project = _typed_review_project(tmp_path)
        review = tmp_path / "review.txt"
        review.write_text(_review_text_with_one_block_deleted(project), encoding="utf-8")

        stats = import_reviewed(project, review)

        retyped = stats.get("retyped_chapters") or []
        assert retyped, "a chapter lost every utterance type and the import said nothing"
        entry = retyped[0]
        assert entry["title"] == project.chapters[0].title
        assert entry["types_lost"] == 2  # PAUSE + DIRECTION cannot be re-derived
        assert "pause" in " ".join(entry["lost_types"]).lower()

        # And the damage is real: the markers came back as plain narration.
        kinds = {u.utterance_type for u in project.chapters[0].utterances}
        assert UtteranceType.PAUSE not in kinds

    def test_import_does_not_report_when_types_were_preserved(self, tmp_path):
        project = _typed_review_project(tmp_path)
        review = export_for_review(project, tmp_path / "review.txt")

        stats = import_reviewed(project, review)

        assert not (stats.get("retyped_chapters") or [])

    def test_cli_warns_by_name_when_types_were_re_derived(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project = _typed_review_project(tmp_path)
        project_path = project.save(tmp_path / "typed.audiobooker")
        review = tmp_path / "review.txt"
        review.write_text(_review_text_with_one_block_deleted(project), encoding="utf-8")

        code = main(["review-import", str(review), "-p", str(project_path)])
        err = capsys.readouterr().err

        assert code == 0
        assert project.chapters[0].title in err
        assert "type" in err.lower()


# ===========================================================================
# CLIUX-H-007 — the malformed-tag hint cannot fix its own most common cause.
# ===========================================================================


def _review_file(tmp_path, body: str):
    path = tmp_path / "bad_review.txt"
    path.write_text(body, encoding="utf-8")
    return path


class TestMalformedTagHints:
    def test_second_emotion_group_gets_a_specific_hint(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        review = _review_file(
            tmp_path,
            "=== Chapter 1: The Beginning ===\n\n"
            "@Alice (whisper) (nervous)\n"
            '"Hello?"\n',
        )

        code = main(["review-import", str(review), "-p", str(project_path)])
        err = capsys.readouterr().err

        assert code == 1
        assert "at most one emotion" in err.lower()
        assert "replace" in err.lower()
        # Following the backslash hint here makes the renderer speak the tag.
        assert "backslash" not in err.lower()

    def test_line_with_no_parenthesised_group_keeps_the_backslash_hint(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        review = _review_file(
            tmp_path,
            "=== Chapter 1: The Beginning ===\n\n"
            "@Alice! she shouted\n"
            "body text\n",
        )

        code = main(["review-import", str(review), "-p", str(project_path)])
        err = capsys.readouterr().err

        assert code == 1
        assert "backslash" in err.lower()

    def test_export_header_warns_against_appending_an_emotion(self, tmp_path):
        project = _typed_review_project(tmp_path)
        path = export_for_review(project, tmp_path / "review.txt")
        header = path.read_text(encoding="utf-8").lower()

        assert "at most one emotion" in header

    def test_cli_error_is_not_duplicated_by_the_module_logger(
        self, tmp_path, monkeypatch, capsys, caplog
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        review = _review_file(
            tmp_path,
            "=== Chapter 1: The Beginning ===\n\n"
            "@Alice (whisper) (nervous)\n"
            '"Hello?"\n',
        )

        with caplog.at_level(logging.WARNING, logger="audiobooker.review"):
            main(["review-import", str(review), "-p", str(project_path)])

        duplicated = [
            r for r in caplog.records
            if r.name == "audiobooker.review" and "speaker tag" in r.getMessage()
        ]
        assert duplicated == [], (
            "the module logger repeated the line the CLI already printed"
        )

    def test_direct_library_use_still_logs_the_warning(self, tmp_path, caplog):
        project = _typed_review_project(tmp_path)
        review = _review_file(
            tmp_path,
            "=== Chapter 1: The Beginning ===\n\n"
            "@Alice (whisper) (nervous)\n"
            '"Hello?"\n',
        )

        with caplog.at_level(logging.WARNING, logger="audiobooker.review"):
            import_reviewed(project, review)

        assert any(
            r.name == "audiobooker.review" and "speaker tag" in r.getMessage()
            for r in caplog.records
        )


# ===========================================================================
# CLIUX-H-008 — review-export's default filename skips the sanitizer.
# ===========================================================================


class TestReviewExportFilenameSanitisation:
    def test_default_filename_is_sanitised(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = AudiobookProject.from_string(
            SAMPLE_TEXT, title="Dune: Part One", author="A"
        )
        project.compile()

        path = export_for_review(project)

        assert ":" not in path.name, (
            "a colon in the title wrote into an NTFS alternate data stream"
        )
        # The file the user can actually see in a file browser.
        assert path.name in {p.name for p in tmp_path.iterdir()}
        assert path.read_text(encoding="utf-8").strip()

    def test_cli_review_export_default_filename_is_sanitised(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project = AudiobookProject.from_string(
            SAMPLE_TEXT, title="Dune: Part One", author="A"
        )
        project.compile()
        project_path = project.save(tmp_path / "dune.audiobooker")

        code = main(["review-export", "-p", str(project_path)])
        capsys.readouterr()

        assert code == 0
        written = [p.name for p in tmp_path.iterdir() if p.name.endswith("_review.txt")]
        assert written, "no visible review file was written"
        assert all(":" not in name for name in written)

    def test_explicit_output_path_is_left_untouched(self, tmp_path):
        project = _typed_review_project(tmp_path)
        target = tmp_path / "my exact name.txt"

        path = export_for_review(project, target)

        assert path == target
        assert target.exists()


# ===========================================================================
# CLIUX-H-009 — export-chapters emits markers from unrendered chapters.
# ===========================================================================


class TestExportChaptersRequiresRenderedAudio:
    def test_refuses_when_nothing_has_been_rendered(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)

        code = main(["export-chapters", "-p", str(project_path), "--format", "cue"])
        captured = capsys.readouterr()
        combined = captured.out + captured.err

        assert code == 1, "a CUE sheet with every track at the same timestamp shipped"
        assert "render" in combined.lower()
        assert "INDEX 01 00:02:00" not in captured.out

    def test_warns_by_name_when_only_some_chapters_are_rendered(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project = AudiobookProject.from_string(SAMPLE_TEXT, title="T", author="A")
        project.compile()
        project.chapters[0].duration_seconds = 61.0
        unrendered_title = project.chapters[1].title
        project_path = project.save(tmp_path / "half.audiobooker")

        code = main(["export-chapters", "-p", str(project_path), "--format", "json"])
        captured = capsys.readouterr()

        assert code == 0
        assert unrendered_title in captured.err

    def test_fully_rendered_project_exports_cleanly(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project = AudiobookProject.from_string(SAMPLE_TEXT, title="T", author="A")
        project.compile()
        for chapter in project.chapters:
            chapter.duration_seconds = 61.0
        project_path = project.save(tmp_path / "full.audiobooker")

        code = main(["export-chapters", "-p", str(project_path), "--format", "json"])
        captured = capsys.readouterr()

        assert code == 0
        assert "WARNING" not in captured.err
        assert json.loads(captured.out)


# ===========================================================================
# CLIUX-H-010 — cache clean deletes hours of audio with no confirmation.
# ===========================================================================


class TestCacheCleanConfirmation:
    def test_refuses_without_yes_on_a_non_interactive_stdin(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))

        code = main(["cache", "clean", "-p", str(project_path)])
        combined = "".join(capsys.readouterr())

        assert code == 1
        assert cache_root.exists(), "hours of audio deleted with no confirmation"
        assert "--yes" in combined
        assert "clean-failed" in combined

    def test_yes_deletes_and_names_the_chapter_count_and_size(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path, count=3)

        code = main(["cache", "clean", "-p", str(project_path), "--yes"])
        out = capsys.readouterr().out

        assert code == 0
        assert not cache_root.exists()
        assert "3" in out
        assert "KB" in out or "MB" in out

    def test_dry_run_deletes_nothing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path, count=3)

        code = main(["cache", "clean", "-p", str(project_path), "--dry-run"])
        out = capsys.readouterr().out

        assert code == 0
        assert cache_root.exists()
        assert "would delete" in out.lower()
        assert "3" in out

    def test_interactive_prompt_aborts_on_no(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        code = main(["cache", "clean", "-p", str(project_path)])
        combined = "".join(capsys.readouterr())

        assert code == 1
        assert cache_root.exists()
        assert "abort" in combined.lower() or "cancel" in combined.lower()

    def test_interactive_prompt_proceeds_on_yes(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        project_path = _saved_compiled_project(tmp_path)
        cache_root = _cache_with_chapters(tmp_path)
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        code = main(["cache", "clean", "-p", str(project_path)])
        capsys.readouterr()

        assert code == 0
        assert not cache_root.exists()
