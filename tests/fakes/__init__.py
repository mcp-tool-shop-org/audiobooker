"""Test fakes for audiobooker renderer tests."""

from tests.fakes.fake_tts import FakeTTSEngine
from tests.fakes.fake_ffmpeg import FakeFFmpegRunner, FakeAssembler

__all__ = ["FakeTTSEngine", "FakeFFmpegRunner", "FakeAssembler"]
