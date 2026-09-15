<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="480" />
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks — <strong>M4B / MP3 / Opus / FLAC / WAV</strong>, with chapter markers, cover art, and mastering to the <strong>ACX audio spec</strong>. From one command.
</p>

```bash
npx @mcptoolshop/audiobooker make mybook.epub --acx
```

Audiobooker detects dialogue, casts a distinct voice to each character, infers emotion, lets you review and correct everything before a single second is rendered, then masters the result to the ACX audio spec — so the output is a *finished* audiobook, not just generated audio.

## Install

**Zero-install (Node):**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python (CLI):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**Docker** — ffmpeg already inside, published to GHCR on every release:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
That one mount is enough, and `--rm` is safe: the render cache lives beside
the project file, not in a home directory, so a re-run **resumes** instead of
re-synthesizing the book.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Tagged `latest`, `3`, `3.0` and the exact version, pushed to GHCR on every
  release.
- The entrypoint **is** `audiobooker`, so pass the subcommand straight after
  the image name — don't repeat the program name.
- The cache lands at `<book-dir>/.audiobooker/cache`. That is why one bind
  mount covers persistence; losing it means paying for the whole TTS run
  again, not just re-muxing.
- `/ext` is an optional second mount, only for supplying your own TTS wheel.
- The container runs as a non-root UID 1000. On Linux, if the mounted
  directory isn't writable by that UID the cache can't be written — add
  `--user "$(id -u):$(id -g)"` or `chown` the directory. Docker Desktop on
  macOS and Windows handles this for you.

</details>

