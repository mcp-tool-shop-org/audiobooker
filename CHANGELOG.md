# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-02-14

### Added

- **BookNLP integration** (optional): NLP-powered speaker co-reference resolution
  - `--booknlp on|off|auto` CLI flag and `ProjectConfig.booknlp_mode`
  - `SpeakerResolver` pipeline stage improves "unknown" attributions when available
  - Graceful fallback to heuristics when BookNLP is not installed
- **Emotion inference**: Rule+lexicon baseline for utterance emotion labeling
  - `emotion_mode: off|rule|auto` and `emotion_confidence_threshold` config knobs
  - Verb-based hints (whispered→whisper, shouted→angry), lexicon (terrified→fearful), punctuation cues
  - Conservative: only applies when confidence >= threshold; never overrides explicit user emotions
- **Voice suggestions**: Explainable, opt-in voice casting assistance
  - `audiobooker cast-suggest` prints top N ranked voices per speaker with reasons
  - `audiobooker cast-apply --auto` applies top suggestions for uncast speakers
  - Heuristics: gender cues, narrator vs dialogue role, diversity (avoids reuse)
- **Performance benchmarks**: Reproducible timing harness in `tests/perf/`
  - Synthetic book generator (10k–200k words, 10–120+ chapters)
  - Parse, compile, emotion inference, and cache lookup benchmarks
  - Budget targets documented (no hard CI fail yet)
- **Renderer UX improvements**:
  - Dynamic progress with percent complete, cached/skipped counts, and ETA
  - Per-voice observed pace tracking for learned duration estimates
  - `render_failure_report.json` on error with chapter, utterance, voice, stack trace
- **Optional dependency extras** in pyproject.toml:
  - `pip install audiobooker-ai[render]` for voice-soundboard
  - `pip install audiobooker-ai[nlp]` for BookNLP

### Changed

- Version bumped to 0.5.0
- `ProjectConfig` gained `booknlp_mode`, `emotion_mode`, `emotion_confidence_threshold` with backward-compatible defaults
- Render engine uses `RenderProgressTracker` for status and `RenderFailureReport` for error bundles
- CLI commands table expanded: `cast-suggest`, `cast-apply`

## [0.4.0] - 2026-02-14

### Added

- **Language profiles**: Extracted all hardcoded English rules into `LanguageProfile` abstraction
  - Registry with `get_profile("en")`, extensible for future languages
  - Frozen dataclass bundles: quote pairs, speaker verbs, emotion hints, blacklist, chapter/scene patterns
- **Programmatic API**: `AudiobookProject.from_string()` and `.from_chapters()` factory methods
- **stdin CLI support**: `audiobooker from-stdin --title "My Book"` reads from pipe
- **`--lang` CLI flag** on `new` and `from-stdin` commands
- **Speaker casing consistency**: `CastingTable.normalize_key()` uses `casefold()` for i18n safety

### Changed

- All dialogue detection and chapter parsing routed through `LanguageProfile` (optional kwarg, defaults to English)
- `ProjectConfig.language_code` added with serialization

## [0.3.0] - 2026-02-14

### Added

- **Persistent render cache**: Content-addressable chapter WAVs with SHA-256 hashing
- **Resume on failure**: Reruns skip chapters with valid cached audio
- **Cache manifest**: Atomic JSON manifest tracks per-chapter status (ok/failed/pending)
- **CLI flags**: `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`
- **Renderer test seams**: Protocol-based `TTSEngine` and `FFmpegRunner` for hermetic testing
- **CI hardening**: Import gate, hermetic test suite, multi-Python matrix (3.10, 3.11, 3.12)

## [0.2.0] - 2025-01-26

### Added

- **Review-before-render workflow** - Export compiled scripts to human-editable format for review before rendering
  - `audiobooker review-export` - Export utterances to review file
  - `audiobooker review-import` - Import edited review file back into project
  - Review format uses `@Speaker (emotion)` tags and `=== Chapter ===` markers
  - Full roundtrip preservation of Unicode, smart quotes, em-dashes
  - Comments with `#` prefix are ignored during import
- **Stability hardening** - 22 edge case tests for:
  - Smart quotes and em-dashes from EPUB sources
  - Unicode text and speaker names
  - Windows/Unix line ending normalization
  - Chapter markers with special characters
  - Empty chapters and edge cases

### Changed

- Project methods added: `export_for_review()`, `import_reviewed()`, `preview_review_format()`

## [0.1.0] - 2025-01-25

### Added

- Initial release
- **Parsing**: EPUB and TXT/Markdown file parsing
  - Chapter detection with multiple delimiter patterns
  - YAML frontmatter support for metadata
- **Dialogue detection**: Heuristic-based speaker attribution
  - Quoted text detection (including smart quotes)
  - Speaker extraction from context ("said Alice" patterns)
  - Inline override syntax: `[Character|emotion] "text"`
  - Speaker validation with blacklist for false positives
- **Casting system**: Character-to-voice mapping
  - Manual casting table with voice IDs
  - Default narrator voice assignment
  - Character line counting
- **Rendering**: Voice-soundboard integration
  - Chapter-by-chapter rendering
  - Structured logging with error context
  - Progress callbacks
- **Output**: M4B audiobook assembly
  - FFmpeg-based chapter concatenation
  - Chapter metadata embedding
  - Configurable chapter pause duration
- **CLI**: Full command-line interface
  - `new`, `load`, `cast`, `compile`, `render`, `info`
  - `voices`, `chapters`, `speakers` listing commands
  - Auto-detection of project file in current directory
- **Project persistence**: JSON-based project files
  - Schema versioning for forward compatibility
  - Full state serialization and resumption
