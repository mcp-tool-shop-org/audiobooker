---
title: Architecture
description: How Audiobooker works under the hood.
sidebar:
  order: 3
---

## Core concepts

### Chapter

A **Chapter** is a chunk of source text with a title and index. After compilation, it contains a list of utterances. After rendering, it carries an audio path and duration.

### Utterance

An **Utterance** is the atomic unit of speech output:

- `speaker` -- who is speaking (e.g., `narrator`, `Alice`)
- `text` -- what to speak
- `type` -- narration vs dialogue
- `emotion` -- optional style hint (e.g., `angry`, `whisper`)

### Casting table

The **CastingTable** maps speaker names to voice IDs (from voice-soundboard), plus optional default emotions. It also defines how to handle unknown speakers and a fallback voice.

Mapping priority:
1. Exact character entry in the casting table
2. Default narrator (if set and cast)
3. Fallback voice (`fallback_voice_id`) as the ultimate last resort

### Project

A **Project** (saved as `.audiobooker`) is the persistent state: metadata, chapters, compiled utterances, casting table, config settings, and render cache pointers.

## Pipeline

```
Source (EPUB/TXT/MD)
  -> Parser
  -> Chapters
  -> Dialogue Detection
  -> Speaker Attribution
  -> Utterances
  -> Review Export/Import (optional)
  -> TTS (voice-soundboard)
  -> Chapter WAVs
  -> FFmpeg assembly
  -> M4B (or M4A fallback when chapters cannot embed)
```

Key design principles:

- **Stage separation** -- parsing, attribution, review, rendering, and assembly are cleanly separated.
- **Human control point** -- the review workflow allows correcting mistakes before you spend compute.
- **Resumability** -- chapter WAVs and a manifest allow continuing after failure without re-rendering.

## Repository structure

```
audiobooker/
  parser/            EPUB/TXT parsing
  casting/           dialogue detection + attribution + voice registry
  language/          language profiles
  nlp/               BookNLP adapter, emotion inference, speaker resolver
  renderer/          TTS + caching + FFmpeg assembly
  review.py          review format import/export
  models.py          core models
  project.py         AudiobookProject orchestration
  cli.py             CLI entrypoint
```

## Rendering and cache

Rendering has two phases:

1. **Synthesis** -- utterances to chapter WAV files (via voice-soundboard)
2. **Assembly** -- chapter WAVs to final M4B (via FFmpeg)

### Cache structure

```
<project_dir>/.audiobooker/cache/
  chapters/
    chapter_0000.wav
    chapter_0001.wav
  manifests/
    render_v1.json
```

A manifest entry tracks validity by hashing the chapter text, casting table inputs, and audio-affecting render parameters. If hashes match and the WAV exists, the chapter is skipped on rerun.

### Resume behavior

- Completed chapters are not re-rendered
- If a render fails at chapter 15, chapters 0-14 remain usable
- Rerun `audiobooker render` to continue
- Use `--no-resume` to force full re-render or `--clean-cache` to wipe cache

## Language profiles

Audiobooker separates language-specific heuristics into a **LanguageProfile** that controls:

- Supported quote characters (straight quotes, smart quotes)
- Speaker attribution verbs and patterns
- Blacklist words to avoid false-positive names
- Valid-name heuristics
- Chapter heading patterns

The default profile is `en` (English). Choose language at project creation with `--lang`.

## Inline overrides

You can override speaker and emotion inline in the source text:

```
[Alice|angry] "How dare you!"
[Bob|whisper] "Shh."
[narrator] The room fell silent.
```

Inline overrides are parsed during compilation and take precedence for that specific line.
