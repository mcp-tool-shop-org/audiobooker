<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Audiobooker 检测对话，为每个角色分配独特的配音，推断情感，让您在渲染单个音轨之前，可以查看并更正所有内容，然后将结果调整到 ACX 音频规范——因此，输出的是一本*完成*的有声读物，而不仅仅是生成的音频。

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

**Docker**——ffmpeg 已经包含在内，每次发布时都会发布到 GHCR：
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
只需挂载一个即可，并且 `--rm` 是安全的：渲染缓存位于项目文件旁边，而不是位于主目录中，因此重新运行会**恢复**，而不是重新合成整个有声读物。

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- 标记了 `latest`、`3`、`3.0` 以及确切的版本，并在每次发布时推送到 GHCR。
- 入口点**是** `audiobooker`，因此在镜像名称之后直接传递子命令——不要重复程序名称。
- 缓存位于 `<book-dir>/.audiobooker/cache`。这就是为什么一个挂载点可以实现持久性；如果丢失了它，则需要再次支付全部 TTS 运行费用，而不仅仅是重新复用。
- `/ext` 是一个可选的第二个挂载点，仅用于提供您自己的 TTS 轮子。
- 容器以非 root 用户身份运行，UID 为 1000。在 Linux 上，如果挂载的目录不能被该 UID 写入，则无法写入缓存——添加 `--user "$(id -u):$(id -g)"` 或 `chown` 到该目录。macOS 和 Windows 上的 Docker Desktop 会为您处理此问题。

</details>

