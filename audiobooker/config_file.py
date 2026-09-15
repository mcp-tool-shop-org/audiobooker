"""
Config-file resolution for audiobooker (FT-CONFIG / F-FEAT-F3, v2.1).

Reads a user-friendly TOML config and returns a flat dict of
ProjectConfig-compatible keys so the CLI can seed a ProjectConfig via
``ProjectConfig(**mapped)`` and merge it under CLI flags.

Precedence (highest first):
    1. project-local config:
        a. a ``.audiobookerrc`` (TOML) next to the source file (or in cwd
           when no source is given), OR
        b. a ``[tool.audiobooker]`` table in the nearest ``pyproject.toml``
           found by walking up from the source/cwd directory.
    2. user config: ``~/.audiobookerrc`` (TOML).

A project-local value overrides a user value for the same key; the two
layers are merged key-by-key (not all-or-nothing).

Design constraints (from the v2.1 contract):
    * Dependency-light: TOML via the stdlib ``tomllib`` (3.11+) with a
      ``tomli`` fallback for 3.10. If neither is importable AND a config file
      exists, we warn once and skip that file (never crash). With no TOML lib
      and no file, ``load_config`` returns ``{}``.
    * Side-effect free: pure read. We never write, create, or mutate files.
    * Unknown keys are ignored with a warning so a typo doesn't crash a run.

The CLI owns the final merge (CLI flag > config-file value > built-in
default). This module only resolves and maps; it does not build a
ProjectConfig or touch argparse.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from audiobooker.errors import ConfigValidationError
from audiobooker.models import ProjectConfig

logger = logging.getLogger("audiobooker.config_file")


class ConfigFileError(ConfigValidationError):
    """A config-file-sourced value failed type/range validation at load time.

    F-CORE-2 (wave 2 amend): before this fix, ``load_config``/``_map_table``
    passed every recognized key straight through with no type or range
    check, so a typo like ``workers = "four"`` in a TOML file would sail
    through as a string and only blow up later -- as a bare ``TypeError``
    deep inside ``project._compile_parallel`` (``min(config.compile_workers,
    3)``), with no message connecting the crash back to the config file or
    the key that caused it. Some bad values (e.g. an out-of-range
    ``emotion_confidence_threshold``) didn't raise at all -- they just made
    every confidence comparison fail silently forever.

    This class is raised here, at load time, naming both the offending key
    and the file/table it came from, before the value ever reaches
    ``ProjectConfig(**mapped)``. It is a thin ``ConfigValidationError``
    subclass (see ``audiobooker.errors``) so it is still catchable as
    ``ConfigValidationError``, ``AudiobookerError``, or plain ``ValueError``.
    """


# ---------------------------------------------------------------------------
# TOML loader (stdlib tomllib on 3.11+, tomli fallback on 3.10)
# ---------------------------------------------------------------------------

# Resolve a TOML parser once at import. ``_toml_load`` is a callable taking a
# binary file object, or None when no library is available.
_toml_load = None
try:  # Python 3.11+
    import tomllib as _tomllib

    _toml_load = _tomllib.load
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10
    try:
        import tomli as _tomli

        _toml_load = _tomli.load
    except ModuleNotFoundError:
        _toml_load = None


def have_toml_support() -> bool:
    """True if a TOML parser (tomllib or tomli) is importable."""
    return _toml_load is not None


# ---------------------------------------------------------------------------
# Friendly-key -> ProjectConfig field mapping
# ---------------------------------------------------------------------------

# Friendly aliases the user may write in their config file, mapped to the
# canonical ProjectConfig field name. Keys not listed here but matching a
# ProjectConfig field directly are passed through as-is (see _PASSTHROUGH).
_ALIAS_TO_FIELD: dict[str, str] = {
    "lang": "language_code",
    "language": "language_code",
    "format": "output_format",
    "profile": "output_profile",
    "wpm": "estimated_wpm",
    "speed": "global_speed",
    "normalize": "normalize_text",
    "clean": "clean_text",
    "fallback_voice": "fallback_voice_id",
    "booknlp": "booknlp_mode",
    "emotion": "emotion_mode",
    "toc": "use_toc",
    "footnotes": "footnote_behavior",
    "workers": "compile_workers",
    "parallel": "parallel_compile",
}

# Canonical ProjectConfig fields that may be set directly from a config file.
#
# CH-B-006 (wave 5 amend): this used to be a hand-typed frozenset "kept in
# sync with audiobooker.models.ProjectConfig dataclass fields" by a comment
# alone, on the claim that "the set is small and stable." It wasn't stable --
# it silently fell three fields behind (emotion_preset, tts_engine,
# utterance_cache) when those were added to ProjectConfig. The real
# consequence: a config file setting any of those three did not error. It
# hit the `else` branch in _map_table below, logged a routine-looking
# "ignoring unknown config key" warning (easy to miss -- Python logging is
# silent by default unless configured), and the setting was silently
# dropped. Someone could set `emotion_preset = "dramatic"` in
# .audiobookerrc, see no error, and never get the preset they asked for.
#
# Fix: derive this set from ProjectConfig's actual dataclass fields instead
# of re-typing them, so it cannot fall behind again -- there is nothing left
# to keep "in sync" by hand. The dependency-light/side-effect-free goal in
# the module docstring is about avoiding THIRD-PARTY deps and file I/O, not
# our own sibling modules: audiobooker.models is a leaf with respect to this
# module (it does not import config_file, directly or transitively -- see
# audiobooker/models.py's own imports), so this does not introduce an import
# cycle, and models.py itself does nothing at import time beyond defining
# classes and a logger.
_PASSTHROUGH_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(ProjectConfig)
)


# ---------------------------------------------------------------------------
# F-CORE-2 (wave 2 amend): load-time type/range validation for the numeric
# passthrough fields. ProjectConfig.__post_init__ validates the same
# constraints (defense in depth for every OTHER construction path -- direct
# Python construction, CLI flags, etc.), but by the time a bad value reaches
# ProjectConfig(**mapped) in the CLI, the config file/table that produced it
# is out of scope. Validating here, at the TOML boundary, lets the error name
# the file. Deliberately NOT re-validating the enum-like fields
# (output_format, booknlp_mode, ...) here -- those are already fully covered
# by ProjectConfig's own __post_init__ and duplicating that list of valid
# values in two places is a maintenance hazard with little added value.
# ---------------------------------------------------------------------------


def _is_intlike(value: Any) -> bool:
    """True for a real int, excluding bool (bool is an int subclass)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_numberlike(value: Any) -> bool:
    """True for a real int/float, excluding bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_positive_int(field: str, value: Any, key: str, origin: str) -> None:
    if not _is_intlike(value) or value <= 0:
        raise ConfigFileError(
            f"Invalid value for {key!r} in {origin}: {field} must be a "
            f"positive integer, got {value!r}.",
            hint=f"Set {key!r} to a whole number greater than 0 in {origin}.",
        )


def _require_non_negative_int(field: str, value: Any, key: str, origin: str) -> None:
    if not _is_intlike(value) or value < 0:
        raise ConfigFileError(
            f"Invalid value for {key!r} in {origin}: {field} must be a "
            f"non-negative integer, got {value!r}.",
            hint=f"Set {key!r} to 0 or a positive whole number in {origin}.",
        )


def _require_unit_interval(field: str, value: Any, key: str, origin: str) -> None:
    if not _is_numberlike(value) or not (0.0 <= value <= 1.0):
        raise ConfigFileError(
            f"Invalid value for {key!r} in {origin}: {field} must be a "
            f"number between 0.0 and 1.0, got {value!r}.",
            hint=f"Set {key!r} to a value between 0.0 and 1.0 in {origin}.",
        )


def _require_range(lo: float, hi: float) -> Callable[[str, Any, str, str], None]:
    """Build a validator requiring a number in the closed interval [lo, hi].

    CH-B-008 (wave 5 amend): added for ``global_speed`` (alias "speed"),
    ProjectConfig's ONE numeric field that had no boundary validator here --
    the global config surface has 9 numeric fields total (chapter_pause_ms,
    narrator_pause_ms, dialogue_pause_ms, sample_rate, estimated_wpm,
    min_chapter_words, compile_workers, emotion_confidence_threshold,
    global_speed) and only 8 were covered before this fix.

    The consequence was worse for this field than for the other 8: those are
    range-checked in ProjectConfig.__post_init__ (audiobooker/models.py) via
    ``_check_positive_int``/``_check_non_negative_int``/``_check_unit_interval``
    helpers that all guard with ``isinstance`` first, so a wrong TYPE from a
    config file (e.g. ``workers = "four"``) still raised a clean
    ConfigValidationError even before F-CORE-2 added a boundary check --
    just one without the config file's name attached. global_speed's own
    check in __post_init__ has no such guard:
    ``if not (0.5 <= self.global_speed <= 2.0)``. Given a string (e.g. a
    config file with ``speed = "fast"``), that comparison itself raises a
    bare, unhandled ``TypeError`` ("'<=' not supported between instances of
    'float' and 'str'") -- not a ConfigValidationError, not a message that
    mentions the config file, just a raw traceback out of ProjectConfig
    construction. An out-of-range but correctly-typed value (``speed = 5.0``)
    at least raised a clean-ish ValueError, but still without naming the
    file it came from.

    The 0.5/2.0 bounds are intentionally duplicated (not imported) from
    ProjectConfig.__post_init__: that check is inline in an ``if`` statement
    there, not an importable named constant, and this module does not own
    models.py this wave. If either bound changes, the other must be updated
    to match -- both are load-bearing for the same fact.
    """

    def _validator(field: str, value: Any, key: str, origin: str) -> None:
        if not _is_numberlike(value) or not (lo <= value <= hi):
            raise ConfigFileError(
                f"Invalid value for {key!r} in {origin}: {field} must be a "
                f"number between {lo} and {hi}, got {value!r}.",
                hint=f"Set {key!r} to a value between {lo} and {hi} in {origin}.",
            )

    return _validator


# field name -> validator(field, value, key, origin). Keyed by the CANONICAL
# ProjectConfig field name (post-alias-resolution), so both a friendly alias
# (e.g. "workers") and the canonical key (e.g. "compile_workers") are checked
# the same way.
_NUMERIC_VALIDATORS: dict[str, Callable[[str, Any, str, str], None]] = {
    "sample_rate": _require_positive_int,
    "compile_workers": _require_positive_int,
    "estimated_wpm": _require_positive_int,
    "chapter_pause_ms": _require_non_negative_int,
    "narrator_pause_ms": _require_non_negative_int,
    "dialogue_pause_ms": _require_non_negative_int,
    "min_chapter_words": _require_non_negative_int,
    "emotion_confidence_threshold": _require_unit_interval,
    # CH-B-008 (wave 5 amend): bounds match ProjectConfig.__post_init__'s
    # `if not (0.5 <= self.global_speed <= 2.0)` in audiobooker/models.py.
    "global_speed": _require_range(0.5, 2.0),
}

# Non-config keys recognized as structured sections (returned as-is, not
# mapped onto ProjectConfig). The CLI reads these to seed BookMetadata or to
# locate auxiliary files.
#   book     -> dict of title/author/series/series_index/year/publisher/...
#   casting  -> str path to a casting JSON file (import_casting)
#   lexicon  -> str path to a pronunciation lexicon (import_lexicon)
_SECTION_KEYS: frozenset[str] = frozenset({"book", "casting", "lexicon"})

# Config file base names.
_PROJECT_RC_NAME = ".audiobookerrc"
_PYPROJECT_NAME = "pyproject.toml"
_USER_RC_NAME = ".audiobookerrc"


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _read_toml(path: Path) -> Optional[dict]:
    """Parse a TOML file, returning a dict or None on any failure.

    Pure read. Emits a warning (never raises) when the file exists but cannot
    be parsed, or when no TOML library is available.
    """
    if _toml_load is None:
        logger.warning(
            "Config file %s found but no TOML parser is available "
            "(install 'tomli' on Python 3.10); skipping.",
            path,
        )
        return None
    try:
        with open(path, "rb") as f:
            data = _toml_load(f)
    except (OSError, ValueError) as e:
        # ValueError covers tomllib.TOMLDecodeError (a ValueError subclass).
        logger.warning("Could not parse config file %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        logger.warning("Config file %s did not contain a TOML table; ignoring.", path)
        return None
    return data


def _base_dir(source_path: Optional[str | Path]) -> Path:
    """Directory to anchor project-local discovery (source dir or cwd)."""
    if source_path:
        p = Path(source_path)
        # If a file path is given, anchor at its parent; if a directory
        # (folder input), anchor at the directory itself.
        if p.is_dir():
            return p
        return p.parent if p.parent != Path("") else Path.cwd()
    return Path.cwd()


def _find_project_rc(base: Path) -> Optional[Path]:
    """Find a .audiobookerrc next to the source/cwd (no upward walk)."""
    candidate = base / _PROJECT_RC_NAME
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _find_pyproject(base: Path) -> Optional[Path]:
    """Walk up from base looking for a pyproject.toml with [tool.audiobooker]."""
    try:
        base = base.resolve()
    except OSError:
        return None
    for directory in (base, *base.parents):
        candidate = directory / _PYPROJECT_NAME
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _user_rc() -> Optional[Path]:
    """Path to ~/.audiobookerrc if it exists."""
    try:
        candidate = Path.home() / _USER_RC_NAME
    except (RuntimeError, OSError):
        return None
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def find_config_files(source_path: Optional[str | Path] = None) -> dict[str, Optional[str]]:
    """Diagnostic helper: report which config sources were found.

    Returns a dict with three keys, each a string path or None:
        project_rc  -> the .audiobookerrc next to source/cwd
        pyproject   -> a pyproject.toml containing [tool.audiobooker]
        user_rc     -> ~/.audiobookerrc

    Pure read — performs the same discovery as load_config without parsing
    values into a merged config. Useful for a `config --where` style command.
    """
    base = _base_dir(source_path)

    project_rc = _find_project_rc(base)

    pyproject_with_table: Optional[Path] = None
    pyproject = _find_pyproject(base)
    if pyproject is not None:
        data = _read_toml(pyproject)
        if data and isinstance(data.get("tool"), dict) and isinstance(
            data["tool"].get("audiobooker"), dict
        ):
            pyproject_with_table = pyproject

    user_rc = _user_rc()

    return {
        "project_rc": str(project_rc) if project_rc else None,
        "pyproject": str(pyproject_with_table) if pyproject_with_table else None,
        "user_rc": str(user_rc) if user_rc else None,
    }


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def _map_table(raw: dict[str, Any], origin: str) -> dict[str, Any]:
    """Map a raw config table to ProjectConfig-compatible keys + sections.

    * Friendly aliases (lang, format, ...) are renamed to canonical fields.
    * Canonical ProjectConfig fields pass through unchanged.
    * Known sections (book, casting, lexicon) pass through under their own key.
    * Unknown keys are dropped with a warning.
    * F-CORE-2 (wave 2 amend): numeric fields are type/range-checked here
      (see ``_NUMERIC_VALIDATORS``) and raise ``ConfigFileError`` naming both
      the key and ``origin`` on a bad value, instead of letting it reach
      ``ProjectConfig(**mapped)`` unchecked.

    ``origin`` is a short label (e.g. "user config", ".audiobookerrc") used
    in the unknown-key warning AND in the ``ConfigFileError`` message so the
    user can locate the typo/bad value.
    """
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        # Structured sections pass through untouched.
        if key in _SECTION_KEYS:
            mapped[key] = value
            continue

        # Resolve an alias to its canonical field name.
        field = _ALIAS_TO_FIELD.get(key, key)

        if field in _PASSTHROUGH_FIELDS:
            validator = _NUMERIC_VALIDATORS.get(field)
            if validator is not None:
                validator(field, value, key, origin)
            mapped[field] = value
        else:
            logger.warning(
                "Ignoring unknown config key %r in %s "
                "(not a recognized audiobooker setting).",
                key,
                origin,
            )
    return mapped


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def load_config(source_path: Optional[str | Path] = None) -> dict[str, Any]:
    """Resolve audiobooker config with project-local > user precedence.

    Args:
        source_path: The book source being processed (file or folder). Used to
            anchor project-local discovery. None anchors at the current
            working directory.

    Returns:
        A flat dict of ProjectConfig-compatible keys (output_format,
        language_code, estimated_wpm, ...) ready for ``ProjectConfig(**mapped)``
        after the CLI strips/handles the section keys. May also include the
        structured section keys ``book`` (dict), ``casting`` (path str), and
        ``lexicon`` (path str) when present in the config.

        Returns ``{}`` when no config file is found (or no TOML library is
        available and a file would have needed parsing). Never raises on a
        missing/malformed file — malformed files warn and are skipped.

    Side effects: none. This is a pure read.
    """
    base = _base_dir(source_path)

    # --- user layer (lowest precedence) ------------------------------------
    user_layer: dict[str, Any] = {}
    user_rc = _user_rc()
    if user_rc is not None:
        data = _read_toml(user_rc)
        if data:
            user_layer = _map_table(data, "user config (~/.audiobookerrc)")

    # --- project-local layer (highest precedence) --------------------------
    # Prefer an explicit .audiobookerrc; otherwise a [tool.audiobooker] table
    # in the nearest pyproject.toml. A repo that has both gets the rc file
    # (the more specific, intentional choice).
    project_layer: dict[str, Any] = {}
    project_rc = _find_project_rc(base)
    if project_rc is not None:
        data = _read_toml(project_rc)
        if data:
            project_layer = _map_table(data, str(project_rc))
    else:
        pyproject = _find_pyproject(base)
        if pyproject is not None:
            data = _read_toml(pyproject)
            tool = data.get("tool") if isinstance(data, dict) else None
            table = tool.get("audiobooker") if isinstance(tool, dict) else None
            if isinstance(table, dict):
                project_layer = _map_table(
                    table, f"{pyproject} [tool.audiobooker]"
                )

    # --- merge: project-local wins key-by-key ------------------------------
    merged: dict[str, Any] = dict(user_layer)
    merged.update(project_layer)
    return merged


__all__ = [
    "load_config",
    "find_config_files",
    "have_toml_support",
    "ConfigFileError",
]