**Rendering audio** needs the [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTS engine (the `[render]` extra) and **FFmpeg** on PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Everything up to render — parse, cast, compile, review — works without them. Run `audiobooker diagnose` to check your setup.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

<details>
<summary><strong>Upgrading from 2.x</strong> — five things changed on purpose</summary>

Each of these is a case where 2.x accepted something and did the wrong thing
quietly. 3.0 refuses instead. Full detail in the [CHANGELOG](CHANGELOG.md).

- **Your first render re-renders every chapter, once.** Three inputs that
  change the audio — emotion preset, utterance intensity, per-character
  speed/pitch/emphasis — were missing from the cache key, so switching preset
  reported "Cached" and returned the old audio. They are in the key now, and a
  2.x cache entry cannot prove what produced it.
- **`--format m4a` is no longer a whole-book option.** It always meant one
  file per chapter; asking for a whole book in `m4a` previously produced a
  single M4B under an `.m4a` name. It is still valid on `podcast --format`.
- **`render` refuses a book whose attribution reads `FAILED`** rather than
  spending a TTS run on it. `--force` overrides. Run `audiobooker report` to
  see which lines it is objecting to.
- **`make` refuses when the project file already exists.** It used to
  overwrite hand-cast voices, pronunciation overrides and edited titles with a
  fresh auto-cast parse. Pass `--overwrite-project` if that is what you want.
- **`compile()` raises when every chapter fails** instead of returning `None`
  the way a clean run does. If you call it from Python, it can now throw.

</details>

## Quick start

```bash
# One command: parse -> auto-cast -> compile -> render -> master
audiobooker make mybook.epub --acx

# ...or the staged workflow, with control at each step:
audiobooker new mybook.epub            # parse into chapters (EPUB/PDF/TXT/MD/DOCX, or a folder)
audiobooker cast --interactive         # guided per-character casting
audiobooker audition Sarah --render    # A/B candidate voices for one character
audiobooker compile                    # detect dialogue, attribute speakers, infer emotion
audiobooker speakers                   # who did compile find?
audiobooker speakers --suggest-aliases # Dr. Merrin / Merrin / The Doctor?
audiobooker speakers merge "Dr. Merrin" Merrin   # fold those slots into one voice
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## Features

### Input & structure
- **EPUB, TXT, Markdown, PDF, DOCX**, or a **folder of per-chapter files** (Scrivener/Obsidian/serialized fiction).
- **TOC-driven EPUB splitting** — chapter boundaries and titles from the book's own table of contents.
- **DOCX** splits on Word `Heading 1/2`/`Title` styles; **PDF** detects headings (with a scanned-PDF guard); custom `--chapter-delimiter`.
- Smart text cleaning, Markdown-aware stripping, footnote handling, and a **reusable pronunciation lexicon** (`pronunciation import/export`, CSV/JSON, with phoneme passthrough).

### Casting & attribution
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.
- **Attribution you can audit.** Every line records *how* its speaker was decided — a speech tag, an inline override, co-reference, your own correction, or a bare alternating-turn guess — and `report` counts the guesses separately from the lines it could not attribute at all. A guess cannot improve the score, so the number goes down when the attribution gets worse, which is the only direction that is useful.

### Rendering & output
- **M4B** (chapter markers + embedded cover + series metadata), **MP3**, **Opus**, **FLAC**, **WAV**; per-chapter export; **podcast/RSS** feed export.
  WAV has no chapter atom, so a WAV render says so plainly rather than reporting a failed chapter mux — reach for it when the audio is going into an editor.
- **ACX-spec mastering** (`--acx`) + a **`master-check`** that reports PASS/FAIL on RMS loudness, peak, and noise floor; retail **`sample`** clips.
- Parallel rendering, a **persistent render cache** with resume, dynamic progress + ETA, and structured failure reports.
  The cache key covers everything that changes the audio — text, cast, voices, engine and version, profile, emotion preset and intensity — so a re-render that says "Cached" means it. An opt-in **per-utterance cache** (`utterance_cache`) narrows a re-render to the lines you actually edited.

### Workflow & ecosystem
- **`make`** one-shot pipeline · **config file** (`.audiobookerrc` / `[tool.audiobooker]`) · **`--watch`** mode · **manifest-driven batch** · shell completion.
- **7 language profiles** (en/fr/de/es/ja/it/pt) · **pluggable TTS engines** (`--engine`, entry-points — bring Piper/Coqui/ElevenLabs) · scriptable `--json` on most commands · structured exit codes.

## Mastering to the ACX audio spec

ACX publishes a precise, measurable audio target. It is the closest thing the
audiobook world has to a mastering standard, and it is worth hitting whatever
you do with the file afterwards.

| Requirement | ACX spec | What `--acx` does |
|---|---|---|
| Loudness | RMS between **−23 and −18 dBFS** | two-pass `loudnorm` at −20 LUFS, which lands inside that window for speech |
| Peak | at or below **−3 dBFS** | enforced in the same pass |
| Noise floor | at or below **−60 dBFS** | measured and reported — never silently "fixed" |
| Format | **44.1 kHz, 192 kbps CBR MP3** | sets the sample rate; add `--format mp3 --bitrate 192k` for the codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Two things the numbers above deserve:

**`master-check` measures unweighted RMS, not LUFS.** They are different
quantities and ACX gates on the former. The −20 LUFS figure is how the
mastering pass *gets* there — it is what `ffmpeg loudnorm` can target — not
what is checked afterwards.

**The noise floor is measured, not corrected.** It is the requirement that
most often fails, and it comes from the source audio. A tool that quietly
gated it would be hiding the one number you need to see.

### Where an AI-narrated audiobook can actually go

Meeting the spec is not the same as being accepted, and this is worth being
plain about: **ACX's standard submission flow is for human narration.** Its
April 2026 requirements list unauthorised text-to-speech and AI recordings
among the things it does not accept, so an AI-narrated title needs prior
authorisation from ACX rather than an ordinary submission.

Routes that do accept AI narration, generally with disclosure, include
Amazon's **Virtual Voice** through KDP (Amazon-only distribution) and
aggregators such as **Spotify Audiobooks for Authors**, **Author's Republic**
and **Kobo Writing Life**. Retailer policy in this area moves quickly —
check the current terms yourself rather than trusting this paragraph.

So: `--acx` is about the audio. Whether a retailer accepts an AI-narrated
title is their decision, not a property of the file you just produced.

## CLI commands

| Command | Description |
|---------|-------------|
| `make <file>` | One-shot: new → compile → auto-cast → render |
| `new <file\|folder>` | Create a project from EPUB/TXT/MD/PDF/DOCX or a folder |
| `from-stdin` | Create a project from piped text |
| `cast <char> <voice>` · `cast-interactive` | Assign voices (or guided per-speaker casting; also `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggest / auto-apply / bulk-assign voices |
| `cast-preset save\|list\|apply\|delete` | Reusable cast presets across books |
| `cast-export` · `cast-import <file>` | Round-trip the cast as JSON/CSV — hand-edit, or reuse across editions |
| `audition <char>` | A/B ranked candidate voices for one character (`--render`) |
| `compile` | Detect dialogue, attribute speakers, infer emotion |
| `report` | Compile quality: unattributed rate, guessed rate, worst lines, emotion mix |
| `review-export` · `review-import <file>` | Human-editable review round-trip |
| `render` | Render the audiobook (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Mastered retail sample · check against the ACX audio spec |
| `export-chapters` · `podcast` | Chapter cue sheet (ffmetadata/cue/json) · podcast RSS feed |
| `preview` · `batch` · `diagnose` | Voice QA clip · batch/`--manifest` · environment check (exits non-zero when the box cannot render) |
| `load <file>` | Open an existing `.audiobooker` project |
| `voices` · `chapters` · `speakers` · `speakers merge` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspect & manage (`speakers merge <from> <to>` folds duplicate names into one cast slot) |

Every command supports `-h/--help`. Global flags: `--silent`, `--debug`. **Exit codes:** `0` ok · `1` user error (including a book that would not compile, or a render refused because attribution failed) · `2` runtime · `3` partial (batch).

## Configuration

Set defaults once instead of re-passing flags — `.audiobookerrc` (TOML) next to your book, or `[tool.audiobooker]` in `pyproject.toml`. Precedence is **CLI flag > project config > user config (`~/.audiobookerrc`) > built-in defaults**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Pluggable TTS engines

The default engine is `voice-soundboard`, but the synthesis backend is swappable via setuptools entry-points (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

A plugin (`pip install audiobooker-piper`) registers itself; no fork required.

## Python API

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` and `compile(...)` accept an injected `engine=` (any object implementing the `TTSEngine` protocol) and a progress callback — embed audiobooker in a GUI or service.

## Architecture

```
audiobooker/
├── parser/      # EPUB, PDF, TXT/MD, DOCX, folder, language-aware splitting
├── language/    # 7 language profiles (quotes, speaker verbs, chapter patterns)
├── casting/     # dialogue detection, voice suggestion, presets, cast-fill
├── nlp/         # BookNLP adapter, emotion inference, speaker/alias resolution
├── renderer/    # synthesis, chapter+utterance cache, mastering, assembly, RSS
├── config_file.py · review.py · project.py · cli.py
```

```
Source (EPUB/PDF/DOCX/TXT/folder) -> Parser -> Chapters -> Dialogue & Emotion ->
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## Security & data scope

- **Network:** none — no telemetry, no data storage, no credentials. Reads your book files, writes audio + cache to your output dirs.
- **Permissions:** read access to inputs, write access to outputs; optional FFmpeg + a TTS engine on PATH.
- See [SECURITY.md](SECURITY.md).

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
