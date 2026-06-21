<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="420" />
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm version"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI version"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks (<strong>M4B / MP3 / Opus / FLAC</strong>) — from one command.
</p>

This is the **`npx` wrapper** for [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). It bootstraps a private Python environment on first run, installs the pinned version from PyPI, and runs the real CLI — no manual `pip`, no changes to your system Python.

## Try it

```bash
npx @mcptoolshop/audiobooker --help
```

Or install globally:

```bash
npm install -g @mcptoolshop/audiobooker
```

First run sets up a managed virtualenv under your user data dir (`~/.local/share/audiobooker`, or `%LOCALAPPDATA%\audiobooker` on Windows) and installs `audiobooker-ai`. Every run after that starts instantly.

**Requires Python 3.10+** on PATH (the wrapper finds `python3` / `py`). If it's missing, the wrapper tells you exactly how to install it for your OS.

## Quick start

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## Audio rendering (voice synthesis)

Parsing, casting, compiling, and the review workflow work out of the box. **Rendering audio** needs the TTS engine, which pulls heavier dependencies — opt in when you're ready:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

Rendering also needs **FFmpeg** on PATH for M4B/MP3 assembly (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Run `audiobooker diagnose` to check your setup.

## What it does

- **Multi-voice casting** with explainable, ranked voice suggestions; `audiobooker audition <character>` lets you A/B candidate voices before you commit.
- **Dialogue detection + speaker attribution** (optional BookNLP co-reference), emotion inference, and reusable pronunciation lexicons.
- **Review-before-render**: export a human-editable script, fix attributions, re-import — nothing is silently changed.
- **ACX / Audible mastering**: `render --acx` plus `master-check` reports PASS/FAIL on loudness, peak, and noise floor.
- **Formats**: M4B (chapter markers + embedded cover + series metadata), MP3, Opus, FLAC; per-chapter export; retail sample clips.
- **7 language profiles** (en/fr/de/es/ja/it/pt) and a per-book config file for set-and-forget defaults.

## Environment variables

| Variable | Effect |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Provision the managed venv **with** the voice engine (for rendering) |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | Rebuild the managed environment from scratch |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | Override where the managed venv lives |

## Prefer pip?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## Links

- **Docs & handbook:** <https://mcp-tool-shop-org.github.io/audiobooker/>
- **Source:** <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI:** <https://pypi.org/project/audiobooker-ai/>

## License

[MIT](LICENSE) © mcp-tool-shop
