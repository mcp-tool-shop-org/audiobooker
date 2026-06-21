<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

オーディオブッカーは、会話を検出し、各キャラクターに特徴的な声を与え、感情を推測し、1秒分の音声もレンダリングする前に、すべてを確認および修正できるようにします。その後、結果を仕様に合わせて最適化します。そのため、出力されるのは単なる生成された音声ではなく、提出可能なオーディオブックになります。

## インストール

**ゼロインストール（Node）：**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python（CLI）：**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**音声のレンダリング**には、[`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTSエンジン（`[render]`エクストラ）と、PATH上の**FFmpeg**が必要です（`winget install ffmpeg`・`brew install ffmpeg`・`apt install ffmpeg`）。レンダリングまでのすべての処理（解析、声優の割り当て、コンパイル、確認）は、これらがなくても実行できます。`audiobooker diagnose`を実行して、環境設定を確認してください。

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## クイックスタート

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

## 機能

### 入力と構造
- **EPUB、TXT、Markdown、PDF、DOCX**、または**各章ごとのファイルのフォルダ**（Scrivener/Obsidian/連載小説）。
- **目次に基づいたEPUBの分割** - 書籍自体の目次から章の区切りとタイトルを抽出します。
- **DOCX**は、Wordの「見出し1/2」または「タイトル」スタイルで分割されます。**PDF**は、見出しを検出し（スキャンされたPDFに対する保護機能付き）、カスタム `--chapter-delimiter` を使用できます。
- スマートなテキストクリーニング、Markdownに対応したストリッピング、脚注処理、および**再利用可能な発音辞書**（`pronunciation import/export`、CSV/JSON形式で、フォネームをそのまま使用可能）。

### 声優の割り当てと属性設定
- **複数音声合成**。説明可能な、ランク付けされた声優の**候補**を表示し、各キャラクターに対してA/Bテストを行うための**`audition`**コマンドを使用できます。
- **インタラクティブな声優の割り当て**、性別/役割による**一括 `cast-fill`**、シリーズ全体で再利用できる**名前付きの声優プリセット**、および共同作業者向けの**CSV形式の声優シート**。
- **会話の検出 + 話者の属性設定**（オプションで**BookNLP**の共参照を使用）、**エイリアスの自動検出**、および調整可能な**強度**、**シーンレベルのムード**、およびジャンル**プリセットパック**を使用した**感情推論**。

### レンダリングと出力
- **M4B**（章マーカー + 埋め込みカバー + シリーズメタデータ）、**MP3**、**Opus**、**FLAC**。各章ごとのエクスポート、**ポッドキャスト/RSS**フィードのエクスポート。
- **ACX/Audibleのマスターリング** (`--acx`) + 音量、ピーク、ノイズフロアに関するPASS/FAILを報告する**`master-check`**。小売用の**`sample`**クリップも作成します。
- 並列レンダリング、再開可能な**永続的なレンダリングキャッシュ**、動的な進行状況とETA表示、および構造化されたエラーレポート。

### ワークフローとエコシステム
- **`make`**によるワンショットパイプライン、**設定ファイル**（`.audiobookerrc` / `[tool.audiobooker]`）、**`--watch`**モード、**マニフェスト駆動型バッチ処理**、シェル補完。
- **7つの言語プロファイル**（en/fr/de/es/ja/it/pt）、**プラグイン可能なTTSエンジン**（`--engine`、エントリーポイント - Piper/Coqui/ElevenLabsを導入可能）、ほとんどのコマンドでスクリプト化された`--json`形式での出力、構造化された終了コード。

## ACX / Audibleへの公開

オーディオブッカーは、測定可能なACX提出仕様に直接対応します。

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`master-check`は、測定可能な要件（音量、ピーク、ノイズフロア）を検証します。ACXには主観的/QC基準もあり、ツールでは認定できませんが、これを使用すれば、音量違反で却下されることはありません。

## CLIコマンド

| コマンド | 説明 |
|---------|-------------|
| `make <file>` | ワンショット：新規作成 → コンパイル → 自動声優割り当て → レンダリング |
| `new <ファイル\ | フォルダ>` | EPUB/TXT/MD/PDF/DOCXまたはフォルダからプロジェクトを作成します。 |
| `from-stdin` | パイプで渡されたテキストからプロジェクトを作成します。 |
| `cast <キャラクター> <声優>`・`cast --interactive` | 声優を割り当てます（または、話者ごとのガイド付きの声優割り当て）。 |
| `cast-suggest`・`cast-apply --auto`・`cast-fill` | 声優候補を提案/自動適用/一括割り当てします。 |
| `cast-preset save\ | list\ | apply\ | delete` | シリーズ全体で再利用できる声優プリセット。 |
| `audition <char>` | 1つのキャラクターに対して、ランク付けされた候補の声優をA/Bテストします（`--render`）。 |
| `compile` | 会話を検出し、話者の属性を設定し、感情を推論します。 |
| `report` | 品質のコンパイル：不明なレート、最も属性が設定されていない行の上位、感情の混合。 |
| `review-export`・`review-import <ファイル>` | 人間が編集できるレビューラウンドトリップ。 |
| `render` | オーディオブックをレンダリングします（`--acx`、`--format`、`--split`、`--bitrate`、`--engine`、`--watch`、`--cover`、`-j N`）。 |
| `sample`・`master-check <ファイル>` | マスターリングされた小売用サンプル・ACXコンプライアンスチェック。 |
| `export-chapters`・`podcast` | 章のキューシート（ffmetadata/cue/json）・ポッドキャストRSSフィード。 |
| `preview`・`batch`・`diagnose` | 音声QAクリップ・バッチ処理/`--manifest`・環境チェック。 |
| `voices`・`chapters`・`speakers`・`info`・`status`・`cache`・`emotions`・`pronunciation`・`completion` | 検査と管理 |

すべてのコマンドは`-h/--help`をサポートします。グローバルフラグ：`--silent`、`--debug`。**終了コード:** `0` OK、`1` ユーザーエラー、`2` ランタイムエラー、`3` 部分的な成功（バッチ処理）。

## 設定

フラグを再入力する代わりに、一度デフォルトを設定します。`.audiobookerrc`（TOML形式）を書籍の横に配置するか、`[tool.audiobooker]`を`pyproject.toml`に記述します。優先順位は**CLIフラグ > プロジェクト設定 > ユーザー設定 (`~/.audiobookerrc`) > デフォルト設定**です。

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## プラグイン可能なTTSエンジン

デフォルトのエンジンは`voice-soundboard`ですが、合成バックエンドはsetuptoolsのエントリーポイント（`audiobooker.tts_engines`）を介して切り替えることができます。

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

プラグイン（`pip install audiobooker-piper`）が自身を登録します。フォークは必要ありません。

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

`render(...)`と`compile(...)`は、注入された`engine=`（`TTSEngine`プロトコルを実装する任意のオブジェクト）と進行状況コールバックを受け入れます。これにより、オーディオブッカーをGUIまたはサービスに組み込むことができます。

## アーキテクチャ

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

## セキュリティとデータ範囲

- **ネットワーク:** なし — テレメトリー、データストレージ、認証情報の送信は行いません。書籍ファイルを読み込み、オーディオファイルとキャッシュをアウトプットディレクトリに書き出します。
- **権限:** 入力への読み取りアクセス、出力への書き込みアクセス。オプションでFFmpegとTTSエンジンをPATHに追加。
- [SECURITY.md](SECURITY.md) を参照してください。

## スコアカード

| ゲート | ステータス |
|------|--------|
| A. セキュリティの基本設定 | 合格 |
| B. エラー処理 | 合格 |
| C. 運用者向けドキュメント | 合格 |
| D. リリース時の衛生管理 | 合格 |
| E. ID管理 | 合格 |

## ライセンス

[MIT](LICENSE)

---

<a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a> によって作成
