# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-09-14

Major, because five things that used to be accepted now fail instead — the
`m4a` whole-book format, a `make` over an existing project, a render whose
attribution is mostly guesswork, a `compile()` where every chapter failed,
and any cache entry written by 2.x. Each one previously did something quiet
and wrong. The upgrade notes in the README list them.

A dogfood swarm in two passes — five health waves, then a feature pass of
four build agents with disjoint file ownership. 200+ findings, tests
1468 → 1947. Every CRITICAL/HIGH severity was re-rated by a model family that
did not author the finding, and the fixes were written test-first with the
failure observed before the fix.

The through-line is worth stating, because it shaped what got found: **defect
after defect was hiding behind something that reported success.** A quality
metric that improved as quality degraded. A cache that printed "Cached" over
audio that did not match the request. A gate that fired only after the money
was spent. And a feature listed under *Added* in a previous release with no
caller at all — which turned out never to have been runnable.

### Fixed — data loss and silent wrong output

- **`make` destroyed a hand-tuned project without asking.** Re-running it
  overwrote hand-cast voices, pronunciation overrides and edited chapter
  titles with a fresh auto-cast parse — and `batch *.epub` did it to every
  project in a directory in one command. The ordering was the real defect, not
  the missing prompt: a confirmation added without moving the *write* still
  destroys the work on the happy path where the render later fails. `make` now
  refuses when the target exists, and an authorised overwrite is staged beside
  the original and moved into place only after the render returns.
- **`compile()` returned normally when every chapter failed.** It recorded each
  per-chapter exception, set `status='error'`, then unconditionally overwrote
  that with `'idle'` ninety lines later and returned `None` exactly as a clean
  run does. A book that produced zero utterances printed "Compiled 0
  utterances" and exited 0. Total failure now raises; partial failures keep
  `status='error'` and report which chapters failed.
- **Spanish and Portuguese gave every line the previous speaker's voice.**
  Attribution never fired on the em-dash (*raya*) form that modern Spanish
  fiction uses almost exclusively, because the raya opener was being treated
  as a quote delimiter while the gap matcher twelve lines away explicitly
  treats it as an attributive separator. It failed silently and shifted the
  whole chapter: only the *first* line was ever `unknown`.
- **Loudness mastering silently vanished for every format but M4B.** The render
  path discovered unsupported assembler options by calling and catching
  `TypeError`, stripping from the end of a list — and `normalize` was last, so
  it was always the first casualty. `--acx` forces normalisation on, so an
  "ACX master" in MP3, Opus, FLAC or `--split` shipped with none, and the
  check that exists to catch that could not fire.
- **`--format wav` did not produce WAV.** It had no assembler and fell through
  to the M4B one, writing AAC-in-MP4 bytes to a `.wav` path. It also skipped
  the ffmpeg preflight, so a machine without ffmpeg rendered the whole book —
  every second of it paid for — before failing at assembly.
- **`render --clean-cache` ran before its own guards**, so a mistyped
  `--cover`, a bad chapter index, or even `--dry-run` destroyed the cache.
- **Every render crashed on a stock Windows console** with a
  `UnicodeEncodeError` from the progress bar's spinner glyph, after the TTS
  pass had already been paid for.
- Project files no longer embed absolute paths, so a `.audiobooker` file
  shared or attached to a bug report no longer carries the author's account
  name. Paths are stored relative to the project file, or `~`-relative when
  the target lives outside it, and projects are now portable between machines.
- **The cache said "Cached" and handed back audio that did not match the
  request.** Utterance `intensity` and `emotion_preset` both change the
  emitted SSML and neither was hashed, so switching to the `literary` preset
  and re-rendering reported every chapter cached and returned the `neutral`
  audio. A pronunciation override added after compile was likewise never
  spoken and re-rendering did not apply it — the single most likely reason
  anyone re-renders a book was the one edit the pipeline dropped.
