<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo-dark.png">
    <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
  </picture>
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

Audiobooker 能够检测对话，为每个角色分配独特的语音，推断情感，让您在渲染单个音轨之前，可以查看并更正所有内容，然后对结果进行优化，使其符合 ACX 音频规范——因此，输出的是一本*完整的*有声读物，而不仅仅是生成的音频。

## 安装

**零安装（Node）：**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python（命令行）：**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**渲染音频**需要 [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTS 引擎（额外的 `[render]`）以及在 PATH 环境变量中配置的 **FFmpeg**（`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`）。在渲染之前的所有步骤——解析、分配角色、编译、审查——都不需要它们。运行 `audiobooker diagnose` 以检查您的设置。

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
- **EPUB、TXT、Markdown、PDF、DOCX**，或者一个**包含按章节划分的文件**的文件夹（适用于 Scrivener/Obsidian/连载小说）。
- **基于目录的 EPUB 分割**——从书籍自身的目录中提取章节边界和标题。
- **DOCX** 根据 Word `Heading 1/2`/`Title` 样式进行分割；**PDF** 检测标题（并带有扫描 PDF 的保护机制）；自定义 `--chapter-delimiter`。
- 智能文本清理、支持 Markdown 的内容去除、脚注处理，以及一个**可重复使用的发音词典**（`pronunciation import/export`，CSV/JSON 格式，支持音素传递）。

### 角色分配和归属
- **多语音合成**，提供可解释的、排序后的语音**建议**，以及一个**`audition`**命令，用于对每个角色进行 A/B 测试。
- **交互式角色分配**、按性别/角色进行**批量 `cast-fill`**、**可重复使用的命名角色预设**（适用于整个系列），以及**CSV 角色表**，方便与合作者共享。
- **对话检测 + 说话者归属**（可选的 **BookNLP** 共同指代），**别名自动发现**，以及**情感推断**，可以调整**强度**、**场景级别的情绪**和**预设的风格包**。

### 渲染和输出
- **M4B**（章节标记 + 嵌入式封面 + 系列元数据）、**MP3**、**Opus**、**FLAC**、**WAV**；按章节导出；**播客/RSS** 订阅源导出。
WAV 格式没有章节标记，因此 WAV 渲染会明确说明这一点，而不是报告章节混合失败——当音频要导入到编辑器中时，可以选择这种格式。
- **符合 ACX 规范的母带处理**（`--acx`）+ 一个**`master-check`**，用于报告 RMS 响度、峰值和噪声底噪是否符合标准；零售**`sample`**片段。
- 并行渲染、**持久的渲染缓存**（支持恢复）、动态进度 + 预计剩余时间，以及结构化的失败报告。

### 工作流程和生态系统
- **`make`** 一次性流水线 · **配置文件**（`.audiobookerrc` / `[tool.audiobooker]`） · **`--watch`** 模式 · **基于清单的批量处理** · 命令行自动补全。
- **7 种语言配置文件**（英语/法语/德语/西班牙语/日语/意大利语/葡萄牙语） · **可插拔的 TTS 引擎**（`--engine`，入口点——支持 Piper/Coqui/ElevenLabs） · 大多数命令都支持脚本化 `--json` · 结构化的退出代码。

## 符合 ACX 音频规范的母带处理

ACX 发布了精确、可测量的音频目标。这是有声读物领域最接近母带处理标准的标准，无论您对文件进行何种处理，都值得达到这个标准。

| 要求 | ACX 规范 | `--acx` 的作用 |
|---|---|---|
| 响度 | RMS 介于 **−23 和 −18 dBFS** 之间 | two-pass `loudnorm` at −20 LUFS, which lands inside that window for speech |
| 峰值 | 峰值应低于或等于 **−3 dBFS** | 在同一阶段进行强制执行 |
| 噪声底噪 | 噪声底噪应低于或等于 **−60 dBFS** | 进行测量和报告——绝不会在不告知的情况下“修复” |
| 格式 | **44.1 kHz，192 kbps CBR MP3** | 设置采样率；添加 `--format mp3 --bitrate 192k` 以指定编解码器 |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

以上数字值得强调的两点：

**`master-check` 测量的是无权重的 RMS 值，而不是 LUFS 值。** 这两者是不同的量，ACX 采用的是前者作为标准。−20 LUFS 值是母带处理阶段*如何达到*该值的手段——这是 `ffmpeg loudnorm` 可以设置的目标——而不是之后进行检查的内容。

**噪声底噪是进行测量，而不是进行校正。** 这是最常导致失败的要求，并且它来自源音频。如果有一个工具可以悄悄地进行门限处理，那么它就会隐藏您需要看到的一个关键数字。

### AI 叙述的有声读物实际上可以达到什么程度

满足规范并不等同于被接受，这一点值得明确说明：**ACX 的标准提交流程适用于人类叙述。** 其 2026 年 4 月的要求清单中，未经授权的文本转语音和 AI 录音被列为不接受的内容，因此，AI 叙述的作品需要事先获得 ACX 的授权，而不是进行普通的提交。

接受 AI 叙述的渠道，通常需要进行说明，包括亚马逊的 **Virtual Voice**（通过 KDP，仅限亚马逊平台分发）以及聚合平台，如 **Spotify Audiobooks for Authors**、**Author's Republic** 和 **Kobo Writing Life**。零售商的政策在这个领域变化很快——请自行检查当前的条款，而不是依赖于本段文字。

因此：`--acx` 关注的是音频。零售商是否接受 AI 叙述的作品，是他们的决定，而不是您刚刚制作的文件所具有的属性。

## 命令行命令

| 命令 | 描述 |
|---------|-------------|
| `make <file>` | 一次性：new → compile → auto-cast → render |
| `new <file\ | folder>` | 从 EPUB/TXT/MD/PDF/DOCX 或包含按章节划分的文件组成的文件夹创建项目 |
| `from-stdin` | 从管道传输的文本创建项目 |
| `cast <char> <voice>` · `cast-interactive` | 分配语音（或引导式逐个角色分配；也支持 `cast -i`） |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | 建议/自动应用/批量分配语音 |
| `cast-preset save\ | list\ | apply\ | delete` | 可重复使用的角色预设，适用于整个系列 |
| `cast-export` · `cast-import <file>` | 将演员阵容转换为 JSON/CSV 格式，以便进行双向传输——手动编辑，或在不同版本中重复使用。 |
| `audition <char>` | 为单个角色（`--render`）提供 A/B 排序的候选配音。 |
| `compile` | 检测对话，归属说话者，推断情感。 |
| `report` | 质量评估：未知比率，未归属的顶级对话，情感混合。 |
| `review-export` · `review-import <file>` | 可人工编辑的审核双向传输。 |
| `render` | 渲染有声读物（`--acx`、`--format`、`--split`、`--bitrate`、`--engine`、`--watch`、`--cover`、`-j N`）。 |
| `sample` · `master-check <file>` | 经过优化的零售样本，对照 ACX 音频规范进行检查。 |
| `export-chapters` · `podcast` | 章节提示表（ffmetadata/cue/json），播客 RSS 订阅源。 |
| `preview` · `batch` · `diagnose` | 语音质量检测片段，批量处理/`--manifest`，环境检查（如果无法渲染，则返回非零值）。 |
| `load <file>` | 打开现有的 `.audiobooker` 项目。 |
| `voices`、`chapters`、`speakers`、`info`、`status`、`cache`、`emotions`、`pronunciation`、`completion`。 | 检查和管理。 |

每个命令都支持 `-h/--help`。全局标志：`--silent`、`--debug`。**退出代码：**`0` 正常 · `1` 用户错误（包括无法编译的书籍，或由于归属失败而拒绝渲染的情况）· `2` 运行时错误 · `3` 部分完成（批量）。

## 配置

一次性设置默认值，而不是每次都重新传递标志——将 `.audiobookerrc`（TOML）放在书籍旁边，或将 `[tool.audiobooker]` 放在 `pyproject.toml` 中。优先级为：**命令行标志 > 项目配置 > 用户配置（`~/.audiobookerrc`）> 内置默认值**。

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## 可插拔的 TTS 引擎

默认引擎是 `voice-soundboard`，但可以通过 setuptools 入口点（`audiobooker.tts_engines`）切换合成后端。

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

一个插件（`pip install audiobooker-piper`）会自行注册；无需分叉。

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

`render(...)` 和 `compile(...)` 接受注入的 `engine=`（任何实现 `TTSEngine` 协议的对象）和一个进度回调——将有声读物制作器嵌入到 GUI 或服务中。

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## 安全性和数据范围

- **网络：** 无——无遥测、无数据存储、无凭据。读取您的书籍文件，并将音频 + 缓存写入您的输出目录。
- **权限：** 具有对输入的读取权限，对输出的写入权限；可选的 FFmpeg + 路径中的 TTS 引擎。
- 请参阅 [SECURITY.md](SECURITY.md)。

## 评估表

| 关卡。 | 状态。 |
|------|--------|
| A. 安全基线。 | 通过。 |
| B. 错误处理。 | 通过。 |
| C. 操作文档。 | 通过。 |
| D. 发布规范。 | 通过。 |
| E. 身份。 | 通过。 |

## 许可证

[MIT](LICENSE)。

---

由 <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a> 构建。
