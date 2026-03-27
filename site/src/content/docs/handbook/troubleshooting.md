---
title: Troubleshooting
description: Common issues and how to fix them.
sidebar:
  order: 4
---

## Render failure reports

On any render error, Audiobooker writes `render_failure_report.json` to the cache directory. This contains:

- Chapter index and title where the error occurred
- Utterance index, speaker, and text preview
- Voice ID and emotion that were being synthesized
- Full stack trace
- Cache and manifest paths

## Quick environment check

Run `audiobooker diagnose` before debugging render failures. It checks Python version, ebooklib, voice-soundboard, FFmpeg, and prints actionable hints for anything missing. Use `--json` for machine-readable output.

## CI passes but render fails locally

Common causes:
- voice-soundboard not installed or not on `PYTHONPATH`
- FFmpeg missing or not in PATH
- Voice ID doesn't exist in the local voice roster

Fixes:
- Run `audiobooker diagnose` to verify all dependencies
- Run `audiobooker voices` to verify voice availability
- Ensure FFmpeg runs: `ffmpeg -version`
- Keep `validate_voices_on_render=True` (the default)

## Voice not found errors

If rendering fails immediately with a `VoiceNotFoundError`, one or more voice IDs in your casting table do not exist in voice-soundboard.

Fixes:
- Run `audiobooker voices` to see what voices are available
- Re-cast the speaker with a valid voice ID: `audiobooker cast <speaker> <valid_voice>`
- To skip validation entirely, set `validate_voices_on_render` to `False` in your project config (not recommended)

## Unknown speakers everywhere

Likely causes:
- Dialogue attribution verbs don't match the writing style
- Missing quotes or unusual formatting

Fixes:
- Use `review-export` and patch attributions manually
- Add inline overrides for tricky passages: `[Alice|angry] "How dare you!"`

## Chapters missing from EPUB

If EPUB sections are very short, Audiobooker may drop them based on `min_chapter_words`.

Fixes:
- Set `ProjectConfig.min_chapter_words` lower
- Keep titled short chapters using `keep_titled_short_chapters=True`

## Chapter markers missing in the final file

This typically indicates FFmpeg chapter embedding failed.

Fixes:
- Verify FFmpeg build supports metadata/chapters
- Inspect stderr excerpt from Audiobooker output
- Audiobooker falls back to M4A without chapter markers when embedding fails

## Common FFmpeg issues

- **FFmpeg not found**: Install via your package manager (winget/brew/apt)
- **Chapter embedding failed**: Audiobooker falls back to M4A without chapter markers
- **Audio quality**: Default is AAC 128kbps at 24kHz (configurable in ProjectConfig)

## Cache issues

```bash
# Clear all cached audio and re-render
audiobooker render --clean-cache

# Ignore cache for this run only
audiobooker render --no-resume

# Start from a specific chapter
audiobooker render --from-chapter 5
```

## Docker

A Dockerfile is included for containerized builds. This is often the simplest way to get a consistent environment with all TTS and FFmpeg dependencies.

```bash
# Build the image
docker build -t audiobooker .

# Run a project inside the container
docker run --rm -v "$(pwd):/work" audiobooker audiobooker new /work/mybook.epub
```

Mount your working directory so the container can access source files and write output.