- **Importing a review erased attribution provenance from the whole book**,
  including the lines the human had just corrected. A hand-edited line is now
  recorded as `user` at full confidence; untouched lines keep what the
  compiler worked out.
- **`utterance_cache = true` removed every pause in the book.** The
  inter-speaker break is emitted only when the SSML builder can see a
  *previous* speaker, and the incremental path hands it one utterance at a
  time — so the break was never emitted, and the stitch concatenates with
  `-c copy`, which inserts nothing. Every speaker change across the whole
  book lost its 750 ms of air and the dialogue ran together. Nothing warned:
  the durations looked plausible and the cache reported a hit rate it had
  genuinely earned, on audio that was not the audio the chapter path
  produces. Found while writing this release's documentation for the
  feature. The silence is now spliced in at assembly, where it belongs —
  baking it into a neighbour's cached WAV would make one utterance's bytes
  depend on the utterance before it, which is the coupling a per-utterance
  cache exists to avoid.
- **Nothing checked the output destination before synthesis.** An unwritable
  path cost all six chapters of a six-chapter book in TTS time and then
  raised a bare `OSError`. It now fails at zero chapters with a structured
  error that names the warm cache, so the retry is free.

### Fixed — the quality signal

The unattributed-dialogue rate, the tool's only attribution-quality number,
**improved as attribution degraded**. Narration inflated its denominator while
three separate defects each converted a would-be `unknown` into an *accepted
wrong speaker*, deflating the numerator. All four are fixed, the rate now
divides dialogue by dialogue, and `compile` prints it.

That fixed the arithmetic but not the blind spot underneath it. Turn-tracking
fills a gap by alternating the last two speakers and recorded every guess as a
**successful** attribution — so a guess *lowered* the unknown rate. `report`
returned quality `ok` on passages measured at 52% and 69% hand-scored speaker
accuracy.

Utterances now carry `attribution_source` (`tag` · `turn` · `nlp` · `inline` ·
`user`) and a confidence, threaded from the candidate tier the resolver was
already computing and discarding: a directly attached speech tag scores high,
an alternation guess is `turn` at 0.25. `compile_report` gains
`dialogue_unverified_rate`, `attribution_quality` and a source distribution.

The same passage now reads quality `ok` beside attribution_quality `failed`.
**A guess moves a line from `unknown` to low-confidence and the unverified
rate does not move**, so guessing harder can no longer improve the number.
`attribution_quality` carries its own thresholds (0.30 warn / 0.60 fail)
rather than inheriting the unknown-rate ones, because a guess is worse for the
user than an admission — an unknown line is visible in the report and the
review export, a confident wrong one is not.

### Fixed — output you read

- **`report` printed the narration-diluted rate this release replaced.**
  `compile` was moved to the dialogue-over-dialogue figure during the health
  pass; the command actually named `report` was left on the other one, so
  adding narration to a book still lowered its score without a single speaker
  being identified. It also said nothing about guesses, though
  `compile_report` had returned the count, the rate, the verdict, the source
  distribution and a ready-made list of the worst lines since the feature
  landed. A book where turn-tracking invented every speaker reported
  "Unattributed rate: 0.0%" and stopped talking.
- **`render --dry-run` renumbered the chapters it listed.** `--chapters 1-2,4`
  hands the renderer a filtered list and the table labelled each row with its
  position in that subset, so the preview showed `[0] [1] [2]` against
  chapters titled 1, 2 and 4 — in the one command you run to decide what to
  pass next.
- **45 printed strings could not render on a legacy Windows console.** Not
  cp1252, which encodes an em-dash fine at 0x97 — the OEM codepages a bare
  `cmd.exe` runs (437 in en-US, 850 in western Europe), which do not have one.
  Since the output streams degrade rather than crash, this failed silently.
  A test now checks the source, so the next one cannot.
