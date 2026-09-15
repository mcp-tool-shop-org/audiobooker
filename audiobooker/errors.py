"""
Structured error types for Audiobooker.

Every user-facing error carries the shipcheck-mandated shape:
  code, message, hint, cause, retryable
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ErrorDetail:
    """Structured error detail attached to every AudiobookerError."""

    code: str
    message: str
    hint: str
    cause: Optional[str] = None
    retryable: bool = False


class AudiobookerError(Exception):
    """Base error with structured detail."""

    def __init__(self, detail: ErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.message)

    @property
    def code(self) -> str:
        return self.detail.code

    @property
    def hint(self) -> str:
        return self.detail.hint

    @property
    def cause(self) -> Optional[str]:
        return self.detail.cause

    @property
    def retryable(self) -> bool:
        return self.detail.retryable

    def structured(self) -> dict:
        """Return the canonical error shape as a dict."""
        d: dict = {
            "code": self.detail.code,
            "message": self.detail.message,
            "hint": self.detail.hint,
            "retryable": self.detail.retryable,
        }
        if self.detail.cause:
            d["cause"] = self.detail.cause
        return d


class ConfigValidationError(AudiobookerError, ValueError):
    """A configuration value failed type/range validation.

    Subclasses BOTH ``AudiobookerError`` (structured ``code``/``message``/
    ``hint``/``retryable``, catchable via ``except AudiobookerError``) and
    ``ValueError`` (so existing callers/tests using ``except ValueError``
    keep working unchanged -- every ProjectConfig/config-file validation
    error historically raised a plain ``ValueError``, and this class's
    __str__/args are identical to what a plain ``ValueError(message)`` would
    have produced).

    Wired up in ``models.ProjectConfig.__post_init__`` (the numeric/type
    field checks added in wave 2, F-CORE-2) and in
    ``config_file.ConfigFileError`` (a thin subclass used for TOML-sourced
    values; see that module for why it defines its own name instead of
    raising this class directly at call sites).

    Wave-2 note (F-CORE-5): ``audiobooker.errors`` was entirely unreferenced
    before that fix -- zero imports, zero instantiations anywhere in the
    repo -- despite SHIP_GATE.md's Gate B citing "AudiobookerError base with
    .structured()" as evidence.

    Wave-3 residual 5 completed the migration: ``RenderError``
    (``renderer/engine.py``), ``PresetError`` (``casting/presets.py``) and
    ``VoiceNotFoundError`` (``casting/voice_registry.py``) -- the other three
    names Gate B cites -- now inherit ``AudiobookerError`` too, each keeping
    its historical base class in the MRO so every existing
    ``except RuntimeError`` / ``except ValueError`` / ``except Exception``
    call site still catches them, and each with ``str(exc)`` byte-identical
    to before.
    """

    def __init__(
        self,
        message: str,
        *,
        hint: str = (
            "Check the value against the field's documented type/range "
            "and fix it at its source."
        ),
        code: str = "CONFIG_INVALID_VALUE",
        cause: Optional[str] = None,
    ) -> None:
        detail = ErrorDetail(
            code=code,
            message=message,
            hint=hint,
            cause=cause,
            retryable=False,
        )
        AudiobookerError.__init__(self, detail)

class CompilationFailedError(AudiobookerError, RuntimeError):
    """Every chapter in the book failed to compile (CH-B-002).

    Carries the shipcheck error shape (``code`` / ``message`` / ``hint`` /
    ``retryable``) like the rest of ``audiobooker.errors``. It subclasses
    ``RuntimeError`` so that ``except Exception`` call sites -- including
    ``cli.main()``'s catch-all, which routes it through ``_report_error`` and
    exits 2 -- keep working untouched.

    Subclassing ``RuntimeError`` keeps every existing ``except Exception``
    call site working untouched; ``cli.USER_ERROR_TYPES`` lists it explicitly
    so a total compile failure exits 1 (the user's book did not compile) and
    not 2 (audiobooker hit a bug).
    """

    def __init__(self, summary: str, *, chapter_count: int) -> None:
        AudiobookerError.__init__(
            self,
            ErrorDetail(
                code="COMPILE_ALL_CHAPTERS_FAILED",
                message=(
                    f"All {chapter_count} chapter(s) failed to compile, so the "
                    f"project has no utterances to render: {summary}"
                ),
                hint=(
                    "The failures above are per chapter — one shared cause is "
                    "likely. Check that the source text parsed (audiobooker "
                    "chapters), that --lang matches the book, and re-run with "
                    "--debug for the full traceback."
                ),
                retryable=False,
            ),
        )
        self.chapter_count = chapter_count


class ProjectSaveLockError(AudiobookerError, ValueError):
    """save() timed out on the occupancy lock — refuse rather than clobber.

    Fail-closed (Lock B1): a 5s wait that never acquired the exclusive lock
    must not write. Last-writer-wins after a timeout is the race the lock
    exists to prevent. Subclasses ``ValueError`` so ``cli.USER_ERROR_TYPES``
    reports it as a user error with the structured payload, not an unexpected
    exit 2.
    """

    def __init__(self, lock_path: str, *, cause: Optional[str] = None) -> None:
        AudiobookerError.__init__(
            self,
            ErrorDetail(
                code="PROJECT_SAVE_LOCK_TIMEOUT",
                message=(
                    f"You asked to save the project; I refused because another "
                    f"save still holds {lock_path} after 5s. Writing anyway "
                    f"would clobber concurrent edits (last-writer-wins)."
                ),
                hint=(
                    "Retry in a moment. If the other process died, delete the "
                    f"stale lock file {lock_path} and save again."
                ),
                cause=cause,
                retryable=True,
            ),
        )
        self.lock_path = lock_path


class PronunciationProtectedError(AudiobookerError, ValueError):
    """A pronunciation override names a cast character and must not be stored.

    Stored-then-refused leftovers rewrite the name on uncast and un-attribute
    every line. Refuse before mutating ``pronunciation_overrides``.
    """

    def __init__(self, word: str) -> None:
        AudiobookerError.__init__(
            self,
            ErrorDetail(
                code="PRONUNCIATION_PROTECTED_NAME",
                message=(
                    f"You asked to add a pronunciation override for {word!r}; "
                    f"I refused because {word!r} is a cast character (or alias) "
                    f"and rewriting it would un-attribute every line they speak."
                ),
                hint=(
                    "Set the pronunciation on the character instead, or uncast "
                    f"{word!r} before adding a prose override."
                ),
                retryable=False,
            ),
        )
        self.word = word
