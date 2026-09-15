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

Audiobooker rileva i dialoghi, assegna una voce distinta a ciascun personaggio, deduce le emozioni, consente di rivedere e correggere tutto prima che venga prodotto anche solo un secondo di audio, quindi ottimizza il risultato in base alle specifiche audio di ACX, in modo che l'output sia un audiolibro *completo*, e non solo un file audio generato.

## Installazione

**Installazione minima (Node):**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python (CLI):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

Per il **rendering dell'audio** è necessario il motore TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l'extra `[render]`) e **FFmpeg** nel PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tutto ciò che precede il rendering (analisi, assegnazione delle voci, compilazione, revisione) funziona anche senza questi componenti. Esegui `audiobooker diagnose` per verificare la configurazione.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## Guida rapida

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

## Funzionalità

### Input e struttura
- **EPUB, TXT, Markdown, PDF, DOCX** o una **cartella di file per capitolo** (Scrivener/Obsidian/romanzi a puntate).
- **Suddivisione di EPUB basata sul sommario:** i capitoli e i titoli vengono estratti dal sommario del libro.
- **DOCX:** suddivisione in base agli stili Word `Heading 1/2`/`Title`; **PDF:** rilevamento dei titoli (con una protezione per i PDF scansionati); personalizzazione `--chapter-delimiter`.
- Pulizia intelligente del testo, rimozione di elementi in Markdown, gestione delle note a piè di pagina e un **lessico di pronuncia riutilizzabile** (`pronunciation import/export`, CSV/JSON, con possibilità di passare i fonemi).

### Assegnazione delle voci e attribuzione
- **Sintesi vocale con più voci** con suggerimenti di voci spiegabili e classificati e un comando **`audition`** per confrontare le voci candidate per ciascun personaggio.
- **Assegnazione interattiva delle voci**, **assegnazione di massa `cast-fill`** in base al genere/ruolo, **preset di voci nominati** riutilizzabili in un'intera serie e **fogli di calcolo CSV** per i collaboratori.
- **Rilevamento dei dialoghi + attribuzione del parlante** (opzionale **BookNLP** per la coreferenza), **individuazione automatica degli alias** e **deduzione delle emozioni** con intensità regolabile, **tono a livello di scena** e pacchetti di preset per genere.

### Rendering e output
- **M4B** (marcatori di capitolo + copertina incorporata + metadati della serie), **MP3**, **Opus**, **FLAC**, **WAV**; esportazione per capitolo; esportazione di **podcast/RSS**.
Il formato WAV non ha un atomo di capitolo, quindi il rendering WAV lo indica esplicitamente invece di segnalare un errore nel mux del capitolo: è consigliabile utilizzarlo quando l'audio deve essere elaborato in un editor.
- **Mastering conforme alle specifiche ACX** (`--acx`) + un controllo **`master-check`** che segnala PASS/FAIL per il volume RMS, il picco e il livello di rumore; clip di **`sample`** per la vendita al dettaglio.
- Rendering parallelo, una **cache di rendering persistente** con ripresa, avanzamento dinamico + tempo stimato e report di errore strutturati.

### Flusso di lavoro ed ecosistema
- **`make`** pipeline a esecuzione singola · **file di configurazione** (`.audiobookerrc` / `[tool.audiobooker]`) · **modalità `--watch`** · **elaborazione batch basata sul manifest** · completamento della shell.
- **7 profili linguistici** (en/fr/de/es/ja/it/pt) · **motori TTS plug-in** (`--engine`, punti di ingresso: è possibile utilizzare Piper/Coqui/ElevenLabs) · script `--json` sulla maggior parte dei comandi · codici di uscita strutturati.

## Mastering conforme alle specifiche audio di ACX

ACX pubblica un obiettivo audio preciso e misurabile. È l'elemento più simile a uno standard di mastering che esiste nel mondo degli audiolibri e vale la pena raggiungerlo, qualunque cosa si faccia con il file in seguito.

| Requisito | Specifiche ACX | Cosa fa `--acx` |
|---|---|---|
| Volume | RMS tra **−23 e −18 dBFS** | two-pass `loudnorm` at −20 LUFS, which lands inside that window for speech |
| Picco | uguale o inferiore a **−3 dBFS** | applicato nello stesso passaggio |
| Livello di rumore | uguale o inferiore a **−60 dBFS** | misurato e segnalato: non viene mai "corretto" silenziosamente |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | imposta la frequenza di campionamento; aggiungi `--format mp3 --bitrate 192k` per il codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Ecco due aspetti importanti relativi ai numeri sopra indicati:

**`master-check` misura l'RMS non ponderato, non i LUFS.** Si tratta di quantità diverse e ACX applica i criteri in base alla prima. Il valore di −20 LUFS indica come il passaggio di mastering *ottiene* tale valore: è l'obiettivo che `ffmpeg loudnorm` può raggiungere, e non ciò che viene controllato in seguito.

**Il livello di rumore viene misurato, non corretto.** È il requisito che più spesso non viene soddisfatto e deriva dall'audio di origine. Uno strumento che lo attenuasse silenziosamente nasconderebbe il numero che è necessario visualizzare.