- **The review file's own header printed a command that would not run.**
  `review-export` names the file from the book title, so a book with a space
  in its name produced `audiobooker review-import My Book_review.txt` —
  which argparse rejects, answering with all 34 subcommands. The CLI's
  printed copy had been fixed; the copy inside the file the user actually
  opens had not.

### Fixed — real books

The parsers were tested against clean fixtures. These are what a book off the
shelf actually does.

- **EPUB TOC splitting silently DELETED spine documents the TOC did not
  reference**, and played what remained in TOC order rather than reading
  order. Orphaned documents are recovered at their spine position and
  chapters emit in spine order — the spine is normative, the TOC is
  navigation.
- **DOCX tables were dropped entirely.** `document.paragraphs` excludes cell
  content, so anything laid out in a table simply was not in the audiobook.
- **PDF nested outlines were discarded** — taking `min(level)` kept only the
  shallowest entries, so an ordinary Part → Chapter tree collapsed and fell
  back to text heuristics.
- **Chapter titles were mangled.** `Chapter 1` produced the title `1`;
  `CHAPTER TWENTY-ONE` produced `Chapter TWENTY: ONE`; localized headings
  were re-worded into English. Bare Roman or Arabic section headings were not
  detected as headings at all.
- **Project Gutenberg boilerplate was narrated**, with the licence fused onto
  the end of the last real chapter where `chapters exclude` could not reach
  it.

### Added

- **WAV output** (`--format wav`) — a real assembler, PCM, reported honestly as
  carrying no chapter markers rather than as a failed chapter mux.
- **Opus and FLAC are selectable.** Both had working assemblers and were
  advertised in the README, but `--format` refused them and the config
  validator rejected `opus` outright.
- `render` refuses a book whose attribution failed, rather than proceeding
  into a paid TTS run; `--force` overrides.
- `make --dry-run`, `make --overwrite-project`, `cache clean --dry-run` and
  `cache clean -y`, and a `diagnose` that reports render-readiness and exits
  non-zero when required components are missing.
- `--jobs` serialises a TTS engine that has not declared itself thread-safe,
  instead of entering one engine from N threads and producing interleaved
  audio that passes every size and duration check.
- **The per-utterance incremental cache is now reachable** (`utterance_cache`
  — opt-in, off by default). It shipped complete, tested and namespaced in
  2.1.0 with zero callers; wiring it revealed it had never been runnable, as
  the stitch step passed no `-f` to ffmpeg while the render path hands it a
  `.wav.tmp` scratch name. Its tests passed because the fakes never reached
  that call. Wiring it as-written would also have *changed the audio*:
  `render_chapter` built its script without the casting table while the
  incremental path built it with, so per-character speed, pitch and emphasis
  reached synthesis only on the path nobody could take. Both ends are fixed.
  Measured: editing one line of a 50-utterance chapter re-synthesises 2,160
  characters with the cache off and 40 with it on.
- `casting_hash` is scoped per chapter, so recasting one character no longer
  re-renders the whole book.
- `make --review`, phase-by-phase narration from `make`, and a
  nearest-valid-key suggestion when a config file carries an unknown key.
- `--json` now covers the **error** path — structured `code` / `message` /
  `hint` / `retryable` — and five more commands. `errors.structured()`
  existed and had never been called.

### Changed

- `diagnose` exits non-zero when the machine cannot render. It previously
  printed "All checks passed." with no ffmpeg and no voice engine installed.
- `--format m4a` is no longer a whole-book option — it always meant one file
  per chapter, and previously produced a single M4B under an `.m4a` name. It
  remains available on `podcast --format`, whose accepted set was widened.
- **`render` refuses a book whose attribution is mostly guesswork**, before
  spending a TTS run rather than after. The gate `--force` advertised did
  exist, but it fired only above 30% of *all* utterances and from inside
  `render_project` — after the progress bar had started — so a typo'd
  secondary character sailed through at 28.6%. The gate now reads
  `attribution_quality`, which can see a guess, rather than the unattributed
  rate, which a guess makes look better.
