"""
Voice registry — queries voice-soundboard for available voice IDs.

Provides a single abstraction point for voice availability checks,
making it easy to mock in tests.
"""

from __future__ import annotations

import importlib.util
import logging
import sys

logger = logging.getLogger("audiobooker.casting")

# The optional dependency that supplies the voice catalog. Kept as a constant so
# the "absent vs drifted" branch below compares against one spelling.
_VOICE_BACKEND_PACKAGE = "voice_soundboard"


class VoiceBackendError(ImportError):
    """
    Base for voice-backend import failures.

    Subclasses ImportError so every historical ``except ImportError`` caller
    keeps working, while callers that care can tell the two very different
    causes apart (and render the truth to the user).
    """

    code = "DEP_VOICE_BACKEND_ERROR"

    def __init__(self, message: str, *, module: str | None = None) -> None:
        super().__init__(message)
        self.module = module
        self.hint = "Run 'audiobooker voices' to see what the backend reports."
        self.retryable = False

    def structured(self) -> dict:
        """Return the canonical error shape as a dict."""
        return {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "module": self.module,
            "retryable": self.retryable,
        }


class VoiceBackendUnavailableError(VoiceBackendError):
    """voice-soundboard is genuinely absent — installing it is the fix."""

    code = "DEP_VOICE_BACKEND_MISSING"

    def __init__(
        self,
        message: str | None = None,
        *,
        module: str | None = "voice_soundboard",
    ) -> None:
        super().__init__(
            message or (
                "voice-soundboard is required for voice validation. "
                "Install with: pip install voice-soundboard"
            ),
            module=module,
        )
        self.hint = "pip install voice-soundboard"


class VoiceBackendIncompatibleError(VoiceBackendError):
    """
    voice-soundboard IS installed but does not expose what we import.

    GitHub issue #1: the reporter's traceback was a ModuleNotFoundError for the
    SUBMODULE ``voice_soundboard.config``.  ModuleNotFoundError subclasses
    ImportError, so the old handler caught an API/version-drift failure and told
    a user who already had the package to install it — advice that is a no-op,
    leaving them stuck.  This type exists so that never happens silently again.
    """

    code = "DEP_VOICE_BACKEND_INCOMPATIBLE"

    def __init__(
        self,
        message: str | None = None,
        *,
        module: str | None = None,
    ) -> None:
        super().__init__(
            message or (
                "voice-soundboard is installed but incompatible: "
                f"could not import {module or 'the expected module'}."
            ),
            module=module,
        )
        self.hint = (
            "voice-soundboard is present but its API has drifted. Check the "
            "installed version against this release's requirement — "
            "reinstalling the same version will not help."
        )


class VoiceNotFoundError(Exception):
    """Raised when one or more voice IDs are not available."""

    def __init__(
        self,
        missing: list[str],
        available_count: int,
    ) -> None:
        self.missing = missing
        self.available_count = available_count
        names = ", ".join(missing)
        msg = (
            f"Voice IDs not found: {names}\n"
            f"  {available_count} voices available. "
            f"Run 'audiobooker voices' to list them.\n"
            f"  To skip validation, set validate_voices_on_render=false in project config."
        )
        super().__init__(msg)
        # Structured error shape (code/message/hint/cause/retryable)
        self.code = "INPUT_VOICE_NOT_FOUND"
        self.hint = "Run 'audiobooker voices' to list available IDs, or set validate_voices_on_render=false."
        self.cause = None
        self.retryable = False

    def structured(self) -> dict:
        """Return the canonical error shape as a dict."""
        return {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "retryable": self.retryable,
        }


_UNSET = object()


