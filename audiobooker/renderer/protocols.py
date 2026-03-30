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

    # F-RENDER-B-012: Optional capabilities discovery
    def capabilities(self) -> dict[str, bool]:
        """Return engine capabilities (optional — defaults provided).

        Known keys:
            streaming: Whether the engine supports streaming synthesis.
            emotions: Whether the engine supports emotion tags.
            ssml: Whether the engine supports SSML input.
            multi_speaker: Whether the engine supports multiple speakers.
        """
        return {
            "streaming": False,
            "emotions": False,
            "ssml": False,
            "multi_speaker": False,
        }


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


# F-RENDER-B-016: Formal AssemblerProtocol
@runtime_checkable
class AssemblerProtocol(Protocol):
    """Interface for audio assembly (chapter WAVs -> final audiobook)."""

    def __call__(
        self,
        chapter_files: list[tuple[Path, str, float]],
        output_path: Path,
        title: str = "Audiobook",
        author: str = "",
        chapter_pause_ms: int = 2000,
    ) -> "AssemblyResult": ...  # noqa: F821 — forward ref to output.AssemblyResult
