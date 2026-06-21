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

__version__ = "2.1.1"

from audiobooker.models import (
    BookMetadata,
    Chapter,
    Utterance,
    Character,
    CastingTable,
    ProjectConfig,
)
from audiobooker.project import AudiobookProject

__all__ = [
    "AudiobookProject",
    "BookMetadata",
    "Chapter",
    "Utterance",
    "Character",
    "CastingTable",
    "ProjectConfig",
]
