<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="280" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## Features

- **Multi-voice synthesis**: Assign unique voices to each character
- **Dialogue detection**: Automatically identifies quoted dialogue vs narration
- **Emotion inference**: Rule+lexicon emotion labeling with configurable confidence
- **Voice suggestions**: Explainable, ranked voice recommendations per speaker
- **BookNLP integration**: Optional NLP-powered speaker co-reference resolution
- **Review-before-render**: Human-editable review format for correcting attributions
- **Persistent render cache**: Resume failed renders without re-synthesizing completed chapters
- **Dynamic progress & ETA**: Real-time rendering status with estimated completion time
- **Failure reports**: Structured JSON diagnostics on render errors
- **Language profiles**: Extensible language-specific rule abstraction
- **M4B output**: Professional audiobook format with chapter navigation
- **Project persistence**: Save/resume rendering sessions

## Installation

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## Optional Features

| Feature | Install | Config |
|---------|---------|--------|
| **TTS rendering** | `pip install audiobooker-ai[render]` or install voice-soundboard | Required for `render` |
| **BookNLP speaker resolution** | `pip install audiobooker-ai[nlp]` | `--booknlp on\|off\|auto` |
| **FFmpeg audio assembly** | System package (winget/brew/apt) | Required for M4B output |

## Quick Start

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

## Review Workflow

The review workflow lets you inspect and correct the compiled script before rendering:

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

**Review file format:**
- `=== Chapter Title ===` - Chapter markers
- `@Speaker` or `@Speaker (emotion)` - Speaker tags
- `# comment` - Comments (ignored on import)
- Delete blocks to remove unwanted utterances
- Change `@Unknown` to `@ActualName` to fix attribution

## Python API

```python
from audiobooker import AudiobookProject

# Create from EPUB
project = AudiobookProject.from_epub("mybook.epub")

# Or from raw text
project = AudiobookProject.from_string("Chapter 1\n\nHello world.", title="My Book")

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

## CLI Commands

| Command | Description |
|---------|-------------|
| `audiobooker new <file>` | Create project from EPUB/TXT |
| `audiobooker cast <char> <voice>` | Assign voice to character |
| `audiobooker cast-suggest` | Suggest voices for uncast speakers |
| `audiobooker cast-apply --auto` | Auto-apply top voice suggestions |
| `audiobooker compile` | Compile chapters to utterances |
| `audiobooker review-export` | Export script for human review |
| `audiobooker review-import <file>` | Import edited review file |
| `audiobooker render` | Render audiobook |
| `audiobooker info` | Show project information |
| `audiobooker voices` | List available voices |
| `audiobooker chapters` | List chapters |
| `audiobooker speakers` | List detected speakers |
| `audiobooker from-stdin` | Create project from piped text |

## Architecture

```
audiobooker/
├── parser/          # EPUB, TXT parsing
├── casting/         # Dialogue detection, voice assignment, suggestions
├── language/        # Language profiles (en, extensible)
├── nlp/             # BookNLP adapter, emotion inference, speaker resolver
├── renderer/        # Audio synthesis, cache, progress, failure reports
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**Flow:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Troubleshooting

**Render failure report**: On any render error, Audiobooker writes `render_failure_report.json` to the cache directory. This contains:
- Chapter index and title where the error occurred
- Utterance index, speaker, and text preview
- Voice ID and emotion that were being synthesized
- Full stack trace
- Cache and manifest paths

**Common FFmpeg issues**:
- `FFmpeg not found`: Install via your package manager (winget/brew/apt)
- `Chapter embedding failed`: Audiobooker falls back to M4A without chapter markers
- Audio quality: Default is AAC 128kbps at 24kHz (configurable in ProjectConfig)

**Cache issues**:
- `audiobooker render --clean-cache` — clear all cached audio and re-render
- `audiobooker render --no-resume` — ignore cache for this run only
- `audiobooker render --from-chapter 5` — start from a specific chapter

## Roadmap

- [x] v0.1.0 - Core pipeline (parse, cast, compile, render)
- [x] v0.2.0 - Review-before-render workflow
- [x] v0.3.0 - Persistent render cache + resume
- [x] v0.4.0 - Language profiles + input flexibility
- [x] v0.5.0 - BookNLP, emotion inference, voice suggestions, UX polish

## License

MIT
