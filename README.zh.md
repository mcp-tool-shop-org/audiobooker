<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks — <strong>M4B / MP3 / Opus / FLAC</strong>, with chapter markers, cover art, and <strong>ACX/Audible-ready</strong> mastering. From one command.
</p>

```bash
npx @mcptoolshop/audiobooker make mybook.epub --acx
```

Audiobooker 可以检测对话，为每个角色分配独特的配音，推断情感，让您在生成最终版本之前检查和更正所有内容，然后根据规范优化结果——因此输出的是一个可以提交的音频书，而不仅仅是生成的音频。

## 安装

**零安装（Node）：**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python（CLI）：**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**渲染音频**需要 [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTS 引擎（`[render]` 扩展）和 **FFmpeg**，并且 FFmpeg 需要添加到 PATH 环境变量中 (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`)。在渲染之前的所有步骤——解析、配音、编译、审查——都可以无需它们完成。运行 `audiobooker diagnose` 来检查您的设置。

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## 快速入门

```bash
# One command: parse -> auto-cast -> compile -> render -> master
audiobooker make mybook.epub --acx

# ...or the staged workflow, with control at each step:
audiobooker new mybook.epub            # parse into chapters (EPUB/PDF/TXT/MD/DOCX, or a folder)
audiobooker cast --interactive         # guided per-character casting
audiobooker audition Sarah --render    # A/B candidate voices for one character
audiobooker compile                    # detect dialogue, attribute speakers, infer emotion
audiobooker report                     # what's weak? unknown-attribution rate + top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## 功能

### 输入和结构
- **EPUB、TXT、Markdown、PDF、DOCX**，或者一个包含按章节划分的文件的**文件夹**（适用于 Scrivener/Obsidian/连载小说）。
- **基于目录结构的 EPUB 分割**——从书中自己的目录中提取章节边界和标题。
- **DOCX** 根据 Word 的“标题 1/2”/“标题”样式进行分割；**PDF** 检测标题（并带有扫描 PDF 的保护机制）；自定义 `--chapter-delimiter` 参数。
- 智能文本清理、支持 Markdown 的去除格式、脚注处理，以及一个**可重复使用的发音词典**（`pronunciation import/export`，CSV/JSON 格式，允许传递音素）。

### 配音和归属
- **多声音合成**，提供可解释的、排序后的声音**建议**，以及一个**`audition`**命令，用于对每个角色进行 A/B 测试。
- **交互式配音**、按性别/角色进行**批量 `cast-fill`**、**可重用的命名配音预设**（可在整个系列中使用），以及用于协作的**CSV 配音表**。
- **对话检测 + 说话者归属**（可选的 **BookNLP** 共指分析）、**别名自动发现**，以及具有可调节**强度**、**场景级别的情绪**和流派**预设包**的情感推断。

### 渲染和输出
- **M4B**（章节标记 + 嵌入封面 + 系列元数据）、**MP3**、**Opus**、**FLAC**；按章节导出；**播客/RSS** 源导出。
- **ACX/Audible 母带处理** (`--acx`) + 一个 **`master-check`** 命令，用于报告响度、峰值和噪声底噪是否符合要求；零售版**`sample`**片段。
- 并行渲染、一个具有恢复功能的**持久渲染缓存**、动态进度 + 预计剩余时间，以及结构化的失败报告。

### 工作流程和生态系统
- **`make`** 一次性流水线 · **配置文件** (`.audiobookerrc` / `[tool.audiobooker]`) · **`--watch`** 模式 · **基于清单的批量处理** · shell 命令补全。
- **7 种语言配置**（英语/法语/德语/西班牙语/日语/意大利语/葡萄牙语）· **可插拔的 TTS 引擎** (`--engine`，setuptools 入口点——支持 Piper/Coqui/ElevenLabs) · 大多数命令都支持脚本化的 `--json` 输出 · 结构化的退出代码。

## 发布到 ACX / Audible

Audiobooker 直接针对可测量的 ACX 提交规范：

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`master-check` 命令会验证可测量的要求（响度、峰值、噪声底噪）。ACX 还具有主观/质量控制标准，工具无法对其进行认证——但您将不再因为响度违规而被拒绝。

## CLI 命令

| 命令 | 描述 |
|---------|-------------|
| `make <file>` | 一次性：new → compile → auto-cast → render |
| `new <file\ | folder>` | 从 EPUB/TXT/MD/PDF/DOCX 或一个文件夹创建项目 |
| `from-stdin` | 从管道传输的文本创建项目 |
| `cast <char> <voice>` · `cast --interactive` | 分配配音（或引导式逐个说话者配音） |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | 建议 / 自动应用 / 批量分配配音 |
| `cast-preset save\ | list\ | apply\ | delete` | 可重用的跨书籍的配音预设 |
| `audition <char>` | A/B 排序后的候选配音，用于一个角色 (`--render`) |
| `compile` | 检测对话、归属说话者、推断情感 |
| `report` | 编译质量：未知比率、未归属的行数最多、情感混合 |
| `review-export` · `review-import <file>` | 可人工编辑的审查循环 |
| `render` | 渲染音频书 (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | 已完成的零售版样本 · ACX 合规性检查 |
| `export-chapters` · `podcast` | 章节提示表（ffmetadata/cue/json）· 播客 RSS 源 |
| `preview` · `batch` · `diagnose` | 语音质量检查片段 · 批量处理 / `--manifest` · 环境检查 |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | 检查和管理 |

每个命令都支持 `-h/--help`。全局标志：`--silent`, `--debug`。**退出代码：** `0` 成功 · `1` 用户错误 · `2` 运行时错误 · `3` 部分完成（批量）。

## 配置

一次性设置默认值，而不是每次都重新传递标志——`.audiobookerrc` (TOML) 文件位于您的书籍旁边，或者在 `pyproject.toml` 中的 `[tool.audiobooker]` 部分。优先级为：**CLI 标志 > 项目配置 > 用户配置 (`~/.audiobookerrc`) > 内置默认值**。

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## 可插拔的 TTS 引擎

默认引擎是 `voice-soundboard`，但合成后端可以通过 setuptools 入口点（`audiobooker.tts_engines`）进行切换：

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

一个插件 (`pip install audiobooker-piper`) 会自动注册；无需分叉。

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

`render(...)` 和 `compile(...)` 接受注入的 `engine=`（任何实现 `TTSEngine` 协议的对象）和一个进度回调——将 Audiobooker 嵌入到 GUI 或服务中。

## 架构

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC
```

## 安全与数据范围

- **网络：** 无——不进行遥测，不存储数据，不使用凭据。读取您的书籍文件，并将音频和缓存写入输出目录。
- **权限：** 具有对输入文件的读取权限，对输出文件的写入权限；可选的 FFmpeg 以及 PATH 环境变量中的文本转语音 (TTS) 引擎。
- 请参阅 [SECURITY.md](SECURITY.md)。

## 评估报告

| 关卡 | 状态 |
|------|--------|
| A. 安全基线 | 通过 |
| B. 错误处理 | 通过 |
| C. 操作文档 | 通过 |
| D. 发布规范 | 通过 |
| E. 身份验证 | 通过 |

## 许可证

[MIT](LICENSE)

---

由 <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a> 构建
