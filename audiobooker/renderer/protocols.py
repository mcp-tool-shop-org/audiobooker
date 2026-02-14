"""
Renderer protocols — lightweight interfaces for TTS and FFmpeg.

These allow the render pipeline to be tested without real
voice-soundboard or FFmpeg installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable


@dataclass
class SynthesisResult:
    """Result of synthesizing a chapter to audio."""
    audio_path: Path
    duration_seconds: float
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class TTSEngine(Protocol):
    """Interface for text-to-speech synthesis."""

    def synthesize(
        self,
        script: str,
        voices: dict[str, str],
        output_path: Path,
        progress_callback: Optional[Callable] = None,
    ) -> SynthesisResult: ...


@dataclass
class RunResult:
    """Result of running an external command."""
    returncode: int
    stdout: str = ""
    stderr: str = ""


@runtime_checkable
class FFmpegRunner(Protocol):
    """Interface for running FFmpeg commands."""

    def run(self, args: list[str]) -> RunResult: ...
