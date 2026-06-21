<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/mcp-tool-shop-org/audiobooker"><img src="https://codecov.io/gh/mcp-tool-shop-org/audiobooker/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT/PDF books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## 功能

### 输入与解析
- 支持 **EPUB / TXT / Markdown** 格式的源文件解析，并能检测章节。
- **PDF 支持**（可选）：通过 PyMuPDF 从 PDF 文件中提取文本（`pip install -e '.[pdf]'`）。
- **文本规范化**：智能引号清理，空格规范化，可配置的文本清理功能。
- **发音覆盖**：自定义专有名词和术语的发音映射。
- **脚注处理**：可配置的脚注行为（`inline`，`end` 或 `skip`）。

### 对话与归属
- **对话检测**：自动识别引用的对话和旁白。
- **高级对话检测**：用于多说话场景的对话轮次跟踪。
- **舞台指示**：检测并处理剧本中的括号内的舞台指示。
- **BookNLP 集成**：可选的基于 NLP 的说话者指代消解功能。
- **角色别名**：将不同的名称映射到主要角色。

### 声音与配音
- **多声音合成**：为每个角色分配独特的语音。
- **语音建议**：根据说话者提供可解释的、排序的语音推荐。
- **情感推断**：基于规则和词典的情感标注，并可配置置信度。
- **角色特定语音参数**：速度（0.5--2.0）和每个说话者的情感。
- **SSML 预处理**：支持 Speech Synthesis Markup Language，用于精细控制。

### 渲染与输出
- **并行渲染**：使用 `--jobs N` 进行多线程章节渲染。
- **多种输出格式**：MP3, M4B, WAV, OGG, FLAC。
- **音频规范化**：跨章节保持一致的音量。
- **封面嵌入**：从 EPUB 文件或用户提供的文件中提取封面，并嵌入到 M4B 输出文件中。
- **持久渲染缓存**：在不重新合成已完成章节的情况下，恢复失败的渲染。
- **动态进度与 ETA**：实时显示渲染状态和预计完成时间。
- **错误报告**：提供结构化的 JSON 格式的渲染错误诊断信息。

### 语言与本地化
- **5 种语言配置文件**：英语、法语、德语、西班牙语、日语（`--lang en|fr|de|es|ja`）。
- **可扩展的配置文件系统**：通过 `LanguageProfile` 抽象来添加新的语言。

### 工作流程与效率
- **渲染前审查**：提供可编辑的审查格式，用于更正归属信息。
- **项目差异**：比较两个项目版本，以查看章节和语句的变化。
- **批量处理**：使用 `audiobooker batch` 一次处理多个书籍。
- **试运行模式**：在不执行的情况下预览渲染或批量操作（`--dry-run`）。
- **语音试听**：渲染一个短样本以验证语音分配（`audiobooker preview`）。
- **章节管理**：在渲染之前，可以合并、拆分和排除章节。
- **情感管理**：在编译后，列出并覆盖每个语句的情感。
- **桌面通知**：在长时间渲染完成后，会收到桌面通知。
- **项目持久化**：保存/恢复渲染会话。

## 安装

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## 可选功能

| 功能 | 安装 | 配置 |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` 或安装 voice-soundboard | 需要 `render` 功能 |
| **BookNLP 说话者消解** | `pip install -e '.[nlp]'` | `--booknlp on\ | off\ | auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | 运行时自动检测 |
| **FFmpeg audio assembly** | 系统包 (winget/brew/apt) | 需要 M4B 输出 |

## 快速开始

```bash
# 1. Create a project from your book
audiobooker new mybook.epub

# 2. Cast voices to characters
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
# Or auto-cast: audiobooker cast-suggest && audiobooker cast-apply --auto

# 3. Compile (dialogue detection + speaker attribution)
audiobooker compile

# 4. Review and correct the script (optional but recommended)
audiobooker review-export        # Creates mybook_review.txt
# Edit the file to fix attributions, then:
audiobooker review-import mybook_review.txt

# 5. Render the audiobook
audiobooker render
```

## 审查工作流程

审查工作流程允许您在渲染之前检查和更正编译的脚本：

```bash
# Export to review format
audiobooker review-export

# Edit the file (example: mybook_review.txt)
# === Chapter 1 ===
#
# @narrator
# The door creaked open.
#
# @Unknown              <-- Change this to @Marcus
# "Hello?" he whispered.
#
# @Sarah (worried)      <-- Emotions are preserved
# "Is anyone there?"

# Import corrections
audiobooker review-import mybook_review.txt

# Render with corrected attributions
audiobooker render
```

**文件格式说明：**
- `=== 章节标题 ===` - 章节标记
- `@Speaker` 或 `@Speaker (情感)` - 说话人标签
- `# 注释` - 注释（导入时会被忽略）
- 删除块以移除不需要的语句
- 将 `@Unknown` 更改为 `@ActualName` 以更正归属

## Python API

```python
from audiobooker import AudiobookProject

# Create from EPUB
project = AudiobookProject.from_epub("mybook.epub")

# Or from raw text
project = AudiobookProject.from_string("Chapter 1\n\nHello world.", title="My Book")

# Cast voices
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")

# Compile (detect dialogue, attribute speakers, infer emotions)
project.compile()

# Review workflow
review_path = project.export_for_review()
# ... edit the file ...
project.import_reviewed(review_path)

# Render to M4B (with automatic resume on re-run)
project.render("mybook.m4b")

# Save project for later
project.save("mybook.audiobooker")
```

## 命令行工具

