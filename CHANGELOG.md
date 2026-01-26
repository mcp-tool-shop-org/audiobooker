# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
