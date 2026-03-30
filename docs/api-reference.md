# API Reference

Core Python API for Audiobooker. All public classes are importable from `audiobooker`.

```python
from audiobooker import (
    AudiobookProject, Chapter, Utterance,
    Character, CastingTable, ProjectConfig, BookMetadata,
)
```

---

## AudiobookProject

Main orchestrator for audiobook generation. Manages the full lifecycle from source parsing through rendering.

### Factory Methods

```python
# From EPUB file
project = AudiobookProject.from_epub(path: str | Path, **kwargs) -> AudiobookProject

# From TXT/Markdown file
project = AudiobookProject.from_text(path: str | Path, **kwargs) -> AudiobookProject

# From raw string (no file needed)
project = AudiobookProject.from_string(
    text: str,
    title: str = "Untitled",
    author: str = "",
    lang: str = "en",
    **kwargs,
) -> AudiobookProject

# From pre-split chapters
project = AudiobookProject.from_chapters(
    chapters: list[tuple[str, str]],  # (title, raw_text) pairs
    title: str = "Untitled",
    author: str = "",
    lang: str = "en",
    **kwargs,
) -> AudiobookProject

# Load saved project
project = AudiobookProject.load(path: str | Path) -> AudiobookProject
```

### Casting

```python
project.cast(
    name: str,              # Character name ("narrator", "Alice")
    voice: str,             # Voice ID ("af_bella", "bm_george")
    emotion: str = None,    # Default emotion
    description: str = None,
    speed: float = 1.0,     # 0.5-2.0
) -> Character

project.list_characters() -> list[str]
project.get_detected_speakers() -> set[str]
project.get_uncast_speakers() -> set[str]
```

### Compilation & Rendering

```python
project.compile(
    progress_callback: Callable[[int, int, str], None] = None,
) -> None

project.render(
    output_path: str | Path = None,
    progress_callback: Callable[[int, int, str], None] = None,
    resume: bool = True,
    from_chapter: int = None,
    allow_partial: bool = False,
    jobs: int = 1,          # Parallel render workers
    force: bool = False,
    output_format: str = None,  # "m4b", "mp3", "wav"
) -> Path
```

### Project Diff

```python
changes = project.diff(other: AudiobookProject) -> dict
# Returns:
# {
#     "added_chapters": list[str],       # Titles in other but not self
#     "removed_chapters": list[str],     # Titles in self but not other
#     "changed_utterances": list[dict],  # {chapter, index, field, old, new}
# }
```

### Voice Audition

```python
# CLI: audiobooker preview --chapter 0 --seconds 30 -o preview.wav
# Renders a short sample from a chapter for voice validation.
# No direct Python API — use the CLI command.
```

### Emotion Management

```python
# Per-chapter emotion summary
project.list_emotions() -> dict[int, dict[str, int]]
# Returns: {chapter_index: {"angry": 3, "neutral": 15, ...}}

# Override emotion on a specific utterance
project.override_emotion(
    chapter_index: int,
    utterance_index: int,
    emotion: str,
) -> None
```

### Chapter Management

```python
project.exclude_chapter(index: int) -> None
project.include_chapter(index: int) -> None
project.merge_chapters(start_index: int, end_index: int) -> Chapter
project.split_chapter(index: int, at_paragraph: int) -> tuple[Chapter, Chapter]
```

### Review Workflow

```python
project.export_for_review(output_path: str | Path = None) -> Path
project.import_reviewed(review_path: str | Path) -> dict
project.preview_review_format(chapter_index: int = 0) -> str
```

### Persistence

```python
project.save(path: str | Path = None) -> Path
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `total_words` | `int` | Total word count across all chapters |
| `estimated_duration_minutes` | `float` | Estimated duration at configured WPM |
| `total_duration_seconds` | `float` | Actual rendered duration |
| `info()` | `dict` | Full project summary |

---

## Chapter

A section of the book with raw text and compiled utterances.

```python
@dataclass
class Chapter:
    index: int                          # Chapter number (0-indexed)
    title: str                          # Chapter title
    raw_text: str                       # Original text content
    utterances: list[Utterance]         # Populated after compile()
    source_file: str | None = None
    audio_path: Path | None = None      # Populated after render()
    duration_seconds: float = 0.0
    skip: bool = False                  # Excluded from rendering
```

| Property | Type | Description |
|----------|------|-------------|
| `word_count` | `int` | Approximate word count |
| `estimated_duration_minutes` | `float` | Estimate at 150 WPM |
| `is_compiled` | `bool` | Has utterances |
| `is_rendered` | `bool` | Audio file exists |

---

## Utterance

A single spoken unit -- the atomic unit for synthesis.

```python
@dataclass
class Utterance:
    speaker: str                        # Character name
    text: str                           # Text to speak
    utterance_type: UtteranceType       # NARRATION or DIALOGUE
    emotion: str | None = None          # Emotion override
    chapter_index: int = 0
    line_index: int = 0
