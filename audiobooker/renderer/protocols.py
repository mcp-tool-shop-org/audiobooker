"""
Renderer protocols — lightweight interfaces for TTS and FFmpeg.

These allow the render pipeline to be tested without real
voice-soundboard or FFmpeg installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from audiobooker.renderer.output import AssemblyResult


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
            thread_safe: Whether ``synthesize()`` may be entered by more than
                one thread at a time on the SAME instance. Defaults to False —
                see the thread-safety contract below.

        Thread-safety contract (RH-B-003)
        ---------------------------------
        ``audiobooker render --jobs N`` renders N chapters at once from a
        thread pool. It used to call ``synthesize()`` on ONE shared engine
        instance from all N workers with nothing written down about whether
        that was allowed. Almost every real TTS backend is stateful — a
        loaded torch/ONNX model, a session object, a single HTTP connection,
        a global voice register — so a third-party engine registered through
        the ``audiobooker.tts_engines`` entry point was entered concurrently
        by construction. The failure mode is not a clean exception; it is
        interleaved or cross-voiced audio in some chapters, which passes the
        size and duration checks and is only found on listen-back.

        So: ``thread_safe`` defaults to **False**, and the renderer serializes
        ``synthesize()`` behind a lock for any engine that does not explicitly
        advertise ``{"thread_safe": True}``. An engine opts in only when
        concurrent ``synthesize()`` calls on one instance are genuinely safe
        (re-entrant model state, per-call sessions, its own internal locking).
        Engines that do not implement ``capabilities()`` at all are treated as
        NOT thread-safe.
        """
        return {
            "streaming": False,
            "emotions": False,
            "ssml": False,
            "multi_speaker": False,
            # RH-B-003: opt-in, never assumed. See the contract above.
            "thread_safe": False,
        }

    # FT-ENGINE-001: Optional voice discovery. Engines MAY implement this to
    # advertise the voice IDs they support; callers MUST tolerate its absence
    # (the built-in voice-soundboard engine does not implement it and instead
    # falls back to voice_soundboard.config.VOICES — see voice_registry).
    #
    # Declared with a default body (rather than `...`) so this stays an OPTIONAL
    # member: a class that omits list_voices() entirely still satisfies the
    # Protocol, and runtime callers use hasattr()/getattr() to detect it.
    def list_voices(self) -> list[str]:  # pragma: no cover - optional protocol member
        """Return the voice IDs this engine supports (optional).

        Returns:
            A list of voice ID strings. Engines that do not implement voice
            discovery simply omit this method; callers fall back to the
            voice-soundboard catalog.
        """
        return []


@dataclass
class RunResult:
    """Result of running an external command."""
    returncode: int
    stdout: str = ""
    stderr: str = ""

    def __post_init__(self) -> None:
        """Enforce the declared ``str`` contract on both streams.

        Every consumer of this type calls ``.strip()`` on stdout/stderr. A
        runner that hands back None (subprocess does exactly that when a
        text-mode decode fails in its reader thread) would break all of them
        identically, so normalize at the boundary instead.
        """
        if self.stdout is None:
            self.stdout = ""
        if self.stderr is None:
            self.stderr = ""


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
    ) -> "AssemblyResult": ...
