"""
Text/Markdown Parser for Audiobooker.

Parses plain text and Markdown files into chapters.
Supports various chapter delimiter patterns.
"""

import re
from pathlib import Path
from typing import Optional

from audiobooker.models import Chapter


# Common chapter delimiter patterns
CHAPTER_PATTERNS = [
    # "Chapter 1", "Chapter I", "Chapter One"
    r"^(?:Chapter|CHAPTER)\s+(\d+|[IVXLCDM]+|[A-Za-z]+)(?:\s*[:\-\.]\s*(.*))?$",
    # "Part 1", "Part I"
    r"^(?:Part|PART)\s+(\d+|[IVXLCDM]+)(?:\s*[:\-\.]\s*(.*))?$",
    # "1.", "1:", "1 -"
    r"^(\d+)\s*[\.\:\-]\s+(.+)$",
    # "# Chapter Title" (Markdown H1)
    r"^#\s+(.+)$",
    # "## Section Title" (Markdown H2)
    r"^##\s+(.+)$",
    # "*** break ***" or "* * *" (scene breaks - not chapters, skip)
    # Handled separately
]

# Scene break patterns (don't create new chapters)
SCENE_BREAK_PATTERNS = [
    r"^\*\s*\*\s*\*\s*$",
    r"^-\s*-\s*-\s*$",
    r"^~\s*~\s*~\s*$",
    r"^###\s*$",
]


def detect_chapter_pattern(text: str) -> Optional[re.Pattern]:
    """
    Detect which chapter pattern is used in the text.

    Scans the text and returns the most commonly matching pattern.
    """
    pattern_counts = {pattern: 0 for pattern in CHAPTER_PATTERNS}

    for line in text.split("\n")[:200]:  # Check first 200 lines
        line = line.strip()
        if not line:
            continue
        for pattern in CHAPTER_PATTERNS:
            if re.match(pattern, line, re.MULTILINE):
                pattern_counts[pattern] += 1

    # Return pattern with most matches (if > 1)
    best_pattern = max(pattern_counts, key=pattern_counts.get)
    if pattern_counts[best_pattern] > 1:
        return re.compile(best_pattern, re.MULTILINE)

    return None


def is_scene_break(line: str) -> bool:
    """Check if a line is a scene break (not a chapter break)."""
    line = line.strip()
    for pattern in SCENE_BREAK_PATTERNS:
        if re.match(pattern, line):
            return True
    return False


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter if present.

    Returns:
        Tuple of (metadata dict, remaining text)
    """
    metadata = {}

    # Check for YAML frontmatter
    if text.startswith("---"):
        end_match = re.search(r"\n---\s*\n", text[3:])
        if end_match:
            frontmatter = text[3:end_match.start() + 3]
            remaining = text[end_match.end() + 3:]

            # Simple YAML parsing (key: value)
            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    metadata[key] = value

            return metadata, remaining

    return metadata, text


def split_into_chapters(
    text: str,
    delimiter_pattern: Optional[str] = None,
) -> list[tuple[str, str]]:
    """
    Split text into chapters using delimiter pattern.

    Args:
        text: Full text content
        delimiter_pattern: Optional custom regex pattern

    Returns:
        List of (title, content) tuples
    """
    if delimiter_pattern:
        pattern = re.compile(delimiter_pattern, re.MULTILINE)
    else:
        pattern = detect_chapter_pattern(text)

    if pattern is None:
        # No chapters detected - treat as single chapter
        return [("Chapter 1", text)]

    chapters = []
    lines = text.split("\n")
    current_title = None
    current_content = []

    for line in lines:
        # Check if this line is a chapter delimiter
        match = pattern.match(line.strip())

        if match:
            # Save previous chapter if exists
            if current_title is not None or current_content:
                title = current_title or "Untitled"
                content = "\n".join(current_content).strip()
                if content:
                    chapters.append((title, content))

            # Start new chapter
            groups = match.groups()
            if len(groups) >= 2 and groups[1]:
                # Pattern has chapter number and title
                current_title = f"Chapter {groups[0]}: {groups[1]}"
            elif len(groups) >= 1:
                current_title = groups[0] if groups[0] else line.strip()
            else:
                current_title = line.strip()

            current_content = []
        else:
            # Add to current chapter
            current_content.append(line)

    # Don't forget the last chapter
    if current_title is not None or current_content:
        title = current_title or "Untitled"
        content = "\n".join(current_content).strip()
        if content:
            chapters.append((title, content))

    return chapters


def parse_text(
    path: Path,
    chapter_delimiter: Optional[str] = None,
) -> tuple[dict, list[Chapter]]:
    """
    Parse a text or Markdown file into chapters.

    Args:
        path: Path to text file
        chapter_delimiter: Optional custom delimiter pattern

    Returns:
        Tuple of (metadata dict, list of Chapters)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")

    # Read file
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # Extract frontmatter if present
    metadata, text = extract_frontmatter(text)

    # Default title from filename
    if "title" not in metadata:
        metadata["title"] = path.stem

    # Split into chapters
    chapter_data = split_into_chapters(text, chapter_delimiter)

    # Create Chapter objects
    chapters = []
    for i, (title, content) in enumerate(chapter_data):
        chapter = Chapter(
            index=i,
            title=title,
            raw_text=content,
            source_file=str(path),
        )
        chapters.append(chapter)

    return metadata, chapters
