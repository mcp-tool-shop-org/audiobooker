<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/mcp-tool-shop-org/audiobooker"><img src="https://codecov.io/gh/mcp-tool-shop-org/audiobooker/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT/PDF books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## Features

### Input & Parsing
- **EPUB / TXT / Markdown** source parsing with chapter detection
- **PDF support** (optional): Extract text from PDF files via PyMuPDF (`pip install -e '.[pdf]'`)
- **Text normalization**: Smart-quote cleanup, whitespace normalization, configurable text cleaners
- **Pronunciation overrides**: Custom word-to-pronunciation mappings for proper nouns and jargon
- **Footnote handling**: Configurable footnote behavior (`inline`, `end`, or `skip`)

### Dialogue & Attribution
- **Dialogue detection**: Automatically identifies quoted dialogue vs narration
- **Advanced dialogue detection**: Conversation turn-tracking for multi-speaker scenes
- **Stage directions**: Detects and handles bracketed stage directions in scripts
- **BookNLP integration**: Optional NLP-powered speaker co-reference resolution
- **Character aliases**: Map alternate names to a primary character

### Voice & Casting
- **Multi-voice synthesis**: Assign unique voices to each character
- **Voice suggestions**: Explainable, ranked voice recommendations per speaker
- **Emotion inference**: Rule+lexicon emotion labeling with configurable confidence
- **Per-character voice parameters**: Speed (0.5--2.0) and emotion per speaker
- **SSML preprocessing**: Speech Synthesis Markup Language support for fine-grained control

### Rendering & Output
- **Parallel rendering**: Multi-worker chapter rendering with `--jobs N`
- **Multiple output formats**: MP3, M4B, WAV, OGG, FLAC
- **Audio normalization**: Consistent volume levels across chapters
- **Cover art embedding**: Extracted from EPUB or user-provided, embedded in M4B output
- **Persistent render cache**: Resume failed renders without re-synthesizing completed chapters
- **Dynamic progress & ETA**: Real-time rendering status with estimated completion time
- **Failure reports**: Structured JSON diagnostics on render errors

### Language & Localization
- **5 language profiles**: English, French, German, Spanish, Japanese (`--lang en|fr|de|es|ja`)
- **Extensible profile system**: Add new languages via the `LanguageProfile` abstraction

### Workflow & Productivity
- **Review-before-render**: Human-editable review format for correcting attributions
- **Project diff**: Compare two project versions to see chapter and utterance changes
- **Batch processing**: Process multiple books in one run with `audiobooker batch`
- **Dry-run mode**: Preview render or batch operations without executing (`--dry-run`)
- **Voice audition**: Render a short sample to validate voice assignments (`audiobooker preview`)
- **Chapter management**: Merge, split, and exclude chapters before rendering
- **Emotion management**: List and override emotions per-utterance after compilation
- **Desktop notifications**: Get notified when long renders complete
- **Project persistence**: Save/resume rendering sessions

## Installation

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## Optional Features

| Feature | Install | Config |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` or install voice-soundboard | Required for `render` |
| **BookNLP speaker resolution** | `pip install -e '.[nlp]'` | `--booknlp on\|off\|auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | Auto-detected at runtime |
| **FFmpeg audio assembly** | System package (winget/brew/apt) | Required for M4B output |

## Quick Start

