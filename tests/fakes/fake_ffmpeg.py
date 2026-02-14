"""
FakeFFmpegRunner + FakeAssembler — test doubles for output assembly.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from audiobooker.renderer.output import AssemblyResult
from audiobooker.renderer.protocols import RunResult


@dataclass
class FFmpegCall:
    """Record of an ffmpeg call."""
    args: list[str]


class FakeFFmpegRunner:
    """Records calls, returns configurable results."""

    def __init__(self, fail_on_call: int = -1) -> None:
        self.calls: list[FFmpegCall] = []
        self.fail_on_call = fail_on_call

    def run(self, args: list[str]) -> RunResult:
        call_index = len(self.calls)
        self.calls.append(FFmpegCall(args=args))

        if call_index == self.fail_on_call:
            return RunResult(returncode=1, stderr="fake ffmpeg error")

        return RunResult(returncode=0, stdout="", stderr="")

    def available(self) -> bool:
        return True


class FakeAssembler:
    """
    Stand-in for assemble_m4b that copies the first chapter WAV
    to the output path and returns a success AssemblyResult.
    """

    def __init__(self, chapters_embedded: bool = True) -> None:
        self._chapters_embedded = chapters_embedded
        self.calls: list[dict] = []

    def __call__(
        self,
        chapter_files: list[tuple[Path, str, float]],
        output_path: Path,
        title: str = "Audiobook",
        author: str = "",
        chapter_pause_ms: int = 2000,
    ) -> AssemblyResult:
        self.calls.append({
            "chapter_files": chapter_files,
            "output_path": output_path,
            "title": title,
            "author": author,
            "chapter_pause_ms": chapter_pause_ms,
        })

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy first chapter file as the "assembled" output
        if chapter_files:
            src = chapter_files[0][0]
            if src.exists():
                shutil.copy(src, output_path)
            else:
                output_path.write_bytes(b"FAKE_M4B")
        else:
            output_path.write_bytes(b"FAKE_M4B")

        return AssemblyResult(
            output_path=output_path,
            chapters_embedded=self._chapters_embedded,
            chapter_error="" if self._chapters_embedded else "fake chapter error",
        )
