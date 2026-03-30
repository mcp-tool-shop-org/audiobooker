# Audiobooker Handbook

**Audiobooker** is a Python CLI + library that converts EPUB/TXT/Markdown books into chaptered audiobooks by:

1) parsing the source into chapters, 2) detecting dialogue vs narration, 3) attributing speakers, 4) letting you review/edit the script, and 5) rendering multi-voice audio via **voice-soundboard**, then assembling a chaptered **M4B** via **FFmpeg**.

This handbook documents how the system works, what each feature does, and how to use it effectively.

---

## Table of Contents

- [1. Quick Start](#1-quick-start)
- [2. Concepts](#2-concepts)
- [3. Pipeline Overview](#3-pipeline-overview)
- [4. CLI Commands](#4-cli-commands)
- [5. Review Workflow](#5-review-workflow)
- [6. Casting and Voices](#6-casting-and-voices)
- [7. Rendering, Cache, and Resume](#7-rendering-cache-and-resume)
- [8. Language Profiles](#8-language-profiles)
- [9. PDF Support](#9-pdf-support)
- [10. Multi-Language Support](#10-multi-language-support)
- [11. Batch Processing](#11-batch-processing)
- [12. Audio Quality](#12-audio-quality)
- [13. Project Files and Data Formats](#13-project-files-and-data-formats)
- [14. Docker Usage](#14-docker-usage)
- [15. Troubleshooting](#15-troubleshooting)
- [16. Development and Testing](#16-development-and-testing)
- [17. Footnotes & Annotations](#17-footnotes--annotations)
- [18. Project Diff](#18-project-diff)
- [19. Emotion Management](#19-emotion-management)
- [20. Pronunciation Overrides](#20-pronunciation-overrides)
- [21. Roadmap](#21-roadmap)
- [ELI5](#eli5)

---

## 1. Quick Start

### Install

- Python: **3.10+** (3.11 recommended)
- Required runtime dependencies:
  - **voice-soundboard** (TTS engine)
  - **FFmpeg** (audio assembly)
  - **ebooklib** (EPUB parsing)

Typical dev install:

```bash
pip install -e .
# voice-soundboard is a sibling repo in many setups
pip install -e ../voice-soundboard
```

Install FFmpeg:

- Windows: `winget install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `apt install ffmpeg`

### Create → Cast → Compile → Review → Render

```bash
# Create a project
audiobooker new mybook.epub

# Assign voices
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm

# Compile (dialogue detection + attribution)
audiobooker compile

# Optional but recommended: review
audiobooker review-export
# Edit the exported review file
audiobooker review-import mybook_review.txt

# Render to audiobook
audiobooker render
```

---

## 2. Concepts

Audiobooker is built on a small set of core concepts:

### 2.1 Chapter
A **Chapter** is a chunk of source text with a title and index.

- `raw_text`: the original content for the chapter
- `utterances`: populated after compilation
- `audio_path` / `duration_seconds`: populated after rendering

### 2.2 Utterance
An **Utterance** is the atomic unit of speech output.

- `speaker`: who is speaking (e.g., `narrator`, `Alice`)
- `text`: what to speak
- `type`: narration vs dialogue
- `emotion`: optional style hint (e.g., `angry`, `whisper`)

Audiobooker compiles each chapter into a list of utterances, then renders them.

### 2.3 Casting Table
The **CastingTable** maps speaker names to voice IDs (from voice-soundboard), plus optional default emotions.

It also defines how to handle unknown speakers and what to do when nothing matches.

### 2.4 Project
A **Project** (saved as `.audiobooker`) is the persistent state:

- metadata: title/author
- chapters + compiled utterances
- casting table
- config settings
- render cache pointers and computed stats

---

## 3. Pipeline Overview

End-to-end flow:

```
Source (EPUB/TXT/MD)
  → Parser
  → Chapters
  → Dialogue Detection
  → Speaker Attribution
  → Utterances
  → Review Export/Import (optional)
  → TTS (voice-soundboard)
  → Chapter WAVs
  → FFmpeg assembly
  → M4B (or M4A fallback when chapters cannot embed)
```

What’s important about this design:

- **Stage separation:** parsing, attribution, review, rendering, and assembly are cleanly separated.
- **Human control point:** the review workflow allows correcting mistakes before you spend compute.
- **Resumability:** chapter WAVs and a manifest allow continuing after failure without re-rendering everything.

---

## 4. CLI Commands

Audiobooker ships a focused CLI. The following commands are available:

### 4.1 `new`
Create a new project from a source file.

```bash
audiobooker new book.epub
# optional:
audiobooker new book.txt --lang en -o book.audiobooker
```

Supported formats: `.epub`, `.txt`, `.md`.

### 4.2 `from-stdin`
Create a project from text piped via stdin.

```bash
cat book.txt | audiobooker from-stdin --title "My Book" --author "Me" -o mybook.audiobooker
```

### 4.3 `cast`
Assign a voice to a character.

```bash
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
```

Notes:
- Character names are stored with a canonical lookup key (case-insensitive, `casefold()`), but the display name is preserved.

### 4.4 `compile`
Compile chapters into utterances (dialogue detection + attribution).

```bash
audiobooker compile
```

The CLI prints uncast speakers after compilation so you can assign voices.

### 4.5 `review-export` / `review-import`
Export the compiled script to a human-editable format, then re-import edits.

```bash
audiobooker review-export
# edit mybook_review.txt
audiobooker review-import mybook_review.txt
```

### 4.6 `render`
Render audio and assemble the final audiobook.

```bash
audiobooker render
```

Useful flags:

- `-o/--output <path>`: output filename
- `-c/--chapter <index>`: render a single chapter (0-indexed)
- `--no-resume`: ignore cache and re-render everything
- `--from-chapter N`: start rendering at chapter N
- `--allow-partial`: assemble even if some chapters failed
- `--clean-cache`: delete render cache before starting

### 4.7 `voices`
List voices available from voice-soundboard.

```bash
audiobooker voices
# optional filters:
audiobooker voices --gender female
audiobooker voices --search george
```

### 4.8 `info`, `chapters`, `speakers`
Introspection commands:

- `info`: show project details (use `--verbose` for more)
- `chapters`: list chapter titles
- `speakers`: list detected speakers

---

## 5. Review Workflow

Audiobooker’s review workflow is the main “quality lever.” Dialogue attribution is hard; human correction is fast.

### 5.1 Why review?
- Correct mis-attributed speakers (common when multiple characters are in one scene)
- Add/adjust emotions for delivery
- Remove junk lines (e.g., OCR artifacts)

### 5.2 Review file format
The exported review file is a plain text script with chapter headers and speaker tags.

Example:

```text
=== Chapter 1 ===

@narrator
The door creaked open.

@Unknown
"Hello?" he whispered.

@Sarah (worried)
"Is anyone there?"
```

Rules:
- `=== Chapter Title ===` starts a new chapter block
- `@Speaker` or `@Speaker (emotion)` selects speaker and optional emotion
- Lines following a speaker tag are part of that utterance until the next speaker tag
- `# comments` are ignored on import
- **Deleting** a block removes that utterance

### 5.3 Casing stability
Speaker lookups are canonicalized (casefold + strip). Review import/export preserves display casing, while keeping stable keys internally.

---

## 6. Casting and Voices

### 6.1 How casting works
During rendering, each utterance’s speaker is mapped to:

- `voice_id` (required)
- `emotion` (optional)

Mapping priority:

1) Exact character entry in the casting table
2) Default narrator (if set and cast)
3) Fallback voice (`fallback_voice_id`) as the ultimate last resort

### 6.2 Configurable fallback voice
The fallback voice is **not hard-coded**; it is controlled by:

- `ProjectConfig.fallback_voice_id`
- `CastingTable.fallback_voice_id`

Best practice: set it to your narrator voice.

### 6.3 Voice validation
If `ProjectConfig.validate_voices_on_render` is enabled (default: `True`), Audiobooker validates that:

- all cast voice IDs exist in voice-soundboard
- the fallback voice exists

This catches “works on my machine” issues early.

### 6.4 Inline overrides
You can override speaker/emotion inline in the source text:

```text
[Alice|angry] "How dare you!"
[Bob|whisper] "Shh."
[narrator] The room fell silent.
```

Inline overrides are parsed during compilation and take precedence for that specific line/segment.

---

## 7. Rendering, Cache, and Resume

Rendering has two distinct parts:

1) **Synthesis:** utterances → chapter WAV files (via voice-soundboard)
2) **Assembly:** chapter WAVs → final M4B (via FFmpeg)

### 7.1 The render cache
Audiobooker writes chapter WAVs into a stable cache directory under the project:

```
<project_dir>/.audiobooker/cache/
  chapters/
    chapter_0000.wav
    chapter_0001.wav
  manifests/
    render_v1.json
```

### 7.2 Cache manifest
A manifest entry tracks “is this WAV still valid for the current input?” by hashing:

- chapter text
- casting table inputs
- audio-affecting render parameters

If hashes match and the WAV exists, the chapter is **skipped** on rerun.

### 7.3 Resume behavior
By default, Audiobooker resumes safely:

- Completed chapters are not re-rendered.
- If a render fails at chapter 15, chapters 0–14 remain usable.
- Rerun `audiobooker render` to continue.

To force full rerender:

```bash
audiobooker render --no-resume
```

To clean cache:

```bash
audiobooker render --clean-cache
```

### 7.4 Partial assembly
Normally, assembly requires all chapters to be rendered.

If you want “best effort output”:

```bash
audiobooker render --allow-partial
```

### 7.5 FFmpeg chapter embedding failures
If FFmpeg fails to embed chapters into M4B, Audiobooker may fall back to producing M4A. When this happens, it should surface the reason and stderr excerpt so you can fix the environment.

---

## 8. Language Profiles

Audiobooker separates language-specific heuristics into a **LanguageProfile**.

### 8.1 What a profile controls
- supported quote characters (straight quotes, smart quotes)
- speaker attribution verbs and patterns
- blacklist words to avoid false-positive names
- valid-name heuristics
- chapter heading patterns

### 8.2 Current status
The default and primary profile is:

- `en` (English)

You can choose language at project creation:

```bash
audiobooker new book.epub --lang en
```

Profiles are implemented under `audiobooker/language/`.

---

## 9. PDF Support

Audiobooker can parse PDF files when PyMuPDF is installed.

### 9.1 Installation

```bash
pip install -e '.[pdf]'
```

This installs the `pymupdf` package (also known as `fitz`).

### 9.2 Usage

```bash
# Create project from PDF
audiobooker new mybook.pdf

# Works the same as EPUB/TXT from here
audiobooker compile
audiobooker render
```

PDF parsing extracts text page-by-page and applies chapter detection heuristics. For best results, use PDFs with a clear chapter structure (headings, page breaks between chapters).

### 9.3 Limitations

- Scanned/image-only PDFs are not supported (no OCR)
- Complex multi-column layouts may produce garbled text ordering
- Tables and figures are skipped

---

## 10. Multi-Language Support

Audiobooker ships language profiles that tune dialogue detection, speaker attribution verbs, and chapter heading patterns for each supported language.

### 10.1 Available profiles

| Code | Language | Status |
|------|----------|--------|
| `en` | English | Full support (default) |
| `fr` | French | Dialogue detection + attribution |
| `de` | German | Dialogue detection + attribution |
| `es` | Spanish | Dialogue detection + attribution |
| `ja` | Japanese | Dialogue detection + attribution |

### 10.2 Usage

```bash
# Set language at project creation
audiobooker new livre.epub --lang fr

# Or from stdin
cat texto.txt | audiobooker from-stdin --lang es --title "Mi Libro"
```

The language profile affects quote-pair recognition, speaker verb patterns (e.g., "dit" for French, "sagte" for German), and chapter heading detection.

---

## 11. Batch Processing

Process multiple books in a single command.

### 11.1 Usage

```bash
# Process all supported files in a directory
audiobooker batch ./books/

# With options
audiobooker batch ./books/ --lang en --format mp3 --jobs 4
```

Batch mode discovers all `.epub`, `.txt`, `.md`, and `.pdf` files in the target directory and processes each one sequentially (compile + render). Output files are written alongside the source files or to a specified output directory with `--output-dir`.

### 11.2 Error handling

If a single book fails during batch processing, Audiobooker logs the error and continues with the remaining books. A summary report is printed at the end showing successes and failures.

---

## 12. Audio Quality

### 12.1 Audio normalization

Audiobooker can normalize audio levels across chapters so listeners do not need to adjust volume between quiet and loud sections.

Normalization is applied as a post-render step before final assembly. It targets a consistent loudness (LUFS) across all chapter WAVs.

Enable via config:

```python
config = ProjectConfig(normalize_audio=True)
```

### 12.2 SSML support

For fine-grained control over speech synthesis, Audiobooker supports SSML (Speech Synthesis Markup Language) preprocessing. SSML tags in your source text are passed through to the TTS engine:

- `<break time="500ms"/>` -- pauses
- `<emphasis level="strong">` -- stress
- `<prosody rate="slow">` -- pacing

SSML is stripped during dialogue detection so it does not interfere with speaker attribution, then re-injected for rendering.

### 12.3 Pronunciation overrides

Custom pronunciations for proper nouns, place names, or technical terms:

```python
config = ProjectConfig(
    pronunciation_overrides={
        "Cthulhu": "kuh-THOO-loo",
        "Hermione": "her-MY-oh-nee",
    }
)
```

Or via CLI:

```bash
audiobooker new book.epub --pronunciation "Cthulhu=kuh-THOO-loo"
```

---

## 13. Project Files and Data Formats

### 9.1 `.audiobooker` project file
Projects are saved as JSON with a schema version.

They include:

- config
- chapters
- utterances
- casting

This makes projects portable and scriptable.

### 9.2 Script format for voice-soundboard
Utterances can be rendered to a dialogue-script line format like:

```
[S1:Alice] (angry) How dare you!
```

This is the bridge format used for synthesis.

---

## 14. Docker Usage

A Dockerfile is included for containerized builds. Typical usage patterns:

- Build image
- Provide a project and run compile/render inside the container
- Mount an output directory

Because TTS and FFmpeg can involve system dependencies, Docker is often the simplest way to get a consistent environment.

---

## 15. Troubleshooting

### 15.1 “CI passes but render fails locally”
Common causes:
- voice-soundboard not installed or not on `PYTHONPATH`
- FFmpeg missing or not in PATH
- voice ID doesn’t exist in the local voice roster

Fixes:
- run `audiobooker voices` to verify availability
- ensure FFmpeg runs: `ffmpeg -version`
- enable/keep `validate_voices_on_render=True`

### 15.2 Unknown speakers everywhere
Likely causes:
- dialogue attribution verbs don’t match the writing style
- missing quotes or unusual formatting

Fixes:
- use `review-export` and patch attributions
- add inline overrides for tricky passages

### 15.3 Chapters missing from EPUB
If EPUB sections are very short, Audiobooker may drop them based on `min_chapter_words`.

Fixes:
- set `ProjectConfig.min_chapter_words` lower
- keep titled short chapters using `keep_titled_short_chapters=True`

### 15.4 Chapter markers missing in the final file
This typically indicates FFmpeg chapter embedding failed.

Fixes:
- verify FFmpeg build supports metadata/chapters
- inspect stderr excerpt from Audiobooker output

---

## 16. Development and Testing

### 16.1 Repository structure

```
audiobooker/
  parser/            EPUB/TXT parsing
  casting/           dialogue detection + attribution + voice registry
  language/          language profiles
  renderer/          TTS + caching + ffmpeg assembly
  review.py          review format import/export
  models.py          core immutable-ish models
  project.py         AudiobookProject orchestration
  cli.py             CLI entrypoint
tests/
  ... unit tests and smoke tests
```

### 16.2 Test strategy
Audiobooker’s tests focus on:

- model serialization/deserialization
- parser correctness
- dialogue detection heuristics
- review import/export round-trips (including edge cases)
- renderer behavior using fakes/mocks (so CI doesn’t require FFmpeg or voice-soundboard)
- resume/cache correctness

Run tests:

```bash
pytest -q
```

---

## 17. Footnotes & Annotations

Audiobooker detects footnotes in source text and handles them according to `ProjectConfig.footnote_behavior`.

### 17.1 Behavior modes

| Mode | Effect |
|------|--------|
| `inline` (default) | Footnotes are read in place, narrated where they appear |
| `end` | Footnotes are collected and read at the end of the chapter |
| `skip` | Footnotes are silently removed from the output |

### 17.2 Configuration

```python
config = ProjectConfig(footnote_behavior="end")
```

Footnote utterances have `utterance_type=UtteranceType.FOOTNOTE`, making them easy to filter or restyle in the review workflow.

---

## 18. Project Diff

Compare two project versions to see what changed. Useful after re-importing a review file or re-compiling with different settings.

### 18.1 Usage

```python
old_project = AudiobookProject.load("v1.audiobooker")
new_project = AudiobookProject.load("v2.audiobooker")

changes = new_project.diff(old_project)
# Returns:
#   added_chapters: list of new chapter titles
#   removed_chapters: list of removed chapter titles
#   changed_utterances: list of {chapter, index, field, old, new}
```

Chapters are matched by ID when available, falling back to index-based comparison.

---

## 19. Emotion Management

After compilation, you can inspect and override emotion labels on individual utterances.

### 19.1 Listing emotions

```python
emotions = project.list_emotions()
# Returns: {chapter_index: {"angry": 3, "neutral": 15, "whisper": 1}}
```

### 19.2 Overriding an emotion

```python
project.override_emotion(chapter_index=2, utterance_index=5, emotion="angry")
```

This is useful for fine-tuning delivery after the automatic emotion inference pass.

---

## 20. Pronunciation Overrides

Custom pronunciations for proper nouns, place names, or technical terms that the TTS engine mispronounces.

### 20.1 Configuration

```python
config = ProjectConfig(
    pronunciation_overrides={
        "Cthulhu": "kuh-THOO-loo",
        "Hermione": "her-MY-oh-nee",
    }
)
```

### 20.2 CLI

```bash
audiobooker new book.epub --pronunciation "Cthulhu=kuh-THOO-loo"
```

Overrides are applied during rendering and stored in the project file for reproducibility.

---

## 21. Roadmap

Planned milestones:

- **v1.1** — BookNLP integration for improved speaker clustering/suggestions
- **v1.2** — Voice suggestions based on character traits
- **v1.3** — Emotion inference from context

Design principle: these features should remain **optional layers** on top of the stable pipeline.

---

## ELI5

Imagine you have a big book, and you want it to become an audiobook.

Audiobooker works like a careful assembly line:

1) **It reads your book** and splits it into chapters.
2) **It figures out who is talking** by looking for quotes like “Hello!”
3) **You tell it which voice to use** for each character (like picking actors).
4) **It prints out a script** you can edit to fix mistakes (so you’re in control).
5) **It reads the script out loud** using the voices you chose.
6) **It glues the chapter audio together** into one audiobook file you can skip around in.

Best part: if it messes up on chapter 15, it doesn’t throw everything away — it keeps chapters 1–14 so you can fix the problem and keep going.
