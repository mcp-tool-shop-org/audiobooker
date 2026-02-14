"""
FFmpeg runner — wraps subprocess calls for mockability and logging.
"""

from __future__ import annotations

import logging
import subprocess

from audiobooker.renderer.protocols import RunResult

logger = logging.getLogger("audiobooker.ffmpeg")


class RealFFmpegRunner:
    """Runs FFmpeg via subprocess. Default in production."""

    def run(self, args: list[str]) -> RunResult:
        logger.debug(f"ffmpeg {' '.join(args)}")
        try:
            proc = subprocess.run(args, capture_output=True, text=True)
            return RunResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except FileNotFoundError:
            return RunResult(
                returncode=-1,
                stderr="ffmpeg not found on PATH",
            )

    def available(self) -> bool:
        result = self.run(["ffmpeg", "-version"])
        return result.returncode == 0
