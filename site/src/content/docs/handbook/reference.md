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
| `cast <char> <voice>` | Assign a voice (`--emotion`, `--description`). |
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
| `report` | Compile quality: unattributed rate, guessed-speaker count, attribution verdict, the worst lines of each kind, emotion mix (`--json`). |
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
- **Config file** — `.audiobookerrc` (TOML) or `[tool.audiobooker]` in `pyproject.toml`, merged under explicit CLI flags. Common keys: `output_format`, `output_profile`, `lang`, `jobs`, `booknlp_mode`, `emotion_mode`, `chapter_pause_ms`. An unrecognised key is reported with the nearest valid one rather than silently ignored.

## The render cache

Rendering is the expensive step, so results are cached and `render` re-synthesises only what changed. `cache info` shows what is stored, `cache clean` clears it.

The cache key covers everything that changes the audio: the chapter text, the casting table (scoped per chapter, so recasting one character does not re-render the book), the voices, the TTS engine and its version, the output profile, the emotion preset and per-utterance intensity, and the per-character speed, pitch and emphasis. If a change would alter a single sample, it misses.

**Upgrading to 3.0 re-renders every chapter once.** Three audio-affecting inputs joined the key in this release, and a cache entry written by 2.x was stored without them — so it cannot prove its audio matches the render you are asking for. Paying that once is the point of the change: before it, switching `emotion_preset` to `literary` reported "Cached" on every chapter and handed back the `neutral` audio.

### `utterance_cache` — opt-in, off by default

```toml
[tool.audiobooker]
utterance_cache = true
```

By default the cache works a chapter at a time: change one line and the whole chapter is re-synthesised. With `utterance_cache = true` each utterance is cached individually, so an edit costs only the lines you touched. Measured on a 50-utterance chapter: editing one line re-synthesises 2,160 characters with it off, 40 with it on.

It is off by default for one reason, worth stating plainly: **the two paths do not produce byte-identical audio.** Per-utterance synthesis hands the engine one utterance at a time where chapter-level synthesis hands it the whole chapter, and a TTS engine's output depends on the span it is given. The pauses are the same either way — the speaker-change silence is spliced back in at assembly — but the speech itself is re-synthesised on different boundaries, so the result is equivalent rather than identical.

Flipping the setting is part of the cache key, so turning it on or off invalidates the cache rather than mixing audio from the two paths within one book.

Turn it on while you are iterating; turn it off for the final master if you need the bytes to be reproducible against an earlier render.

## Python API

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("book.epub")   # from_docx / from_pdf / from_folder / from_string
project.compile()
project.render("book.m4b", output_profile="acx")
```

See the [Usage](../usage/) page for the full API walkthrough, and [Architecture](../architecture/) for how the pieces fit together.
