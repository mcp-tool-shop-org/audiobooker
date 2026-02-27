<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/mcp-tool-shop-org/audiobooker"><img src="https://codecov.io/gh/mcp-tool-shop-org/audiobooker/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## 特徴

- **多声音合成**: 各キャラクターに固有の声を割り当て可能
- **会話検出**: 発話とナレーションを自動的に区別
- **感情推論**: 設定可能な信頼度を持つ、ルールベースと辞書に基づく感情ラベル
- **音声の提案**: 話者ごとに、説明可能なランキング形式で音声の推奨
- **BookNLP連携**: オプションで、NLPを活用した話者参照解決機能
- **レンダリング前のレビュー**: 属性の修正を容易にする、人間が編集可能なレビュー形式
- **永続的なレンダリングキャッシュ**: 完了した章を再合成せずに、中断されたレンダリングを再開可能
- **動的な進捗状況と推定完了時間**: リアルタイムのレンダリング状況と推定完了時間表示
- **エラーレポート**: レンダリングエラーに関する構造化されたJSON形式の診断情報
- **言語プロファイル**: 言語ごとのルールを拡張可能
- **M4B出力**: チャプターナビゲーション機能付きのプロフェッショナルなオーディオブック形式
- **プロジェクトの永続化**: レンダリングセッションを保存/再開可能

## インストール

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

## オプション機能

| 機能 | インストール | 設定 |
|---------|---------|--------|
| **TTS rendering** | `pip install audiobooker-ai[render]` または voice-soundboard をインストール | `render` 機能に必要なもの |
| **BookNLPによる話者解決機能** | `pip install audiobooker-ai[nlp]` | `--booknlp on` | `off` | `auto` |
| **FFmpeg audio assembly** | システムパッケージ (winget/brew/apt) | M4B出力に必要なもの |

## クイックスタート

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

## レビューワークフロー

レビューワークフローを使用すると、レンダリング前にコンパイルされたスクリプトを検査および修正できます。

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

**レビューファイル形式:**
- `=== 章のタイトル ===` - 章のマーカー
- `@話者` または `@話者 (感情)` - 話者のタグ
- `# コメント` - コメント (インポート時に無視されます)
- 不要な発話を削除するために、ブロックを削除します。
- `@Unknown` を `@実際の名前` に変更して、属性を修正します。

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

## CLIコマンド

| コマンド | 説明 |
|---------|-------------|
| `audiobooker new <file>` | EPUB/TXTからプロジェクトを作成 |
| `audiobooker cast <char> <voice>` | 話者に声を割り当てる |
| `audiobooker cast-suggest` | 未割り当ての話し者に音声の提案を行う |
| `audiobooker cast-apply --auto` | 上位の音声提案を自動的に適用する |
| `audiobooker compile` | 章を発話にコンパイルする |
| `audiobooker review-export` | 人間のレビュー用のスクリプトをエクスポートする |
| `audiobooker review-import <file>` | 編集されたレビューファイルをインポートする |
| `audiobooker render` | オーディオブックをレンダリングする |
| `audiobooker info` | プロジェクト情報を表示する |
| `audiobooker voices` | 利用可能な音声を一覧表示する |
| `audiobooker chapters` | 章を一覧表示する |
| `audiobooker speakers` | 検出された話者を一覧表示する |
| `audiobooker from-stdin` | パイプでテキストからプロジェクトを作成する |

## アーキテクチャ

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

**フロー:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## トラブルシューティング

**レンダリングエラーレポート**: レンダリングエラーが発生した場合、Audiobookerはキャッシュディレクトリに `render_failure_report.json` を書き込みます。これには以下が含まれます。
- エラーが発生した章のインデックスとタイトル
- エラーが発生した発話のインデックス、話者、およびテキストのプレビュー
- 合成に使用された音声IDと感情
- 完全なスタックトレース
- キャッシュとマニフェストのパス

**一般的なFFmpegの問題**:
- `FFmpegが見つかりません`: パッケージマネージャー (winget/brew/apt) を使用してインストールしてください。
- `章の埋め込みに失敗しました`: Audiobookerは、チャプターマーカーのないM4A形式にフォールバックします。
- 音声品質: デフォルトはAAC 128kbps at 24kHz (ProjectConfigで設定可能)

**キャッシュの問題**:
- `audiobooker render --clean-cache` — すべてのキャッシュされたオーディオをクリアし、再レンダリングします。
- `audiobooker render --no-resume` — この実行でのみ、キャッシュを無視します。
- `audiobooker render --from-chapter 5` — 特定の章から開始します。

## ロードマップ

- [x] v0.1.0 - コアパイプライン (解析、キャスト、コンパイル、レンダリング)
- [x] v0.2.0 - レンダリング前のレビューワークフロー
- [x] v0.3.0 - 永続的なレンダリングキャッシュ + 再開機能
- [x] v0.4.0 - 言語プロファイル + 入力柔軟性
- [x] v0.5.0 - BookNLP、感情推論、音声の提案、UIの改善

## セキュリティとデータ範囲

- **アクセスするデータ:** ローカルファイルシステムからEPUB/TXTファイルを読み込みます。音声ファイルとキャッシュファイルを、出力ディレクトリに書き込みます。オプションで、TTS（テキスト読み上げ）のためにボイス・サウンドボード、および音声の結合のためにFFmpegを使用します。
- **アクセスしないデータ:** ネットワークへのリクエストは行いません。テレメトリー機能はありません。ユーザーデータの保存も行いません。認証情報やトークンも使用しません。
- **必要な権限:** 入力となる書籍ファイルへの読み取り権限。出力ディレクトリへの書き込み権限。オプション：FFmpegがPATHに設定されていること。

## 評価

| ゲート | ステータス |
|------|--------|
| A. セキュリティ基準 | 合格 |
| B. エラー処理 | 合格 |
| C. 運用者向けドキュメント | 合格 |
| D. リリース時の品質管理 | 合格 |
| E. 識別情報 | 合格 |

## ライセンス

[MIT](LICENSE)

---

作成者: <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