- **Render cache manifest v3.** Three audio-affecting inputs joined the cache
  keys: utterance intensity, `emotion_preset`, and `utterance_cache`; the
  casting key gained per-character speed/pitch/emphasis and per-chapter
  speaker scoping. A v2 entry was written without them and cannot prove its
  WAV matches the render about to run, **so the first render after upgrading
  re-renders every chapter once.** That cost is deliberate — the alternative
  is what shipped before the bump, where switching emotion preset reported
  "Cached" on every chapter and returned the old audio.
- Every printed chapter reference now carries both numbering schemes.
- The README no longer claims ACX/Audible submittability. It documents the ACX
  **audio spec** as a mastering target, states the RMS/peak/noise-floor
  numbers that `master-check` actually measures, and says plainly that ACX's
  standard submission flow is for human narration, pointing AI-narrated titles
  at the routes that accept them.

### Internal

- One output-format table replaces six drifting allowlists.
- Four hand-maintained copies of the version reduced to two derived ones.
- A vacuous assertion sweep: four tests that could not fail in any
  environment, one of which was standing over the Spanish attribution bug.
- `tests/test_e2e_smoke.py` ran in no environment at all — skipped locally,
  ignored in CI, and its Makefile target invoked by nothing.
- `make audit` audited nothing: `--strict --skip-editable` turned the skip of
  the repo's own editable install into a collection failure, exiting 1 after
  one line and taking `make verify` with it.
- Four documented `from_*` constructors raised `TypeError` on the
  `title`/`author` keyword arguments their own docstrings advertise. Only the
  documented Python API hit it, which is the worst place for it to be.
- A non-ASCII book title crashed the CLI's own success message on a stock
  Windows console — project saved fine, exit code 2. Third instance of a bug
  fixed twice before; fixed once at the output primitive this time.
- `find_config_files()` got its first caller.

## [2.1.1] - 2026-06-21

### Fixed

- README logo and translation-nav links now use absolute URLs, so they render
  on the PyPI project page (relative `assets/` paths and `README.*.md` links
  break on PyPI, which serves the long-description in isolation).

## [2.1.0] - 2026-06-21

A full dogfood-swarm pass: a four-stage health audit (bug/security/data-loss +
proactive + humanization), then a feature pass. Tests 650 → 1231. Every
CRITICAL/HIGH finding was cross-verified by an independent (non-Claude) model.

### Added

- **Inputs**: DOCX parsing (Word `Heading 1/2`/`Title` styles); folder-of-files
  input (one file per chapter); TOC/nav-driven EPUB chapter splitting;
  `--chapter-delimiter` and `--force-text` flags; reusable pronunciation
  **lexicon** files (`pronunciation import/export`, CSV/JSON, phoneme passthrough);
  Markdown-aware text cleaning; Italian + Portuguese language profiles (now 7).
- **Casting**: `audition` command (A/B candidate voices per character);
  `cast --interactive`; bulk `cast-fill` by gender/role; named cast **presets**
  (`cast-preset`, reusable across a series); CSV cast sheets; emotion **intensity**,
  scene-level mood spans, and genre emotion **preset packs**; alias auto-discovery
  (`speakers --suggest-aliases`).
- **Output**: full metadata tags (narrator/genre/series/year); auto-embedded EPUB
  cover; **Opus** and **FLAC** formats; per-chapter `--split`; `--bitrate`;
  **ACX/Audible** mastering (`render --acx`) + `master-check`; retail `sample`;
  `export-chapters` (ffmetadata/cue/json); `podcast` RSS feed; utterance-level
  incremental cache.
- **Workflow**: `make` one-shot pipeline; **config file** (`.audiobookerrc` /
  `[tool.audiobooker]`); `--watch`; manifest-driven `batch`; shell `completion`;
  `chapters rename/reorder`; `report` (compile quality); `--json` on info/status/
  batch/report; observability surfaced from compile (speakers/emotions/NLP errors).
