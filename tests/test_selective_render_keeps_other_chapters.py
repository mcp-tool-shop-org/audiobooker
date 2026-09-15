"""`render --chapters N` destroyed the other chapters' cached audio.

The CLI implements a chapter selection by REPLACING `project.chapters`
with the filtered subset. The renderer then walks that subset with
`enumerate`, and uses the enumerate position for three things that are
chapter *identity*, not loop position:

    manifest.get_entry(i)
    get_chapter_wav_path(cache_root, i)   ->  chapter_{i:04d}.wav
    ChapterCacheEntry(chapter_index=i, ...)

So on a four-chapter book, `--chapters 4` gives a one-element list, i=0,
and chapter 4's audio is written to `chapter_0000.wav` — the file holding
chapter 1's cached audio — and recorded at manifest key 0.

It is not wrong audio: `ChapterCacheEntry.is_valid()` compares the text,
casting and render-params hashes, so a later full render sees a mismatch
at key 0 and re-renders rather than reading chapter 4's WAV as chapter 1.
The damage is destroyed cache and repeated paid TTS time, on exactly the
long books where anyone reaches for a selection. It also contradicts the
README's "a re-render that says Cached means it".

The utterance-level cache in the same module already gets this right —
`get_utterance_wav_dir(cache_root, chapter.index)` — so under a selection
the two caches currently disagree about which chapter they are caching.
"""

from __future__ import annotations

import json
from pathlib import Path

from audiobooker import AudiobookProject
from audiobooker.renderer import engine as engine_mod
from audiobooker.renderer.cache_manifest import (
    get_cache_root, get_chapter_wav_path, get_manifest_path,
)
from audiobooker.renderer.engine import filter_chapters_by_selection
from audiobooker.renderer.output import AssemblyResult
from tests.fakes.fake_tts import FakeTTSEngine

BOOK = "\n\n".join(
    f'Chapter {n}: Section {n}\n\n'
    f'The hall was cold. "Lamp {n} is out," said Alice.\n\n'
    f'He counted them again and there were still {n}.'
    for n in range(1, 5)
)


