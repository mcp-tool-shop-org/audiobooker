<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## 功能

- **多声音合成**: 为每个角色分配独特的语音
- **对话检测**: 自动识别引用的对话与旁白
- **情感推断**: 基于规则和词典的情感标注，并具有可配置的置信度
- **语音建议**: 提供可解释的、按说话人排序的语音推荐
- **BookNLP 集成**: 可选的基于 NLP 的说话人指代消解
- **渲染前审查**: 人工可编辑的审查格式，用于更正归属
- **持久渲染缓存**: 在不重新合成已完成章节的情况下，恢复失败的渲染
- **动态进度和预计完成时间**: 实时渲染状态，并显示预计完成时间
- **错误报告**: 结构化的 JSON 格式的渲染错误诊断信息
- **语言配置文件**: 扩展的、特定于语言的规则抽象
- **M4B 输出**: 专业的有声书格式，支持章节导航
- **项目持久性**: 保存/恢复渲染会话

## 安装

```bash
# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg
# Linux: apt install ffmpeg
```

## 可选功能

| 功能 | 安装 | 配置 |
| --------- | --------- | -------- |
| **TTS rendering** | `pip install audiobooker-ai[render]` 或安装 voice-soundboard | `render` 功能的依赖项 |
| **BookNLP 说话人消解** | `pip install audiobooker-ai[nlp]` | `--booknlp on` |off\|auto` |
| **FFmpeg audio assembly** | 系统包 (winget/brew/apt) | M4B 输出的依赖项 |

## 快速开始

```bash
# 1. Create project from EPUB
audiobooker new mybook.epub

# 2. Get voice suggestions
audiobooker cast-suggest

# 3. Assign voices (or auto-apply suggestions)
audiobooker cast narrator bm_george --emotion calm
audiobooker cast Alice af_bella --emotion warm
# Or: audiobooker cast-apply --auto

# 4. Compile and review
audiobooker compile
audiobooker review-export     # Creates mybook_review.txt

# 5. Edit the review file to fix attributions, then import
audiobooker review-import mybook_review.txt

# 6. Render
audiobooker render
```

## 审查工作流程

审查工作流程允许您在渲染之前检查和更正编译后的脚本：

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

**审查文件格式：**
- `=== 章节标题 ===` - 章节标记
- `@Speaker` 或 `@Speaker (emotion)` - 说话人标签
- `# comment` - 注释（导入时会被忽略）
- 删除块以删除不需要的语句
- 将 `@Unknown` 更改为 `@ActualName` 以修复归属

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

## 命令行

| 命令 | 描述 |
| --------- | ------------- |
| `audiobooker new <file>` | 从 EPUB/TXT 创建项目 |
| `audiobooker cast <char> <voice>` | 为角色分配语音 |
| `audiobooker cast-suggest` | 为未分配说话人的角色提供语音建议 |
| `audiobooker cast-apply --auto` | 自动应用最佳语音建议 |
| `audiobooker compile` | 将章节编译为语句 |
| `audiobooker review-export` | 导出脚本以供人工审查 |
| `audiobooker review-import <file>` | 导入已编辑的审查文件 |
| `audiobooker render` | 渲染有声书 |
| `audiobooker info` | 显示项目信息 |
| `audiobooker voices` | 列出可用语音 |
| `audiobooker chapters` | 列出章节 |
| `audiobooker speakers` | 列出检测到的说话人 |
| `audiobooker from-stdin` | 从管道文本创建项目 |

## 架构

```
audiobooker/
├── parser/          # EPUB, TXT parsing
├── casting/         # Dialogue detection, voice assignment, suggestions
├── language/        # Language profiles (en, extensible)
├── nlp/             # BookNLP adapter, emotion inference, speaker resolver
├── renderer/        # Audio synthesis, cache, progress, failure reports
├── review.py        # Review format export/import
└── cli.py           # Command-line interface
```

**流程：**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## 故障排除

**渲染失败报告：** 发生任何渲染错误时，Audiobooker 会将 `render_failure_report.json` 写入缓存目录。其中包含：
- 发生错误的章节索引和标题
- 语句索引、说话人和文本预览
- 正在合成的语音 ID 和情感
- 完整的堆栈跟踪
- 缓存和清单路径

**常见的 FFmpeg 问题：**
- `FFmpeg not found`: 通过您的包管理器 (winget/brew/apt) 安装
- `Chapter embedding failed`: Audiobooker 会回退到不带章节标记的 M4A 格式
- 音频质量：默认值为 128kbps 的 AAC，采样率为 24kHz（可在 ProjectConfig 中配置）

**缓存问题：**
- `audiobooker render --clean-cache` — 清除所有缓存的音频并重新渲染
- `audiobooker render --no-resume` — 仅本次运行忽略缓存
- `audiobooker render --from-chapter 5` — 从特定章节开始

## 路线图

- [x] v0.1.0 - 核心流水线（解析、转换、编译、渲染）
- [x] v0.2.0 - 渲染前审查工作流程
- [x] v0.3.0 - 持久化渲染缓存 + 恢复功能
- [x] v0.4.0 - 语言配置文件 + 输入灵活性
- [x] v0.5.0 - BookNLP、情感推理、语音建议、用户体验优化

## 许可证

MIT
