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

これは、[`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/)（Python）の**`npx`ラッパー**です。初回実行時に、プライベートなPython環境をセットアップし、PyPIから指定されたバージョンのパッケージをインストールして、実際のCLIを実行します。手動で`pip`を使用したり、システムにインストールされているPythonを変更する必要はありません。

## 試してみてください

```bash
npx @mcptoolshop/audiobooker --help
```

または、グローバルにインストールしてください。

```bash
npm install -g @mcptoolshop/audiobooker
```

初回実行時に、ユーザーデータディレクトリ（`~/.local/share/audiobooker`、またはWindowsの場合は`%LOCALAPPDATA%\audiobooker`）の下に管理された仮想環境をセットアップし、`audiobooker-ai`をインストールします。それ以降の実行はすぐに開始されます。

**PATHにはPython 3.10以上が必要です**（ラッパーは`python3`/`py`を見つけます）。見つからない場合は、ラッパーがオペレーティングシステムに合わせてインストールする方法を正確に教えてくれます。

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

解析、キャスト、コンパイル、およびレビューワークフローはすぐに利用できます。**オーディオのレンダリング**にはTTSエンジンが必要であり、より多くの依存関係を必要とします。準備ができたら有効にしてください。

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

レンダリングには、M4B/MP3のアセンブリのために、PATHに**FFmpeg**も必要です（`winget install ffmpeg`/`brew install ffmpeg`/`apt install ffmpeg`）。`audiobooker diagnose`を実行して、セットアップを確認してください。

## 機能

- 説明可能でランク付けされた音声候補による**マルチボイスキャスト**。`audiobooker audition <character>`を使用すると、確定する前に候補の音声をA/Bテストできます。
- **対話検出 + 話者アトリビューション**（オプションのBookNLP共同参照）、感情推論、および再利用可能な発音辞書。
- **レンダリング前のレビュー**: 人間が編集できるスクリプトをエクスポートし、アトリビューションを修正して、再度インポートします。何もサイレントに変更されることはありません。
- **ACX / Audibleマスタリング**: `render --acx`に加えて、`master-check`はラウドネス、ピーク、およびノイズフロアに関するPASS/FAILのレポートを出力します。
- **形式**: M4B（チャプターマーカー + 埋め込みカバー + シリーズメタデータ）、MP3、Opus、FLAC。チャプターごとのエクスポート、小売用のサンプルクリップ。
- **7つの言語プロファイル**（en/fr/de/es/ja/it/pt）と、設定を一度行えば自動的に適用されるブックごとの構成ファイル。

## 環境変数

| 変数 | 効果 |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | 管理された仮想環境に**音声エンジンを含めてプロビジョニングする**（レンダリング用） |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | 管理された環境を最初から再構築する |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | 管理された仮想環境の場所をオーバーライドする |

## pipを使用することを優先するか？

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## リンク

- **ドキュメントとハンドブック**: <https://mcp-tool-shop-org.github.io/audiobooker/>
- **ソースコード**: <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI**: <https://pypi.org/project/audiobooker-ai/>

## ライセンス

[MIT](LICENSE) © mcp-tool-shop
