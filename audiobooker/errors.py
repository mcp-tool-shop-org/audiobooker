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