class _Assembler:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> AssemblyResult:
        self.calls.append(kwargs)
        out = Path(kwargs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE-AUDIO")
        return AssemblyResult(output_path=out, chapters_embedded=True)


def _project(tmp_path=None) -> AudiobookProject:
    """Saved into tmp_path when given, because `dry_run_render` derives
    its cache root from `project.project_path` rather than taking one.

    An unsaved project falls back to the CWD (with a warning), so a
    preview test that skipped the save would read a different cache than
    the render it is checking against — and report a mismatch that says
    nothing about the code.
    """
    p = AudiobookProject.from_string(BOOK, title="Sel", author="A")
    p.cast("narrator", "af_heart")
    p.cast("Alice", "af_bella")
    p.compile()
    assert len(p.chapters) == 4, [c.title for c in p.chapters]
    if tmp_path is not None:
        p.save(Path(tmp_path) / "book.audiobooker")
    return p


def _render(project, tmp_path, cache_root, name="book.m4b"):
    return engine_mod.render_project(
        project,
        tmp_path / name,
        engine=FakeTTSEngine(),
        assembler=_Assembler(),
        cache_root=cache_root,
    )


def _wav_bytes(cache_root: Path) -> dict[int, bytes]:
    out = {}
    for idx in range(4):
        p = get_chapter_wav_path(cache_root, idx)
        if p.exists():
            out[idx] = p.read_bytes()
    return out


def _manifest_keys(cache_root: Path) -> dict:
    path = get_manifest_path(cache_root)
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("chapters") or data.get("entries") or []
    if isinstance(entries, dict):
        return {int(k): v for k, v in entries.items()}
    return {int(e["chapter_index"]): e for e in entries}


class TestASelectiveRenderLeavesTheOthersAlone:
    def test_it_does_not_overwrite_another_chapter_s_wav(self, tmp_path):
        cache_root = get_cache_root(tmp_path)

        project = _project()
        _render(project, tmp_path, cache_root)
        before = _wav_bytes(cache_root)
        assert len(before) == 4, f"full render produced {sorted(before)}"

        # Now re-render ONLY chapter 4, the way cmd_render does it.
        selective = _project()
        selective.chapters = filter_chapters_by_selection(
            selective.chapters, include_ranges="4"
        )
        assert [c.index for c in selective.chapters] == [3]
        _render(selective, tmp_path, cache_root, name="ch4.m4b")

        after = _wav_bytes(cache_root)
        for idx in (0, 1, 2):
            assert after.get(idx) == before.get(idx), (
                f"rendering chapter 4 alone rewrote chapter {idx + 1}'s "
                f"cached audio at {get_chapter_wav_path(cache_root, idx).name}"
            )

    def test_the_selected_chapter_lands_on_its_own_file(self, tmp_path):
        cache_root = get_cache_root(tmp_path)
        project = _project()
        project.chapters = filter_chapters_by_selection(
            project.chapters, include_ranges="4"
        )
        _render(project, tmp_path, cache_root, name="ch4.m4b")

        assert get_chapter_wav_path(cache_root, 3).exists(), (
            "chapter 4 did not render to chapter_0003.wav; files present: "
            f"{sorted(p.name for p in cache_root.rglob('chapter_*.wav'))}"
        )
        assert not get_chapter_wav_path(cache_root, 0).exists(), (
            "chapter 4 rendered to chapter_0000.wav, which belongs to "
            "chapter 1"
        )

    def test_the_manifest_records_it_under_its_own_index(self, tmp_path):
        cache_root = get_cache_root(tmp_path)
        project = _project()
        project.chapters = filter_chapters_by_selection(
            project.chapters, include_ranges="4"
        )
        _render(project, tmp_path, cache_root, name="ch4.m4b")

        keys = _manifest_keys(cache_root)
        assert set(keys) == {3}, (
            f"chapter 4 was recorded under manifest key(s) {sorted(keys)}; "
            "it is chapter index 3"
        )

    def test_a_full_render_afterwards_reuses_everything(self, tmp_path):
        """The payoff. This is the promise the README makes and the one
        the bug broke: work already paid for is not paid for twice."""
        cache_root = get_cache_root(tmp_path)

        project = _project()
        _render(project, tmp_path, cache_root)

        selective = _project()
        selective.chapters = filter_chapters_by_selection(
            selective.chapters, include_ranges="4"
        )
        _render(selective, tmp_path, cache_root, name="ch4.m4b")

        again = _project(tmp_path)
        summary = _render(again, tmp_path, cache_root,
                          name="full2.m4b").render_summary
        assert summary.skipped_cached == 4, (
            f"{summary.rendered} of 4 chapters were re-synthesized after a "
            "selective render; every one of them was already in the cache"
        )
        assert summary.rendered == 0


    def test_a_selective_rerender_reuses_its_own_cached_chapter(self,
                                                                tmp_path):
        """The read side of the key, which the write-side tests above do
        not pin.

        Mutation-checked: reverting only `manifest.get_entry(chapter.index)`
        to `get_entry(i)` leaves every other test in this file green. The
        symptom is quieter than the overwrite — a selective re-render
        silently misses its own cache and pays for the chapter again —
        but it is the same conflation and needs its own test.
        """
        cache_root = get_cache_root(tmp_path)

        project = _project()
        _render(project, tmp_path, cache_root)

        selective = _project()
        selective.chapters = filter_chapters_by_selection(
            selective.chapters, include_ranges="4"
        )
        summary = _render(selective, tmp_path, cache_root,
                          name="ch4.m4b").render_summary

        assert summary.skipped_cached == 1, (
            "re-rendering chapter 4 alone re-synthesized it, though the "
            "full render had just cached it — the cache was looked up "
            "under this run's loop position rather than the chapter's "
            "own index"
        )
        assert summary.rendered == 0


class TestThePreviewAgreesWithTheRender:
    """RH-B-004's invariant, under a selection.

    `dry_run_render` exists to predict what `render` will do. The two
    read the cache through separate code paths, and the docstring on
    `dry_run_render` records the last time they drifted: a wave-2 change
    added arguments to the real render's params hash and not to the
    preview's, so `--acx --dry-run` reported a fully cached book that
    then re-rendered from scratch.

    Keying is the same class of shared assumption, so it gets the same
    kind of test.
    """

    def test_the_dry_run_says_cached_when_the_render_would_be(
        self, tmp_path, capsys
    ):
        cache_root = get_cache_root(tmp_path)

        project = _project(tmp_path)
        _render(project, tmp_path, cache_root)
        capsys.readouterr()

        selective = _project(tmp_path)
        selective.chapters = filter_chapters_by_selection(
            selective.chapters, include_ranges="4"
        )
        # The engine is part of the render-params cache key, so a preview
        # that omits it hashes differently from the render it is
        # predicting and reports every chapter as needing work. That is
        # RH-B-004, and the CLI's own call site was making exactly this
        # mistake until this commit.
        engine_mod.dry_run_render(
            selective, resume=True, engine=FakeTTSEngine()
        )
        preview = capsys.readouterr().out

        assert "To render:  0" in preview, (
            f"the preview expects to render a cached chapter:\n{preview}"
        )
        assert "Cached:     1" in preview, preview

        # ...and the render agrees.
        again = _project(tmp_path)
        again.chapters = filter_chapters_by_selection(
            again.chapters, include_ranges="4"
        )
        summary = _render(again, tmp_path, cache_root,
                          name="ch4.m4b").render_summary
        assert summary.skipped_cached == 1
        assert summary.rendered == 0


class TestTheTwoCachesAgreeOnWhatAChapterIs:
    def test_chapter_and_utterance_caches_use_the_same_identity(self,
                                                                tmp_path):
        """The utterance cache already keys off chapter.index. Under a
        selection the chapter cache keyed off the loop position, so the
        two disagreed about which chapter they were caching."""
        from audiobooker.renderer.cache_manifest import (
            get_utterance_manifest_path,
        )

        cache_root = get_cache_root(tmp_path)
        project = _project()
        project.chapters = filter_chapters_by_selection(
            project.chapters, include_ranges="4"
        )
        chapter = project.chapters[0]
        _render(project, tmp_path, cache_root, name="ch4.m4b")

        utt = get_utterance_manifest_path(cache_root, chapter.index)
        wav = get_chapter_wav_path(cache_root, chapter.index)
        assert f"{chapter.index:04d}" in wav.name
        assert str(chapter.index) in str(utt), (
            "the utterance cache path does not carry chapter.index; the "
            "premise of this test has changed"
        )
