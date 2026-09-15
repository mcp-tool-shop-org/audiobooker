<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

## 試してみてください

```bash
npx @mcptoolshop/audiobooker --help
```

または、グローバルにインストールします。

```bash
npm install -g @mcptoolshop/audiobooker
```

初回実行時に、ユーザーデータディレクトリ（`~/.local/share/audiobooker`、またはWindowsでは`%LOCALAPPDATA%\audiobooker`）に管理された仮想環境をセットアップし、`audiobooker-ai`をインストールします。それ以降の実行は、すぐに開始されます。

**PATHにPython 3.10以上が必要です**（ラッパーは`python3` / `py`を検索します）。もし見つからない場合は、ラッパーがOSに合わせてインストール方法を正確に教えてくれます。

## クイックスタート

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## オーディオレンダリング（音声合成）

解析、キャスト、コンパイル、およびレビューワークフローは、すぐに利用できます。**オーディオのレンダリング**には、TTSエンジンが必要であり、より多くの依存関係を必要とします。準備ができたら、有効にしてください。

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

レンダリングには、M4B/MP3のアセンブリのために、**FFmpeg**がPATHにある必要があります（`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`）。セットアップを確認するには、`audiobooker diagnose`を実行してください。

## 機能

- 説明可能でランク付けされた音声候補による**マルチボイスキャスト**。`audiobooker audition <character>`を使用すると、確定する前に候補の音声をA/Bテストできます。
- **対話検出 + 話者アトリビューション**（オプションのBookNLP共同参照）、感情推論、および再利用可能な発音辞書。
- **レンダリング前のレビュー**：人間が編集可能なスクリプトをエクスポートし、アトリビューションを修正し、再インポートします。何も変更が自動的に行われることはありません。
- **ACX仕様のマスターリング**：`render --acx`は、ACXオーディオターゲット（RMSは-23〜-18 dBFS、ピークは-3以下、ノイズフロアは-60以下）にマスターリングし、`master-check`は、これらの3つの測定制限に対してPASS/FAILを報告します。
ただし、仕様を満たすことは、承認されることと同じではありません。ACXの標準的な提出フローは、人間のナレーション用です。AIナレーションされたオーディオブックが実際に利用できる経路については、[メインのREADME](https://github.com/mcp-tool-shop-org/audiobooker#where-an-ai-narrated-audiobook-can-actually-go)を参照してください。
- **形式**：M4B（チャプターマーカー + 埋め込みカバー + シリーズメタデータ）、MP3、Opus、FLAC。チャプターごとのエクスポート、小売用のサンプルクリップ。
- **7つの言語プロファイル**（en/fr/de/es/ja/it/pt）と、設定を一度行えば自動的に適用される、書籍ごとの設定ファイル。

## 環境変数

| 変数 | 効果 |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | 管理された仮想環境に、音声エンジンを**含めて**プロビジョニングする（レンダリング用） |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | 管理された環境を最初から再構築する |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | 管理された仮想環境の場所をオーバーライドする |

## pipを優先するか？

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## リンク

- **ドキュメントとハンドブック**：<https://mcp-tool-shop-org.github.io/audiobooker/>
- **ソース**：<https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI**：<https://pypi.org/project/audiobooker-ai/>

## ライセンス

[MIT](LICENSE) © mcp-tool-shop
