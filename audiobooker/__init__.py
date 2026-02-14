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

__version__ = "0.5.0"

from audiobooker.models import (
    Chapter,
    Utterance,
    Character,
    CastingTable,
    ProjectConfig,
)
from audiobooker.project import AudiobookProject

__all__ = [
    "AudiobookProject",
    "Chapter",
    "Utterance",
    "Character",
    "CastingTable",
    "ProjectConfig",
]
