"""
FakeTTSEngine — writes deterministic minimal WAV files for testing.

No external dependencies. Produces valid RIFF/WAVE headers.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from audiobooker.renderer.protocols import SynthesisResult


@dataclass
class SynthCall:
    """Record of a synthesize() call for assertions."""
    script: str
    voices: dict[str, str]
    output_path: Path


SAMPLE_RATE = 24000
DURATION_PER_CALL = 0.25  # seconds


def write_silence_wav(path: Path, duration_s: float = DURATION_PER_CALL, sample_rate: int = SAMPLE_RATE) -> None:
    """Write a minimal valid WAV file (mono 16-bit PCM silence)."""
    num_samples = int(sample_rate * duration_s)
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))  # file size - 8
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))              # chunk size
        f.write(struct.pack("<H", 1))               # PCM format
        f.write(struct.pack("<H", 1))               # mono
        f.write(struct.pack("<I", sample_rate))      # sample rate
        f.write(struct.pack("<I", sample_rate * 2))  # byte rate
        f.write(struct.pack("<H", 2))               # block align
        f.write(struct.pack("<H", 16))              # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)                # silence


def assert_wav_header_valid(path: Path) -> None:
    """Validate RIFF/WAVE header. Raises AssertionError on invalid."""
    with open(path, "rb") as f:
        riff = f.read(4)
        assert riff == b"RIFF", f"Expected RIFF, got {riff!r}"
        _size = f.read(4)
        wave = f.read(4)
        assert wave == b"WAVE", f"Expected WAVE, got {wave!r}"
        fmt_id = f.read(4)
        assert fmt_id == b"fmt ", f"Expected 'fmt ', got {fmt_id!r}"


class FakeTTSEngine:
    """
    Deterministic TTS engine for tests.

    - Writes valid WAV silence to the requested output path.
    - Records calls for assertion.
    - Optionally raises on a specific call index.
    """

    def __init__(
        self,
        duration_per_call: float = DURATION_PER_CALL,
        fail_on_call: int = -1,
        fail_error: str = "Fake TTS failure",
    ) -> None:
        self.duration_per_call = duration_per_call
        self.fail_on_call = fail_on_call
        self.fail_error = fail_error
        self.calls: list[SynthCall] = []

    def synthesize(
        self,
        script: str,
        voices: dict[str, str],
        output_path: Path,
        progress_callback: Optional[Callable] = None,
    ) -> SynthesisResult:
        call_index = len(self.calls)
        self.calls.append(SynthCall(script=script, voices=voices, output_path=Path(output_path)))

        if call_index == self.fail_on_call:
            raise RuntimeError(self.fail_error)

        output_path = Path(output_path)
        write_silence_wav(output_path, self.duration_per_call)

        return SynthesisResult(
            audio_path=output_path,
            duration_seconds=self.duration_per_call,
        )
