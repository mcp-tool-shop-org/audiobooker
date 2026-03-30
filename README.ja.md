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
  AI Audiobook Generator — Convert EPUB/TXT/PDF books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## 機能

### 入力と解析
- **EPUB / TXT / Markdown** ファイルの解析機能（章の自動検出）
- **PDFサポート**（オプション）：PyMuPDF（`pip install -e '.[pdf]'`）を使用してPDFファイルからテキストを抽出
- **テキストの正規化**: スマートクォートの修正、空白の正規化、設定可能なテキストクリーナー
- **発音のオーバーライド**: 固有名詞や専門用語に対するカスタムの発音マッピング
- **注釈の処理**: 注釈の表示方法を設定可能（`inline`: 行内、`end`: 脚注、`skip`: 飛ばす）

### 会話と登場人物
- **会話の検出**: 会話とナレーションを自動的に区別
- **高度な会話検出**: 複数の登場人物が登場するシーンでの会話の流れを追跡
- **舞台指示**: 脚本中の括弧で囲まれた舞台指示を検出し、処理
- **BookNLP連携**: オプションで、NLP（自然言語処理）を活用した登場人物の参照解決機能
- **登場人物の別名**: 複数の名前を主要な登場人物にマッピング

### 音声と配役
- **マルチボイス合成**: 各登場人物に異なる声の割り当て
- **音声の提案**: 登場人物ごとに、説明付きのランキング形式で音声の推奨
- **感情の推測**: 設定可能な信頼度で、ルールの組み合わせと辞書を用いて感情をラベル付け
- **登場人物ごとの音声パラメータ**: 再生速度（0.5～2.0）と感情
- **SSML前処理**: Speech Synthesis Markup Language（音声合成マークアップ言語）による、詳細な制御

### レンダリングと出力
- **並列レンダリング**: `--jobs N` オプションで、複数のプロセスを使用して章を並行してレンダリング
- **複数の出力形式**: MP3、M4B、WAV、OGG、FLAC
- **音声の正規化**: 章ごとに音量を均一化
- **カバーアートの埋め込み**: EPUBファイルから抽出するか、ユーザーが提供したカバーアートをM4Bファイルに埋め込み
- **レンダリングキャッシュの永続化**: 失敗したレンダリングを再開し、完了済みの章を再合成しない
- **リアルタイムの進捗状況と推定完了時間**: レンダリングの状況をリアルタイムで表示し、完了までの推定時間を表示
- **エラーレポート**: レンダリングエラーに関する構造化されたJSON形式の診断情報

### 言語と地域設定
- **5つの言語プロファイル**: 英語、フランス語、ドイツ語、スペイン語、日本語 (`--lang en|fr|de|es|ja`)
- **拡張可能なプロファイルシステム**: `LanguageProfile` の抽象化を利用して、新しい言語を追加

### ワークフローと生産性
- **レンダリング前のレビュー**: 属性を修正するための、人間が編集可能なレビュー形式
- **プロジェクトの差分**: プロジェクトの2つのバージョンを比較し、章と発話の変化を確認
- **一括処理**: `audiobooker batch` コマンドを使用して、複数の書籍を一括で処理
- **プレビューモード**: `--dry-run` オプションで、レンダリングや一括処理を実際に実行せずにプレビュー
- **音声の試聴**: 短いサンプルをレンダリングして、音声の割り当てを検証 (`audiobooker preview`)
- **章の管理**: マージ、分割、およびレンダリング前の章の除外
- **感情の管理**: コンパイル後、発話ごとに感情をリスト表示し、オーバーライド
- **デスクトップ通知**: 長時間のレンダリングが完了した際に通知
- **プロジェクトの永続化**: レンダリングセッションを保存および再開

## インストール

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

## オプション機能

| 機能 | インストール | 設定 |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` または voice-soundboard をインストール | `render` 機能に必要なもの |
| **BookNLPによる登場人物の参照解決** | `pip install -e '.[nlp]'` | `--booknlp on` | `off` | `auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | 実行時に自動検出 |
| **FFmpeg audio assembly** | システムパッケージ (winget/brew/apt) | M4B出力に必要なもの |

## クイックスタート

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
- `=== 章のタイトル ===` - 章の区切り
- `@Speaker` または `@Speaker (感情)` - 話者タグ
- `# コメント` - コメント（インポート時に無視されます）
- 不要な発話を削除するには、ブロックを削除してください。
- `@Unknown` を `@ActualName` に変更して、発話者の誤りを修正してください。

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

## CLI コマンド

