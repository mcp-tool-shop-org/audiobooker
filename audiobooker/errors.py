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
    before this fix -- zero imports, zero instantiations anywhere in the
    repo -- despite SHIP_GATE.md's Gate B citing "AudiobookerError base with
    .structured()" as evidence. This class (plus ``config_file.ConfigFileError``,
    which also inherits ``AudiobookerError`` through this class) is what makes
    that citation true for the paths this wave's fixes touch. ``RenderError``,
    ``PresetError``, and ``VoiceNotFoundError`` live in
    ``renderer/engine.py``, ``casting/presets.py``, and
    ``casting/voice_registry.py`` -- outside this domain's owned globs this
    wave -- so they were NOT migrated to inherit ``AudiobookerError`` here;
    see this wave's ``skipped[]`` entry for that decision.
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
