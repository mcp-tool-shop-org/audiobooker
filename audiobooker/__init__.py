"""
Audiobooker - AI Audiobook Generator

Convert EPUB/TXT books into professionally narrated audiobooks
using multi-voice synthesis with character-specific voices.

Example:
    from audiobooker import AudiobookProject

    project = AudiobookProject.from_epub("book.epub")
    project.cast("narrator", voice="bm_george", emotion="calm")
    project.cast("Alice", voice="af_bella", emotion="warm")
    project.render("output.m4b")
"""

# CH-B-005 (wave 5 amend): __version__ used to be a hand-maintained literal
# here, independently of pyproject.toml's `version` -- one of FOUR
# hand-maintained copies of the same fact across this repo (pyproject.toml,
# here, npm/package.json, npm/bin/audiobooker.js), and they have already
# drifted from each other in this repo's history. pyproject.toml is the
# canonical source (it is what `pip install` / `python -m build` actually
# reads); every other Python-side copy is now DERIVED from the installed
# distribution's metadata instead of retyped, so there is nothing left here
# to forget to bump. The npm side (npm/package.json + npm/bin/audiobooker.js)
# is a separate packaging ecosystem that release.yml already checks against
# the release tag independently -- see that workflow, not this comment, for
# how that pair stays honest.
try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("audiobooker-ai")
except PackageNotFoundError:  # pragma: no cover - only when not installed at all
    # Running from a raw checkout with no `pip install`/`pip install -e .`
    # ever having been done (e.g. a stray sys.path hack). Real usage always
    # goes through an installed distribution (editable dev install, the
    # built wheel, or the npm launcher's managed venv), so this fallback
    # exists only to avoid a hard crash on import in that unsupported case.
    __version__ = "0.0.0+unknown"

from audiobooker.models import (
    BookMetadata,
    Chapter,
    Utterance,
    Character,
    CastingTable,
    ProjectConfig,
)
from audiobooker.project import AudiobookProject
from audiobooker.errors import AudiobookerError, ConfigValidationError, ErrorDetail

__all__ = [
    "AudiobookProject",
    "BookMetadata",
    "Chapter",
    "Utterance",
    "Character",
    "CastingTable",
    "ProjectConfig",
    "AudiobookerError",
    "ConfigValidationError",
    "ErrorDetail",
]