| コマンド | 説明 |
|---------|-------------|
| `audiobooker new <file>` | EPUB/TXT/MD/PDF からプロジェクトを作成 |
| `audiobooker load <project>` | 既存の `.audiobooker` プロジェクトをロード |
| `audiobooker from-stdin` | パイプで渡されたテキストからプロジェクトを作成 |
| `audiobooker cast <char> <voice>` | キャラクターに声優を割り当てる |
| `audiobooker cast-suggest` | 未割り当ての音声に最適な声優を提案 |
| `audiobooker cast-apply --auto` | 最適な声優の提案を自動的に適用 |
| `audiobooker compile` | 章を音声ファイルに変換 |
| `audiobooker review-export` | 人間のレビュー用にスクリプトをエクスポート |
| `audiobooker review-import <file>` | 編集されたレビューファイルをインポート |
| `audiobooker render` | オーディオブックをレンダリング（`--dry-run`、`--jobs N`、`--format`、`--cover` をサポート） |
| `audiobooker preview` | 音声の検証用に短いサンプルをレンダリング（`--chapter N`、`--seconds S`） |
| `audiobooker batch <files...>` | 複数の書籍をまとめて処理（`--dry-run` をサポート） |
| `audiobooker info` | プロジェクト情報を表示 |
| `audiobooker status` | レンダリング/キャッシュの状態を表示 |
| `audiobooker voices` | 利用可能な声優を一覧表示（`--gender`、`--search` をサポート） |
| `audiobooker chapters` | 章のタイトルとインデックスを一覧表示 |
| `audiobooker speakers` | 検出された話者を一覧表示 |
| `audiobooker cache info` | `clean` | `clean-failed` | レンダリングキャッシュを管理 |
| `audiobooker diagnose` | 環境を確認（依存関係、音声エンジン、FFmpeg） |

## 完全な CLI リファレンス

すべてのコマンドは、詳細な使用方法を表示するために `-h` / `--help` をサポートします。主なオプション：

- **`new`**: `-o <プロジェクト名>`、`--lang <言語コード>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <感情>`、`--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`、`--no-resume`、`--from-chapter N`、`--allow-partial`、`--clean-cache`、`--jobs N`、`-o <パス>`、`--format mp3|m4b|wav|ogg|flac`、`--cover <画像ファイル>`
- **`preview`**: `--chapter N`、`--seconds S`、`-o <パス>`
- **`batch`**: `--dry-run`、`--jobs N`、`--format <形式>`、`--lang <言語コード>`、`--output-dir <ディレクトリ>`
- **`voices`**: `--gender <男性|女性>`、`--search <検索語句>`
- **`info`**: `--verbose`

## アーキテクチャ

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

**フロー:**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## 一般的な問題

| 問題 | 解決策 |
|---------|-----|
| **FFmpeg not found** | パッケージマネージャーからインストール：`winget install ffmpeg` (Windows)、`brew install ffmpeg` (macOS)、`apt install ffmpeg` (Linux)。FFmpeg は PATH に設定する必要があります。 |
| **voice-soundboard がインストールされていない** | 関連リポジトリをクローンしてインストール：`git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`。または、`pip install -e '.[render]'` でインストールします。 |
| **BookNLP のエラーまたは起動が遅い** | BookNLP はオプションです。NLP による話者認識が不要な場合は、`--booknlp off` を設定するか、`auto` のままにします（自動的にフォールバックします）。必要な場合にのみ、`pip install -e '.[nlp]'` でインストールしてください。 |

詳細なトラブルシューティングについては、[マニュアル](docs/handbook.md#15-troubleshooting) を参照してください。

## トラブルシューティング

**レンダリングエラーレポート**: レンダリング中にエラーが発生した場合、Audiobooker はキャッシュディレクトリに `render_failure_report.json` というファイルを書き込みます。このファイルには、次の情報が含まれます。
- エラーが発生した章のインデックスとタイトル
- エラーが発生した発話のインデックス、話者、テキストのプレビュー
- 合成に使用された音声 ID と感情
- 完全なスタックトレース
- キャッシュとマニフェストのパス

**一般的な FFmpeg の問題**:
- `FFmpeg が見つからない`: パッケージマネージャー（winget/brew/apt）からインストールしてください。
- `章の埋め込みに失敗`: Audiobooker は、章マーカーのない M4A ファイルにフォールバックします。
- 音声品質: デフォルトは AAC 128kbps at 24kHz です（ProjectConfig で設定可能）。

**キャッシュに関する問題:**
- `audiobooker render --clean-cache`：すべてのキャッシュされたオーディオデータをクリアし、再レンダリングを実行します。
- `audiobooker render --no-resume`：今回の実行ではキャッシュを無視します。
- `audiobooker render --from-chapter 5`：特定の章から開始します。

## ロードマップ

- [x] コアパイプライン（解析、変換、コンパイル、レンダリング）
- [x] レンダリング前のレビューワークフロー
- [x] 永続的なレンダリングキャッシュと再開機能
- [x] 言語プロファイルと入力の柔軟性
- [x] BookNLP、感情推論、音声の提案、UXの改善
- [x] v1.0.0 - プロダクションリリース

## セキュリティとデータ範囲

- **アクセスされるデータ:** ローカルファイルシステムからEPUB/TXTファイルを読み込みます。オーディオファイルとキャッシュのマニフェストを出力ディレクトリに書き込みます。オプションで、TTS（テキスト読み上げ）のためにボイス・サウンドボード、およびオーディオの結合のためにFFmpegを使用します。
- **アクセスされないデータ:** ネットワークリクエストは行いません。テレメトリー機能はありません。ユーザーデータの保存もありません。認証情報やトークンも使用しません。
- **必要な権限:** 入力ファイルの読み取り権限、出力ディレクトリへの書き込み権限。オプション：FFmpegがPATHに設定されていること。

## 評価項目

| ゲート | ステータス |
|------|--------|
| A. セキュリティ基準 | 合格 |
| B. エラー処理 | 合格 |
| C. 運用者向けドキュメント | 合格 |
| D. リリースの品質 | 合格 |
| E. 認証 | 合格 |

## ライセンス

[MIT](LICENSE)

---

作成者: <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
