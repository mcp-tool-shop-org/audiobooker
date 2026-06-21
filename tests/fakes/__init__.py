"""Test fakes for audiobooker renderer tests."""

from tests.fakes.fake_tts import FakeTTSEngine
from tests.fakes.fake_ffmpeg import FakeFFmpegRunner, FakeAssembler
from tests.fakes.fake_registry import FakeRegistry, make_fake_registry

__all__ = [
    "FakeTTSEngine",
    "FakeFFmpegRunner",
    "FakeAssembler",
    "FakeRegistry",
    "make_fake_registry",
]
