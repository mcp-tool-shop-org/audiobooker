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

### `audiobooker load <project>`

Load an existing `.audiobooker` project file.

```bash
audiobooker load mybook.audiobooker
```

### `audiobooker diagnose`

Check environment: Python version, ebooklib, voice-soundboard, FFmpeg, and Audiobooker version. Useful for debugging installation problems before rendering.

```bash
audiobooker diagnose
audiobooker diagnose --json
```

## Python API reference

### Creating projects

```python
from audiobooker import AudiobookProject

# From EPUB
project = AudiobookProject.from_epub("mybook.epub")

# From text file (TXT or Markdown)
project = AudiobookProject.from_text("mybook.txt")

# From raw text string (no file needed)
project = AudiobookProject.from_string(
    "Chapter 1\n\nHello world.",
    title="My Book",
    author="Author Name",
    lang="en",
)

# From pre-split chapters
project = AudiobookProject.from_chapters(
    [("Chapter 1", "Chapter text..."), ("Chapter 2", "More text...")],
    title="My Book",
)
```

All factory methods accept an optional `config` keyword argument to pass a custom `ProjectConfig`.

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
# Full render with defaults (resume enabled)
project.render("mybook.m4b")

# Force full re-render
project.render("mybook.m4b", resume=False)

# Start from a specific chapter
project.render("mybook.m4b", from_chapter=5)

# Allow partial assembly even if some chapters failed
project.render("mybook.m4b", allow_partial=True)
```

### Saving and loading

```python
# Save project state
project.save("mybook.audiobooker")

# Load an existing project
project = AudiobookProject.load("mybook.audiobooker")
```

Projects are saved as JSON with a schema version, containing config, chapters, utterances, and casting data. Calling `save()` with no arguments writes to the last-used path.

### Inspecting a project

```python
# Project summary dict
project.info()

# Total word count
project.total_words

# Estimated duration in minutes (based on estimated_wpm)
project.estimated_duration_minutes

# Speakers detected after compilation
project.get_detected_speakers()

# Speakers not yet assigned a voice
project.get_uncast_speakers()

# List all cast character names
project.list_characters()
```

## Project configuration

Key settings in `ProjectConfig`:

| Setting | Default | Description |
|---------|---------|-------------|
| `fallback_voice_id` | `"af_heart"` | Voice used when no cast entry matches |
| `validate_voices_on_render` | `True` | Verify all voice IDs exist before rendering |
| `min_chapter_words` | `50` | Minimum words to keep a chapter |
| `keep_titled_short_chapters` | `True` | Keep short chapters if they have titles |
| `chapter_pause_ms` | `2000` | Silence between chapters (ms) |
| `narrator_pause_ms` | `600` | Extra pause after narrator lines (ms) |
| `dialogue_pause_ms` | `400` | Pause between dialogue lines (ms) |
| `sample_rate` | `24000` | Audio sample rate (Hz) |
| `output_format` | `"m4b"` | Default output format |
| `estimated_wpm` | `150` | Words-per-minute for duration estimates |
| `language_code` | `"en"` | ISO language code for profile selection |
| `booknlp_mode` | `"auto"` | NLP speaker resolution: `on`, `off`, `auto` |
| `emotion_mode` | `"rule"` | Emotion inference: `off`, `rule`, `auto` |
| `emotion_confidence_threshold` | `0.75` | Minimum confidence to apply inferred emotion |

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
