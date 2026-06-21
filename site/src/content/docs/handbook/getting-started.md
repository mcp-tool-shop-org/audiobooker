---
title: Getting Started
description: Install Audiobooker and create your first audiobook.
sidebar:
  order: 1
---

Audiobooker converts **EPUB, PDF, DOCX, TXT, and Markdown** books (or a folder of per-chapter files) into chaptered, multi-voice audiobooks — **M4B, MP3, Opus, or FLAC** — with dialogue detection, emotion inference, a review-before-render workflow, and ACX/Audible-ready mastering.

## Requirements

- **Python 3.10+** (3.11 or 3.12 recommended)
- **FFmpeg** on PATH — for M4B/MP3 audio assembly
- **A TTS engine** for rendering audio — `voice-soundboard` (the `[render]` extra) by default
- `ebooklib` (EPUB) is installed automatically; `pymupdf` (PDF) and `python-docx` (DOCX) are optional extras

## Install

**Zero-install (Node):**

```bash
npx @mcptoolshop/audiobooker --help
```

**Python:**

```bash
pipx install audiobooker-ai            # isolated CLI
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

Install FFmpeg for your platform:

```bash
winget install ffmpeg   # Windows
brew install ffmpeg     # macOS
apt install ffmpeg      # Linux
```

Run `audiobooker diagnose` to confirm your environment (Python, dependencies, voice engine, FFmpeg).

## Optional extras

| Feature | Install | Notes |
|---------|---------|-------|
| **TTS rendering** | `pip install "audiobooker-ai[render]"` | Required for `render` (pulls voice-soundboard) |
| **PDF input** | `pip install "audiobooker-ai[pdf]"` | `audiobooker new book.pdf` |
| **DOCX input** | `pip install "audiobooker-ai[docx]"` | `audiobooker new book.docx` |
| **BookNLP speaker resolution** | `pip install "audiobooker-ai[nlp]"` | `--booknlp on\|off\|auto` |
| **Rich progress bars** | `pip install "audiobooker-ai[rich]"` | Auto-detected at runtime |

## Quick start

The fastest path is one command — parse, auto-cast, compile, render, and master:

```bash
audiobooker make mybook.epub --acx
```

Or the staged workflow, with control at each step:

```bash
audiobooker new mybook.epub            # parse into chapters
audiobooker cast --interactive         # guided per-character casting
audiobooker compile                    # dialogue, speakers, emotion
audiobooker report                     # see what's weak before rendering
audiobooker review-export              # human-editable script
# ...edit mybook_review.txt to fix attributions...
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise
```

The render cache means you can stop and resume at any point. If chapter 15 fails, chapters 0–14 stay cached and ready.
