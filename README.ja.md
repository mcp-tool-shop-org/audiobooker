<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

オーディオブッカーは、会話を検出し、各キャラクターに異なる声を与え、感情を推測し、1秒分の音声もレンダリングする前に、すべてを確認および修正できるようにし、最後に結果をACXオーディオ仕様に合わせて最適化します。そのため、出力されるのは「完成された」オーディオブックであり、単なる生成された音声ではありません。

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

**Docker** — ffmpegはすでに内蔵されており、すべてのリリース時にGHCRに公開されます。
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
この1つのマウントで十分であり、`--rm`は安全です。レンダリングキャッシュは、プロジェクトファイルと一緒に保存され、ホームディレクトリには保存されないため、再実行すると、オーディオブック全体を再合成するのではなく、中断したところから再開されます。

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- `latest`、`3`、`3.0`、および正確なバージョンにタグ付けし、すべてのリリース時にGHCRにプッシュします。
- エントリーポイントは`audiobooker`であるため、イメージ名の直後にサブコマンドを渡します。プログラム名を繰り返さないでください。
- キャッシュは`<book-dir>/.audiobooker/cache`に保存されます。そのため、1つのバインドマウントで永続化が可能です。これを失うと、TTS処理全体を再度実行する必要があり、単に再多重化するだけでは済みません。
- `/ext`はオプションの2番目のマウントであり、独自のTTSホイールを供給する場合にのみ使用します。
- コンテナは、非rootユーザーID 1000として実行されます。Linuxでは、マウントされたディレクトリがそのUIDによって書き込み可能でない場合、キャッシュに書き込むことができません。`--user "$(id -u):$(id -g)"`または`chown`をディレクトリに追加してください。macOSおよびWindows上のDocker Desktopは、これを自動的に処理します。

</details>

