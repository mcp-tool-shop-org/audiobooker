---
title: Reference
description: Full CLI and Python API reference for Audiobooker.
sidebar:
  order: 5
---

## CLI reference

### `audiobooker new <file>`

Create a new project from a source file.

```bash
audiobooker new book.epub
audiobooker new book.txt --lang en -o book.audiobooker
```

Supported formats: `.epub`, `.txt`, `.md`.

### `audiobooker from-stdin`

Create a project from text piped via stdin.

```bash
cat book.txt | audiobooker from-stdin --title "My Book" --author "Me" -o mybook.audiobooker
```

### `audiobooker cast <character> <voice>`

Assign a voice to a character. Character names are stored with a canonical lookup key (case-insensitive via `casefold()`), but the display name is preserved.

```bash
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
```

### `audiobooker cast-suggest`

Suggest voices for all uncast speakers. Returns ranked, explainable recommendations.

### `audiobooker cast-apply --auto`

Auto-apply the top voice suggestion for each uncast speaker.

### `audiobooker compile`

Compile chapters into utterances (dialogue detection + speaker attribution). Prints uncast speakers after compilation so you can assign voices.

### `audiobooker review-export`

Export the compiled script to a human-editable review format.

### `audiobooker review-import <file>`

Import an edited review file back into the project.

### `audiobooker render`

Render audio and assemble the final audiobook.

| Flag | Description |
|------|-------------|
| `-o/--output <path>` | Output filename |
| `-c/--chapter <index>` | Render a single chapter (0-indexed) |
| `--no-resume` | Ignore cache and re-render everything |
| `--from-chapter N` | Start rendering at chapter N |
| `--allow-partial` | Assemble even if some chapters failed |
| `--clean-cache` | Delete render cache before starting |

### `audiobooker voices`

List voices available from voice-soundboard.

```bash
audiobooker voices
audiobooker voices --gender female
audiobooker voices --search george
```

### `audiobooker info`

Show project details. Use `--verbose` for additional output.

### `audiobooker chapters`

List chapter titles.

### `audiobooker speakers`

List detected speakers.

## Python API reference

### Creating projects

```python
from audiobooker import AudiobookProject

# From EPUB
project = AudiobookProject.from_epub("mybook.epub")

# From raw text
project = AudiobookProject.from_string(
    "Chapter 1\n\nHello world.",
    title="My Book"
)
```

### Casting voices

```python
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
```

### Compiling

```python
project.compile()
```

### Review workflow

```python
review_path = project.export_for_review()
# ... edit the file ...
project.import_reviewed(review_path)
```

### Rendering

```python
project.render("mybook.m4b")
```

### Saving and loading

```python
project.save("mybook.audiobooker")
```

Projects are saved as JSON with a schema version, containing config, chapters, utterances, and casting data.

## Project configuration

Key settings in `ProjectConfig`:

| Setting | Default | Description |
|---------|---------|-------------|
| `fallback_voice_id` | (none) | Voice used when no cast entry matches |
| `validate_voices_on_render` | `True` | Verify all voice IDs exist before rendering |
| `min_chapter_words` | (varies) | Minimum words to keep a chapter |
| `keep_titled_short_chapters` | `False` | Keep short chapters if they have titles |

## Data formats

### `.audiobooker` project file

JSON file containing config, chapters, utterances, and casting. Portable and scriptable.

### Review file format

Plain text with chapter headers and speaker tags:

```
=== Chapter 1 ===

@narrator
The door creaked open.

@Unknown
"Hello?" he whispered.

@Sarah (worried)
"Is anyone there?"
```

### Voice-soundboard script format

Bridge format for synthesis:

```
[S1:Alice] (angry) How dare you!
```