### Dove un audiolibro narrato dall'IA può effettivamente arrivare

Rispettare le specifiche non è la stessa cosa di essere accettati, ed è importante essere chiari su questo: **il flusso di invio standard di ACX è per la narrazione umana.** I suoi requisiti dell'aprile 2026 elencano la sintesi vocale non autorizzata e le registrazioni AI tra gli elementi che non accetta, quindi un titolo narrato dall'IA richiede un'autorizzazione preventiva da parte di ACX anziché un invio ordinario.

I canali che accettano la narrazione AI, generalmente con una dichiarazione, includono l'opzione **Virtual Voice** di Amazon tramite KDP (distribuzione solo su Amazon) e gli aggregatori come **Spotify Audiobooks for Authors**, **Author's Republic** e **Kobo Writing Life**. Le politiche dei rivenditori in questo settore cambiano rapidamente: controlla i termini correnti da solo anziché fidarti di questo paragrafo.

Quindi: `--acx` riguarda l'audio. Se un rivenditore accetta un titolo narrato dall'IA è una sua decisione, e non una proprietà del file che hai appena prodotto.

## Comandi CLI

| Comando | Descrizione |
|---------|-------------|
| `make <file>` | Esecuzione singola: nuovo → compilazione → assegnazione automatica delle voci → rendering |
| `new <file\ | cartella>` | Crea un progetto da EPUB/TXT/MD/PDF/DOCX o da una cartella |
| `from-stdin` | Crea un progetto da testo inserito tramite pipe |
| `cast <char> <voice>` · `cast-interactive` | Assegna le voci (o esegui l'assegnazione guidata delle voci per ogni personaggio; vedi anche `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggerisci / applica automaticamente / assegna in blocco le voci |
| `cast-preset save\ | list\ | apply\ | delete` | Preset di voci riutilizzabili tra i libri |
| `cast-export` · `cast-import <file>` | Esporta e importa il cast in formato JSON/CSV: modifica manualmente o riutilizza tra le diverse edizioni. |
| `audition <char>` | Classifica le voci dei candidati per un singolo personaggio (`--render`). |
| `compile` | Rileva i dialoghi, attribuisci i parlanti, inferisci le emozioni. |
| `report` | Qualità della compilazione: tasso sconosciuto, righe principali non attribuite, mix di emozioni. |
| `review-export` · `review-import <file>` | Ciclo di revisione modificabile manualmente. |
| `render` | Renderizza l'audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`). |
| `sample` · `master-check <file>` | Esempio di prodotto finale: verifica rispetto alle specifiche audio di ACX. |
| `export-chapters` · `podcast` | Foglio di riferimento dei capitoli (ffmetadata/cue/json) · feed RSS del podcast. |
| `preview` · `batch` · `diagnose` | Clip di controllo della qualità della voce · batch/`--manifest` · verifica dell'ambiente (restituisce un codice di errore diverso da zero se il rendering non è possibile). |
| `load <file>` | Apri un progetto `.audiobooker` esistente. |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Ispeziona e gestisci. |

Ogni comando supporta `-h/--help`. Flag globali: `--silent`, `--debug`. **Codici di uscita:** `0` ok · `1` errore utente (incluso un libro che non può essere compilato o un rendering rifiutato perché l'attribuzione è fallita) · `2` errore di runtime · `3` parziale (batch).

## Configurazione

Imposta i valori predefiniti una sola volta invece di passare ripetutamente i flag: `.audiobookerrc` (TOML) accanto al libro o `[tool.audiobooker]` in `pyproject.toml`. La precedenza è la seguente: **flag CLI > configurazione del progetto > configurazione utente (`~/.audiobookerrc`) > valori predefiniti integrati**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motori TTS (Text-to-Speech) modulari

Il motore predefinito è `voice-soundboard`, ma il backend di sintesi può essere sostituito tramite i punti di ingresso di setuptools (`audiobooker.tts_engines`).

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un plugin (`pip install audiobooker-piper`) si registra automaticamente; non è necessario creare una copia.

## API Python

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` e `compile(...)` accettano un `engine=` iniettato (qualsiasi oggetto che implementa il protocollo `TTSEngine`) e una funzione di callback per il monitoraggio dell'avanzamento: integra audiobooker in un'interfaccia grafica o in un servizio.

## Architettura

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

## Sicurezza e ambito dei dati

- **Rete:** nessuna: nessun telemetria, nessun archivio dati, nessuna credenziale. Legge i file del libro, scrive l'audio e la cache nelle directory di output.
- **Autorizzazioni:** accesso in lettura agli input, accesso in scrittura agli output; FFmpeg e un motore TTS opzionali nel PATH.
- Consulta [SECURITY.md](SECURITY.md).

## Valutazione

| Controllo. | Stato. |
|------|--------|
| A. Baseline di sicurezza. | SUPERATO. |
| B. Gestione degli errori. | SUPERATO. |
| C. Documentazione per l'operatore. | SUPERATO. |
| D. Procedure di rilascio. | SUPERATO. |
| E. Identità. | SUPERATO. |

## Licenza

[MIT](LICENSE).

---

Creato da <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.
