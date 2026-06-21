<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

这是用于 [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/)（Python）的 **`npx` 包装器**。它在首次运行时会创建一个私有 Python 环境，从 PyPI 安装指定版本的软件包，并运行实际的命令行界面——无需手动使用 `pip`，也不会更改您的系统 Python。

## 试用一下

```bash
npx @mcptoolshop/audiobooker --help
```

或者全局安装：

```bash
npm install -g @mcptoolshop/audiobooker
```

首次运行时，会在您的用户数据目录下（`~/.local/share/audiobooker`，或 Windows 上的 `%LOCALAPPDATA%\audiobooker`）设置一个受管理的虚拟环境，并安装 `audiobooker-ai`。此后每次运行都会立即启动。

**需要在 PATH 中包含 Python 3.10+**（包装器会查找 `python3`/`py`）。如果缺少，包装器会准确地告诉您如何为您的操作系统安装它。

## 快速入门

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## 音频渲染（语音合成）

解析、角色分配、编译和审核流程都可以直接使用。**音频渲染**需要 TTS 引擎，该引擎会引入更多的依赖项——在您准备好时启用：

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

渲染还需要 **FFmpeg** 在 PATH 中，用于 M4B/MP3 的组装（`winget install ffmpeg`/`brew install ffmpeg`/`apt install ffmpeg`）。运行 `audiobooker diagnose` 以检查您的设置。

## 它的作用

- **多声音角色分配**，提供可解释的、排序后的语音建议；`audiobooker audition <character>` 允许您在确定之前对候选声音进行 A/B 测试。
- **对话检测 + 说话者归属**（可选 BookNLP 共指）、情感推断和可重用的发音词典。
- **渲染前审核**：导出可供人工编辑的脚本，修复归属信息，重新导入——没有任何内容会被静默更改。
- **ACX / Audible 母带处理**：`render --acx` 加上 `master-check` 会报告响度、峰值和噪声底噪是否通过测试（PASS/FAIL）。
- **格式**：M4B（章节标记 + 内嵌封面 + 系列元数据）、MP3、Opus、FLAC；按章节导出；零售示例片段。
- **7 种语言配置文件**（英语/法语/德语/西班牙语/日语/意大利语/葡萄牙语）和一个用于设置和忘记默认值的每个书籍的配置文件。

## 环境变量

| 变量 | 效果 |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | **包含**语音引擎来配置受管理的虚拟环境（用于渲染） |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | 从头开始重建受管理的虚拟环境 |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | 覆盖受管理的虚拟环境的存储位置 |

## 是否使用 pip？

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## 链接

- **文档和手册**：<https://mcp-tool-shop-org.github.io/audiobooker/>
- **源代码**：<https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI**：<https://pypi.org/project/audiobooker-ai/>

## 许可证

[MIT](LICENSE) © mcp-tool-shop
