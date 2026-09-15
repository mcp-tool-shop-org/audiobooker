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

オーディオブッカーは、会話を検出し、各キャラクターに異なる声を与え、感情を推測し、1秒分の音声もレンダリングする前に、すべてを確認および修正できるようにし、最後に結果をACXのオーディオ仕様に合わせて調整します。そのため、出力されるのは「完成」したオーディオブックであり、単なる生成されたオーディオではありません。

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

**Docker** — ffmpegはすでに含まれており、すべてのリリース時にGHCRに公開されます。
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
この1つのマウントで十分であり、`--rm`は安全です。レンダリングキャッシュは、プロジェクトファイルと一緒に、ホームディレクトリではなく保存されます。そのため、再実行すると、最初からオーディオブックを再合成するのではなく、中断したところから**再開**されます。

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- `latest`、`2`、`2.1`、および正確なバージョンにタグ付けし、すべてのリリース時にGHCRにプッシュします。
- エントリーポイントは`audiobooker`であるため、イメージ名の直後にサブコマンドを渡します。プログラム名を繰り返さないでください。
- キャッシュは`<book-dir>/.audiobooker/cache`に保存されます。そのため、1つのバインドマウントで永続化が可能です。これを失うと、TTS処理全体を再度実行する必要があり、単に再マルチプレックスするだけでは済みません。
- `/ext`はオプションの2番目のマウントであり、独自のTTSホイールを供給する場合にのみ使用します。
- コンテナは、非rootユーザーID 1000として実行されます。Linuxでは、マウントされたディレクトリがそのUIDによって書き込み可能でない場合、キャッシュに書き込むことができません。`--user "$(id -u):$(id -g)"`または`chown`をディレクトリに追加してください。macOSおよびWindowsのDocker Desktopは、これを自動的に処理します。

</details>

