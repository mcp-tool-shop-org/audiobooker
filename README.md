# Audiobooker

AI Audiobook Generator - Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.

## Features

- **Multi-voice synthesis**: Assign unique voices to each character
- **Dialogue detection**: Automatically identifies quoted dialogue vs narration
- **Review-before-render**: Human-editable review format for correcting attributions
- **Chapter management**: Preserves book structure with chapter markers
- **Flexible casting**: Manual voice assignment with emotion control
- **M4B output**: Professional audiobook format with chapter navigation
- **Project persistence**: Save/resume rendering sessions

## Installation

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## Quick Start

```bash
# 1. Create project from EPUB
audiobooker new mybook.epub

# 2. Assign voices to characters
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
audiobooker cast Bob am_michael --emotion grumpy

# 3. Compile and review
audiobooker compile
audiobooker review-export     # Creates mybook_review.txt

# 4. Edit the review file to fix attributions, then import
audiobooker review-import mybook_review.txt

# 5. Render
audiobooker render
```

## Review Workflow (v0.2.0)

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

# Cast voices
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")

# Compile (detect dialogue, attribute speakers)
project.compile()

# Review workflow
review_path = project.export_for_review()
# ... edit the file ...
project.import_reviewed(review_path)

# Render to M4B
project.render("mybook.m4b")

# Save project for later
project.save("mybook.audiobooker")
```

## Casting Table

The casting table maps characters to voices:

```python
# Cast with emotion
project.cast("Gandalf", "bm_george", emotion="wise", description="Ancient wizard")

# Cast dialogue character
project.cast("Frodo", "am_adam", emotion="nervous")

# Unknown speakers fall back to narrator
project.casting.unknown_character_behavior = "narrator"
```

## Inline Overrides

Override voice/emotion for specific passages in your source text:

```text
[Alice|angry] "How dare you!"

[Bob|whisper] "Shh, they'll hear us."

[narrator] The tension was palpable.
```

## Dialogue Detection

Audiobooker uses heuristics to detect dialogue:

1. Text in "double quotes" (or smart quotes) -> dialogue
2. Attribution patterns: "said Alice", "Bob whispered" -> speaker detection
3. Everything else -> narrator

For best results, ensure your source text has properly formatted dialogue.

## CLI Commands

| Command | Description |
|---------|-------------|
| `audiobooker new <file>` | Create project from EPUB/TXT |
| `audiobooker cast <char> <voice>` | Assign voice to character |
| `audiobooker compile` | Compile chapters to utterances |
| `audiobooker review-export` | Export script for human review |
| `audiobooker review-import <file>` | Import edited review file |
| `audiobooker render` | Render audiobook |
| `audiobooker info` | Show project information |
| `audiobooker voices` | List available voices |
| `audiobooker chapters` | List chapters |
| `audiobooker speakers` | List detected speakers |

## Project File Format

Projects are saved as JSON (`.audiobooker`):

```json
{
  "schema_version": 1,
  "title": "My Book",
  "author": "Author Name",
  "chapters": [...],
  "casting": {
    "characters": {
      "narrator": {"voice": "bm_george", "emotion": "calm"},
      "alice": {"voice": "af_bella", "emotion": "warm"}
    }
  }
}
```

## Requirements

- Python 3.10+ (3.11 recommended for voice-soundboard compatibility)
- [voice-soundboard](https://github.com/mcp-tool-shop/voice-soundboard) - TTS engine
- FFmpeg - Audio assembly
- ebooklib - EPUB parsing

## Architecture

```
audiobooker/
├── parser/          # EPUB, TXT parsing
├── casting/         # Dialogue detection, voice assignment
├── renderer/        # Audio synthesis
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**Flow:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio -> FFmpeg -> M4B with Chapters
```

## Roadmap

- [x] v0.1.0 - Core pipeline (parse, cast, compile, render)
- [x] v0.2.0 - Review-before-render workflow
- [ ] v0.3.0 - BookNLP integration for speaker suggestions
- [ ] v0.4.0 - Voice suggestion based on character traits
- [ ] v0.5.0 - Emotion inference from context

## License

MIT