```

`UtteranceType` is an enum:

| Value | Description |
|-------|-------------|
| `NARRATION` | Narrative text (default) |
| `DIALOGUE` | Quoted character dialogue |
| `DIRECTION` | Stage directions (bracketed text) |
| `PAUSE` | Inserted pause between sections |
| `FOOTNOTE` | Footnote or annotation text |

---

## CastingTable

Maps characters to voice profiles. Central configuration for voice assignment.

```python
@dataclass
class CastingTable:
    characters: dict[str, Character]
    default_narrator: str = "narrator"
    unknown_character_behavior: str = "narrator"  # "narrator" | "skip" | "ask"
    fallback_voice_id: str = "af_heart"
```

### Methods

```python
table.cast(name, voice, emotion=None, description=None, speed=1.0) -> Character
table.get_voice(speaker: str) -> tuple[str, str | None]  # (voice_id, emotion)
table.get_speed(speaker: str) -> float
table.resolve_alias(speaker: str) -> Character | None
table.list_characters() -> list[str]
table.normalize_key(name: str) -> str  # casefold for i18n-safe lookup
```

---

## ProjectConfig

Project-level settings controlling parsing, compilation, and rendering behavior.

```python
@dataclass
class ProjectConfig:
    chapter_pause_ms: int = 2000
    narrator_pause_ms: int = 600
    dialogue_pause_ms: int = 400
    sample_rate: int = 24000
    output_format: str = "m4b"          # "m4b", "mp3", "wav", "ogg", "flac"
    fallback_voice_id: str = "af_heart"
    validate_voices_on_render: bool = True
    estimated_wpm: int = 150
    min_chapter_words: int = 50
    keep_titled_short_chapters: bool = True
    language_code: str = "en"
    booknlp_mode: str = "auto"          # "on", "off", "auto"
    emotion_mode: str = "rule"          # "off", "rule", "auto"
    emotion_confidence_threshold: float = 0.75
    global_speed: float = 1.0           # 0.5-2.0
    pronunciation_overrides: dict[str, str] = {}
    clean_text: bool = True
    footnote_behavior: str = "inline"   # "inline", "end", "skip"
```

---

## BookMetadata

Metadata for embedding in output audiobook files.

```python
@dataclass
class BookMetadata:
    cover_art_path: Path | None = None
    genre: str = ""
    series: str = ""
    series_index: int | None = None
    year: int | None = None
    narrator_name: str = ""
    publisher: str = ""
```

All model classes support `to_dict()` and `from_dict()` for JSON serialization.

---

## Text Cleaners

Text normalization pipeline for preprocessing source text before compilation.

```python
from audiobooker.parser.text_cleaners import normalize_text, TextCleanerPipeline

# Quick normalize (smart quotes, whitespace, ligatures)
cleaned = normalize_text(raw_text: str) -> str

# Custom pipeline
pipeline = TextCleanerPipeline([
    "smart_quotes",      # Normalize smart quotes to straight quotes
    "whitespace",        # Collapse multiple whitespace
    "ligatures",         # Expand ligatures (fi, fl, etc.)
    "dashes",            # Normalize em/en dashes
])
cleaned = pipeline.run(raw_text)
```

Cleaners are applied automatically when `ProjectConfig.clean_text` is `True`.

---

## PDF Parser

PDF text extraction (requires `pymupdf`).

```python
from audiobooker.parser.pdf import parse_pdf

# Extract chapters from PDF
chapters = parse_pdf(
    path: str | Path,
    lang: str = "en",
) -> list[tuple[str, str]]  # (title, text) pairs
```

Chapters are detected via heading heuristics and page-break patterns. Install with `pip install -e '.[pdf]'`.

---

## Audio Normalizer

Post-render audio normalization for consistent volume levels.

```python
from audiobooker.renderer.normalizer import normalize_chapter_audio

# Normalize a single chapter WAV to target LUFS
normalize_chapter_audio(
    wav_path: Path,
    target_lufs: float = -16.0,
) -> Path
```

Called automatically during assembly when `ProjectConfig.normalize_audio` is enabled.

---

## Compile Report

Summary statistics after compilation.

```python
# After project.compile()
report = project.compile_report() -> dict

# Returns:
# {
#     "total_chapters": int,
#     "total_utterances": int,
#     "total_words": int,
#     "speakers": list[str],
#     "uncast_speakers": list[str],
#     "dialogue_ratio": float,      # fraction of utterances that are dialogue
#     "estimated_duration_minutes": float,
# }
```

---

## Batch Command

Process multiple books from a directory.

```python
from audiobooker.cli import batch_process

# Programmatic batch processing
results = batch_process(
    input_dir: str | Path,
    output_dir: str | Path = None,
    lang: str = "en",
    output_format: str = "m4b",
    jobs: int = 1,
) -> list[dict]  # per-book result summaries
```

CLI equivalent:

```bash
audiobooker batch ./books/ --lang en --format mp3 --jobs 4 --output-dir ./output/
```