```bash
# 1. Create a project from your book
audiobooker new mybook.epub

# 2. Cast voices to characters
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
# Or auto-cast: audiobooker cast-suggest && audiobooker cast-apply --auto

# 3. Compile (dialogue detection + speaker attribution)
audiobooker compile

# 4. Review and correct the script (optional but recommended)
audiobooker review-export        # Creates mybook_review.txt
# Edit the file to fix attributions, then:
audiobooker review-import mybook_review.txt

# 5. Render the audiobook
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
| `audiobooker new <file>` | Create project from EPUB/TXT/MD/PDF |
| `audiobooker load <project>` | Load existing `.audiobooker` project |
| `audiobooker from-stdin` | Create project from piped text |
| `audiobooker cast <char> <voice>` | Assign voice to character |
| `audiobooker cast-suggest` | Suggest voices for uncast speakers |
| `audiobooker cast-apply --auto` | Auto-apply top voice suggestions |
| `audiobooker compile` | Compile chapters to utterances |
| `audiobooker review-export` | Export script for human review |
| `audiobooker review-import <file>` | Import edited review file |
| `audiobooker render` | Render audiobook (supports `--dry-run`, `--jobs N`, `--format`, `--cover`) |
| `audiobooker preview` | Render a short sample for voice validation (`--chapter N`, `--seconds S`) |
| `audiobooker batch <files...>` | Batch-process multiple books (supports `--dry-run`) |
| `audiobooker info` | Show project information |
| `audiobooker status` | Show render/cache status |
| `audiobooker voices` | List available voices (supports `--gender`, `--search`) |
| `audiobooker chapters` | List chapter titles and indices |
| `audiobooker speakers` | List detected speakers |
| `audiobooker cache info\|clean\|clean-failed` | Manage the render cache |
| `audiobooker diagnose` | Check environment (deps, voice engine, FFmpeg) |

## Full CLI Reference

Every command supports `-h` / `--help` for detailed usage. Key flags:

- **`new`**: `-o <project>`, `--lang <code>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <emotion>`, `--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`, `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`, `--jobs N`, `-o <path>`, `--format mp3|m4b|wav|ogg|flac`, `--cover <image>`
- **`preview`**: `--chapter N`, `--seconds S`, `-o <path>`
- **`batch`**: `--dry-run`, `--jobs N`, `--format <fmt>`, `--lang <code>`, `--output-dir <dir>`
- **`voices`**: `--gender <male|female>`, `--search <query>`
- **`info`**: `--verbose`

**Global flags** (before any command):
- `--silent` — suppress all output except errors
- `--debug` — enable debug logging and stack traces

**Exit codes:** `0` success · `1` user error · `2` runtime error · `3` partial success (batch)

## Architecture

```
audiobooker/
├── parser/          # EPUB, TXT, PDF parsing
├── casting/         # Dialogue detection, voice assignment, suggestions
├── language/        # Language profiles (en, extensible)
├── nlp/             # BookNLP adapter, emotion inference, speaker resolver
├── renderer/        # Audio synthesis, cache, progress, failure reports
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**Flow:**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Common Issues

| Problem | Fix |
|---------|-----|
| **FFmpeg not found** | Install via your package manager: `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `apt install ffmpeg` (Linux). FFmpeg must be on PATH. |
| **voice-soundboard not installed** | Clone and install the sibling repo: `git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`. Or install with `pip install -e '.[render]'`. |
| **BookNLP errors or slow startup** | BookNLP is optional. If you don't need NLP speaker resolution, set `--booknlp off` or leave it at `auto` (graceful fallback). Install with `pip install -e '.[nlp]'` only if needed. |

See the [handbook](docs/handbook.md#15-troubleshooting) for full troubleshooting guidance.

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

- [x] Core pipeline (parse, cast, compile, render)
- [x] Review-before-render workflow
- [x] Persistent render cache + resume
- [x] Language profiles + input flexibility
- [x] BookNLP, emotion inference, voice suggestions, UX polish
- [x] v1.0.0 - Production release

## Security & Data Scope

- **Data accessed:** Reads EPUB/TXT files from local filesystem. Writes audio files and cache manifests to output directories. Optionally uses voice-soundboard for TTS and FFmpeg for audio assembly.
- **Data NOT accessed:** No network requests. No telemetry. No user data storage. No credentials or tokens.
- **Permissions required:** Read access to input book files. Write access to output directories. Optional: FFmpeg on PATH.

## Scorecard

| Gate | Status |
|------|--------|
| A. Security Baseline | PASS |
| B. Error Handling | PASS |
| C. Operator Docs | PASS |
| D. Shipping Hygiene | PASS |
| E. Identity | PASS |

## License

[MIT](LICENSE)

---

Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
