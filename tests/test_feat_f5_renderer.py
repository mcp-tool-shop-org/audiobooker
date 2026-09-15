"""
F5 renderer / casting-registry feature tests (v2.1 ECOSYSTEM).

Covers the approved v2.1 ECOSYSTEM features:

- FT-ENGINE-001   Pluggable TTS engine registry (entry-point + env + default
                  resolution chain) + optional list_voices() on the protocol
                  + voice_registry.get_available_voices(engine=...)
- FT-RENDER-M-008 Podcast RSS feed (iTunes RSS 2.0) — output.export_podcast_rss
- FT-RENDER-P-004 Utterance-level incremental cache (opt-in, namespaced) —
                  engine.render_chapter_incremental + the namespaced utterance
                  manifest, asserting the chapter cache is untouched when off.

All tests are hermetic: no real ffmpeg, no voice-soundboard. The TTS engine is
faked via FakeTTSEngine and the ffmpeg concat step (incremental stitch) is
faked via a recording runner that materializes its output.
"""

from __future__ import annotations

import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from audiobooker.models import (
    BookMetadata,
    CastingTable,
    Chapter,
    ProjectConfig,
    Utterance,
    UtteranceType,
)
from audiobooker.renderer import engine as engine_mod
from audiobooker.renderer.engine import (
    DEFAULT_ENGINE_NAME,
    EngineNotFoundError,
    get_default_engine,
    list_registered_engines,
    render_chapter_incremental,
)
from audiobooker.renderer.output import export_podcast_rss
from audiobooker.casting.voice_registry import get_available_voices
from tests.fakes.fake_tts import FakeTTSEngine, write_silence_wav


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _StitchRunner:
    """Fake ffmpeg runner for the incremental-stitch concat step.

    Records every call and writes a placeholder WAV at the final argument
    (the ffmpeg output path) so callers that assert the file exists see it.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        from audiobooker.renderer.protocols import RunResult
        self.calls.append(list(args))
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        write_silence_wav(out, 0.1)
        return RunResult(returncode=0, stdout="", stderr="")


class _FakeEntryPoint:
    """Minimal importlib.metadata EntryPoint stand-in."""

    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        return self._obj


class _PluginEngine:
    """A registered third-party engine that advertises its own voices."""

    def __init__(self) -> None:
        self.synth_calls = 0

    def synthesize(self, script, voices, output_path, progress_callback=None):
        from audiobooker.renderer.protocols import SynthesisResult
        self.synth_calls += 1
        output_path = Path(output_path)
        write_silence_wav(output_path, 0.2)
        return SynthesisResult(audio_path=output_path, duration_seconds=0.2)

    def list_voices(self) -> list[str]:
        return ["plugin_voice_a", "plugin_voice_b"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_casting() -> CastingTable:
    casting = CastingTable()
    casting.cast("narrator", "af_heart")
    casting.cast("Alice", "af_bella")
    casting.cast("Bob", "bm_george")
    return casting


def _grow_dir(base: Path, target_len: int) -> Path:
    """Nest boring-named subdirectories under ``base`` until the resulting
    path's string length is at least ``target_len``.

    COORD-B-002: deterministic regardless of how long ``base`` already is
    (pytest's own ``tmp_path``/``--basetemp`` length varies by host/CI) --
    this measures the actual starting length and pads exactly as much as
    needed, splitting the padding across multiple path components (capped at
    80 chars each) so no single component gets anywhere near NTFS's 255-char
    per-component ceiling. The directory is created before returning.
    """
    d = base
    while len(str(d)) < target_len:
        remaining = target_len - len(str(d)) - 1  # -1 for the "\" being added
        if remaining <= 0:
            break
        d = d / ("p" * min(remaining, 80))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_chapter(index: int = 0) -> Chapter:
    ch = Chapter(index=index, title=f"Chapter {index + 1}", raw_text="x")
    ch.utterances = [
        Utterance(speaker="narrator", text="The sun rose.",
                  utterance_type=UtteranceType.NARRATION),
        Utterance(speaker="Alice", text="Good morning.",
                  utterance_type=UtteranceType.DIALOGUE, emotion="happy"),
        Utterance(speaker="Bob", text="Hello there.",
                  utterance_type=UtteranceType.DIALOGUE),
    ]
    return ch


# ===========================================================================
# FT-ENGINE-001: Pluggable engine registry
# ===========================================================================

class TestEngineRegistry:
    """get_default_engine resolution chain + protocol list_voices()."""

    def _patch_entry_points(self, monkeypatch, mapping: dict):
        """Patch _load_engine_entry_points to return the given {name: ep}."""
        eps = {name: _FakeEntryPoint(name, obj) for name, obj in mapping.items()}
        monkeypatch.setattr(
            engine_mod, "_load_engine_entry_points", lambda: eps
        )

    def _patch_builtin(self, monkeypatch):
        """Replace the built-in engine class with a marker stub.

        The real _VoiceSoundboardEngine() raises ImportError when
        voice-soundboard isn't installed, so for resolution tests we swap in a
        sentinel class and assert get_default_engine() picks it — proving the
        built-in is what was selected, not which package is installed.
        """
        marker = type("_BuiltinMarker", (), {})
        monkeypatch.setattr(engine_mod, "_VoiceSoundboardEngine", marker)
        return marker

    def test_default_none_returns_builtin(self, monkeypatch):
        """get_default_engine(None) ALWAYS resolves to the built-in engine.

        Byte-identical to historical behavior: the built-in resolves without
        ever reading entry-point metadata.
        """
        # Even with NO entry points registered, None resolves to the built-in.
        self._patch_entry_points(monkeypatch, {})
        marker = self._patch_builtin(monkeypatch)
        monkeypatch.delenv(engine_mod.ENGINE_ENV_VAR, raising=False)
        eng = get_default_engine()
        assert isinstance(eng, marker)

    def test_explicit_voice_soundboard_is_builtin(self, monkeypatch):
        """Explicit 'voice-soundboard' resolves to the built-in (no metadata)."""
        self._patch_entry_points(monkeypatch, {})
        marker = self._patch_builtin(monkeypatch)
        eng = get_default_engine(DEFAULT_ENGINE_NAME)
        assert isinstance(eng, marker)

    def test_env_var_selects_engine(self, monkeypatch):
        """AUDIOBOOKER_ENGINE selects a registered plugin when name is None."""
        self._patch_entry_points(monkeypatch, {"piper": _PluginEngine})
        monkeypatch.setenv(engine_mod.ENGINE_ENV_VAR, "piper")
        eng = get_default_engine()
        assert isinstance(eng, _PluginEngine)

    def test_explicit_name_beats_env_var(self, monkeypatch):
        """Explicit name arg wins over the env var."""
        self._patch_entry_points(
            monkeypatch, {"piper": _PluginEngine, "other": _PluginEngine}
        )
        monkeypatch.setenv(engine_mod.ENGINE_ENV_VAR, "other")
        eng = get_default_engine("piper")
        assert isinstance(eng, _PluginEngine)

    def test_blank_env_var_falls_back_to_default(self, monkeypatch):
        """A blank/whitespace env var is treated as unset → built-in default."""
        self._patch_entry_points(monkeypatch, {})
        marker = self._patch_builtin(monkeypatch)
        monkeypatch.setenv(engine_mod.ENGINE_ENV_VAR, "   ")
        eng = get_default_engine()
        assert isinstance(eng, marker)

    def test_unknown_engine_raises_clear_error(self, monkeypatch):
        """An unknown named engine raises EngineNotFoundError with the hint."""
        self._patch_entry_points(monkeypatch, {"piper": _PluginEngine})
        monkeypatch.delenv(engine_mod.ENGINE_ENV_VAR, raising=False)
        with pytest.raises(EngineNotFoundError) as exc_info:
            get_default_engine("does-not-exist")
        msg = str(exc_info.value)
        assert "Unknown TTS engine 'does-not-exist'" in msg
        assert "Installed:" in msg
        assert "pip install audiobooker-piper" in msg
        # Installed list includes the built-in + the registered plugin.
        assert "voice-soundboard" in msg
        assert "piper" in msg

    def test_engine_not_found_structured(self, monkeypatch):
        """EngineNotFoundError exposes the structured error shape."""
        self._patch_entry_points(monkeypatch, {})
        err = EngineNotFoundError("nope", ["voice-soundboard"])
        d = err.structured()
        assert d["code"] == "INPUT_UNKNOWN_ENGINE"
        assert d["retryable"] is False
        assert "nope" in d["message"]

    def test_list_registered_engines_includes_builtin(self, monkeypatch):
        """list_registered_engines always includes the built-in default."""
        self._patch_entry_points(monkeypatch, {"piper": _PluginEngine})
        names = list_registered_engines()
        assert DEFAULT_ENGINE_NAME in names
        assert "piper" in names
        assert names == sorted(names)

    def test_registered_engine_loaded_by_name(self, monkeypatch):
        """A registered engine resolves by its explicit name."""
        self._patch_entry_points(monkeypatch, {"piper": _PluginEngine})
        eng = get_default_engine("piper")
        assert isinstance(eng, _PluginEngine)


class TestProtocolListVoices:
    """protocols.TTSEngine optional list_voices() member."""

    def test_protocol_has_default_list_voices(self):
        """The Protocol declares list_voices with a default (optional) body."""
        from audiobooker.renderer.protocols import TTSEngine
        assert hasattr(TTSEngine, "list_voices")

    def test_list_voices_is_optional_callers_tolerate_absence(self):
        """list_voices() is OPTIONAL — engines may omit it; callers probe.

        FakeTTSEngine implements only synthesize(). Callers must use hasattr()
        (not isinstance against the Protocol) so an engine without list_voices()
        still works — get_available_voices falls back to the voice catalog.
        """
        fake = FakeTTSEngine()
        assert not hasattr(fake, "list_voices")

    def test_engine_with_list_voices_detected_by_hasattr(self):
        """An engine that DOES implement list_voices() is detectable."""
        eng = _PluginEngine()
        assert hasattr(eng, "list_voices")
        assert eng.list_voices() == ["plugin_voice_a", "plugin_voice_b"]


class TestGetAvailableVoices:
    """voice_registry.get_available_voices(engine=...) — FT-ENGINE-001."""

    def test_engine_with_list_voices_used(self):
        """When the engine has list_voices(), its catalog is used."""
        eng = _PluginEngine()
        voices = get_available_voices(engine=eng)
        assert voices == {"plugin_voice_a", "plugin_voice_b"}
        assert isinstance(voices, set)

    def test_engine_without_list_voices_falls_back(self, monkeypatch):
        """An engine lacking list_voices() falls back to the import path."""
        # FakeTTSEngine has no list_voices() — must hit the VOICES import,
        # which we stub so the test doesn't need voice-soundboard installed.
        import audiobooker.casting.voice_registry as vr

        class _FakeVoicesModule:
            VOICES = {"af_heart": object(), "bm_george": object()}

        import sys
        monkeypatch.setitem(sys.modules, "voice_soundboard", object())
        monkeypatch.setitem(sys.modules, "voice_soundboard.config", _FakeVoicesModule)
        voices = vr.get_available_voices(engine=FakeTTSEngine())
        assert voices == {"af_heart", "bm_george"}

    def test_default_no_engine_uses_import(self, monkeypatch):
        """engine=None (default) preserves the historical import behavior."""
        import sys

        class _FakeVoicesModule:
            VOICES = {"af_sky": object()}

        monkeypatch.setitem(sys.modules, "voice_soundboard", object())
        monkeypatch.setitem(sys.modules, "voice_soundboard.config", _FakeVoicesModule)
        voices = get_available_voices()
        assert voices == {"af_sky"}


# ===========================================================================
# FT-RENDER-M-008: Podcast RSS feed
# ===========================================================================

class _MiniProject:
    """Tiny stand-in carrying the fields export_podcast_rss reads."""

    def __init__(self, title, author, metadata=None, config=None):
        self.title = title
        self.author = author
        self.metadata = metadata or BookMetadata()
        self.config = config or ProjectConfig()


class TestPodcastRss:
    """export_podcast_rss — valid iTunes RSS 2.0."""

    def _items(self):
        return [
            {
                "title": "Chapter 1: The Beginning",
                "filename": "ch01.mp3",
                "duration_seconds": 3661.0,  # 1:01:01
                "length": 12345,
            },
            {
                "title": "Chapter 2: The Middle",
                "filename": "ch02.mp3",
                "duration_seconds": 90.0,  # 0:01:30
                "length": 6789,
            },
        ]

    def test_rss_is_well_formed_xml(self):
        proj = _MiniProject("My Book", "Jane Doe")
        xml = export_podcast_rss(proj, self._items(), base_url="https://x.test/feed/")
        # Parses as valid XML.
        root = ET.fromstring(xml)
        assert root.tag == "rss"
        assert root.attrib["version"] == "2.0"

    def test_channel_from_metadata(self):
        meta = BookMetadata(
            genre="Fiction", narrator_name="Sam Narrator", publisher="ACME Audio"
        )
        proj = _MiniProject("My Book", "Jane Doe", metadata=meta)
        xml = export_podcast_rss(proj, self._items())
        root = ET.fromstring(xml)
        channel = root.find("channel")
        assert channel.find("title").text == "My Book"
        ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        assert channel.find("itunes:author", ns).text == "Sam Narrator"
        cat = channel.find("itunes:category", ns)
        assert cat.attrib["text"] == "Fiction"

    def test_one_item_per_chapter(self):
        proj = _MiniProject("My Book", "Jane Doe")
        xml = export_podcast_rss(proj, self._items())
        root = ET.fromstring(xml)
        items = root.find("channel").findall("item")
        assert len(items) == 2
        assert items[0].find("title").text == "Chapter 1: The Beginning"

    def test_enclosure_url_joins_base_url(self):
        proj = _MiniProject("My Book", "Jane Doe")
        xml = export_podcast_rss(proj, self._items(), base_url="https://x.test/feed/")
        root = ET.fromstring(xml)
        enc = root.find("channel").find("item").find("enclosure")
        assert enc.attrib["url"] == "https://x.test/feed/ch01.mp3"
        assert enc.attrib["length"] == "12345"
        assert enc.attrib["type"] == "audio/mpeg"

    def test_enclosure_url_joins_without_trailing_slash(self):
        proj = _MiniProject("My Book", "Jane Doe")
        xml = export_podcast_rss(proj, self._items(), base_url="https://x.test/feed")
        root = ET.fromstring(xml)
        enc = root.find("channel").find("item").find("enclosure")
        assert enc.attrib["url"] == "https://x.test/feed/ch01.mp3"

    def test_itunes_duration_formatted_hms(self):
        proj = _MiniProject("My Book", "Jane Doe")
        xml = export_podcast_rss(proj, self._items())
        root = ET.fromstring(xml)
        ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        items = root.find("channel").findall("item")
        assert items[0].find("itunes:duration", ns).text == "01:01:01"
        assert items[1].find("itunes:duration", ns).text == "00:01:30"

    def test_item_has_pubdate_and_guid(self):
        proj = _MiniProject("My Book", "Jane Doe")
        xml = export_podcast_rss(proj, self._items(), base_url="https://x.test/")
        root = ET.fromstring(xml)
        item = root.find("channel").find("item")
        assert item.find("pubDate").text  # non-empty RFC 822 string
        guid = item.find("guid")
        assert guid.text == "https://x.test/ch01.mp3"

    def test_special_characters_escaped(self):
        proj = _MiniProject("Tom & Jerry <Tales>", "A & B")
        items = [{"title": "Ch <1> & more", "filename": "a.mp3",
                  "duration_seconds": 1.0, "length": 1}]
        xml = export_podcast_rss(proj, items)
        # Raw ampersand/angle-brackets must be escaped — parses cleanly.
        root = ET.fromstring(xml)
        assert root.find("channel").find("title").text == "Tom & Jerry <Tales>"

    def test_empty_items_still_valid(self):
        proj = _MiniProject("Empty Book", "Nobody")
        xml = export_podcast_rss(proj, [])
        root = ET.fromstring(xml)
        assert root.find("channel").findall("item") == []

    def test_mime_type_inferred_from_extension(self):
        proj = _MiniProject("My Book", "Jane Doe")
        items = [{"title": "C", "filename": "ch.m4b",
                  "duration_seconds": 1.0, "length": 1}]
        xml = export_podcast_rss(proj, items)
        root = ET.fromstring(xml)
        enc = root.find("channel").find("item").find("enclosure")
        assert enc.attrib["type"] == "audio/x-m4b"


# ===========================================================================
# FT-RENDER-P-004: Utterance-level incremental cache (opt-in, namespaced)
# ===========================================================================

class TestUtteranceIncrementalCache:
    """render_chapter_incremental + namespaced utterance manifest."""

    def test_first_run_synthesizes_every_utterance(self, tmp_path):
        engine = FakeTTSEngine()
        runner = _StitchRunner()
        chapter = _make_chapter()
        casting = _make_casting()
        out = tmp_path / "chapter_0000.wav"

        result = render_chapter_incremental(
            chapter, casting, out,
            engine=engine,
            cache_root=tmp_path / "cache",
            render_params_hash="paramhash",
            runner=runner,
        )

        assert result.utterances_total == 3
        assert result.utterances_synthesized == 3
        assert result.utterances_reused == 0
        assert len(engine.calls) == 3  # one synth call per utterance
        assert out.exists()

    def test_second_run_reuses_unchanged_utterances(self, tmp_path):
        casting = _make_casting()
        cache_root = tmp_path / "cache"
        out = tmp_path / "chapter_0000.wav"

        # First pass.
        eng1 = FakeTTSEngine()
        render_chapter_incremental(
            _make_chapter(), casting, out,
            engine=eng1, cache_root=cache_root,
            render_params_hash="paramhash", runner=_StitchRunner(),
        )

        # Second pass with a NEW engine — everything should be reused, so the
        # new engine is never called.
        eng2 = FakeTTSEngine()
        result = render_chapter_incremental(
            _make_chapter(), casting, out,
            engine=eng2, cache_root=cache_root,
            render_params_hash="paramhash", runner=_StitchRunner(),
        )
        assert result.utterances_reused == 3
        assert result.utterances_synthesized == 0
        assert len(eng2.calls) == 0

    def test_editing_one_utterance_resynthesizes_only_that_one(self, tmp_path):
        casting = _make_casting()
        cache_root = tmp_path / "cache"
        out = tmp_path / "chapter_0000.wav"

        render_chapter_incremental(
            _make_chapter(), casting, out,
            engine=FakeTTSEngine(), cache_root=cache_root,
            render_params_hash="paramhash", runner=_StitchRunner(),
        )

        # Edit the middle utterance's text; the other two are unchanged.
        edited = _make_chapter()
        edited.utterances[1].text = "Good morning, friend."

        eng2 = FakeTTSEngine()
        result = render_chapter_incremental(
            edited, casting, out,
            engine=eng2, cache_root=cache_root,
            render_params_hash="paramhash", runner=_StitchRunner(),
        )
        assert result.utterances_synthesized == 1
        assert result.utterances_reused == 2
        assert len(eng2.calls) == 1

    def test_utterance_manifest_is_namespaced(self, tmp_path):
        """The utterance manifest lives in its OWN file, not render_v1.json."""
        from audiobooker.renderer.cache_manifest import (
            get_utterance_manifest_path,
            UTTERANCE_MANIFEST_FILENAME,
        )
        cache_root = tmp_path / "cache"
        out = tmp_path / "chapter_0000.wav"
        render_chapter_incremental(
            _make_chapter(), _make_casting(), out,
            engine=FakeTTSEngine(), cache_root=cache_root,
            render_params_hash="paramhash", runner=_StitchRunner(),
        )
        upath = get_utterance_manifest_path(cache_root, 0)
        assert upath.exists()
        assert UTTERANCE_MANIFEST_FILENAME in upath.name
        # The chapter-level manifest (render_v1.json) was NEVER created by the
        # incremental path — the chapter cache is untouched when this is off.
        chapter_manifest = cache_root / "manifests" / "render_v1.json"
        assert not chapter_manifest.exists()

    def test_chapter_cache_path_byte_identical_when_off(self, tmp_path):
        """render_chapter (the OFF/default path) ignores the utterance cache.

        Running the historical render_chapter() must produce its single WAV via
        one whole-chapter synthesize() call, regardless of any utterance cache
        on disk — proving the default path is unaffected by FT-RENDER-P-004.
        """
        from audiobooker.renderer.engine import render_chapter

        engine = FakeTTSEngine()
        chapter = _make_chapter()
        out = tmp_path / "default.wav"
        render_chapter(chapter, _make_casting(), out, engine=engine)

        # The historical path makes exactly ONE synthesize call for the whole
        # chapter (not one per utterance).
        assert len(engine.calls) == 1
        assert out.exists()

    def test_old_utterance_manifest_future_version_ignored(self, tmp_path):
        """A future-version utterance manifest is ignored, not mis-read."""
        from audiobooker.renderer.cache_manifest import (
            UtteranceCacheManifest,
            load_utterance_manifest,
            save_utterance_manifest,
            get_utterance_manifest_path,
        )
        cache_root = tmp_path / "cache"
        upath = get_utterance_manifest_path(cache_root, 0)
        upath.parent.mkdir(parents=True, exist_ok=True)
        m = UtteranceCacheManifest(version=999)
        save_utterance_manifest(m, upath)
        assert load_utterance_manifest(upath) is None

    def test_single_utterance_chapter_stitches_via_copy(self, tmp_path):
        """A one-utterance chapter is copied (no concat) and still produces a WAV."""
        chapter = Chapter(index=0, title="Solo", raw_text="x")
        chapter.utterances = [
            Utterance(speaker="narrator", text="Only one line.",
                      utterance_type=UtteranceType.NARRATION),
        ]
        runner = _StitchRunner()
        out = tmp_path / "solo.wav"
        result = render_chapter_incremental(
            chapter, _make_casting(), out,
            engine=FakeTTSEngine(), cache_root=tmp_path / "cache",
            render_params_hash="paramhash", runner=runner,
        )
        assert result.utterances_total == 1
        assert out.exists()
        # No ffmpeg concat needed for a single utterance (copy path).
        assert runner.calls == []


class TestUtteranceHash:
    """hash_utils.utterance_hash — FT-RENDER-P-004 keying."""

    def test_same_utterance_same_hash(self):
        from audiobooker.renderer.hash_utils import utterance_hash
        u = Utterance(speaker="Alice", text="Hi", emotion="happy")
        h1 = utterance_hash(u, "af_bella", "params")
        h2 = utterance_hash(u, "af_bella", "params")
        assert h1 == h2

    def test_text_change_changes_hash(self):
        from audiobooker.renderer.hash_utils import utterance_hash
        u1 = Utterance(speaker="Alice", text="Hi")
        u2 = Utterance(speaker="Alice", text="Bye")
        assert utterance_hash(u1, "af_bella", "p") != utterance_hash(u2, "af_bella", "p")

    def test_voice_change_changes_hash(self):
        from audiobooker.renderer.hash_utils import utterance_hash
        u = Utterance(speaker="Alice", text="Hi")
        assert utterance_hash(u, "af_bella", "p") != utterance_hash(u, "bm_george", "p")

    def test_intensity_distinguished_from_none(self):
        from audiobooker.renderer.hash_utils import utterance_hash
        bare = Utterance(speaker="Alice", text="Hi", emotion="happy")
        graded = Utterance(speaker="Alice", text="Hi", emotion="happy", intensity=0.0)
        assert utterance_hash(bare, "v", "p") != utterance_hash(graded, "v", "p")


# ---------------------------------------------------------------------------
# COORD-B-002: utterance cache vs. Windows MAX_PATH
# ---------------------------------------------------------------------------
#
# The per-utterance cache filename embeds a full 64-character SHA-256 hex
# digest (``utt_<64 hex>.wav``, longer still as the ``.tmp`` scratch name
# used during synthesis), which on a sufficiently long project directory
# pushes the write past Windows' 260-character MAX_PATH. The write then
# fails with an ordinary ``FileNotFoundError: [Errno 2]``, which the old
# code reported as "failed to synthesize" -- blaming the TTS engine for a
# filesystem problem.
#
# These tests construct the overflow deterministically by padding a
# directory to a *computed* target length (via `_grow_dir`), never by
# assuming anything about how long pytest's own tmp_path/--basetemp happens
# to be on this host.

WINDOWS_MAX_PATH = 260


def _utterance_and_hash(text: str = "Only one line.") -> tuple[Utterance, str]:
    from audiobooker.renderer.hash_utils import utterance_hash as _utterance_hash
    utt = Utterance(speaker="narrator", text=text, utterance_type=UtteranceType.NARRATION)
    uhash = _utterance_hash(utt, "af_heart", "paramhash")
    return utt, uhash


def _fixed_suffix_len() -> int:
    """Chars added between a project dir and its utterance-cache directory.

    Measured from the real cache-layout functions (not hardcoded) so this
    stays correct if the directory layout ever changes.
    """
    from audiobooker.renderer.cache_manifest import get_cache_root, get_utterance_wav_dir
    probe_root = "C:/probe"
    probe_dir = get_utterance_wav_dir(get_cache_root(Path(probe_root)), 0)
    return len(str(probe_dir)) - len(probe_root)


class TestUtteranceCachePathLength:
    """COORD-B-002 (wave 5, MEDIUM): utterance cache path budget + diagnosis.

    Windows-only: MAX_PATH is a Windows concept, so these skip on other
    platforms rather than fake an OS behavior that wouldn't be real there.
    """

    # mkdir(parents=True) for the utterance directory happens BEFORE any
    # per-utterance filename is added, and is a separate (unhandled) call
    # site from the one this finding is about. Both tests below must keep
    # the DIRECTORY comfortably under MAX_PATH on its own -- only directory
    # + leaf filename may cross the line -- or they'd exercise the wrong
    # code path (a raw mkdir() OSError, never reaching engine.synthesize()).
    _MKDIR_SAFETY_MARGIN = 20   # utt_dir stays this far under MAX_PATH
    _FIT_MARGIN = 10            # post-fix dir+leaf stays this far under it

    def test_reclaiming_filename_budget_fixes_a_realistic_overflow(self, tmp_path):
        """A project dir long enough to overflow the OLD 64-hex filename
        scheme must render successfully once the filename is shortened --
        proving the reclaimed budget covers the realistic case the finding
        described (e.g. a synced OneDrive path + nested series folder).
        """
        if os.name != "nt":
            pytest.skip("Windows MAX_PATH overflow is platform-specific")

        utt, uhash = _utterance_and_hash()
        old_leaf = f"utt_{uhash}.wav"
        new_leaf = f"utt_{uhash[:16]}.wav"
        old_tmp_len = len(engine_mod._chapter_tmp_path(Path(old_leaf)).name)
        new_tmp_len = len(engine_mod._chapter_tmp_path(Path(new_leaf)).name)
        suffix_len = _fixed_suffix_len()

        # The fix must free up more headroom than our fit margin, or the
        # window below is empty -- this is a harness sanity check, not the
        # thing under test (fails loudly here rather than picking a bogus
        # target and failing confusingly later).
        assert old_tmp_len - new_tmp_len > self._FIT_MARGIN, (
            "harness bug: shortening the hash doesn't reclaim enough budget "
            "for this test's margins to make sense"
        )

        # Target utt_dir length: the largest value that still leaves the NEW
        # (post-fix) leaf fitting under MAX_PATH with _FIT_MARGIN to spare.
        # Because old_tmp_len > new_tmp_len by more than _FIT_MARGIN (just
        # asserted above), this same target is guaranteed to overflow the
        # OLD leaf -- i.e. RED before the fix, GREEN after.
        dir_target = WINDOWS_MAX_PATH - new_tmp_len - 1 - self._FIT_MARGIN
        project_dir = _grow_dir(tmp_path, max(dir_target - suffix_len, len(str(tmp_path)) + 1))

        from audiobooker.renderer.cache_manifest import get_cache_root, get_utterance_wav_dir
        cache_root = get_cache_root(project_dir)
        utt_dir = get_utterance_wav_dir(cache_root, 0)
        dir_len = len(str(utt_dir))
        assert dir_len <= WINDOWS_MAX_PATH - self._MKDIR_SAFETY_MARGIN, (
            "harness bug: the directory chain alone is too close to MAX_PATH "
            "-- mkdir() itself would fail, which is a different code path"
        )
        assert dir_len + 1 + old_tmp_len > WINDOWS_MAX_PATH, (
            "harness bug: chosen project_dir doesn't actually overflow the "
            "pre-fix (64-hex) filename scheme"
        )
        assert dir_len + 1 + new_tmp_len <= WINDOWS_MAX_PATH, (
            "harness bug: chosen project_dir still overflows even the "
            "shortened (16-hex) filename scheme -- tighten the margins"
        )

        chapter = Chapter(index=0, title="Solo", raw_text="x")
        chapter.utterances = [utt]
        out = project_dir / "chapter_0000.wav"

        # RED (pre-fix): this raises RenderError("...failed to synthesize:
        # [Errno 2] No such file or directory: ...") because the 64-hex
        # filename overflows MAX_PATH. GREEN (post-fix): the shortened
        # filename fits, so this completes normally.
        result = render_chapter_incremental(
            chapter, _make_casting(), out,
            engine=FakeTTSEngine(),
            cache_root=cache_root,
            render_params_hash="paramhash",
            runner=_StitchRunner(),
        )
        assert result.utterances_synthesized == 1
        assert out.exists()

    def test_directory_chain_overflow_is_structured_not_a_raw_oserror(
        self, tmp_path
    ):
        """The cache DIRECTORY chain can overflow before any filename exists.

        One level deeper than COORD-B-002. That finding was about the leaf
        filename and the try/except around engine.synthesize(); this is the
        `utt_dir.mkdir(parents=True)` call that runs first, and it was the
        only failure path in render_chapter_incremental that did not produce
        a structured RenderError.

        RED before the fix: a raw FileNotFoundError/OSError propagates, with
        no code, no hint, and nothing pointing at path length — the caller
        gets a bare stack trace where every other failure here is actionable.
        """
        if os.name != "nt":
            pytest.skip("Windows MAX_PATH overflow is platform-specific")

        from audiobooker.renderer.cache_manifest import (
            get_cache_root,
            get_utterance_wav_dir,
        )
        from audiobooker.renderer.engine import RenderError

        utt, _ = _utterance_and_hash()
        suffix_len = _fixed_suffix_len()

        # Overflow the DIRECTORY itself, not the leaf: aim utt_dir past
        # MAX_PATH while keeping project_dir comfortably creatable.
        dir_target = WINDOWS_MAX_PATH + 12
        project_dir = _grow_dir(
            tmp_path, max(dir_target - suffix_len, len(str(tmp_path)) + 1)
        )
        assert len(str(project_dir)) < WINDOWS_MAX_PATH, (
            "harness bug: project_dir itself is uncreatable, so the test "
            "would fail in _grow_dir rather than in the code under test"
        )

        cache_root = get_cache_root(project_dir)
        utt_dir = get_utterance_wav_dir(cache_root, 0)
        assert len(str(utt_dir)) > WINDOWS_MAX_PATH, (
            "harness bug: the directory chain does not actually overflow, "
            "so mkdir() would succeed and this tests nothing"
        )

        chapter = Chapter(index=0, title="Solo", raw_text="x")
        chapter.utterances = [utt]

        with pytest.raises(RenderError) as excinfo:
            render_chapter_incremental(
                chapter, _make_casting(), project_dir / "chapter_0000.wav",
                engine=FakeTTSEngine(),
                cache_root=cache_root,
                render_params_hash="paramhash",
                runner=_StitchRunner(),
            )

        err = excinfo.value
        assert err.code == "CACHE_PATH_TOO_LONG"
        # Hedged, never asserted as certain — path length is a heuristic.
        assert "likely" in str(err).lower()
        # And it must NOT blame synthesis: nothing was ever synthesized.
        assert "failed to synthesize" not in str(err).lower()

    def test_diagnosis_names_path_length_when_still_too_long(self, tmp_path):
        """Even after reclaiming budget, a pathological project dir can still
        overflow. When it does, the error must name the real cause (a
        Windows path-length problem) instead of blaming the TTS engine.
        """
        if os.name != "nt":
            pytest.skip("Windows MAX_PATH overflow is platform-specific")

        from audiobooker.renderer.engine import RenderError

        utt, uhash = _utterance_and_hash()
        # Compute how long the tmp name would be under the shortened (16-hex)
        # scheme this fix introduces, WITHOUT depending on the fix existing
        # yet -- _chapter_tmp_path only touches the leaf, so this is exact
        # regardless of whether the source has been patched.
        new_leaf = f"utt_{uhash[:16]}.wav"
        new_tmp_len = len(engine_mod._chapter_tmp_path(Path(new_leaf)).name)
        suffix_len = _fixed_suffix_len()

        # Target utt_dir length: as close to MAX_PATH as the mkdir safety
        # margin allows, which is still well past the point where even the
        # NEW, shorter leaf overflows -- this case is not fixable by
        # reclaiming filename budget alone.
        dir_target = WINDOWS_MAX_PATH - self._MKDIR_SAFETY_MARGIN
        project_dir = _grow_dir(tmp_path, max(dir_target - suffix_len, len(str(tmp_path)) + 1))

        from audiobooker.renderer.cache_manifest import get_cache_root, get_utterance_wav_dir
        cache_root = get_cache_root(project_dir)
        utt_dir = get_utterance_wav_dir(cache_root, 0)
        dir_len = len(str(utt_dir))
        assert dir_len <= WINDOWS_MAX_PATH - self._MKDIR_SAFETY_MARGIN + 1, (
            "harness bug: the directory chain alone is too close to MAX_PATH "
            "-- mkdir() itself would fail, which is a different code path"
        )
        assert dir_len + 1 + new_tmp_len > WINDOWS_MAX_PATH, (
            "harness bug: chosen project_dir doesn't overflow even the "
            "shortened (16-hex) filename scheme"
        )

        chapter = Chapter(index=0, title="Solo", raw_text="x")
        chapter.utterances = [utt]
        out = project_dir / "chapter_0000.wav"

        with pytest.raises(RenderError) as exc_info:
            render_chapter_incremental(
                chapter, _make_casting(), out,
                engine=FakeTTSEngine(),
                cache_root=cache_root,
                render_params_hash="paramhash",
                runner=_StitchRunner(),
            )

        err = exc_info.value
        # RED (pre-fix): message says "failed to synthesize" -- the wrong
        # cause, pointing at the TTS engine instead of the filesystem.
        # GREEN (post-fix): a distinct code + a message naming path length.
        assert "failed to synthesize" not in str(err), (
            "the TTS engine did not fail -- the cache write did; the message "
            "must not blame synthesis"
        )
        assert err.code == "CACHE_PATH_TOO_LONG"
        assert "path" in str(err).lower()

    def test_short_path_engine_failure_still_blames_synthesis(self, tmp_path):
        """An ordinary (short-path) engine failure must keep the original
        "failed to synthesize" message -- the new path-length diagnosis must
        not fire on, or swallow, an unrelated failure. Cross-platform: this
        does not depend on any OS path-length behavior.
        """
        from audiobooker.renderer.engine import RenderError

        chapter = _make_chapter()
        cache_root = tmp_path / "cache"
        out = tmp_path / "chapter_0000.wav"

        with pytest.raises(RenderError) as exc_info:
            render_chapter_incremental(
                chapter, _make_casting(), out,
                engine=FakeTTSEngine(fail_on_call=0, fail_error="voice model missing"),
                cache_root=cache_root,
                render_params_hash="paramhash",
                runner=_StitchRunner(),
            )

        err = exc_info.value
        assert "failed to synthesize" in str(err)
        assert "voice model missing" in str(err)
        assert err.code == "RUNTIME_RENDER"

    def test_old_style_full_hash_filename_still_resolves(self, tmp_path):
        """An utterance cached under the OLD (pre-fix) full-64-hex filename
        must still be found and reused after the filename is shortened.

        The manifest stores a concrete `wav_path` per entry (cache_manifest.
        UtteranceCacheEntry) -- `is_valid()` stats exactly that path, it
        never recomputes a filename from the hash -- so an existing cache
        keeps resolving its old (longer) filenames untouched; only NEW
        utterances synthesized from here on get the shorter name. This is
        the empirical proof behind that claim, not just a reading of the
        code: it writes a manifest + WAV in the pre-fix shape by hand and
        confirms the current code reuses it without re-synthesizing.
        """
        from audiobooker.renderer.cache_manifest import (
            UtteranceCacheEntry, UtteranceCacheManifest,
            get_utterance_wav_dir, get_utterance_manifest_path,
            save_utterance_manifest,
        )

        utt, uhash = _utterance_and_hash()
        cache_root = tmp_path / "cache"
        utt_dir = get_utterance_wav_dir(cache_root, 0)
        utt_dir.mkdir(parents=True, exist_ok=True)

        # Simulate a WAV cached by the OLD (pre-fix) full-hash filename.
        old_style_wav = utt_dir / f"utt_{uhash}.wav"
        write_silence_wav(old_style_wav, 0.3)

        manifest_path = get_utterance_manifest_path(cache_root, 0)
        manifest = UtteranceCacheManifest()
        manifest.set_entry(UtteranceCacheEntry(
            utterance_hash=uhash, wav_path=str(old_style_wav), duration_s=0.3,
        ))
        save_utterance_manifest(manifest, manifest_path)

        chapter = Chapter(index=0, title="Solo", raw_text="x")
        chapter.utterances = [utt]

        engine = FakeTTSEngine()
        result = render_chapter_incremental(
            chapter, _make_casting(), tmp_path / "chapter_0000.wav",
            engine=engine,
            cache_root=cache_root,
            render_params_hash="paramhash",
            runner=_StitchRunner(),
        )

        assert result.utterances_reused == 1
        assert result.utterances_synthesized == 0
        assert len(engine.calls) == 0
        # The old-style file is what got reused -- left untouched, not
        # replaced by a new short-name file.
        assert old_style_wav.exists()
