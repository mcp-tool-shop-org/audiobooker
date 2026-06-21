"""
Review File Format for Audiobooker.

Provides human-editable script format for review-before-render workflow.

Format:
    === Chapter 1: The Beginning ===

    @narrator
    The door creaked open.

    @Alice (nervous)
    "Hello? Is anyone there?"

    @narrator
    She stepped inside.

    @Bob (whisper)
    "Over here."

Rules:
- Lines starting with @ are speaker tags: @SpeakerName or @SpeakerName (emotion)
- Following lines until next @ or === are that speaker's text
- Lines starting with === are chapter markers
- Lines starting with # are comments (ignored on import)
- Blank lines are preserved for readability but don't affect output
- Delete a speaker block to remove it from output
- Change @Unknown to @ActualName to fix attribution
"""

import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from audiobooker.models import Utterance, UtteranceType

if TYPE_CHECKING:
    from audiobooker.project import AudiobookProject


# Pattern for speaker tag: @SpeakerName or @SpeakerName (emotion)
# Supports names with spaces, hyphens, apostrophes, and dots (e.g. "Mary Jane", "O'Brien")
SPEAKER_PATTERN = re.compile(r"^@([\w .'\-]+?)(?:\s*\(([^)]+)\))?$")

# Pattern for chapter marker: === Chapter Title === or === Chapter Title === [id:abc123]
CHAPTER_PATTERN = re.compile(r'^===\s*(.+?)\s*===(?:\s*\[id:([^\]]+)\])?$')

# REVIEW-A-002: Control tokens that begin a structural line. Body text that
# coincidentally starts with one of these is escaped with a leading backslash
# on export and unescaped on import so it survives a round-trip.
_CONTROL_PREFIXES = ("#", "@", "===")


def _escape_body_line(text: str) -> str:
    """Escape a body line whose first char would otherwise be parsed as a control token."""
    stripped = text.lstrip()
    if stripped.startswith("\\") or any(stripped.startswith(p) for p in _CONTROL_PREFIXES):
        return "\\" + text
    return text


def _unescape_body_line(text: str) -> str:
    """Reverse _escape_body_line: drop a single leading backslash if present."""
    if text.startswith("\\"):
        return text[1:]
    return text