**渲染音频**需要 [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTS 引擎（额外的 `[render]`）和 PATH 上的 **FFmpeg**（`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`）。在渲染之前的所有操作——解析、配音、编译、审查——都不需要它们。运行 `audiobooker diagnose` 以检查您的设置。

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

这些都是 2.x 版本接受某些内容并默默地执行错误操作的情况。3.0 版本会拒绝。完整详细信息请参见 [CHANGELOG](CHANGELOG.md)。

- **您第一次渲染会重新渲染每个章节，一次性完成。** 三个会改变音频的输入——情感预设、语调强度、每个角色的语速/音调/强调——都缺失在缓存键中，因此切换预设会报告“已缓存”并返回旧的音频。现在它们都在键中，并且 2.x 版本的缓存条目无法证明生成它的内容。
- **`--format m4a` 不再是整个有声读物的选项。** 它一直意味着每个章节一个文件；以前，请求整个有声读物会在 `m4a` 中生成一个 M4B 文件，文件名为 `.m4a`。它在 `podcast --format` 中仍然有效。
- **`render` 会拒绝有声读物，其署名信息为 `FAILED`**，而不是花费 TTS 运行时间来处理它。`--force` 会覆盖。运行 `audiobooker report` 以查看它反对哪些行。
- **`make` 会拒绝，如果项目文件已经存在。** 以前，它会覆盖手动分配的配音、发音覆盖和编辑后的标题，并使用新的自动配音解析。如果这是您想要的，请传递 `--overwrite-project`。
- **`compile()` 会在每个章节都失败时引发错误**，而不是像干净的运行那样返回 `None`。如果您从 Python 调用它，现在它可以引发异常。

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
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## 功能

### 输入和结构
- **EPUB、TXT、Markdown、PDF、DOCX**，或一个**包含每个章节文件的文件夹**（Scrivener/Obsidian/连载小说）。
- **基于目录的 EPUB 分割**——从书籍自身的目录中获取章节边界和标题。
- **DOCX** 根据 Word `Heading 1/2`/`Title` 样式进行分割；**PDF** 检测标题（带有扫描 PDF 保护）；自定义 `--chapter-delimiter`。
- 智能文本清理、Markdown 感知的去除、脚注处理以及一个**可重用的发音词典**（`pronunciation import/export`，CSV/JSON，带有音素传递）。

### 配音和署名
- **多音轨合成**，具有可解释的、排序的配音**建议**，以及一个**`audition`**命令，用于为每个角色进行 A/B 候选测试。
- **交互式配音**、按性别/角色进行**批量 `cast-fill`**、可跨系列重用的**命名配音预设**以及用于协作人员的**CSV 配音表**。
- **对话检测 + 说话者署名**（可选的 **BookNLP** 共同指代），**别名自动发现**以及**情感推断**，具有可调节的**强度**、**场景级别的情绪**和**预设包**。
- **您可以审核的署名。** 每行记录*如何*确定其说话者——语音标签、内联覆盖、共同指代、您自己的更正或简单的交替轮流猜测——并且 `report` 会单独计算猜测次数和无法署名的行数。猜测无法提高分数，因此当署名变得更糟时，数字会减少，这是唯一有用的方向。

### 渲染和输出
- **M4B**（章节标记 + 嵌入封面 + 系列元数据）、**MP3**、**Opus**、**FLAC**、**WAV**；每个章节导出；**播客/RSS** 订阅源导出。
WAV 没有章节原子，因此 WAV 渲染会明确说明这一点，而不是报告章节复用的失败——当音频要进入编辑器时，请使用它。
- **符合 ACX 规范的母带处理**（`--acx`）+ 一个**`master-check`**，用于报告 RMS 响度、峰值和噪声底噪是否通过；零售**`sample`**片段。
- 并行渲染、具有恢复功能的**持久渲染缓存**、动态进度 + 预计剩余时间以及结构化的失败报告。
缓存键涵盖所有会改变音频的内容——文本、配音、配音演员、引擎和版本、配置文件、情感预设和强度——因此，如果重新渲染显示“已缓存”，则意味着它确实已缓存。可选的**每语调缓存**（`utterance_cache`）会将重新渲染缩小到您实际编辑的行。

### 工作流程和生态系统
- **`make`** 一次性流水线 · **配置文件**（`.audiobookerrc` / `[tool.audiobooker]`） · **`--watch`** 模式 · **基于清单的批量处理** · shell 补全。
- **7 种语言配置文件**（en/fr/de/es/ja/it/pt） · **可插拔的 TTS 引擎**（`--engine`，入口点——提供 Piper/Coqui/ElevenLabs） · 大多数命令的可编写脚本的 **`--json`** · 结构化的退出代码。

## 符合 ACX 音频规范的母带处理

ACX 发布精确、可测量的音频目标。这是有声读物领域最接近于母带制作标准的标准，无论之后如何处理文件，都值得达到这个标准。

| 要求 | ACX 规范 | `--acx` 的作用 |
|---|---|---|
| 响度 | RMS 介于 **-23 和 -18 dBFS** 之间 | 两次处理 `loudnorm`，LUFS 值为 -20，这符合语音的范围 |
| 峰值 | 等于或低于 **-3 dBFS** | 在同一处理过程中强制执行 |
| 噪声底限 | 等于或低于 **-60 dBFS** | 进行测量并报告——绝不静默“修复” |
| 格式 | **44.1 kHz，192 kbps CBR MP3** | 设置采样率；添加 `--format mp3 --bitrate 192k` 以指定编解码器 |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

以上数字值得关注的两点：

**`master-check` 测量的是无权重 RMS，而不是 LUFS。** 它们是不同的量，ACX 采用的是前者。-20 LUFS 值是母带制作过程*达到*该值的手段——这是 `ffmpeg loudnorm` 可以设定的目标——而不是之后进行检查的内容。

**噪声底限是测量，而不是校正。** 这是最容易不符合要求，并且源于原始音频。如果有一个工具可以静默地抑制噪声，那就会隐藏你需要看到的一个关键数字。

### AI 叙述的有声读物实际上可以达到什么程度

满足规范并不等同于被接受，这一点值得明确说明：**ACX 的标准提交流程适用于人工叙述。** 其 2026 年 4 月的要求清单中，未经授权的文本转语音和 AI 录音被列为不接受的内容，因此，AI 叙述的作品需要事先获得 ACX 的授权，而不是进行普通提交。

接受 AI 叙述的渠道，通常需要进行说明，包括亚马逊的 **Virtual Voice**（通过 KDP，仅限亚马逊分发）以及 **Spotify Audiobooks for Authors**、**Author's Republic** 和 **Kobo Writing Life** 等聚合平台。该领域的零售商政策变化迅速——请自行检查当前的条款，而不是依赖于本段文字。

因此：`--acx` 关注的是音频。零售商是否接受 AI 叙述的作品，是他们的决定，而不是你刚刚制作的文件所具有的属性。

## CLI 命令

| 命令 | 描述 |
|---------|-------------|
| `make <file>` | 一次性：new → compile → auto-cast → render |
| `new <file\ | folder>` | 从 EPUB/TXT/MD/PDF/DOCX 或文件夹创建项目 |
| `from-stdin` | 从管道文本创建项目 |
| `cast <char> <voice>` · `cast-interactive` | 分配角色（或引导式逐角色分配；也包括 `cast -i`） |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | 建议/自动应用/批量分配角色 |
| `cast-preset save\ | list\ | apply\ | delete` | 可在不同书籍中重复使用的角色预设 |
| `cast-export` · `cast-import <file>` | 以 JSON/CSV 格式进行双向传输——手动编辑，或在不同版本中重复使用 |
| `audition <char>` | 对一个角色（`--render`）进行 A/B 排序的候选角色 |
| `compile` | 检测对话、归属角色、推断情感 |
| `report` | 编译质量：未归属的比例、推断的比例、最差的片段、情感混合 |
| `review-export` · `review-import <file>` | 可由人工编辑的审核双向传输 |
| `render` | 渲染有声读物（`--acx`、`--format`、`--split`、`--bitrate`、`--engine`、`--watch`、`--cover`、`-j N`） |
| `sample` · `master-check <file>` | 母带制作的零售样本——检查是否符合 ACX 音频规范 |
| `export-chapters` · `podcast` | 章节提示表（ffmetadata/cue/json）——播客 RSS 订阅源 |
| `preview` · `batch` · `diagnose` | 角色 QA 剪辑——批量/`--manifest`——环境检查（如果无法渲染，则以非零值退出） |
| `load <file>` | 打开现有的 `.audiobooker` 项目 |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | 检查和管理 |

每个命令都支持 `-h/--help`。全局标志：`--silent`、`--debug`。**退出代码：** `0` 正常 · `1` 用户错误（包括无法编译的书籍，或者由于归属失败而拒绝渲染）· `2` 运行时 · `3` 部分（批量）。

## 配置

一次性设置默认值，而不是每次都重新传递标志——将 `.audiobookerrc`（TOML）放在你的书籍旁边，或者将 `[tool.audiobooker]` 放在 `pyproject.toml` 中。优先级为：**CLI 标志 > 项目配置 > 用户配置（`~/.audiobookerrc`）> 默认值。**

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## 可插拔的 TTS 引擎

默认引擎是 `voice-soundboard`，但可以通过 setuptools 入口点（`audiobooker.tts_engines`）切换合成后端：

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

一个插件（`pip install audiobooker-piper`）会注册自身；无需分叉。

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

- **网络：** 无——无遥测、无数据存储、无凭据。读取你的书籍文件，并将音频 + 缓存写入你的输出目录。
- **权限：** 具有对输入文件的读取权限，对输出文件的写入权限；可选的 FFmpeg + 路径中的 TTS 引擎。
- 请参阅 [SECURITY.md](SECURITY.md)。

## 评分表

| 关卡 | 状态 |
|------|--------|
| A. 安全基线 | 通过 |
| B. 错误处理 | 通过 |
| C. 操作文档 | 通过 |
| D. 发布卫生 | 通过 |
| E. 身份 | 通过 |

## 许可证

[MIT](LICENSE)

---

由 <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a> 构建
