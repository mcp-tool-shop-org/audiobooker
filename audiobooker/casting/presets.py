"""
FT-CAST-020: Named cast preset library.

A small, user-config-dir-backed library of named casting presets. Each preset
is a list of character dicts in the SAME shape produced by
``AudiobookProject.export_casting`` (keys: name, voice, emotion, speed,
aliases, description), so presets round-trip cleanly through import_casting.

Resolution of the on-disk location:
1. ``platformdirs.user_config_dir("audiobooker")`` when platformdirs is
   importable (the preferred, cross-platform path).
2. Fallback: ``%APPDATA%\\audiobooker`` on Windows, ``~/.config/audiobooker``
   on POSIX.

Presets are stored as ``<preset_dir>/presets/<slug>.json``. Names are slugged
for the filename but the original name is preserved in the file payload so
``list_presets`` returns human-readable names.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("audiobooker.casting.presets")

_APP_NAME = "audiobooker"
_PRESET_SUBDIR = "presets"

# Filenames are derived from the preset name; this keeps them filesystem-safe.
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


class PresetError(ValueError):
    """A cast preset could not be saved, loaded, or found."""


def _config_root() -> Path:
    """
    Resolve the user config directory for audiobooker.

    Prefers platformdirs; falls back to the platform convention when it is
    unavailable so the feature still works in minimal installs.
    """
    try:
        import platformdirs

        return Path(platformdirs.user_config_dir(_APP_NAME))
    except ImportError:
        if os.name == "nt":
            base = os.environ.get("APPDATA")
            if base:
                return Path(base) / _APP_NAME
            return Path.home() / "AppData" / "Roaming" / _APP_NAME
        return Path.home() / ".config" / _APP_NAME


def preset_dir() -> Path:
    """
    Return the directory that holds saved cast presets, creating it if needed.

    Returns:
        Path to ``<user-config>/audiobooker/presets``.
    """
    target = _config_root() / _PRESET_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _slug(name: str) -> str:
    """Filesystem-safe slug for a preset name."""
    slug = _SLUG_RE.sub("-", name.strip().casefold()).strip("-._")
    return slug or "preset"


def _preset_path(name: str) -> Path:
    return preset_dir() / f"{_slug(name)}.json"


def save_preset(name: str, casting_table_as_list: list[dict]) -> Path:
    """
    Save a named cast preset.

    Args:
        name: Human-readable preset name (e.g. "Fantasy Ensemble").
        casting_table_as_list: List of character dicts in export_casting shape
            (keys: name, voice, emotion, speed, aliases, description). Extra
            keys are preserved; the only hard requirements are 'name' + 'voice'.

    Returns:
        Path to the written preset file.

    Raises:
        PresetError: If the name is empty or the payload is not a list of dicts.
    """
    if not name or not name.strip():
        raise PresetError("Preset name must be a non-empty string.")
    if not isinstance(casting_table_as_list, list):
        raise PresetError(
            "Preset casting table must be a list of character dicts, got "
            f"{type(casting_table_as_list).__name__}."
        )
    for entry in casting_table_as_list:
        if not isinstance(entry, dict):
            raise PresetError(
                f"Each preset entry must be a dict, got {type(entry).__name__}."
            )
        if "name" not in entry or "voice" not in entry:
            raise PresetError(
                "Each preset entry needs at least 'name' and 'voice' keys. "
                f"Got keys: {', '.join(sorted(entry.keys()))}"
            )

    payload = {
        "name": name.strip(),
        "characters": list(casting_table_as_list),
    }
    path = _preset_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    logger.info(
        "Saved cast preset %r (%d characters) to %s",
        name, len(casting_table_as_list), path,
    )
    return path


def list_presets() -> list[str]:
    """
    List saved cast preset names (sorted, human-readable).

    Returns:
        Sorted list of preset display names. Empty if none saved.
    """
    target = preset_dir()
    names: list[str] = []
    for path in sorted(target.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            display = data.get("name") if isinstance(data, dict) else None
            names.append(display or path.stem)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable preset %s: %s", path, exc)
            continue
    return sorted(names, key=str.casefold)


def load_preset(name: str) -> list[dict]:
    """
    Load a named cast preset as a list of character dicts.

    Args:
        name: Preset name (matched via the same slug used to save it).

    Returns:
        List of character dicts in export_casting shape, ready to feed to
        import_casting / Character.from_dict.

    Raises:
        PresetError: If the preset does not exist or is malformed.
    """
    path = _preset_path(name)
    if not path.exists():
        raise PresetError(
            f"Cast preset {name!r} not found. "
            f"Use list_presets() to see available presets."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise PresetError(f"Cast preset {name!r} is corrupted: {exc}") from exc

    # Tolerate both the wrapped {"name", "characters"} payload and a bare list
    # (in case a preset file was hand-written in raw export_casting shape).
    if isinstance(data, dict):
        characters = data.get("characters", [])
    elif isinstance(data, list):
        characters = data
    else:
        raise PresetError(
            f"Cast preset {name!r} has an unexpected shape "
            f"({type(data).__name__}); expected a list or object."
        )
    if not isinstance(characters, list):
        raise PresetError(f"Cast preset {name!r} 'characters' must be a list.")
    return characters


def delete_preset(name: str) -> bool:
    """
    Delete a named cast preset.

    Args:
        name: Preset name to delete.

    Returns:
        True if a preset file was removed, False if none existed.
    """
    path = _preset_path(name)
    if path.exists():
        path.unlink()
        logger.info("Deleted cast preset %r (%s)", name, path)
        return True
    logger.info("Cast preset %r not found — nothing to delete", name)
    return False


def find_preset_path(name: str) -> Optional[Path]:
    """Return the on-disk path for a preset name, or None if it does not exist."""
    path = _preset_path(name)
    return path if path.exists() else None