def export_for_review(project: "AudiobookProject", output_path: Optional[Path] = None) -> Path:
    """
    Export compiled project to human-editable review format.

    Args:
        project: AudiobookProject with compiled chapters
        output_path: Output file path (default: {title}_review.txt)

    Returns:
        Path to review file
    """
    if output_path is None:
        output_path = Path(f"{project.title}_review.txt")
    else:
        output_path = Path(output_path)

    lines = []

    # Header
    lines.append("# Audiobooker Review File")
    lines.append(f"# Title: {project.title}")
    lines.append(f"# Author: {project.author}")
    lines.append("#")
    lines.append("# Instructions:")
    lines.append("#   - Edit speaker names by changing @OldName to @NewName")
    lines.append("#   - Edit emotions by changing @Name (old) to @Name (new)")
    lines.append("#   - Delete entire speaker blocks to remove them")
    lines.append("#   - Add emotions: @narrator -> @narrator (somber)")
    lines.append("#   - Lines starting with # are comments (ignored)")
    lines.append("#")
    lines.append(f"# After editing, import with: audiobooker review-import {output_path.name}")
    lines.append("")

    for chapter in project.chapters:
        # Chapter header — include ID if available for stable matching on import
        if chapter.id:
            lines.append(f"=== {chapter.title} === [id:{chapter.id}]")
        else:
            lines.append(f"=== {chapter.title} ===")
        lines.append("")

        if not chapter.utterances:
            lines.append("# (Chapter not compiled - no utterances)")
            lines.append("")
            continue

        current_speaker = None
        current_emotion = None

        for utterance in chapter.utterances:
            # Check if speaker/emotion changed
            if utterance.speaker != current_speaker or utterance.emotion != current_emotion:
                # Add blank line before new speaker (except at start)
                if current_speaker is not None:
                    lines.append("")

                # Speaker tag
                if utterance.emotion:
                    lines.append(f"@{utterance.speaker} ({utterance.emotion})")
                else:
                    lines.append(f"@{utterance.speaker}")

                current_speaker = utterance.speaker
                current_emotion = utterance.emotion

            # Text content. REVIEW-A-002: escape body lines that would otherwise
            # be parsed as control tokens (#, @, ===) so they round-trip.
            for body_line in utterance.text.split("\n"):
                lines.append(_escape_body_line(body_line))

        lines.append("")  # Blank line after chapter

    # Write file
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def import_reviewed(project: "AudiobookProject", review_path: Path) -> dict:
    """
    Import edited review file back into project.

    Args:
        project: AudiobookProject to update
        review_path: Path to edited review file

    Returns:
        Dict with import statistics
    """
    review_path = Path(review_path)
    if not review_path.exists():
        raise FileNotFoundError(f"Review file not found: {review_path}")

    content = review_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Parse the review file
    chapters_data = []
    current_chapter_title = None
    current_chapter_id = None
    current_chapter_utterances = []
    current_speaker = None
    current_emotion = None
    current_text_lines = []

    def flush_utterance():
        """Save accumulated text as utterance."""
        nonlocal current_text_lines, current_speaker
        if current_speaker and current_text_lines:
            text = " ".join(current_text_lines).strip()
            if text:
                current_chapter_utterances.append({
                    "speaker": current_speaker,
                    "emotion": current_emotion,
                    "text": text,
                })
        current_text_lines = []

    def flush_chapter():
        """Save current chapter data."""
        nonlocal current_chapter_title, current_chapter_id, current_chapter_utterances
        flush_utterance()
        if current_chapter_title is not None:
            chapters_data.append({
                "title": current_chapter_title,
                "id": current_chapter_id,
                "utterances": current_chapter_utterances,
            })
        current_chapter_utterances = []
        current_chapter_id = None

    for line in lines:
        line_stripped = line.strip()

        # REVIEW-A-002: A leading backslash marks an escaped body line whose
        # text coincidentally starts with a control token (#, @, ===). Treat it
        # as body and unescape — never as a comment/speaker/chapter marker.
        if line_stripped.startswith("\\"):
            if current_speaker:
                current_text_lines.append(_unescape_body_line(line_stripped))
            continue

        # Skip comments
        if line_stripped.startswith("#"):
            continue

        # Skip blank lines (but they don't break speaker continuity)
        if not line_stripped:
            continue

        # Check for chapter marker
        chapter_match = CHAPTER_PATTERN.match(line_stripped)
        if chapter_match:
            flush_chapter()
            current_chapter_title = chapter_match.group(1)
            current_chapter_id = chapter_match.group(2)  # may be None
            current_speaker = None
            current_emotion = None
            continue

        # Check for speaker tag
        speaker_match = SPEAKER_PATTERN.match(line_stripped)
        if speaker_match:
            flush_utterance()
            current_speaker = speaker_match.group(1)
            current_emotion = speaker_match.group(2)
            continue

        # Regular text line - accumulate
        if current_speaker:
            current_text_lines.append(line_stripped)

    # Flush final chapter
    flush_chapter()

    # Update project chapters
    stats = {
        "chapters_updated": 0,
        "utterances_imported": 0,
        "speakers_found": set(),
    }

    for chapter_data in chapters_data:
        # Find matching chapter — prefer ID match, fall back to title match
        matching_chapter = None
        review_id = chapter_data.get("id")
        if review_id:
            for chapter in project.chapters:
                if getattr(chapter, "id", "") == review_id:
                    matching_chapter = chapter
                    break

        if matching_chapter is None:
            # Fall back to title match
            for chapter in project.chapters:
                if chapter.title == chapter_data["title"]:
                    matching_chapter = chapter
                    break

        if matching_chapter is None:
            continue

        # REVIEW-A-001: If the block count is unchanged, the user only edited
        # speakers/emotions/text in place — preserve each original utterance's
        # UtteranceType by index so PAUSE/DIRECTION/FOOTNOTE don't collapse to
        # NARRATION on round-trip. If blocks were added/removed, fall back to the
        # quote heuristic (we can no longer line up types by position).
        original_utterances = matching_chapter.utterances
        preserve_types = len(original_utterances) == len(chapter_data["utterances"])

        # Rebuild utterances
        new_utterances = []
        for i, utt_data in enumerate(chapter_data["utterances"]):
            if preserve_types:
                utterance_type = original_utterances[i].utterance_type
            else:
                utterance_type = (
                    UtteranceType.DIALOGUE
                    if utt_data["text"].startswith('"')
                    else UtteranceType.NARRATION
                )
            utterance = Utterance(
                speaker=utt_data["speaker"],
                text=utt_data["text"],
                utterance_type=utterance_type,
                emotion=utt_data["emotion"],
                chapter_index=matching_chapter.index,
                line_index=i,
            )
            new_utterances.append(utterance)
            stats["speakers_found"].add(utt_data["speaker"])

        matching_chapter.utterances = new_utterances
        stats["chapters_updated"] += 1
        stats["utterances_imported"] += len(new_utterances)

    stats["speakers_found"] = list(stats["speakers_found"])
    return stats


def preview_review_format(project: "AudiobookProject", chapter_index: int = 0) -> str:
    """
    Preview what the review format looks like for a single chapter.

    Args:
        project: AudiobookProject
        chapter_index: Which chapter to preview

    Returns:
        Review format string for that chapter
    """
    if chapter_index >= len(project.chapters):
        return "# Chapter not found"

    chapter = project.chapters[chapter_index]
    lines = []

    lines.append(f"=== {chapter.title} ===")
    lines.append("")

    if not chapter.utterances:
        lines.append("# (Not compiled)")
        return "\n".join(lines)

    current_speaker = None
    current_emotion = None

    for utterance in chapter.utterances:
        if utterance.speaker != current_speaker or utterance.emotion != current_emotion:
            if current_speaker is not None:
                lines.append("")

            if utterance.emotion:
                lines.append(f"@{utterance.speaker} ({utterance.emotion})")
            else:
                lines.append(f"@{utterance.speaker}")

            current_speaker = utterance.speaker
            current_emotion = utterance.emotion

        lines.append(utterance.text)

    return "\n".join(lines)
