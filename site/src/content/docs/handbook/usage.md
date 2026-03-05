---
title: Usage
description: CLI commands, review workflow, and Python API.
sidebar:
  order: 2
---

## CLI commands

Audiobooker ships a focused CLI with these commands:

| Command | Description |
|---------|-------------|
| `audiobooker new <file>` | Create project from EPUB/TXT/MD |
| `audiobooker cast <char> <voice>` | Assign voice to character |
| `audiobooker cast-suggest` | Suggest voices for uncast speakers |
| `audiobooker cast-apply --auto` | Auto-apply top voice suggestions |
| `audiobooker compile` | Compile chapters to utterances |
| `audiobooker review-export` | Export script for human review |
| `audiobooker review-import <file>` | Import edited review file |
| `audiobooker render` | Render audiobook to M4B |
| `audiobooker info` | Show project information |
| `audiobooker voices` | List available voices |
| `audiobooker chapters` | List chapters |
| `audiobooker speakers` | List detected speakers |
| `audiobooker from-stdin` | Create project from piped text |

### Render flags

- `-o/--output <path>` -- output filename
- `-c/--chapter <index>` -- render a single chapter (0-indexed)
- `--no-resume` -- ignore cache and re-render everything
- `--from-chapter N` -- start rendering at chapter N
- `--allow-partial` -- assemble even if some chapters failed
- `--clean-cache` -- delete render cache before starting

## Review workflow

The review workflow is the main quality lever. Dialogue attribution is hard; human correction is fast.

### Why review?

- Correct mis-attributed speakers (common in multi-character scenes)
- Add or adjust emotions for delivery
- Remove junk lines (e.g., OCR artifacts)

### Export, edit, import

```bash
# Export to review format
audiobooker review-export

# Edit the file (example: mybook_review.txt)
# === Chapter 1 ===
#
# @narrator
# The door creaked open.
#
# @Unknown              <-- Change this to @Marcus
# "Hello?" he whispered.
#
# @Sarah (worried)      <-- Emotions are preserved
# "Is anyone there?"

# Import corrections
audiobooker review-import mybook_review.txt

# Render with corrected attributions
audiobooker render
```

### Review file format

- `=== Chapter Title ===` -- chapter markers
- `@Speaker` or `@Speaker (emotion)` -- speaker tags
- `# comment` -- comments (ignored on import)
- Delete blocks to remove unwanted utterances
- Change `@Unknown` to `@ActualName` to fix attribution
- Speaker lookups are case-insensitive; display casing is preserved

## Python API

```python
from audiobooker import AudiobookProject

# Create from EPUB
project = AudiobookProject.from_epub("mybook.epub")

# Or from raw text
project = AudiobookProject.from_string(
    "Chapter 1\n\nHello world.",
    title="My Book"
)

# Cast voices
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")

# Compile (detect dialogue, attribute speakers, infer emotions)
project.compile()

# Review workflow
review_path = project.export_for_review()
# ... edit the file ...
project.import_reviewed(review_path)

# Render to M4B (with automatic resume on re-run)
project.render("mybook.m4b")

# Save project for later
project.save("mybook.audiobooker")
```
