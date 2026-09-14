"""
FFmpeg runner — wraps subprocess calls for mockability and logging.
"""

from __future__ import annotations

import logging
import subprocess

from audiobooker.renderer.protocols import RunResult

logger = logging.getLogger("audiobooker.ffmpeg")

# ffmpeg writes UTF-8 on stderr — it echoes back input paths, metadata values
# and chapter titles verbatim. Decoding those bytes with the process's locale
# codepage (what text=True does when no encoding is given) is a real crash on
# Windows: cp1252 has *undefined* bytes at 0x81/0x8D/0x8F/0x90/0x9D, and the
# UTF-8 encoding of ordinary CJK text is full of them. The decode blows up
# inside subprocess's reader thread, which does not re-raise — proc.stderr just
# arrives as None, and the next .strip() dies with AttributeError after a
# multi-hour render. Pin the encoding, and never let a mangled byte abort a
# render: errors='replace' degrades a log line, a raise loses the book.
_TEXT_KWARGS = {
    "capture_output": True,
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
}


def _as_text(value: object) -> str:
    """Coerce a captured stream to the ``str`` RunResult declares.

    RunResult.stdout/stderr are annotated ``str`` and every consumer calls
    .strip() on them (output.py, engine.py). A None here would violate that
    contract identically in all of them.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class RealFFmpegRunner:
    """Runs FFmpeg via subprocess. Default in production."""

    def run(self, args: list[str]) -> RunResult:
        """Run a subprocess command.

        Args:
            args: Full command-line argument list. The first element must be
                the executable name/path (e.g. ``["ffmpeg", "-y", ...]``).
        """
        logger.debug(f"ffmpeg {' '.join(args)}")
        try:
            proc = subprocess.run(args, **_TEXT_KWARGS)
            stdout = _as_text(getattr(proc, "stdout", ""))
            stderr = _as_text(getattr(proc, "stderr", ""))
            # F-RENDER-B-010: Log warning on non-zero returncode
            if proc.returncode != 0:
                logger.warning(
                    f"ffmpeg exited with rc={proc.returncode}: "
                    f"{stderr.strip()[:300]}"
                )
            return RunResult(
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except FileNotFoundError:
            return RunResult(
                returncode=-1,
                stderr="ffmpeg not found on PATH",
            )
        except OSError as e:
            # A non-executable binary, a bad interpreter line, a permission
            # denial or a too-long argument list raise sibling OSErrors rather
            # than FileNotFoundError. All of them mean "could not run ffmpeg",
            # and all of them must return the structured RunResult rather than
            # escaping into assembly code that has no handler for them.
            logger.warning(f"ffmpeg could not be executed: {e}")
            return RunResult(
                returncode=-1,
                stderr=f"ffmpeg could not be executed (not found or not runnable): {e}",
            )

    def available(self) -> bool:
        result = self.run(["ffmpeg", "-version"])
        return result.returncode == 0
