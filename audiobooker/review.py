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

CLI-1 (wave 2): ONE @-tag block == ONE utterance. Export writes a speaker tag
for EVERY utterance, not only when the speaker/emotion changes. The old
"tag on change" form made the block boundary invisible whenever consecutive
utterances shared a speaker — which is most of a real book — so a zero-edit
export/import round trip silently fused them into a single utterance and
destroyed every non-NARRATION utterance_type in the run (a PAUSE marker came
back as narrated prose). The boundary must be explicit on BOTH sides.

CLI-2 (wave 2): an @-leading line that does NOT parse as a speaker tag is
NEVER body text. Absorbing it made the renderer narrate the literal string
"@Bob, the baker" aloud while losing the character. Such lines are collected
into ``stats['malformed_lines']`` so the CLI can refuse the import.
"""

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from audiobooker.models import Utterance, UtteranceType
from audiobooker.shell_quote import quote_arg

if TYPE_CHECKING:
    from audiobooker.project import AudiobookProject

logger = logging.getLogger("audiobooker.review")


# CLIUX-H-007: the CLI prints its own structured, per-line error for every
# malformed tag. ``main()`` calls ``logging.basicConfig(level=WARNING)``, so
# the module logger printed each of those lines a SECOND time to stderr,
# doubling an already alarming error report. Inside this context the per-line
# records drop to DEBUG (so ``--debug`` still keeps them) while every other
# warning in this module is untouched. Library callers are unaffected.
_CALLER_REPORTS_MALFORMED = False


@contextmanager
def caller_reports_malformed():
    """Downgrade the per-line malformed-tag warning to DEBUG for this block.

    Use it when the caller renders its own report of ``stats['malformed_lines']``
    — otherwise the user reads the same line twice in two different formats.
    """
    global _CALLER_REPORTS_MALFORMED
    previous = _CALLER_REPORTS_MALFORMED
    _CALLER_REPORTS_MALFORMED = True
    try:
        yield
    finally:
        _CALLER_REPORTS_MALFORMED = previous


# Pattern for speaker tag: @SpeakerName or @SpeakerName (emotion)
# Supports names with spaces, hyphens, apostrophes, and dots (e.g. "Mary Jane",
# "O'Brien").
#
# CLI-2: commas, ampersands and colons are ordinary in the appositive labels
# BookNLP produces ("Bob, the baker", "Mrs. Hale, the housekeeper"). The old
# class excluded them, so those tags failed to parse and were absorbed as body
# text — the renderer then narrated "@Bob, the baker" aloud.
#
# The emotion group deliberately stays single-level (``[^)]+``): a line like
# "@Bob (terrified) (fearful)" — what the file's own instruction ("change
# @Name (old) to @Name (new)") produces when a user appends rather than
# replaces — is genuinely ambiguous. It must be REPORTED as malformed by
# import_reviewed, never guessed at and never absorbed as body text.
SPEAKER_PATTERN = re.compile(r"^@([\w .,'\-&:]+?)(?:\s*\(([^)]+)\))?$")

# Pattern for chapter marker: === Chapter Title === or === Chapter Title === [id:abc123]
CHAPTER_PATTERN = re.compile(r'^===\s*(.+?)\s*===(?:\s*\[id:([^\]]+)\])?$')

# REVIEW-A-002: Control tokens that begin a structural line. Body text that
# coincidentally starts with one of these is escaped with a leading backslash
# on export and unescaped on import so it survives a round-trip.
_CONTROL_PREFIXES = ("#", "@", "===")

# CLIUX-H-007: an @-line carrying a SECOND parenthesised group — exactly what
# the file's own instruction ("change @Name (old) to @Name (new)") produces
# when a user appends instead of replacing. This is the dominant real cause of
# a malformed tag, and the old blanket hint ("if the line is body text, escape
# it with a leading backslash") actively makes it worse: escaping the tag makes
# the renderer SPEAK it. Classify before hinting.
_MULTI_EMOTION_TAG = re.compile(r"^@[^()]*\([^)]*\)\s*\(")

_MALFORMED_HINTS = {
    "multi_emotion": (
        "a tag carries at most one emotion — REPLACE the old one rather than "
        "appending a second: '@Name (new)', not '@Name (old) (new)'."
    ),
    "no_group": (
        "a speaker tag is '@Name' or '@Name (emotion)'. If this line is body "
        "text, escape it with a leading backslash: '\\@Name'."
    ),
    "unbalanced_group": (
        "a speaker tag is '@Name' or '@Name (emotion)' with ONE balanced pair "
        "of parentheses. Check for an unclosed '(' or a stray ')'."
    ),
}


def _classify_malformed_tag(text: str) -> tuple[str, str]:
    """Return ``(kind, hint)`` for an @-leading line that is not a valid tag.

    CLIUX-H-007: the hint has to name the actual cause. Three shapes cover
    what users produce: a second emotion group (appended instead of replaced),
    a line with no parentheses at all (usually genuine body text that wants
    escaping), and everything else (an unbalanced or unparseable group).
    """
    if _MULTI_EMOTION_TAG.match(text):
        return "multi_emotion", _MALFORMED_HINTS["multi_emotion"]
    if "(" not in text and ")" not in text:
        return "no_group", _MALFORMED_HINTS["no_group"]
    return "unbalanced_group", _MALFORMED_HINTS["unbalanced_group"]


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


def _unescape_indented_body_line(text: str) -> str:
    """Drop the escaping backslash while preserving the line's indentation.

    ``_escape_body_line`` prefixes the backslash to the WHOLE line, so the
    original leading whitespace sits after it; a hand-written file may also
    indent the backslash itself. Either way, remove exactly the first
    backslash and keep everything else byte-for-byte (CLI-1: verse keeps its
    shape).
    """
    idx = text.find("\\")
    if idx == -1:
        return text
    return text[:idx] + text[idx + 1:]


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
        # CLIUX-H-008: route the default through the SAME sanitizer that
        # render / from-stdin / make / save already use. Colons are ordinary
        # in EPUB titles ("Dune: Part One"), and on Windows the raw title
        # wrote the review text into an NTFS alternate data stream: exists()
        # said True, the directory showed a single zero-byte file named
        # "Dune", and the review file was invisible to every GUI. An explicit
        # output_path is the caller's business and is left untouched.
        from audiobooker.project import _sanitize_filename

        output_path = Path(f"{_sanitize_filename(project.title)}_review.txt")
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
    lines.append("#   - Edit emotions by changing @Name (old) to @Name (new).")
    # CLIUX-H-007: this instruction is what produces the single most common
    # malformed tag — a user appends the new emotion instead of replacing the
    # old one. Say so here, where they are reading it.
    lines.append("#     REPLACE it, never append - a tag carries at most one emotion,")
    lines.append("#     and '@Name (old) (new)' is REJECTED on import.")
    lines.append("#   - Delete entire speaker blocks to remove them - but know the cost:")
    # CLIUX-H-006: deleting a block changes the block count, and import can
    # then only re-derive utterance types from a starts-with-a-quote
    # heuristic. Telling users to delete without telling them that is how
    # PAUSE / DIRECTION markers ended up narrated aloud.
    lines.append("#     deleting ANY block makes import re-derive EVERY utterance type in")
    lines.append("#     that chapter from a text heuristic, so PAUSE / DIRECTION / FOOTNOTE")
    lines.append("#     markers come back as plain narration and the renderer reads their")
    lines.append("#     marker text ('[PAUSE]', '[SFX ...]') ALOUD. Edit speakers, emotions")
    lines.append("#     and text in place wherever you can; delete only when you mean it.")
    lines.append("#   - Add emotions: @narrator -> @narrator (somber)")
    lines.append("#   - Lines starting with # are comments (ignored)")
    lines.append("#   - Do NOT edit the '=== Title === [id:...]' line — the id is")
    lines.append("#     how import matches each block back to its chapter. Change")
    lines.append("#     it and that chapter will be skipped on import.")
    lines.append("#")
    # Quoted, because this is the copy of the command the user actually has
    # in front of them — it sits at the top of the file they just opened to
    # edit. review-export names the file from the book TITLE, so a book with
    # a space in its name produced a command argparse rejects, and argparse
    # answers a rejected argument by dumping all 34 subcommands. The CLI's
    # own printed copy was fixed; this one was missed. Same helper, so the
    # two cannot drift apart on one platform.
    lines.append(
        "# After editing, import with: audiobooker review-import "
        f"{quote_arg(output_path.name)}"
    )
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

        # CLI-1: one @-tag per utterance. Emitting the tag only when the
        # speaker/emotion CHANGED left consecutive same-speaker utterances with
        # no boundary at all in the file, and import fused them back into one.
        for i, utterance in enumerate(chapter.utterances):
            # Blank line between blocks (except before the first one).
            if i:
                lines.append("")

            if utterance.emotion:
                lines.append(f"@{utterance.speaker} ({utterance.emotion})")
            else:
                lines.append(f"@{utterance.speaker}")

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
    # CLI-2: @-leading lines that parse as neither a speaker tag nor an escaped
    # body line. Recorded (with 1-based line numbers) rather than narrated.
    malformed_lines: list[dict] = []

    def flush_utterance():
        """Save accumulated text as utterance."""
        nonlocal current_text_lines, current_speaker
        if current_speaker and current_text_lines:
            # CLI-1: join on newline, not space, so a multi-line utterance
            # (verse, an epigraph, a stanza) keeps its shape through the round
            # trip. Only the outer edges are stripped.
            text = "\n".join(current_text_lines).strip()
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

    for line_no, line in enumerate(lines, 1):
        line_stripped = line.strip()
        # CLI-1: body keeps its leading indentation (only trailing whitespace
        # and the CR of a CRLF file are dropped) so verse survives the trip.
        body_line = line.rstrip()

        # REVIEW-A-002: A leading backslash marks an escaped body line whose
        # text coincidentally starts with a control token (#, @, ===). Treat it
        # as body and unescape — never as a comment/speaker/chapter marker.
        if line_stripped.startswith("\\"):
            if current_speaker:
                current_text_lines.append(_unescape_indented_body_line(body_line))
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

        # CLI-2: an @-leading line that did not parse as a speaker tag is a
        # MALFORMED TAG, never body text. Absorbing it made the renderer speak
        # the literal "@Bob, the baker" and dropped the character entirely.
        if line_stripped.startswith("@"):
            # CLIUX-H-007: classify before hinting. The remedy for an appended
            # second emotion group is the OPPOSITE of the remedy for body text.
            kind, hint = _classify_malformed_tag(line_stripped)
            malformed_lines.append({
                "line": line_no,
                "text": line_stripped,
                "kind": kind,
                "hint": hint,
            })
            logger.log(
                logging.DEBUG if _CALLER_REPORTS_MALFORMED else logging.WARNING,
                "Review file line %d is not a valid speaker tag and was NOT "
                "imported: %r. %s",
                line_no,
                line_stripped,
                hint,
            )
            continue

        # Regular text line - accumulate
        if current_speaker:
            current_text_lines.append(body_line)

    # Flush final chapter
    flush_chapter()

    # Update project chapters
    stats = {
        "chapters_updated": 0,
        "utterances_imported": 0,
        "speakers_found": set(),
        # REVIEW-C-005: blocks in the review file that match no existing chapter
        # (by id or title) are silently dropped today. Count and name them so the
        # CLI can warn the user instead of leaving them wondering where edits went.
        "chapters_skipped": 0,
        "skipped_titles": [],
        # CLI-2: @-leading lines that parsed as neither a speaker tag nor an
        # escaped body line. Non-empty means the file is not safe to apply.
        "malformed_lines": malformed_lines,
        # CLI-1: chapters that HAD utterances and came back with none. Almost
        # always a review-file edit gone wrong, and it silently mutes a chapter.
        "emptied_chapters": [],
        # CLIUX-H-006: chapters whose block count changed, so EVERY utterance
        # type in them was re-derived from the starts-with-a-quote heuristic.
        # PAUSE / DIRECTION / FOOTNOTE cannot survive that — the renderer then
        # reads their marker text aloud as prose. Named, with the count.
        "retyped_chapters": [],
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
            # REVIEW-C-005: no chapter matched this block by id or title. Don't
            # drop it silently — record it so the CLI can tell the user which
            # edits were not applied (usually a renamed title or a mangled id).
            skipped_title = chapter_data.get("title") or "(untitled)"
            stats["chapters_skipped"] += 1
            stats["skipped_titles"].append(skipped_title)
            logger.warning(
                "Review block %r matched no existing chapter (by id or title) — "
                "skipped. Restore the original '=== Title === [id:...]' line to "
                "re-link it.",
                skipped_title,
            )
            continue

        # REVIEW-A-001: preserve UtteranceType only when the text at this
        # index still matches. Equal block counts are not identity — deleting
        # one block and adding another with the same count must not keep the
        # old PAUSE/DIRECTION/FOOTNOTE type. Fall back to the quote heuristic
        # and record retyped_chapters when identity breaks.
        original_utterances = matching_chapter.utterances
        same_block_count = len(original_utterances) == len(chapter_data["utterances"])
        identity_broke = False

        # Rebuild utterances
        new_utterances = []
        for i, utt_data in enumerate(chapter_data["utterances"]):
            prior = (
                original_utterances[i]
                if i < len(original_utterances) else None
            )
            text_matches = prior is not None and prior.text == utt_data["text"]
            if text_matches:
                utterance_type = prior.utterance_type
            else:
                utterance_type = (
                    UtteranceType.DIALOGUE
                    if utt_data["text"].startswith('"')
                    else UtteranceType.NARRATION
                )
                if prior is not None:
                    identity_broke = True
            # FEAT-CAST-001 provenance. Rebuilding the utterance used to drop
            # attribution_source and confidence, so importing a review erased
            # the provenance from every line in the book — including the ones
            # the human had just corrected by hand. Backwards twice over: a
            # human decision is the HIGHEST-confidence attribution there is,
            # and ATTRIBUTION_SOURCES has carried an unused `user` member for
            # exactly this since the feature landed.
            #
            # A line whose speaker the reviewer changed becomes `user` at 1.0.
            # A line they left alone keeps whatever the compiler worked out,
            # so importing a review does not relabel the whole book as
            # human-verified — which would be the same lie in the other
            # direction.
            speaker_changed = (
                prior is not None and prior.speaker != utt_data["speaker"]
            )
            if speaker_changed:
                source, confidence = "user", 1.0
            elif prior is not None:
                source, confidence = prior.attribution_source, prior.confidence
            else:
                source, confidence = None, None

            # Synthesizer inputs the review file does not carry: copy from the
            # prior utterance at this index unless the reviewer changed that
            # field (they cannot, so a zero-edit round-trip keeps intensity).
            intensity = prior.intensity if prior is not None else None
            start_pos = prior.start_pos if prior is not None else -1
            end_pos = prior.end_pos if prior is not None else -1
            utt_id = prior.id if prior is not None else None

            utt_kwargs = dict(
                speaker=utt_data["speaker"],
                text=utt_data["text"],
                utterance_type=utterance_type,
                emotion=utt_data["emotion"],
                intensity=intensity,
                chapter_index=matching_chapter.index,
                line_index=i,
                start_pos=start_pos,
                end_pos=end_pos,
                attribution_source=source,
                confidence=confidence,
            )
            if utt_id is not None:
                utt_kwargs["id"] = utt_id
            utterance = Utterance(**utt_kwargs)
            new_utterances.append(utterance)
            stats["speakers_found"].add(utt_data["speaker"])

        # CLI-1: a chapter that had content and now has none is a silent mute
        # in the finished audiobook. Name it so the CLI can warn.
        if original_utterances and not new_utterances:
            title = matching_chapter.title or f"(chapter {matching_chapter.index})"
            stats["emptied_chapters"].append(title)
            logger.warning(
                "Chapter %r had %d utterance(s) before import and has none "
                "after — it will render silent. Check the review file for a "
                "deleted or mistyped block.",
                title,
                len(original_utterances),
            )

        # CLIUX-H-006: the export file tells users to "delete entire speaker
        # blocks to remove them", and doing so silently re-derives every type
        # in the chapter. Report it by name, with the types that provably
        # could not survive (the heuristic can only ever emit NARRATION or
        # DIALOGUE). An emptied chapter is already reported above and more
        # severe, so it is not double-counted here.
        if original_utterances and new_utterances and (
            not same_block_count or identity_broke
        ):
            lost = [
                t for t in (u.utterance_type for u in original_utterances)
                if t not in (UtteranceType.NARRATION, UtteranceType.DIALOGUE)
            ]
            title = matching_chapter.title or f"(chapter {matching_chapter.index})"
            stats["retyped_chapters"].append({
                "title": title,
                "blocks_before": len(original_utterances),
                "blocks_after": len(new_utterances),
                "types_lost": len(lost),
                "lost_types": sorted({t.value for t in lost}),
            })
            logger.warning(
                "Chapter %r utterance identity broke (blocks %d -> %d), so "
                "utterance types were re-derived from a text heuristic; %d "
                "marker type(s) were lost (%s).",
                title,
                len(original_utterances),
                len(new_utterances),
                len(lost),
                ", ".join(sorted({t.value for t in lost})) or "none",
            )

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

    # CLI-1: mirror export_for_review exactly — one @-tag per utterance — so
    # the preview shows the real block boundaries the importer relies on.
    for i, utterance in enumerate(chapter.utterances):
        if i:
            lines.append("")

        if utterance.emotion:
            lines.append(f"@{utterance.speaker} ({utterance.emotion})")
        else:
            lines.append(f"@{utterance.speaker}")

        lines.append(utterance.text)

    return "\n".join(lines)