**オーディオのレンダリング**には、[`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTSエンジン（`[render]`の追加機能）と、PATHにある**FFmpeg**（`winget install ffmpeg`・`brew install ffmpeg`・`apt install ffmpeg`）が必要です。解析、キャスト、コンパイル、レビューなど、レンダリングまでのすべての処理は、これらがなくても実行できます。`audiobooker diagnose`を実行して、セットアップを確認してください。

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
- **EPUB、TXT、Markdown、PDF、DOCX**、または**チャプターごとのファイルのフォルダ**（Scrivener / Obsidian / シリアライズされたフィクション）。
- **TOC駆動のEPUB分割** — 書籍自体の目次からチャプターの境界とタイトルを取得します。
- **DOCX**は、Wordの`Heading 1/2`/`Title`スタイルで分割します。**PDF**は、見出しを検出し（スキャンされたPDFに対するガード付き）、カスタムの`--chapter-delimiter`を使用します。
- スマートなテキストクリーニング、Markdown対応のストリッピング、脚注の処理、および**再利用可能な発音辞書**（`pronunciation import/export`、CSV / JSON、およびフォネームのパススルー）。

### キャストとアトリビューション
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.

### レンダリングと出力
- **M4B**（チャプターマーカー + 埋め込みカバー + シリーズメタデータ）、**MP3**、**Opus**、**FLAC**、**WAV**。チャプターごとのエクスポート。**ポッドキャスト/RSS**フィードのエクスポート。
WAVにはチャプターアトムがないため、WAVレンダリングでは、チャプターのマルチプレックスに失敗したというメッセージが表示されるのではなく、そのことを明示的に示します。オーディオをエディターに渡す場合は、WAVを使用してください。
- **ACX仕様に準拠したマスタリング**（`--acx`）+ **RMSラウドネス、ピーク、およびノイズフロア**でPASS / FAILを報告する**`master-check`**。小売用の**`sample`**クリップ。
- 並列レンダリング、**永続的なレンダリングキャッシュ**（再開機能付き）、動的な進行状況 + ETA、および構造化されたエラーレポート。

### ワークフローとエコシステム
- **`make`**ワンショットパイプライン、**構成ファイル**（`.audiobookerrc` / `[tool.audiobooker]`）、**`--watch`**モード、**マニフェスト駆動のバッチ**、およびシェル補完。
- **7つの言語プロファイル**（en / fr / de / es / ja / it / pt）、**プラグ可能なTTSエンジン**（`--engine`、エントリーポイント — Piper / Coqui / ElevenLabs）、ほとんどのコマンドでスクリプト可能な`--json`、および構造化された終了コード。

## ACXオーディオ仕様へのマスタリング

ACXは、正確で測定可能なオーディオターゲットを公開しています。これは、オーディオブックの世界におけるマスタリング標準に最も近いものであり、ファイルに対してどのような処理を行っても、この基準を満たす価値があります。

| 要件 | ACX仕様 | `--acx`が何をするか |
|---|---|---|
| ラウドネス | RMSは**-23〜-18 dBFS**の間 | -20 LUFSで2パスの`loudnorm`処理を行い、これにより、この範囲内に収まります。 |
| ピーク | **-3 dBFS以下** | 同じパスで強制されます。 |
| ノイズフロア | **-60 dBFS以下** | 測定およびレポートされます。ただし、サイレントに「修正」されることはありません。 |
| フォーマット | **44.1 kHz、192 kbps CBR MP3** | サンプルレートを設定します。コーデックには`--format mp3 --bitrate 192k`を追加します。 |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

上記の数値について、以下の2点に注意する必要があります。

**`master-check`は、非加重RMSを測定するものであり、LUFSではありません。**これらは異なる量であり、ACXは前者に対してゲートを設定します。-20 LUFSの数値は、マスタリングパスがそれを**どのように達成するか**であり、これは`ffmpeg loudnorm`がターゲットにできる値であり、その後にチェックされるものではありません。

**ノイズフロアは測定されますが、修正はされません。**これは、最も失敗しやすい要件であり、ソースオーディオから発生します。ツールがこれを静かにゲートで処理すると、確認する必要がある唯一の数値が隠されてしまいます。

### AIナレーションオーディオブックが実際にどこまで行けるか

仕様を満たすことは、承認されることと同じではありません。これは明確にしておく価値があります。**ACXの標準的な送信フローは、人間のナレーション用です。**2026年4月の要件リストには、許可されていないテキスト読み上げおよびAI録音が、受け入れられないものとして記載されています。したがって、AIナレーションのタイトルは、通常の送信ではなく、ACXからの事前の承認が必要です。

AIによるナレーションを受け入れる販売ルートは、通常、その旨の明示とともに、AmazonのKDP（Amazonのみでの販売）を通じた**Virtual Voice**や、**Spotify Audiobooks for Authors**、**Author's Republic**、**Kobo Writing Life**などの集約サービスなどが含まれます。この分野における販売業者のポリシーは急速に変化するため、この段落を鵜呑みにせず、最新の利用規約を必ずご自身でご確認ください。

したがって、`--acx`はオーディオに関するものです。販売業者がAIによるナレーションのタイトルを受け入れるかどうかは、その販売業者の判断であり、あなたが作成したファイルの特性ではありません。

## CLIコマンド

| コマンド | 説明 |
|---------|-------------|
| `make <file>` | ワンショット：新規作成→コンパイル→自動キャスト→レンダリング |
| `new <ファイル\ | フォルダ>` | EPUB/TXT/MD/PDF/DOCXファイルまたはフォルダからプロジェクトを作成します。 |
| `from-stdin` | パイプで渡されたテキストからプロジェクトを作成します。 |
| `cast <char> <voice>` · `cast-interactive` | 音声の割り当て（または、キャラクターごとのガイダンス付きのキャスト。また、`cast -i`も同様）。 |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | 音声の提案/自動適用/一括割り当て |
| `cast-preset save\ | list\ | apply\ | delete` | 複数の書籍で再利用可能なキャストプリセット |
| `cast-export` · `cast-import <file>` | キャストをJSON/CSV形式で双方向変換します。手動で編集したり、複数のエディションで再利用したりできます。 |
| `audition <char>` | 1つのキャラクターに対するA/B評価された候補音声（`--render`） |
| `compile` | 会話の検出、話者の属性付け、感情の推測 |
| `report` | 品質のコンパイル：不明なレート、属性が割り当てられていない上位の行、感情の混合 |
| `review-export` · `review-import <file>` | 人間が編集可能なレビューの双方向変換 |
| `render` | オーディオブックをレンダリングします（`--acx`、`--format`、`--split`、`--bitrate`、`--engine`、`--watch`、`--cover`、`-j N`） |
| `sample` · `master-check <file>` | マスターされた小売サンプル。ACXのオーディオ仕様に照らして確認します。 |
| `export-chapters` · `podcast` | チャプターのキューシート（ffmetadata/cue/json）。ポッドキャストのRSSフィード。 |
| `preview` · `batch` · `diagnose` | 音声QAクリップ。バッチ処理/`--manifest`。環境チェック（ボックスがレンダリングできない場合、ゼロ以外の値を返します）。 |
| `load <file>` | 既存の`.audiobooker`プロジェクトを開きます。 |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | 検査と管理 |

すべてのコマンドは`-h/--help`をサポートします。グローバルフラグ：`--silent`、`--debug`。**終了コード：**`0` OK · `1` ユーザーエラー（コンパイルできない書籍、または属性付けが失敗したためレンダリングが拒否された場合を含む）· `2` ランタイム · `3` 部分（バッチ）。

## 設定

フラグを毎回再指定する代わりに、デフォルト値を一度設定します。`.audiobookerrc`（TOML）を書籍の横に配置するか、`[tool.audiobooker]`を`pyproject.toml`に配置します。優先順位は、**CLIフラグ > プロジェクト設定 > ユーザー設定（`~/.audiobookerrc`）> 組み込みのデフォルト**です。

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

プラグイン（`pip install audiobooker-piper`）は自身を登録します。フォークは必要ありません。

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

`render(...)`と`compile(...)`は、注入された`engine=`（`TTSEngine`プロトコルを実装する任意のオブジェクト）と、進捗状況コールバックを受け入れます。オーディオブック作成ツールをGUIまたはサービスに組み込むことができます。

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

- **ネットワーク：** なし。テレメトリ、データストレージ、認証情報は一切使用しません。書籍ファイルを読み取り、オーディオとキャッシュを出力ディレクトリに書き込みます。
- **権限：** 入力への読み取りアクセス、出力への書き込みアクセス。オプションで、FFmpegとPATHにあるTTSエンジンが必要です。
- [SECURITY.md](SECURITY.md)を参照してください。

## スコアカード

| ゲート | ステータス |
|------|--------|
| A. セキュリティの基本 | PASS |
| B. エラー処理 | PASS |
| C. 運用ドキュメント | PASS |
| D. リリースの衛生管理 | PASS |
| E. 識別 | PASS |

## ライセンス

[MIT](LICENSE)

---

MCP Tool Shopによって作成されました。