- **Ecosystem**: pluggable TTS-engine registry (`--engine`, `AUDIOBOOKER_ENGINE`,
  `audiobooker.tts_engines` entry-points); **npm launcher** (`npx
  @mcptoolshop/audiobooker`, venv-bootstrap); `pipx`/`uvx` install path.

### Changed

- `--lang` is now honored for EPUB **and** PDF (localized chapter patterns), not
  text only.
- `strip_page_numbers` no longer deletes bare standalone numbers (countdowns,
  years, verse numbers); only prefixed/centered page markers are stripped.
- Ambiguous abbreviations `St.`/`Co.` are no longer auto-expanded by default.
- ffmpeg is now checked **before** the render loop, not at assembly time.
- The upfront render estimate is relabeled "Audiobook length" (it was playback
  length, not wall-clock).

### Fixed

- **CRITICAL** `render --chapters` permanently deleted the unselected chapters
  from the saved project file.
- **HIGH** command injection via an untrusted book title in `--notify`
  (PowerShell / osascript).
- **HIGH** review round-trip collapsed `PAUSE`/`DIRECTION` utterance types.
- Review-import now warns on edited blocks that match no chapter (was a silent
  drop); review text starting with `#`/`@`/`===` survives the round-trip.
- Ordinal narration: "101st" → "one hundred first" (was "...oneth").
- EPUB zip-bomb size guard; PyMuPDF document handle closed on mid-parse errors;
  UTF-16 EPUB/TXT BOM handling; cover-art extension allowlist.
- Manifest crash-recovery now consults the `.bak`; render summary counters are
  lock-guarded; SSML output is XML-escaped.
- Error messages surface a `.hint` and honor `--debug` everywhere; `--silent`
  actually suppresses output; exit-code taxonomy made consistent.
- Removed the leaked developer path from install hints; one canonical
  `pip install voice-soundboard`.
- `load` subcommand wired; non-dict project files raise a clear error;
  German speaker-blacklist typo `nervos` → `nervös`.

### Security

- Release workflow (`release.yml`, renamed from `publish.yml`) publishes both PyPI (`audiobooker-ai`, protected `pypi` environment) and the npm launcher via OIDC Trusted Publishing.
- GitHub Actions on Node-24-compatible releases; `docker/login-action` v4.

## [2.0.1] - 2026-04-23

### Fixed

- **Structured error shape**: `RenderError`, `VoiceNotFoundError` now carry `code`/`message`/`hint`/`cause`/`retryable` fields with `.structured()` method. New `AudiobookerError` base class in `audiobooker.errors`.
- **Exit codes**: CLI now uses exit code 2 for runtime errors and 3 for partial success (batch). Previously only 0 and 1.
- **Stack trace gating**: All `traceback.print_exc()` calls gated behind `--debug` flag. No raw stacks in normal mode.
- **Logging levels**: Global `--silent` and `--debug` flags configure logging (silent=CRITICAL, debug=DEBUG, default=WARNING). Secret-pattern redaction filter on all log handlers.
- **Dependency updates**: Added `.github/dependabot.yml` for automated pip + GitHub Actions updates.

## [2.0.0] - 2026-03-30

### Added

