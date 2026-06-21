---
title: Usage
description: Workflows, casting, ACX mastering, configuration, and the Python API.
sidebar:
  order: 2
---

## Two ways to work

**One-shot** — parse, auto-cast, compile, render, and master in a single command:

```bash
audiobooker make mybook.epub --acx --format m4b
```

**Staged** — full control at each step (recommended when you care about casting):

```bash
audiobooker new mybook.epub        # parse (EPUB/PDF/DOCX/TXT/MD or a folder)
audiobooker cast --interactive     # guided per-character casting
audiobooker compile                # dialogue, speakers, emotion
audiobooker report                 # unknown-attribution rate + weak lines
audiobooker review-export          # human-editable script
audiobooker review-import mybook_review.txt
audiobooker render --acx
audiobooker master-check mybook.m4b
```

## Casting

Casting is the one creative decision in the pipeline. Audiobooker gives you several routes:

```bash
audiobooker cast Alice af_bella --emotion warm   # assign one voice directly
audiobooker cast-suggest                          # ranked, explainable suggestions
audiobooker audition Alice --render               # A/B the top candidates as audio
audiobooker cast --interactive                    # walk each uncast speaker
audiobooker cast-fill --gender female --voices af_bella,af_sky,af_nova
audiobooker cast-apply --auto                     # apply the top suggestion to all
```

Reuse a cast across a series with **presets**, and hand a CSV to a collaborator:

```bash
audiobooker cast-preset save mystery-series
audiobooker cast-preset apply mystery-series      # on book 2
audiobooker cast-export --format csv cast.csv     # edit in a spreadsheet
audiobooker cast-import --format csv cast.csv
```

## Publishing to ACX / Audible

```bash
audiobooker render --acx           # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b  # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180  # a mastered retail sample clip
audiobooker podcast --base-url https://cdn.example.com/   # per-chapter audio + RSS
```

`master-check` verifies the *measurable* ACX specs (loudness, peak, noise floor) — ACX also has subjective/QC criteria a tool can't certify.

## Output formats

`--format m4b` (chapter markers + cover + series tags) · `mp3` · `opus` · `flac`. Add `--split` for one file per chapter, `--bitrate 192k` to override quality, and `export-chapters` for a cue/ffmetadata/json chapter sheet.

## Review workflow

Dialogue attribution is hard; human correction is fast. Export a script, fix it, re-import — nothing is silently changed (you're warned if an edited block matches no chapter).

```bash
audiobooker review-export
# === Chapter 1 === [id:ab12cd]   <- don't edit the [id:...] tag
#
# @narrator
# The door creaked open.
#
# @Unknown              <-- change to @Marcus
# "Hello?" he whispered.
#
# @Sarah (worried:0.7)  <-- emotion + optional intensity
# "Is anyone there?"
audiobooker review-import mybook_review.txt
```

## Configuration

Set defaults once in `.audiobookerrc` (TOML) next to your book, or `[tool.audiobooker]` in `pyproject.toml`. Precedence: **CLI flag > project config > `~/.audiobookerrc` > defaults**.

```toml
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Pluggable TTS engines

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

A plugin package registers itself via the `audiobooker.tts_engines` entry-point group — no fork required.

## Python API

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` and `compile(...)` accept an injected `engine=` (any object implementing the `TTSEngine` protocol) and a `progress_callback=` — so you can embed Audiobooker in a GUI or service.
