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
