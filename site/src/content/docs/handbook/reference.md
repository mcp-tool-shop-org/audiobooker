---
title: Reference
description: Full CLI reference for Audiobooker.
sidebar:
  order: 5
---

Every command supports `-h`/`--help`. Global flags (before or after the subcommand): `--silent`, `--debug`. **Exit codes:** `0` success · `1` user error · `2` runtime error · `3` partial success (batch).

## Create & inspect

| Command | Description |
|---------|-------------|
| `make <file>` | One-shot: `new` → `compile` → auto-cast → `render`. Flags: `--format`, `--acx`, `--bitrate`, `--lang`, `--cover`, `-j N`, `--watch`, `-o`. |
| `new <file\|folder>` | Create a project from EPUB/PDF/DOCX/TXT/MD or a folder of chapter files. Flags: `--lang`, `--booknlp`, `--chapter-delimiter <regex>`, `--force-text`, `-o`. |
| `from-stdin` | Create a project from piped text (`--title`). |
| `load <project>` | Load and summarize an existing `.audiobooker` project. |
| `info` · `status` | Project details · render/cache status (`--json`). |
| `chapters` · `chapters rename\|reorder` | List / rename / reorder chapters. |
| `speakers` · `speakers --suggest-aliases` | List speakers · propose epithet/honorific aliases (`--apply`). |
| `voices` | List the engine's voices (`--gender`, `--search`, `--engine`). |
| `diagnose` | Check Python, dependencies, voice engine, FFmpeg, ffprobe. |

## Casting

| Command | Description |
|---------|-------------|
| `cast <char> <voice>` | Assign a voice (`--emotion`, `--speed`). |
| `cast --interactive` | Guided per-uncast-speaker casting. |
| `cast-suggest` · `cast-apply --auto` | Ranked suggestions · auto-apply the top pick. |
| `cast-fill` | Bulk-assign by gender/role: `--gender`, `--voices a,b,c`, `--narrator`, `--minor-voice`, `--minor-threshold`. |
| `audition <char>` | A/B ranked candidate voices for one character (`-n`, `--render`, `--line`, `--json`). |
| `cast-preset save\|list\|apply\|delete` | Named, reusable cast presets (across a series). |
| `cast-export` · `cast-import` | Move a cast table to/from a file (`--format json\|csv`). |

## Compile, review & emotion

| Command | Description |
|---------|-------------|
| `compile` | Detect dialogue, attribute speakers, infer emotion. `--booknlp`, `--emotion-preset`. |
| `report` | Compile quality: unknown-attribution rate, top weak lines, emotion mix (`--json`). |
| `review-export` · `review-import <file>` | Human-editable review round-trip. |
| `emotions` | List/override emotions; `emotions presets`; `emotions mood-span`. |
| `pronunciation add\|remove\|list\|import\|export` | Pronunciation overrides + lexicon files (CSV/JSON, phoneme passthrough). |

## Render & output

| Command | Description |
|---------|-------------|
| `render` | Render the audiobook. Flags: `--format m4b\|mp3\|opus\|flac`, `--acx`, `--split`, `--bitrate`, `--engine`, `--cover`, `--narrator/--genre/--series`, `-j N`, `--from-chapter N`, `--no-resume`, `--allow-partial`, `--clean-cache`, `--watch`, `--chapters`, `-o`. |
| `sample` | A mastered retail sample clip (`--from-chapter`, `--start-seconds`, `--duration`, `--acx`). |
| `master-check <file>` | Measure a file vs ACX loudness/peak/noise-floor limits (`--json`). |
| `export-chapters` | Chapter cue sheet: `--format ffmetadata\|cue\|json`. |
| `podcast` | Per-chapter render + iTunes RSS feed (`--base-url`, `-o`). |
| `preview` | Short voice-QA clip in the cast voices (`--chapter`, `--seconds`). |
| `batch <files…>` | Batch-process books or a `--manifest <toml\|json>` (per-book metadata/cast). |
| `cache info\|clean\|clean-failed` | Manage the render cache. |
| `completion bash\|zsh\|fish` | Print a shell-completion script. |

## Engines & configuration

- **`--engine NAME`** (render/batch/preview/make/voices) selects a TTS backend resolved from `--engine` > `AUDIOBOOKER_ENGINE` > config > the built-in `voice-soundboard`. Plugins register via the `audiobooker.tts_engines` entry-point group.
- **Config file** — `.audiobookerrc` (TOML) or `[tool.audiobooker]` in `pyproject.toml`, merged under explicit CLI flags. Common keys: `output_format`, `output_profile`, `lang`, `jobs`, `booknlp_mode`, `emotion_mode`, `chapter_pause_ms`.

## Python API

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("book.epub")   # from_docx / from_pdf / from_folder / from_string
project.compile()
project.render("book.m4b", output_profile="acx")
```

See the [Usage](../usage/) page for the full API walkthrough, and [Architecture](../architecture/) for how the pieces fit together.