def _voice_backend_installed() -> bool:
    """
    True when the top-level ``voice_soundboard`` package is actually present.

    ``ModuleNotFoundError.name`` alone is not enough to classify the failure: a
    submodule import can report the SUBMODULE's name whether or not the parent
    package exists. This asks the real question — is the package installed —
    which is what decides between "pip install it" and "your copy has drifted".
    """
    cached = sys.modules.get(_VOICE_BACKEND_PACKAGE, _UNSET)
    if cached is None:
        return False  # explicitly blocked (a test, or a failed earlier import)
    if cached is not _UNSET:
        return True
    try:
        return importlib.util.find_spec(_VOICE_BACKEND_PACKAGE) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def get_available_voices(engine: object | None = None) -> set[str]:
    """
    Query the active TTS engine (or voice-soundboard) for available voice IDs.

    FT-ENGINE-001: when ``engine`` exposes a ``list_voices()`` method, its
    result is used (a pluggable engine advertises its own catalog). Otherwise
    — including the default ``engine=None`` path and engines that don't
    implement ``list_voices()`` — this falls back to importing the
    voice-soundboard catalog, exactly as before.

    Args:
        engine: Optional TTS engine. When it has a ``list_voices()`` method,
            that method supplies the voice IDs. Defaults to None, which
            preserves the historical voice-soundboard import behavior.

    Returns:
        Set of available voice ID strings.

    Raises:
        ImportError: If no engine is given (or the engine lacks ``list_voices``)
            and voice-soundboard is not installed.
    """
    # FT-ENGINE-001: prefer an engine that advertises its own voices. Callers
    # must tolerate the method's absence, so probe with hasattr() rather than
    # assuming it exists on the Protocol.
    if engine is not None and hasattr(engine, "list_voices"):
        voices = engine.list_voices()
        # Engines return a list (voice_suggester protocol); normalize to a set
        # so downstream set algebra (validate_voices) keeps working unchanged.
        return set(voices)

    try:
        from voice_soundboard.config import VOICES
    except ModuleNotFoundError as exc:
        # Branch on WHICH module was missing. Only the top-level package being
        # absent means "not installed"; a missing submodule means the package is
        # there but does not look the way this release expects.
        missing = getattr(exc, "name", None) or ""
        if not missing or missing == _VOICE_BACKEND_PACKAGE or not _voice_backend_installed():
            raise VoiceBackendUnavailableError() from exc
        raise VoiceBackendIncompatibleError(
            "voice-soundboard is installed but incompatible with this release: "
            f"no module named {missing!r} (expected "
            f"'{_VOICE_BACKEND_PACKAGE}.config'). The installed version's API "
            "has drifted — check its version, do not reinstall the same one.",
            module=missing,
        ) from exc
    except ImportError as exc:
        # e.g. "cannot import name 'VOICES'" — the module exists, the symbol
        # does not. Same class of failure: installed but drifted.
        raise VoiceBackendIncompatibleError(
            "voice-soundboard is installed but incompatible with this release: "
            f"{exc}. The installed version's API has drifted.",
            module=f"{_VOICE_BACKEND_PACKAGE}.config",
        ) from exc

    return set(VOICES.keys())


def validate_voices(
    voice_ids: set[str],
    available: set[str] | None = None,
) -> list[str]:
    """
    Check which voice IDs are missing from the available set.

    Args:
        voice_ids: Voice IDs to validate.
        available: Available voices (queries registry if None).

    Returns:
        List of missing voice IDs (empty if all valid).
        Returns empty list with a WARNING when voice-soundboard is genuinely
        not installed — validation is skipped, loudly.

    Raises:
        VoiceBackendIncompatibleError: when voice-soundboard IS installed but
            its API has drifted. Returning [] there would report "all voice IDs
            valid" against a backend we could not read, which is a silent lie
            that lets a typo'd voice reach a long TTS run.
    """
    if available is None:
        try:
            available = get_available_voices()
        except VoiceBackendIncompatibleError as exc:
            # Fall back only for genuine absence. Drift is surfaced, naming the
            # module that actually failed.
            logger.warning(
                "Cannot validate voice IDs: voice-soundboard is installed but "
                "module %r could not be imported (%s). Not falling back — an "
                "unreadable catalog cannot certify any voice ID.",
                exc.module, exc,
            )
            raise
        except VoiceBackendUnavailableError:
            logger.warning(
                "voice-soundboard is not installed — skipping voice validation. "
                "Voice IDs will NOT be checked before rendering."
            )
            return []
        except ImportError as exc:  # pragma: no cover - defensive
            logger.warning(
                "voice-soundboard not importable (%s) — skipping voice validation", exc,
            )
            return []

    # Filter out empty/whitespace-only voice IDs and log affected characters
    empty_ids = {v for v in voice_ids if not v or not v.strip()}
    if empty_ids:
        logger.warning(
            "Filtered %d empty/whitespace voice IDs during validation", len(empty_ids),
        )
    voice_ids = {v for v in voice_ids if v and v.strip()}
    return sorted(voice_ids - available)
