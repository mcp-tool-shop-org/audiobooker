---
title: Beginners
description: New to Audiobooker? Start here for a guided introduction.
sidebar:
  order: 99
---

New to Audiobooker? This page walks you through the core ideas, a first project, and common questions so you can start making audiobooks with confidence.

## What is Audiobooker?

Audiobooker is a Python tool that converts EPUB, TXT, and Markdown books into chaptered audiobooks. It uses multi-voice text-to-speech synthesis (via voice-soundboard) to give each character a distinct voice, automatically detects dialogue, infers emotions, and produces M4B files with chapter navigation.

The pipeline works in stages: parse the book, detect dialogue, assign voices, let you review and correct attributions, render audio per chapter, then assemble the final audiobook. Each stage is independent, so you can stop, fix mistakes, and resume without re-rendering completed work.

## Prerequisites

Before you begin, make sure you have:

- **Python 3.10 or newer** -- check with `python --version`
- **voice-soundboard** -- the TTS engine that powers audio rendering
- **FFmpeg** -- for assembling chapter audio into M4B format
- **ebooklib** -- installed automatically when you install Audiobooker

Install FFmpeg for your platform:

```bash
# Windows
winget install ffmpeg

# macOS
brew install ffmpeg

# Linux
apt install ffmpeg
```

Install Audiobooker and voice-soundboard:

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .
pip install -e ../voice-soundboard
```

Run `audiobooker diagnose` to verify everything is set up correctly.

## Your first audiobook

Here is the simplest path from a book file to a finished audiobook:

```bash
# 1. Create a project from your EPUB
audiobooker new mybook.epub

# 2. Compile -- detects dialogue and attributes speakers
audiobooker compile

# 3. Check what speakers were found
audiobooker speakers

# 4. Assign voices to characters
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm

# 5. Render the audiobook
audiobooker render
```

That produces `mybook.m4b` with chapter markers. If rendering fails partway through, just run `audiobooker render` again -- completed chapters are cached and skipped.

For non-English books, pass `--lang` when creating the project:

```bash
audiobooker new mybook.epub --lang en
```

Only English (`en`) is built in currently, but the language profile system is extensible.

## Key concepts

**Project file (.audiobooker)** -- A JSON file that stores your book's chapters, casting table, config, and render state. Created by `audiobooker new` and updated as you cast, compile, and render. You can share this file or pick up where you left off.

**Casting table** -- Maps speaker names to voice IDs. The narrator gets a default voice (`af_heart`) automatically. You assign other characters with `audiobooker cast`. Use `audiobooker cast-suggest` to get ranked voice recommendations, or `audiobooker cast-apply --auto` to accept the top suggestion for every uncast speaker.

**Utterance** -- The atomic unit of the pipeline. Each utterance has a speaker, text, type (narration or dialogue), and an optional emotion. Compilation breaks raw chapter text into utterances; rendering synthesizes each one.

**Review workflow** -- After compiling, you can export a human-editable script (`audiobooker review-export`), fix any mis-attributed speakers or adjust emotions in a text editor, then import the corrections (`audiobooker review-import`). This is the main quality lever -- automated attribution is good but not perfect.

**Render cache** -- Each chapter's audio is cached by hashing its text, casting, and render parameters. If any of those change, only the affected chapters are re-rendered. Use `--no-resume` to force a full re-render, or `--clean-cache` to wipe the cache.

## Common workflows

### Quick render (trust the defaults)

```bash
audiobooker new mybook.epub
audiobooker cast-apply --auto
audiobooker render
```

### Careful review (recommended for long books)

```bash
audiobooker new mybook.epub
audiobooker compile
audiobooker review-export
# Edit mybook_review.txt in your text editor
audiobooker review-import mybook_review.txt
audiobooker render
```

### Pipe text from stdin

```bash
cat chapter.txt | audiobooker from-stdin --title "My Story" --author "Me"
audiobooker render
```

### Render a single chapter for testing

```bash
audiobooker render --chapter 0 -o test_chapter.wav
```

## FAQ

**Q: What voices are available?**
Run `audiobooker voices` to list all voices from voice-soundboard. Filter by gender with `--gender female` or search by name with `--search george`.

**Q: What if a speaker is mis-attributed?**
Use the review workflow: `audiobooker review-export`, change `@Unknown` to `@ActualName` in the text file, then `audiobooker review-import`. You can also use inline overrides in your source text: `[Alice|angry] "How dare you!"`.

**Q: Can I use BookNLP for better attribution?**
Yes. Install with `pip install audiobooker-ai[nlp]` and create your project with `--booknlp on`. When set to `auto` (the default), Audiobooker uses BookNLP if installed and falls back to heuristics otherwise.

**Q: How do emotions work?**
Audiobooker infers emotions using a rule-based system that checks attribution verbs, a curated word lexicon, and punctuation cues. It only applies an emotion when confidence is above the threshold (default 0.75). You can override any emotion in the review file or with inline tags. Set `emotion_mode` to `off` to disable inference entirely.

**Q: What if rendering fails?**
Audiobooker writes a `render_failure_report.json` to the cache directory with full diagnostics. Completed chapters remain cached. Fix the issue and run `audiobooker render` again to resume. Use `audiobooker diagnose` to check your environment.

**Q: What output formats are supported?**
The default is M4B (AAC with chapter markers). If FFmpeg cannot embed chapters, Audiobooker falls back to M4A. You can also render individual chapters as WAV files with `--chapter N`.

**Q: Can I use Docker instead of installing locally?**
Yes. A Dockerfile is included for a consistent environment with all dependencies. Build with `docker build -t audiobooker .` and mount your working directory: `docker run --rm -v "$(pwd):/work" audiobooker audiobooker new /work/mybook.epub`.

**Q: How does the voice naming convention work?**
Voice IDs follow a prefix convention: `af_` = American female, `am_` = American male, `bf_` = British female, `bm_` = British male. For example, `bm_george` is a British male voice and `af_bella` is an American female voice. Run `audiobooker voices --gender female` to filter by gender.

## Next steps

- **[Getting Started](/audiobooker/handbook/getting-started/)** -- detailed installation and first-project walkthrough
- **[Usage](/audiobooker/handbook/usage/)** -- full CLI command list, review workflow details, and Python API
- **[Reference](/audiobooker/handbook/reference/)** -- every command flag and configuration option
