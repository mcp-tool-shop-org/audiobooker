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

オーディオブッカーは、セリフを検出し、各キャラクターに特徴的な声を与え、感情を推測し、1秒分の音声が生成される前に、すべてを確認および修正できるようにし、最後に結果をACXのオーディオ仕様に合わせて調整します。そのため、出力されるのは「完成した」オーディオブックであり、単なる生成されたオーディオではありません。

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

**オーディオのレンダリング**には、[`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTSエンジン（追加の`[render]`）と、PATHに設定された**FFmpeg**（`winget install ffmpeg`・`brew install ffmpeg`・`apt install ffmpeg`）が必要です。レンダリングまでのすべての処理（解析、キャスト、コンパイル、レビュー）は、これらがなくても実行できます。セットアップを確認するには、`audiobooker diagnose`を実行してください。

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
- **EPUB、TXT、Markdown、PDF、DOCX**、または**章ごとのファイルを含むフォルダー**（Scrivener / Obsidian / シリーズ小説）。
- **TOC（目次）に基づいたEPUBの分割** - 章の区切りとタイトルは、書籍自体の目次から取得されます。
- **DOCX**は、Wordの`Heading 1/2`/`Title`スタイルに基づいて分割されます。**PDF**は、見出しを検出し（スキャンされたPDFに対する保護機能付き）、カスタムの`--chapter-delimiter`を使用します。
- スマートなテキストクリーニング、Markdownに対応したテキストの削除、脚注の処理、および**再利用可能な発音辞書**（`pronunciation import/export`、CSV / JSON形式で、フォネームをそのまま使用）。

### キャストとアトリビューション
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.

### レンダリングと出力
- **M4B**（章マーカー + 埋め込まれた表紙 + シリーズメタデータ）、**MP3**、**Opus**、**FLAC**、**WAV**。章ごとのエクスポート、**ポッドキャスト/RSS**フィードのエクスポート。
WAVには章アトムがないため、WAVでレンダリングした場合、章の結合に失敗したというメッセージが表示されるのではなく、その旨が明示的に表示されます。オーディオを編集ツールに渡す場合は、WAVを使用してください。
- **ACX仕様に準拠したマスタリング**（`--acx`）+ **RMSラウドネス、ピーク、およびノイズフロア**でPASS / FAILを報告する**`master-check`**。小売用の**`sample`**クリップ。
- 並列レンダリング、**再開可能な永続的なレンダリングキャッシュ**、動的な進行状況 + 残り時間表示、および構造化されたエラーレポート。

### ワークフローとエコシステム
- **`make`**ワンショットパイプライン、**設定ファイル**（`.audiobookerrc` / `[tool.audiobooker]`）、**`--watch`**モード、**マニフェスト駆動型のバッチ処理**、シェル補完。
- **7つの言語プロファイル**（en / fr / de / es / ja / it / pt）、**プラグイン可能なTTSエンジン**（`--engine`、エントリポイント - Piper / Coqui / ElevenLabsを導入）、ほとんどのコマンドでスクリプト可能な`--json`、構造化された終了コード。

## ACXオーディオ仕様へのマスタリング

ACXは、正確で測定可能なオーディオターゲットを公開しています。これは、オーディオブック業界におけるマスタリング標準に最も近いものであり、ファイルに対してどのような処理を行っても、この基準を満たす価値があります。

| 要件 | ACX仕様 | `--acx`が実行すること |
|---|---|---|
| ラウドネス | RMSは**-23 dBFSと-18 dBFSの間** | -20 LUFSで2パスの`loudnorm`処理を行い、これにより、この範囲内に収まります。 |
| ピーク | **-3 dBFS以下** | 同じパスで強制されます。 |
| ノイズフロア | **-60 dBFS以下** | 測定およびレポートされます。ただし、サイレントに「修正」することはありません。 |
| フォーマット | **44.1 kHz、192 kbps CBR MP3** | サンプルレートを設定します。コーデックには、`--format mp3 --bitrate 192k`を追加します。 |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

上記の数値について、特に注意すべき点は次の2点です。

**`master-check`は、非加重RMSを測定するものであり、LUFSではありません。**これらは異なる量であり、ACXは前者に基づいてゲートを設定します。-20 LUFSという数値は、マスタリングパスがどのようにしてその値に到達するかを示しており、これは`ffmpeg loudnorm`がターゲットにできる値であり、後でチェックされる値ではありません。

**ノイズフロアは測定されますが、修正はされません。**これは、最も頻繁に要件を満たせない原因であり、ソースオーディオに起因します。ツールがこれを静かにゲートで処理すると、確認する必要がある数値を隠してしまうことになります。

### AIによるナレーションのオーディオブックが実際にどのようなものになり得るか

仕様を満たすことは、承認されることと同じではありません。これは明確にしておくべき点です。**ACXの標準的な提出フローは、人間のナレーション用です。**2026年4月の要件リストには、許可されていないテキスト読み上げおよびAI録音が、受け入れられないものとして記載されています。したがって、AIによるナレーションのタイトルは、通常の提出ではなく、ACXからの事前の承認が必要です。

AIナレーションを受け入れるルート（通常は開示が必要）には、Amazonの**Virtual Voice**（KDP経由、Amazonのみの配信）や、**Spotify Audiobooks for Authors**、**Author's Republic**、**Kobo Writing Life**などのアグリゲーターがあります。この分野における小売業者のポリシーは急速に変化するため、この段落を信頼するのではなく、現在の条件を自分で確認してください。

したがって、`--acx`はオーディオに関するものです。小売業者がAIによるナレーションのタイトルを受け入れるかどうかは、彼らの決定であり、あなたが作成したファイルの特性ではありません。

## CLIコマンド

| コマンド | 説明 |
|---------|-------------|
| `make <file>` | ワンショット：新規作成 → コンパイル → 自動キャスト → レンダリング |
| `new <ファイル\ | フォルダー>` | EPUB / TXT / MD / PDF / DOCX、またはフォルダーからプロジェクトを作成します。 |
| `from-stdin` | パイプで渡されたテキストからプロジェクトを作成します。 |
| `cast <char> <voice>`・`cast-interactive` | 音声の割り当て（または、ガイダンス付きのスピーカーごとのキャスト、および`cast -i`）。 |
| `cast-suggest`・`cast-apply --auto`・`cast-fill` | 音声の提案/自動適用/一括割り当て |
| `cast-preset save\ | list\ | apply\ | delete` | シリーズ全体で再利用できるキャストプリセット。 |
| `cast-export`・`cast-import <file>` | JSON/CSV形式でキャストを読み込み/書き出し — 手動で編集するか、複数のバージョンで再利用 |
| `audition <char>` | 1つのキャラクターに対して、A/B評価された候補の音声（`--render`） |
| `compile` | 対話を検出し、話者を特定し、感情を推測する |
| `report` | 品質の評価：不明な割合、最も問題のある行、感情のブレ |
| `review-export`・`review-import <file>` | 人間が編集可能なレビューを繰り返し行う |
| `render` | オーディオブックをレンダリングする（`--acx`、`--format`、`--split`、`--bitrate`、`--engine`、`--watch`、`--cover`、`-j N`） |
| `sample`・`master-check <file>` | 最終版のサンプルを作成し、ACXのオーディオ仕様と比較する |
| `export-chapters`・`podcast` | チャプターのキューシート（ffmetadata/cue/json）、ポッドキャストのRSSフィード |
| `preview`・`batch`・`diagnose` | 音声QAクリップ、バッチ処理/`--manifest`、環境チェック（レンダリングできない場合、ゼロ以外の値を返す） |
| `load <file>` | 既存の`.audiobooker`プロジェクトを開く |
| `voices`、`chapters`、`speakers`、`info`、`status`、`cache`、`emotions`、`pronunciation`、`completion` | 確認と管理 |

すべてのコマンドは`-h/--help`をサポートします。グローバルフラグ：`--silent`、`--debug`。**終了コード：** `0`（正常）、`1`（ユーザーエラー、コンパイルできない書籍、またはアトリビューションに失敗してレンダリングを拒否した場合を含む）、`2`（実行時）、`3`（バッチ処理）。

## 設定

フラグを毎回再指定する代わりに、デフォルト値を一度設定する — `.audiobookerrc`（TOML）を書籍のディレクトリに配置するか、`[tool.audiobooker]`を`pyproject.toml`に配置する。優先順位は、**CLIフラグ > プロジェクト設定 > ユーザー設定（`~/.audiobookerrc`）> デフォルト設定**。

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## プラグイン可能なTTSエンジン

デフォルトのエンジンは`voice-soundboard`ですが、setuptoolsのエントリーポイント（`audiobooker.tts_engines`）を介して合成バックエンドを切り替えることができます。

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

プラグイン（`pip install audiobooker-piper`）は自身を登録します。フォークは不要です。

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

`render(...)`と`compile(...)`は、注入された`engine=`（`TTSEngine`プロトコルを実装する任意のオブジェクト）と進捗コールバックを受け入れます — GUIまたはサービスにオーディオブック作成機能を組み込むことができます。

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## セキュリティとデータ範囲

- **ネットワーク：** なし — テレメトリー、データストレージ、認証情報は使用しません。書籍ファイルを読み込み、オーディオとキャッシュを出力ディレクトリに書き込みます。
- **権限：** 入力への読み取りアクセス、出力への書き込みアクセス。オプションで、FFmpegとTTSエンジンをPATHに設定します。
- [SECURITY.md](SECURITY.md)を参照してください。

## スコアカード

| ゲート | ステータス |
|------|--------|
| A. セキュリティの基本 | 合格 |
| B. エラー処理 | 合格 |
| C. 運用ドキュメント | 合格 |
| D. リリース時の衛生管理 | 合格 |
| E. 識別 | 合格 |

## ライセンス

[MIT](LICENSE)

---

MCP Tool Shopによって作成されました。
