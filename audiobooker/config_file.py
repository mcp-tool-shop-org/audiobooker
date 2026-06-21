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

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("audiobooker.config_file")

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
# Kept in sync with audiobooker.models.ProjectConfig dataclass fields. We do
# NOT import ProjectConfig at module load to keep this module dependency-light
# and side-effect free; the set is small and stable.
_PASSTHROUGH_FIELDS: frozenset[str] = frozenset(
    {
        "chapter_pause_ms",
        "narrator_pause_ms",
        "dialogue_pause_ms",
        "sample_rate",
        "output_format",
        "fallback_voice_id",
        "validate_voices_on_render",
        "estimated_wpm",
        "min_chapter_words",
        "keep_titled_short_chapters",
        "language_code",
        "booknlp_mode",
        "emotion_mode",
        "emotion_confidence_threshold",
        "global_speed",
        "pronunciation_overrides",
        "clean_text",
        "normalize_text",
        "parallel_compile",
        "compile_workers",
        "user_emotion_rules",
        "footnote_behavior",
        "output_profile",
        "aac_bitrate",
        "mp3_bitrate",
        "use_toc",
        "phoneme_overrides",
    }
)

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

    ``origin`` is a short label (e.g. "user config", ".audiobookerrc") used
    only in the unknown-key warning so the user can locate the typo.
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
]