| 命令 | 描述 |
|---------|-------------|
| `audiobooker new <file>` | 从 EPUB/TXT/MD/PDF 创建项目 |
| `audiobooker load <project>` | 加载现有的 `.audiobooker` 项目 |
| `audiobooker from-stdin` | 从文本流创建项目 |
| `audiobooker cast <char> <voice>` | 为角色分配声音 |
| `audiobooker cast-suggest` | 为未分配声音的角色推荐声音 |
| `audiobooker cast-apply --auto` | 自动应用最佳声音推荐 |
| `audiobooker compile` | 将章节转换为语句 |
| `audiobooker review-export` | 导出用于人工审核的脚本 |
| `audiobooker review-import <file>` | 导入已编辑的审核文件 |
| `audiobooker render` | 渲染有声书（支持 `--dry-run`、`--jobs N`、`--format`、`--cover`） |
| `audiobooker preview` | 生成一个短音频片段以验证声音（`--chapter N`、`--seconds S`） |
| `audiobooker batch <files...>` | 批量处理多个书籍（支持 `--dry-run`） |
| `audiobooker info` | 显示项目信息 |
| `audiobooker status` | 显示渲染/缓存状态 |
| `audiobooker voices` | 列出可用的声音（支持 `--gender`、`--search`） |
| `audiobooker chapters` | 列出章节标题和索引 |
| `audiobooker speakers` | 列出检测到的说话人 |
| `audiobooker cache info` | `clean` | `clean-failed` | 管理渲染缓存 |
| `audiobooker diagnose` | 检查环境（依赖项、声音引擎、FFmpeg） |

## 完整的命令行参考

每个命令都支持 `-h` / `--help` 以获取详细的使用说明。 关键参数：

- **`new`**: `-o <project>`、`--lang <code>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <emotion>`、`--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`、`--no-resume`、`--from-chapter N`、`--allow-partial`、`--clean-cache`、`--jobs N`、`-o <path>`、`--format mp3|m4b|wav|ogg|flac`、`--cover <image>`
- **`preview`**: `--chapter N`、`--seconds S`、`-o <path>`
- **`batch`**: `--dry-run`、`--jobs N`、`--format <fmt>`、`--lang <code>`、`--output-dir <dir>`
- **`voices`**: `--gender <male|female>`、`--search <query>`
- **`info`**: `--verbose`

## 架构

```
audiobooker/
├── parser/          # EPUB, TXT, PDF parsing
├── casting/         # Dialogue detection, voice assignment, suggestions
├── language/        # Language profiles (en, extensible)
├── nlp/             # BookNLP adapter, emotion inference, speaker resolver
├── renderer/        # Audio synthesis, cache, progress, failure reports
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**流程：**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## 常见问题

| 问题 | 解决方案 |
|---------|-----|
| **FFmpeg not found** | 通过您的包管理器安装：`winget install ffmpeg` (Windows)、`brew install ffmpeg` (macOS)、`apt install ffmpeg` (Linux)。 FFmpeg 必须在 PATH 环境变量中。 |
| **未安装 voice-soundboard** | 克隆并安装相关的仓库：`git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`。 或者使用 `pip install -e '.[render]'` 进行安装。 |
| **BookNLP 错误或启动缓慢** | BookNLP 是可选的。 如果您不需要 NLP 说话人识别，请设置 `--booknlp off` 或将其保留为 `auto`（优雅降级）。 仅在需要时使用 `pip install -e '.[nlp]'` 进行安装。 |

请参阅 [手册](docs/handbook.md#15-troubleshooting) 以获取完整的故障排除指南。

## 故障排除

**渲染失败报告：** 在任何渲染错误发生时，Audiobooker 会将 `render_failure_report.json` 文件写入缓存目录。 该文件包含：
- 发生错误的章节索引和标题
- 语句索引、说话人和文本预览
- 正在合成的声音 ID 和情感
- 完整的堆栈跟踪
- 缓存和清单路径

**常见的 FFmpeg 问题：**
- `FFmpeg not found`: 通过您的包管理器（winget/brew/apt）安装
- `Chapter embedding failed`: Audiobooker 会回退到不带章节标记的 M4A 格式
- 音频质量：默认是 AAC 128kbps at 24kHz（可以在 ProjectConfig 中配置）

**缓存问题：**
- `audiobooker render --clean-cache` — 清除所有缓存的音频文件，并重新渲染。
- `audiobooker render --no-resume` — 此次运行期间忽略缓存。
- `audiobooker render --from-chapter 5` — 从指定的章节开始。

## 发展路线图

- [x] 核心流水线（解析、转换、编译、渲染）
- [x] 渲染前审查工作流程
- [x] 持久化渲染缓存 + 恢复功能
- [x] 语言配置文件 + 输入灵活性
- [x] BookNLP、情感推理、语音建议、用户体验优化
- [x] v1.0.0 - 正式发布

## 安全与数据范围

- **访问的数据：** 从本地文件系统中读取 EPUB/TXT 文件。将音频文件和缓存清单写入输出目录。可选地使用语音合成器和 FFmpeg 进行音频组装。
- **未访问的数据：** 不进行任何网络请求。不收集任何遥测数据。不存储任何用户数据。不涉及任何凭证或令牌。
- **所需权限：** 访问输入书籍文件的读取权限。写入输出目录的写入权限。可选：FFmpeg 必须在 PATH 环境变量中。

## 评估标准

| 关卡 | 状态 |
|------|--------|
| A. 安全基线 | 通过 |
| B. 错误处理 | 通过 |
| C. 操作文档 | 通过 |
| D. 发布准备 | 通过 |
| E. 身份验证 | 通过 |

## 许可证

[MIT](LICENSE)

---

由 <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a> 构建。
