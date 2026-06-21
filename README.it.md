<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Audiobooker rileva i dialoghi, assegna una voce distinta a ciascun personaggio, deduce le emozioni, consente di rivedere e correggere tutto prima che venga generato anche solo un secondo di audio, quindi ottimizza il risultato per soddisfare i requisiti specifici: in questo modo, l'output è un audiolibro *pronto per essere inviato*, non semplicemente un file audio generato.

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

Per la **generazione dell'audio**, è necessario il motore TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l'opzione extra `[render]`) e **FFmpeg** nel PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tutto ciò che precede la fase di rendering (analisi, assegnazione delle voci, compilazione, revisione) funziona anche senza questi componenti. Esegui `audiobooker diagnose` per verificare la configurazione del sistema.

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
- **EPUB, TXT, Markdown, PDF, DOCX** o una **cartella contenente i file per ogni capitolo** (Scrivener/Obsidian/romanzi a puntate).
- **Suddivisione di EPUB basata sul sommario:** i confini e i titoli dei capitoli vengono estratti dal sommario del libro.
- **DOCX:** suddivisione in base agli stili Word `Heading 1/2`/`Title`; **PDF:** rilevamento degli intestazioni (con una protezione per i PDF scansionati); delimitatore di capitolo personalizzato `--chapter-delimiter`.
- Pulizia intelligente del testo, rimozione dei tag Markdown, gestione delle note a piè di pagina e un **lessico di pronuncia riutilizzabile** (`pronunciation import/export`, CSV/JSON, con possibilità di specificare i fonemi).

### Assegnazione delle voci e attribuzione
- **Sintesi vocale multi-voce** con suggerimenti di voce spiegabili e classificati e un comando **`audition`** per confrontare le diverse opzioni per ciascun personaggio.
- **Assegnazione interattiva delle voci**, **assegnazione massiva tramite `cast-fill`** in base al genere/ruolo, **preset di assegnazione riutilizzabili** per l'intera serie e **fogli di calcolo CSV** per i collaboratori.
- **Rilevamento dei dialoghi + attribuzione degli interlocutori** (opzionale: co-riferimento tramite **BookNLP**), **individuazione automatica degli alias** e **deduzione delle emozioni** con intensità regolabile, tono a livello di scena e pacchetti predefiniti per genere.

### Rendering e output
- **M4B** (marcatori di capitolo + copertina incorporata + metadati della serie), **MP3**, **Opus**, **FLAC**; esportazione per ogni capitolo; esportazione del feed **podcast/RSS**.
- **Mastering ACX/Audible** (`--acx`) + un controllo **`master-check`** che segnala se il risultato è ACCETTABILE o meno in base al volume, al picco e al livello di rumore; clip di esempio per la vendita.
- Rendering parallelo, una **cache di rendering persistente** con ripresa, avanzamento dinamico + tempo stimato rimanente e report strutturati sugli errori.

### Flusso di lavoro ed ecosistema
- **`make`:** pipeline a esecuzione singola · **file di configurazione** (`.audiobookerrc` / `[tool.audiobooker]`) · modalità **`--watch`** · elaborazione batch basata sul manifest · completamento automatico della shell.
- **7 profili linguistici** (en/fr/de/es/ja/it/pt) · **motori TTS plug-in** (`--engine`, entry-point: è possibile utilizzare Piper/Coqui/ElevenLabs) · scriptabile tramite `--json` per la maggior parte dei comandi · codici di uscita strutturati.

## Pubblicazione su ACX / Audible

Audiobooker mira direttamente a soddisfare i requisiti misurabili per l'invio ad ACX:

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`master-check` verifica i requisiti misurabili (volume, picco, livello di rumore). ACX ha anche criteri soggettivi/di controllo qualità che uno strumento non può certificare, ma non si verificherà più che il tuo audiolibro venga rifiutato a causa di problemi relativi al volume.

## Comandi CLI

| Comando | Descrizione |
|---------|-------------|
| `make <file>` | Esecuzione singola: nuovo → compilazione → assegnazione automatica delle voci → rendering |
| `new <file\ | folder>` | Crea un progetto da EPUB/TXT/MD/PDF/DOCX o da una cartella. |
| `from-stdin` | Crea un progetto da testo fornito tramite pipe. |
| `cast <char> <voice>` · `cast --interactive` | Assegna le voci (o esegui l'assegnazione guidata delle voci per ogni personaggio). |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggerisci / applica automaticamente / assegna in blocco le voci. |
| `cast-preset save\ | list\ | apply\ | delete` | Preset di assegnazione riutilizzabili per diversi libri. |
| `audition <char>` | Confronta le voci candidate classificate per un personaggio (`--render`). |
| `compile` | Rileva i dialoghi, attribuisci gli interlocutori, deduci le emozioni. |
| `report` | Qualità della compilazione: tasso sconosciuto, numero di righe non attribuite, mix di emozioni. |
| `review-export` · `review-import <file>` | Ciclo di revisione modificabile manualmente. |
| `render` | Genera l'audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`). |
| `sample` · `master-check <file>` | Clip di esempio ottimizzata per la vendita · controllo della conformità ad ACX. |
| `export-chapters` · `podcast` | Foglio di marcatura dei capitoli (ffmetadata/cue/json) · feed RSS del podcast. |
| `preview` · `batch` · `diagnose` | Clip di test della voce · elaborazione batch / `--manifest` · controllo dell'ambiente. |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Ispeziona e gestisci. |

Ogni comando supporta `-h/--help`. Flag globali: `--silent`, `--debug`. **Codici di uscita:** `0` ok · `1` errore utente · `2` errore in fase di esecuzione · `3` parziale (batch).

## Configurazione

Imposta i valori predefiniti una sola volta invece di passare ripetutamente gli stessi flag: `.audiobookerrc` (TOML) accanto al libro, oppure `[tool.audiobooker]` in `pyproject.toml`. La precedenza è la seguente: **flag CLI > configurazione del progetto > configurazione utente (`~/.audiobookerrc`) > valori predefiniti**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motori TTS plug-in

Il motore predefinito è `voice-soundboard`, ma il backend di sintesi può essere modificato tramite gli entry-point di setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un plugin (`pip install audiobooker-piper`) si registra automaticamente; non è necessario creare una copia del codice.

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

`render(...)` e `compile(...)` accettano un motore iniettato (`engine=`, qualsiasi oggetto che implementi il protocollo `TTSEngine`) e una funzione di callback per l'avanzamento: è possibile integrare Audiobooker in un'interfaccia grafica o in un servizio.

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC
```

## Sicurezza e ambito dei dati

- **Rete:** nessuna — nessun sistema di telemetria, nessun archivio dati, nessuna credenziale. Legge i file del libro, scrive l'audio e la cache nelle directory di output.
- **Autorizzazioni:** accesso in lettura agli input, accesso in scrittura agli output; FFmpeg opzionale + un motore TTS nel PATH.
- Consultare [SECURITY.md](SECURITY.md).

## Scheda di valutazione

| Gateway | Stato |
|------|--------|
| A. Standard di sicurezza | SUPERATO |
| B. Gestione degli errori | SUPERATO |
| C. Documentazione per l'operatore | SUPERATO |
| D. Procedure di rilascio | SUPERATO |
| E. Identità | SUPERATO |

## Licenza

[MIT](LICENSE)

---

Realizzato da <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