- **Project diff**: `project.diff(other)` computes structured diffs between projects (added/removed chapters, changed utterances)
- **Footnote support**: `UtteranceType.FOOTNOTE` enum value and `ProjectConfig.footnote_behavior` (`inline`, `end`, `skip`)
- **BookNLP chunking**: NLP-powered speaker co-reference via `--booknlp on|off|auto` with graceful fallback
- **Voice audition**: `audiobooker preview` command renders a short sample from a chapter for voice validation
- **Emotion management**: `project.list_emotions()` per-chapter summary and `project.override_emotion()` for targeted edits
- **Pronunciation overrides**: `ProjectConfig.pronunciation_overrides` dict for custom word-to-pronunciation mappings
- **CLI `chapters` command**: `audiobooker chapters` lists all chapter titles and indices
- **CLI `cast-export`/`cast-import`**: Export and import casting tables for reuse across projects (via `cast-suggest` / `cast-apply --auto`)
- **Render dry-run**: `audiobooker render --dry-run` previews what would be rendered without executing
- **Batch dry-run**: `audiobooker batch --dry-run` shows what files would be processed without rendering
- **PDF parsing**: Extract text from PDF files via PyMuPDF (`pip install -e '.[pdf]'`)
- **Text normalization**: Configurable text cleaners pipeline for smart quotes, ligatures, and whitespace
- **SSML preprocessing**: Speech Synthesis Markup Language support for fine-grained voice control
- **Batch processing**: `audiobooker batch` command for processing multiple books in one run
- **Audio normalization**: Consistent volume levels across chapters via post-render normalization
- **Chapter selection**: `--chapters` flag to render specific chapters by index or range
- **Desktop notifications**: Optional notification when long renders complete
- **Language profiles (es/ja)**: Spanish and Japanese language profiles alongside English, French, German
- **Advanced dialogue detection**: Improved multi-speaker scene handling with conversation turn context
- **Stage directions**: Detection and handling of bracketed stage directions in script-format text (`UtteranceType.DIRECTION`, `UtteranceType.PAUSE`)
- **Per-character voice parameters**: Per-speaker speed, pitch, and voice tuning in casting table
- **Rich progress bars**: Optional rich-powered progress display (`pip install -e '.[rich]'`)
- **Compile report**: `compile_report()` method for summary statistics after compilation
- **Parallel rendering**: Multi-worker chapter rendering with `--jobs N` flag
- **MP3 output**: Direct MP3 export via `--format mp3` (alongside M4B, WAV, OGG, FLAC)
- **Conversation tracking**: Dialogue turn tracking for multi-speaker scenes
- **Multi-word speaker names**: Robust parsing of names like "Dr. Sarah Chen" in dialogue attribution
- **Character aliases**: Map alternate names to a primary character (`Character.aliases`)
- **Chapter merge/split/exclude**: `merge_chapters()`, `split_chapter()`, `exclude_chapter()` for chapter management
- **Cover art embedding**: `BookMetadata.cover_art_path` extracted from EPUB or user-provided, embedded in M4B output
- **Speed control**: Per-character `speed` (0.5-2.0) and global `ProjectConfig.global_speed`
- **Language profiles (fr/de)**: French and German language profile stubs alongside English
- **Casting validation**: Pre-render voice ID validation with `validate_voices_on_render` config
- **Text cleaning**: `ProjectConfig.clean_text` option for normalizing smart quotes and whitespace
- **Render status & cache CLI**: `audiobooker status` and `audiobooker cache info|clean|clean-failed` commands
- **Diagnose command**: `audiobooker diagnose` checks environment (deps, voice engine, FFmpeg)
- **Publish workflow**: `.github/workflows/publish.yml` for PyPI trusted publishing via OIDC
- **Release template**: `.github/release.yml` for auto-generated release notes from PR labels
- **Pre-commit config**: `.pre-commit-config.yaml` with ruff check + format hooks
- **Demo script**: `examples/demo.py` showing parse-compile-review cycle
- **API reference**: `docs/api-reference.md` documenting the core Python API
- **Common Issues section**: Top 3 issues in README with quick fixes

## [1.0.0] - 2026-02-27

### Added

- SECURITY.md with vulnerability reporting and data scope
- SHIP_GATE.md and SCORECARD.md for product standards
- Security & Data Scope section and scorecard in README
- Makefile with verify target (lint + test)
- Coverage reporting in CI with Codecov upload
- Dep-audit job in CI
- Ruff linting + pytest-cov + pip-audit in dev dependencies

### Changed

- Bumped version from 0.5.2 to 1.0.0
- Consolidated CI into single job with coverage

---

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
