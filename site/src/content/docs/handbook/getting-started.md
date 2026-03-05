---
title: Getting Started
description: Install Audiobooker and create your first audiobook.
sidebar:
  order: 1
---

Audiobooker converts EPUB, TXT, and Markdown books into chaptered audiobooks with multi-voice synthesis, dialogue detection, and emotion inference.

## Requirements

- **Python 3.10+** (3.11 recommended)
- **voice-soundboard** (TTS engine)
- **FFmpeg** (audio assembly)
- **ebooklib** (EPUB parsing, installed automatically)

## Install

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
pip install -e ../voice-soundboard
```

Install FFmpeg for your platform:

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg

# Linux
apt install ffmpeg
```

## Optional features

| Feature | Install | Notes |
|---------|---------|-------|
| **TTS rendering** | `pip install audiobooker-ai[render]` or install voice-soundboard | Required for `render` |
| **BookNLP speaker resolution** | `pip install audiobooker-ai[nlp]` | `--booknlp on\|off\|auto` |
| **FFmpeg audio assembly** | System package (winget/brew/apt) | Required for M4B output |

## Quick start

```bash
# 1. Create project from EPUB
audiobooker new mybook.epub

# 2. Get voice suggestions
audiobooker cast-suggest

# 3. Assign voices (or auto-apply suggestions)
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
# Or: audiobooker cast-apply --auto

# 4. Compile and review
audiobooker compile
audiobooker review-export     # Creates mybook_review.txt

# 5. Edit the review file to fix attributions, then import
audiobooker review-import mybook_review.txt

# 6. Render
audiobooker render
```

The render cache means you can stop and resume at any point. If chapter 15 fails, chapters 0-14 remain cached and ready.