**オーディオのレンダリング**には、[`voice-soundboard`](https://pypi.org/project/voice-soundboard/) TTSエンジン（`[render]`の追加機能）と、PATHにある**FFmpeg**（`winget install ffmpeg`・`brew install ffmpeg`・`apt install ffmpeg`）が必要です。解析、キャスト、コンパイル、レビューなど、レンダリングまでのすべての処理は、これらなしでも実行できます。`audiobooker diagnose`を実行して、セットアップを確認してください。

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

これらはすべて、2.xバージョンでは許容され、静かに誤った処理を行っていたケースです。3.0バージョンでは、これらを拒否します。詳細については、[CHANGELOG](CHANGELOG.md)を参照してください。

- **最初のレンダリングでは、すべてのチャプターが1回再レンダリングされます。** オーディオを変更する3つの入力（感情プリセット、発話強度、キャラクターごとの速度/ピッチ/強調）がキャッシュキーから除外されていたため、プリセットを切り替えると「キャッシュ済み」と表示され、古いオーディオが返されていました。これらは現在キーに含まれており、2.xバージョンのキャッシュエントリでは、それがどのように生成されたかを証明できません。
- **`--format m4a`は、もはやオーディオブック全体のオプションではありません。** 常に1つのチャプターにつき1つのファイルという意味であり、以前は`m4a`でオーディオブック全体を要求すると、`.m4a`という名前の単一のM4Bファイルが生成されていました。これは、`podcast --format`でも引き続き有効です。
- **`render`は、アトリビューションが`FAILED`となっているオーディオブックを拒否します。** TTS処理を実行するのではなく。`--force`でオーバーライドできます。`audiobooker report`を実行して、どの行に問題があるかを確認してください。
- **`make`は、プロジェクトファイルがすでに存在する場合に拒否します。** 以前は、手動でキャストされた音声、発音のオーバーライド、編集されたタイトルを、新しい自動キャスト解析で上書きしていました。そのようにしたい場合は、`--overwrite-project`を渡してください。
- **`compile()`は、すべてのチャプターが失敗した場合に例外を発生させます。** これは、正常に実行された場合に返される`None`とは異なります。Pythonから呼び出す場合、例外をスローできるようになりました。

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
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## 機能

### 入力と構造
- **EPUB、TXT、Markdown、PDF、DOCX**、または**チャプターごとのファイルのフォルダ**（Scrivener/Obsidian/連載小説）。
- **TOC駆動型のEPUB分割** — チャプターの境界とタイトルは、オーディオブック自体の目次から取得します。
- **DOCX**は、Wordの`Heading 1/2`/`Title`スタイルで分割します。**PDF**は、見出しを検出し（スキャンされたPDFに対するガード付き）、カスタムの`--chapter-delimiter`を使用します。
- スマートなテキストクリーニング、Markdown対応のストリッピング、脚注の処理、および**再利用可能な発音辞書**（`pronunciation import/export`、CSV/JSON、およびフォネームのパススルー）。

### キャストとアトリビューション
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.
- **Attribution you can audit.** Every line records *how* its speaker was decided — a speech tag, an inline override, co-reference, your own correction, or a bare alternating-turn guess — and `report` counts the guesses separately from the lines it could not attribute at all. A guess cannot improve the score, so the number goes down when the attribution gets worse, which is the only direction that is useful.

### レンダリングと出力
- **M4B**（チャプターマーカー + 埋め込みカバー + シリーズメタデータ）、**MP3**、**Opus**、**FLAC**、**WAV**。チャプターごとのエクスポート。**ポッドキャスト/RSS**フィードのエクスポート。
WAVにはチャプターアトムがないため、WAVレンダリングでは、チャプターの多重化が失敗したというメッセージが明確に表示されます。オーディオをエディターに渡す場合は、これを使用してください。
- **ACX仕様に準拠したマスタリング**（`--acx`）+ **RMSラウドネス、ピーク、ノイズフロアでPASS/FAILを報告する**`master-check`**、および小売用の**`sample`**クリップ。
- 並列レンダリング、**再開機能付きの永続的なレンダリングキャッシュ**、動的な進行状況 + ETA、および構造化されたエラーレポート。
キャッシュキーには、テキスト、キャスト、音声、エンジンとバージョン、プロファイル、感情プリセットと強度など、オーディオを変更するすべてのものが含まれています。そのため、「キャッシュ済み」と表示される再レンダリングは、実際にキャッシュを使用していることを意味します。オプションの**発話ごとのキャッシュ**（`utterance_cache`）を有効にすると、再レンダリングは実際に編集した行に絞られます。

### ワークフローとエコシステム
- **`make`**ワンショットパイプライン · **設定ファイル**（`.audiobookerrc` / `[tool.audiobooker]`） · **`--watch`**モード · **マニフェスト駆動型のバッチ** · シェル補完。
- **7つの言語プロファイル**（en/fr/de/es/ja/it/pt） · **プラグ可能なTTSエンジン**（`--engine`、エントリーポイント — Piper/Coqui/ElevenLabsを導入） · ほとんどのコマンドでスクリプト可能な`--json` · 構造化された終了コード。

## ACXオーディオ仕様へのマスタリング

ACXは、正確で測定可能なオーディオターゲットを公開しています。これは、オーディオブック業界におけるマスタリング標準に最も近いものであり、ファイルに対してどのような処理を行っても、この基準を満たすことが重要です。

| 要件 | ACX仕様 | `--acx`の機能 |
|---|---|---|
| ラウドネス | **−23 dBFSと−18 dBFSの間**のRMS | −20 LUFSで2パスの`loudnorm`処理を行い、これにより、スピーチに適した範囲内に収まります。 |
| ピーク | **−3 dBFS以下** | 同じパスで強制 |
| ノイズフロア | **−60 dBFS以下** | 測定および報告され、サイレントに「修正」されることはありません。 |
| フォーマット | **44.1 kHz、192 kbps CBR MP3** | サンプルレートを設定します。コーデックには`--format mp3 --bitrate 192k`を追加します。 |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

上記の数値について考慮すべき2つの点：

**`master-check`は、LUFSではなく、非加重RMSを測定します。**これらは異なる量であり、ACXは後者に基づいてゲート処理を行います。−20 LUFSの値は、マスタリングパスがどのようにしてその値に到達するかを示しており、これは`ffmpeg loudnorm`がターゲットにできる値であり、後でチェックされる値ではありません。

**ノイズフロアは測定され、修正はされません。**これは、最も頻繁に要件を満たせない原因であり、ソースオーディオに起因します。静かにゲート処理を行うツールは、確認する必要がある数値を隠してしまうことになります。

### AIによるナレーションのオーディオブックが実際にどのようなものになり得るか

仕様を満たすことは、承認されることと同じではありません。これは明確にしておくべき点です。**ACXの標準的な提出フローは、人間のナレーション用です。**2026年4月の要件リストには、許可されていないテキスト読み上げおよびAI録音が、承認されないものとして記載されています。したがって、AIによるナレーションのタイトルは、通常の提出ではなく、ACXからの事前の承認が必要です。

AIナレーションを許可する経路（通常は開示を条件とする）には、KDP（Amazon限定の配信）を通じてAmazonの**Virtual Voice**や、**Spotify Audiobooks for Authors**、**Author's Republic**、**Kobo Writing Life**などのアグリゲーターが含まれます。この分野における小売業者のポリシーは急速に変化するため、この段落を信頼するのではなく、現在の条件を自分で確認してください。

したがって、`--acx`はオーディオに関するものです。小売業者がAIによるナレーションのタイトルを承認するかどうかは、彼らの決定であり、あなたが作成したファイルの特性ではありません。

## CLIコマンド

| コマンド | 説明 |
|---------|-------------|
| `make <file>` | ワンショット：新規作成→コンパイル→自動キャスト→レンダリング |
| `new <ファイル\ | フォルダ>` | EPUB/TXT/MD/PDF/DOCXまたはフォルダからプロジェクトを作成します。 |
| `from-stdin` | パイプされたテキストからプロジェクトを作成します。 |
| `cast <char> <voice>` · `cast-interactive` | ボイスを割り当てます（または、スピーカーごとのガイド付きキャスト、および`cast -i`）。 |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | ボイスを提案/自動適用/一括割り当てします。 |
| `cast-preset save\ | list\ | apply\ | delete` | 複数の書籍で再利用できるキャストプリセット。 |
| `cast-export` · `cast-import <file>` | キャストをJSON/CSVとして双方向転送します。手動で編集したり、複数のエディションで再利用したりできます。 |
| `audition <char>` | 1つのキャラクターに対して、A/Bランク付けされた候補ボイス（`--render`）。 |
| `compile` | ダイアログを検出し、スピーカーを特定し、感情を推測します。 |
| `report` | コンパイル品質：未割り当ての割合、推測された割合、最悪の行、感情の混合。 |
| `review-export` · `review-import <file>` | 人間が編集可能なレビューの双方向転送。 |
| `render` | オーディオブックをレンダリングします（`--acx`、`--format`、`--split`、`--bitrate`、`--engine`、`--watch`、`--cover`、`-j N`）。 |
| `sample` · `master-check <file>` | マスタリングされた小売サンプル。ACXのオーディオ仕様に対してチェックします。 |
| `export-chapters` · `podcast` | チャプターのキューシート（ffmetadata/cue/json）。ポッドキャストRSSフィード。 |
| `preview` · `batch` · `diagnose` | ボイスQAクリップ。バッチ処理/`--manifest`。環境チェック（レンダリングできない場合、ゼロ以外の値を返します）。 |
| `load <file>` | 既存の`.audiobooker`プロジェクトを開きます。 |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | 検査と管理 |

すべてのコマンドは`-h/--help`をサポートします。グローバルフラグ：`--silent`、`--debug`。**終了コード：**`0` OK · `1` ユーザーエラー（コンパイルできない書籍、またはアトリビューションが失敗したためにレンダリングが拒否された場合を含む）· `2` ランタイム · `3` 部分（バッチ）。

## 設定

フラグを再送信する代わりに、一度だけデフォルトを設定します。`.audiobookerrc`（TOML）を書籍の横に配置するか、または`[tool.audiobooker]`を`pyproject.toml`に配置します。優先順位は、**CLIフラグ > プロジェクト設定 > ユーザー設定（`~/.audiobookerrc`）> 組み込みのデフォルト**です。

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## プラグ可能なTTSエンジン

デフォルトのエンジンは`voice-soundboard`ですが、合成バックエンドはsetuptoolsのエントリーポイント（`audiobooker.tts_engines`）を介して交換可能です。

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

`render(...)`と`compile(...)`は、注入された`engine=`（`TTSEngine`プロトコルを実装する任意のオブジェクト）と、進捗コールバックを受け入れます。オーディオブック作成ツールをGUIまたはサービスに埋め込みます。

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

- **ネットワーク：** なし - テレメトリ、データストレージ、認証情報はありません。書籍ファイルを読み取り、オーディオとキャッシュを出力ディレクトリに書き込みます。
- **権限：** 入力への読み取りアクセス、出力への書き込みアクセス。オプションで、FFmpegとPATH上のTTSエンジン。
- [SECURITY.md](SECURITY.md)を参照してください。

## スコアカード

| ゲート | ステータス |
|------|--------|
| A. セキュリティベースライン | PASS |
| B. エラー処理 | PASS |
| C. 運用ドキュメント | PASS |
| D. 配送衛生 | PASS |
| E. 識別 | PASS |

## ライセンス

[MIT](LICENSE)

---

MCP Tool Shopによって作成されました。
