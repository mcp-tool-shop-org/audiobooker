<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
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

Audiobooker rileva i dialoghi, assegna una voce distinta a ciascun personaggio, deduce le emozioni, consente di rivedere e correggere tutto prima che venga elaborato anche solo un secondo, quindi ottimizza il risultato in base alle specifiche audio di ACX, in modo che l'output sia un audiolibro *completo*, e non solo un file audio generato.

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

**Docker:** ffmpeg è già incluso, pubblicato su GHCR ad ogni rilascio:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
Questo singolo punto di mount è sufficiente e `--rm` è sicuro: la cache di rendering si trova accanto al file del progetto, non in una directory utente, quindi una nuova esecuzione **riprende** invece di risintetizzare l'intero libro.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Tagged `latest`, `2`, `2.1` e la versione esatta, pubblicati su GHCR ad ogni rilascio.
- Il punto di ingresso **è** `audiobooker`, quindi passa il sottocomando immediatamente dopo il nome dell'immagine; non ripetere il nome del programma.
- La cache viene salvata in `<book-dir>/.audiobooker/cache`. Ecco perché un singolo punto di mount copre la persistenza; perderlo significa dover pagare di nuovo per l'intera esecuzione TTS, e non solo per il re-muxing.
- `/ext` è un secondo punto di mount opzionale, solo per fornire il proprio motore TTS.
- Il container viene eseguito come UID non root 1000. Su Linux, se la directory montata non è scrivibile da tale UID, la cache non può essere scritta; aggiungi `--user "$(id -u):$(id -g)"` o `chown` alla directory. Docker Desktop su macOS e Windows gestisce questo aspetto per te.

</details>

**Il rendering audio** richiede il motore TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l'extra `[render]`) e **FFmpeg** nel PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tutto ciò che precede il rendering (analisi, assegnazione delle voci, compilazione, revisione) funziona senza di essi. Esegui `audiobooker diagnose` per verificare la configurazione.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## Avvio rapido

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
- **Suddivisione EPUB basata sul sommario:** i confini e i titoli dei capitoli vengono estratti dal sommario del libro.
- **DOCX:** suddivisione in base agli stili Word `Heading 1/2`/`Title`; **PDF:** rilevamento delle intestazioni (con una protezione per i PDF scansionati); personalizzazione `--chapter-delimiter`.
- Pulizia intelligente del testo, rimozione di elementi in Markdown, gestione delle note a piè di pagina e un **lessico di pronuncia riutilizzabile** (`pronunciation import/export`, CSV/JSON, con passaggio dei fonemi).

### Assegnazione delle voci e attribuzione
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.

### Rendering e output
- **M4B** (marcatori di capitolo + copertina incorporata + metadati della serie), **MP3**, **Opus**, **FLAC**, **WAV**; esportazione per capitolo; esportazione del feed **podcast/RSS**.
WAV non ha un atomo di capitolo, quindi il rendering WAV lo indica esplicitamente invece di segnalare un errore nel muxing del capitolo; utilizzalo quando l'audio deve essere elaborato in un editor.
- **Mastering conforme alle specifiche ACX** (`--acx`) + un controllo **`master-check`** che segnala PASS/FAIL per la rumorosità RMS, il picco e il livello di rumore di fondo; clip di **test** per la vendita al dettaglio **`sample`**.
- Rendering parallelo, una **cache di rendering persistente** con ripresa, progressione dinamica + tempo stimato di completamento e report di errore strutturati.

### Flusso di lavoro ed ecosistema
- **Pipeline `make`** a esecuzione singola · **file di configurazione** (`.audiobookerrc` / `[tool.audiobooker]`) · **modalità `--watch`** · **batch guidato dal manifesto** · completamento della shell.
- **7 profili linguistici** (en/fr/de/es/ja/it/pt) · **motori TTS plug-in** (`--engine`, punti di ingresso: fornisci Piper/Coqui/ElevenLabs) · script `--json` sulla maggior parte dei comandi · codici di uscita strutturati.

## Mastering conforme alle specifiche audio di ACX

ACX pubblica un obiettivo audio preciso e misurabile. È la cosa più simile a uno standard di mastering che il mondo degli audiolibri abbia, e vale la pena raggiungerlo, qualunque cosa tu faccia con il file in seguito.

| Requisito | Specifiche ACX | Cosa fa `--acx` |
|---|---|---|
| Rumorosità | RMS tra **−23 e −18 dBFS** | passaggio `loudnorm` a due fasi a −20 LUFS, che rientra in tale intervallo per la voce |
| Picco | uguale o inferiore a **−3 dBFS** | applicato nello stesso passaggio |
| Livello di rumore di fondo | uguale o inferiore a **−60 dBFS** | misurato e segnalato; non viene mai "corretto" silenziosamente |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | imposta la frequenza di campionamento; aggiungi `--format mp3 --bitrate 192k` per il codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Ecco due aspetti importanti sui numeri sopra:

**`master-check` misura l'RMS non ponderata, non i LUFS.** Sono quantità diverse e ACX si basa su quest'ultima. Il valore di −20 LUFS è il modo in cui il passaggio di mastering *ottiene* tale valore; è ciò che `ffmpeg loudnorm` può raggiungere, e non ciò che viene controllato in seguito.

**Il livello di rumore di fondo viene misurato, non corretto.** È il requisito che più spesso non viene soddisfatto e deriva dall'audio di origine. Uno strumento che lo corregge silenziosamente nasconderebbe il numero di cui hai bisogno.

### Dove un audiolibro narrato dall'IA può effettivamente arrivare

Rispettare le specifiche non è la stessa cosa di essere accettati, ed è importante essere chiari: **il flusso di invio standard di ACX è per la narrazione umana.** I suoi requisiti dell'aprile 2026 elencano la sintesi vocale non autorizzata e le registrazioni AI tra le cose che non accetta, quindi un titolo narrato dall'IA richiede un'autorizzazione preventiva da parte di ACX anziché un invio ordinario.

Le piattaforme che accettano la narrazione tramite intelligenza artificiale, generalmente con l'indicazione di tale utilizzo, includono:
**Virtual Voice** di Amazon, tramite KDP (distribuzione esclusiva Amazon) e aggregatori come **Spotify Audiobooks for Authors**, **Author's Republic** e **Kobo Writing Life**. Le politiche dei rivenditori in questo ambito cambiano rapidamente, quindi è consigliabile verificare i termini attuali invece di affidarsi a questo paragrafo.

Quindi: `--acx` riguarda l'audio. Il fatto che un rivenditore accetti un titolo narrato tramite intelligenza artificiale è una sua decisione, e non una caratteristica del file che hai appena prodotto.

## Comandi CLI

| Comando | Descrizione |
|---------|-------------|
| `make <file>` | Esecuzione singola: nuovo → compilazione → assegnazione automatica → rendering |
| `new <file\ | folder>` | Crea un progetto da EPUB/TXT/MD/PDF/DOCX o da una cartella |
| `from-stdin` | Crea un progetto da testo fornito in input |
| `cast <char> <voice>` · `cast-interactive` | Assegna voci (o guida l'assegnazione per ogni personaggio; anche `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggerisci / applica automaticamente / assegna in blocco le voci |
| `cast-preset save\ | list\ | apply\ | delete` | Preset di assegnazione riutilizzabili tra i libri |
| `cast-export` · `cast-import <file>` | Trasferisci l'assegnazione in formato JSON/CSV: modifica manualmente o riutilizza tra le edizioni |
| `audition <char>` | Voci candidate classificate per un personaggio (`--render`) |
| `compile` | Rileva i dialoghi, attribuisci i personaggi, inferisci le emozioni |
| `report` | Qualità della compilazione: frequenza sconosciuta, righe non attribuite, mix di emozioni |
| `review-export` · `review-import <file>` | Revisione modificabile manualmente con trasferimento bidirezionale |
| `render` | Esegui il rendering dell'audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Esempio di vendita definitivo: verifica rispetto alle specifiche audio di ACX |
| `export-chapters` · `podcast` | Foglio di riferimento dei capitoli (ffmetadata/cue/json): feed RSS per podcast |
| `preview` · `batch` · `diagnose` | Clip di controllo della voce: batch/`--manifest`: verifica dell'ambiente (il processo termina con un codice di errore diverso da zero se non è possibile eseguire il rendering) |
| `load <file>` | Apri un progetto `.audiobooker` esistente |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Ispeziona e gestisci |

Ogni comando supporta `-h/--help`. Flag globali: `--silent`, `--debug`. **Codici di uscita:** `0` ok · `1` errore utente (incluso un libro che non può essere compilato o un rendering rifiutato perché l'attribuzione non è riuscita) · `2` errore di runtime · `3` parziale (batch).

## Configurazione

Imposta i valori predefiniti una sola volta invece di passare ripetutamente i flag: `.audiobookerrc` (TOML) accanto al tuo libro, o `[tool.audiobooker]` in `pyproject.toml`. La precedenza è: **flag CLI > configurazione del progetto > configurazione utente (`~/.audiobookerrc`) > valori predefiniti integrati**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motori TTS plug-in

Il motore predefinito è `voice-soundboard`, ma il backend di sintesi può essere modificato tramite i punti di ingresso di setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un plug-in (`pip install audiobooker-piper`) si registra automaticamente; non è necessario creare una copia.

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
- **Autorizzazioni:** accesso in lettura agli input, accesso in scrittura agli output; FFmpeg opzionale e un motore TTS nel PATH.
- Consulta [SECURITY.md](SECURITY.md).

## Valutazione

| Porta | Stato |
|------|--------|
| A. Baseline di sicurezza | PASS |
| B. Gestione degli errori | PASS |
| C. Documentazione per l'operatore | PASS |
| D. Igiene della distribuzione | PASS |
| E. Identità | PASS |

## Licenza

[MIT](LICENSE)

---

Creato da <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
