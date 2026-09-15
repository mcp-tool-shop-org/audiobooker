"""
FakeTTSEngine — writes deterministic minimal WAV files for testing.

No external dependencies. Produces valid RIFF/WAVE headers.

C2 (F-fb583507 / F-4e8c1a92): the stock fake used to write byte-identical
PCM silence for every synthesize() call. Tests that compared chapter WAV
bytes, baked-in pauses, SSML emphasis, or "wrong audio served as Cached"
then passed against the bug they existed to catch. Duration and a few PCM
samples are now derived from a stable digest of script+voices (zlib.crc32,
not hash() — str hashing is salted per process). SSML <break> tags add
their declared time so a pause baked into a per-utterance script makes
that WAV grow.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from dataclasses import dataclass
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

# SSML <break time="750ms"/> / <break time="1s"/>. FakeTTS used to ignore
# markup entirely, so baking a pause into the script still wrote 0.25s of
# silence and test_a_cached_utterance_wav_holds_no_pause stayed green.
_BREAK_RE = re.compile(
    r"""<break\s+[^>]*time=["'](\d+(?:\.\d+)?)(m?s)["'][^>]*/?>""",
    re.IGNORECASE,
)


def _stable_digest(script: str, voices: Optional[dict] = None) -> int:
    """Process-stable digest of script+voices (not PYTHONHASHSEED-salted)."""
    payload = script + "\0" + json.dumps(voices or {}, sort_keys=True, ensure_ascii=False)
    return zlib.crc32(payload.encode("utf-8")) & 0xFFFFFFFF


def _ssml_break_seconds(script: str) -> float:
    total = 0.0
    for mag, unit in _BREAK_RE.findall(script):
        val = float(mag)
        total += val / 1000.0 if unit.lower() == "ms" else val
    return total


def write_silence_wav(
    path: Path,
    duration_s: float = DURATION_PER_CALL,
    sample_rate: int = SAMPLE_RATE,
    marker: int = 0,
) -> None:
    """Write a minimal valid WAV file (mono 16-bit PCM).

    ``marker`` stamps a few non-zero samples so two equal-duration clips
    are not byte-identical. marker=0 is genuine silence (the historical
    helper, kept for tests that want a known-quiet file).
    """
    num_samples = max(1, int(sample_rate * duration_s))
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample
    path.parent.mkdir(parents=True, exist_ok=True)

    pcm = bytearray(data_size)
    if marker:
        n = min(16, num_samples)
        seed = marker & 0xFFFFFFFF
        for i in range(n):
            seed = (seed * 1664525 + 1013904223 + i) & 0xFFFFFFFF
            sample = (seed % 32767) + 1  # never zero
            if seed & 1:
                sample = -sample
            struct.pack_into("<h", pcm, i * 2, sample)

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
        f.write(pcm)


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

    - Writes a valid WAV whose duration and a few PCM samples come from a
      stable digest of script+voices (plus any SSML <break> times).
    - Records calls for assertion.
    - Optionally raises on a specific call index.

    Passing a non-default ``duration_per_call`` locks the speech duration
    (breaks still add); the default path varies like the old _DistinctEngine
    so two chapters cannot be byte-identical silence.
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

    @staticmethod
    def strip_breaks(script: str) -> str:
        return _BREAK_RE.sub("", script)

    @staticmethod
    def pcm_marker(script: str, voices: Optional[dict] = None) -> int:
        return _stable_digest(script, voices)

    @staticmethod
    def duration_for(
        script: str,
        voices: Optional[dict] = None,
        *,
        duration_per_call: float = DURATION_PER_CALL,
    ) -> float:
        """Speech duration this engine would write for ``script``.

        Default ``duration_per_call`` varies by digest (0.10–0.46s), matching
        the former _DistinctEngine. A caller-pinned duration is honored as
        the speech floor; SSML <break> times are always added on top.
        """
        if duration_per_call == DURATION_PER_CALL:
            digest = _stable_digest(script, voices)
            speech = 0.10 + (digest % 37) / 100.0
        else:
            speech = float(duration_per_call)
        return speech + _ssml_break_seconds(script)

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
        duration = self.duration_for(
            script, voices, duration_per_call=self.duration_per_call
        )
        write_silence_wav(
            output_path, duration, marker=self.pcm_marker(script, voices)
        )

        return SynthesisResult(
            audio_path=output_path,
            duration_seconds=duration,
        )
