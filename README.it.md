<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Audiobooker rileva i dialoghi, assegna una voce distinta a ciascun personaggio, deduce le emozioni, consente di rivedere e correggere tutto prima che venga elaborato anche solo un secondo di audio, quindi ottimizza il risultato in base alle specifiche audio di ACX, in modo che l'output sia un audiolibro *completo*, e non solo un audio generato.

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

- Tagged `latest`, `3`, `3.0` e la versione esatta, pubblicati su GHCR ad ogni rilascio.
- Il punto di ingresso **è** `audiobooker`, quindi passa il sottocomando immediatamente dopo il nome dell'immagine; non ripetere il nome del programma.
- La cache viene salvata in `<book-dir>/.audiobooker/cache`. Ecco perché un singolo punto di mount garantisce la persistenza; perderlo significa dover pagare di nuovo per l'intera esecuzione TTS, e non solo per il re-muxing.
- `/ext` è un secondo punto di mount opzionale, utilizzato solo per fornire il proprio motore TTS.
- Il container viene eseguito come UID non root 1000. Su Linux, se la directory montata non è scrivibile da tale UID, la cache non può essere scritta; aggiungi `--user "$(id -u):$(id -g)"` o `chown` alla directory. Docker Desktop su macOS e Windows gestisce questo aspetto automaticamente.

</details>

**Il rendering dell'audio** richiede il motore TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l'extra `[render]`) e **FFmpeg** nel PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tutto ciò che precede il rendering (analisi, assegnazione delle voci, compilazione, revisione) funziona senza di essi. Esegui `audiobooker diagnose` per verificare la configurazione.

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

Ognuno di questi è un caso in cui la versione 2.x accettava qualcosa e agiva in modo errato in silenzio. La versione 3.0 rifiuta invece. Dettagli completi nel [CHANGELOG](CHANGELOG.md).

- **La prima esecuzione di rendering esegue nuovamente il rendering di ogni capitolo, una sola volta.** Tre input che modificano l'audio (preset delle emozioni, intensità dell'enunciato, velocità/tono/enfasi per personaggio) mancavano dalla chiave della cache, quindi il cambio di preset segnalava "Memorizzato nella cache" e restituiva l'audio precedente. Ora sono inclusi nella chiave e una voce della cache 2.x non può dimostrare cosa l'ha prodotta.
- **`--format m4a` non è più un'opzione per l'intero libro.** Significava sempre un file per capitolo; richiedere un intero libro in `m4a` in precedenza produceva un singolo M4B con un nome `.m4a`. È ancora valido su `podcast --format`.
- **`render` rifiuta un libro in cui l'attribuzione indica `FAILED`** invece di eseguire un'elaborazione TTS. `--force` sovrascrive. Esegui `audiobooker report` per vedere a quali righe si oppone.
- **`make` rifiuta quando il file del progetto esiste già.** In precedenza sovrascriveva le voci assegnate manualmente, le modifiche alla pronuncia e i titoli modificati con una nuova analisi automatica. Passa `--overwrite-project` se è quello che vuoi.
- **`compile()` genera un errore quando ogni capitolo fallisce** invece di restituire `None` come farebbe un'esecuzione corretta. Se lo chiami da Python, ora può generare un'eccezione.

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
audiobooker speakers                   # who did compile find?
audiobooker speakers --suggest-aliases # Dr. Merrin / Merrin / The Doctor?
audiobooker speakers merge "Dr. Merrin" Merrin   # fold those slots into one voice
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## Funzionalità

### Input e struttura
- **EPUB, TXT, Markdown, PDF, DOCX** o una **cartella di file per capitolo** (Scrivener/Obsidian/romanzi a puntate).
- **Suddivisione EPUB basata sul TOC** (indice): i confini dei capitoli e i titoli vengono estratti dall'indice del libro.
- **DOCX** suddivide in base agli stili Word `Heading 1/2`/`Title`; **PDF** rileva le intestazioni (con una protezione per i PDF scansionati); personalizzazione `--chapter-delimiter`.
- Pulizia intelligente del testo, rimozione con consapevolezza del Markdown, gestione delle note a piè di pagina e un **lessico di pronuncia riutilizzabile** (`pronunciation import/export`, CSV/JSON, con passaggio dei fonemi).

### Assegnazione delle voci e attribuzione
- **Sintesi vocale con più voci**, con **suggerimenti** vocali classificati e spiegabili e un comando **`audition`** per confrontare le diverse opzioni per ogni personaggio.
- **Assegnazione interattiva delle voci**, **assegnazione massiva `cast-fill`** in base al genere/ruolo, **profili di voci predefiniti** riutilizzabili in una serie e **fogli di calcolo CSV** per i collaboratori.
- **Rilevamento dei dialoghi + attribuzione del parlante** (opzionale **BookNLP** co-riferimento), **individuazione automatica degli alias** e **inferenza delle emozioni** con **intensità** regolabile, **atmosfera a livello di scena** e pacchetti di **impostazioni predefinite** per genere.
- **Attribuzione verificabile.** Ogni riga registra *come* è stato deciso il parlante: un tag vocale, una modifica diretta, un co-riferimento, la tua correzione o una semplice ipotesi a turno alternato. `report` conta le ipotesi separatamente dalle righe a cui non è stato possibile attribuire un parlante. Un'ipotesi non può migliorare il punteggio, quindi il numero diminuisce quando l'attribuzione peggiora, ed è l'unica direzione utile.

### Rendering e output
- **M4B** (marcatori di capitolo + copertina incorporata + metadati della serie), **MP3**, **Opus**, **FLAC**, **WAV**; esportazione per capitolo; esportazione del feed **podcast/RSS**.
Il formato WAV non prevede un atomo di capitolo, quindi, in caso di rendering WAV, viene indicato esplicitamente che non è stato possibile creare i capitoli, anziché segnalare un errore nel processo di multiplexing. È consigliabile utilizzare questo formato quando l'audio deve essere elaborato in un editor.
- **Mastering conforme alle specifiche ACX** (`--acx`) + uno strumento **`master-check`** che indica se il livello di volume RMS, il picco e il rumore di fondo sono accettabili o meno; creazione di clip per la **distribuzione al dettaglio** **`sample`**.
- Rendering parallelo, una **cache di rendering persistente** con ripresa, avanzamento dinamico + tempo stimato di completamento e report di errore strutturati.
La chiave della cache copre tutti gli elementi che modificano l'audio: testo, interpreti, voci, motore e versione, profilo, preimpostazione e intensità delle emozioni, in modo che un nuovo rendering contrassegnato come "Memorizzato nella cache" significhi proprio questo. Una **cache opzionale per ogni frase** (`utterance_cache`) limita il nuovo rendering alle frasi che sono state effettivamente modificate.

### Flusso di lavoro ed ecosistema
- **Pipeline `make`** a esecuzione singola · **file di configurazione** (`.audiobookerrc` / `[tool.audiobooker]`) · **modalità `--watch`** · **elaborazione batch basata su manifest** · completamento della shell.
- **7 profili linguistici** (en/fr/de/es/ja/it/pt) · **motori TTS plug-in** (`--engine`, punti di ingresso: fornisci Piper/Coqui/ElevenLabs) · script `--json` sulla maggior parte dei comandi · codici di uscita strutturati.

## Mastering conforme alle specifiche audio di ACX

ACX pubblica un obiettivo audio preciso e misurabile. È la cosa più simile a uno standard di mastering che il mondo degli audiolibri abbia, e vale la pena raggiungerlo, qualunque cosa tu faccia con il file in seguito.

| Requisito | Specifiche ACX | Cosa fa `--acx` |
|---|---|---|
| Livello di volume | RMS tra **−23 e −18 dBFS** | elaborazione in due passaggi `loudnorm` a −20 LUFS, che rientra in tale intervallo per il parlato |
| Picco | a o inferiore a **−3 dBFS** | applicato nello stesso passaggio |
| Livello di rumore di fondo | a o inferiore a **−60 dBFS** | misurato e segnalato, non "corretto" silenziosamente |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | imposta la frequenza di campionamento; aggiungere `--format mp3 --bitrate 192k` per il codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Ecco due aspetti importanti relativi ai valori sopra indicati:

**`master-check` misura l'RMS non ponderato, non i LUFS.** Si tratta di quantità diverse e ACX applica i controlli sulla prima. Il valore di −20 LUFS indica come il passaggio di mastering *ottiene* tale risultato; è il valore che `ffmpeg loudnorm` può raggiungere, non quello che viene controllato in seguito.

**Il livello di rumore di fondo viene misurato, non corretto.** È il requisito che più spesso non viene soddisfatto e deriva dall'audio di origine. Uno strumento che lo attenuasse silenziosamente nasconderebbe il valore che è necessario visualizzare.

### Dove un audiolibro narrato da un'intelligenza artificiale può effettivamente arrivare

Rispettare le specifiche non è la stessa cosa di essere accettati, ed è importante essere chiari su questo: **il flusso di invio standard di ACX è per la narrazione umana.** Nell'elenco dei requisiti di aprile 2026, sono inclusi tra le cose che non accetta la sintesi vocale non autorizzata e le registrazioni AI, quindi un titolo narrato da un'IA richiede un'autorizzazione preventiva da parte di ACX anziché un invio ordinario.

I canali che accettano la narrazione AI, generalmente con una dichiarazione, includono **Virtual Voice** di Amazon tramite KDP (distribuzione solo su Amazon) e aggregatori come **Spotify Audiobooks for Authors**, **Author's Republic** e **Kobo Writing Life**. Le politiche dei rivenditori in questo settore cambiano rapidamente: controlla i termini correnti invece di affidarti a questo paragrafo.

Quindi: `--acx` riguarda l'audio. Se un rivenditore accetta un titolo narrato da un'IA è una sua decisione, non una proprietà del file che hai appena prodotto.

## Comandi CLI

| Comando | Descrizione |
|---------|-------------|
| `make <file>` | Elaborazione in un unico passaggio: nuovo → compilazione → assegnazione automatica → rendering |
| `new <file\|folder>` | Crea un progetto da EPUB/TXT/MD/PDF/DOCX o da una cartella |
| `from-stdin` | Crea un progetto da testo in input |
| `cast <char> <voice>` · `cast-interactive` | Assegna le voci (o l'assegnazione guidata per ogni personaggio; anche `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggerisci / applica automaticamente / assegna in blocco le voci |
| `cast-preset save\|list\|apply\|delete` | Preset di assegnazione riutilizzabili tra i libri |
| `cast-export` · `cast-import <file>` | Trasferisci l'assegnazione in formato JSON/CSV: modifica manualmente o riutilizza tra le edizioni |
| `audition <char>` | Voci candidate classificate A/B per un personaggio (`--render`) |
| `compile` | Rileva i dialoghi, attribuisci i personaggi, inferisci le emozioni |
| `report` | Qualità della compilazione: tasso di attribuzione, tasso stimato, righe peggiori, mix di emozioni |
| `review-export` · `review-import <file>` | Revisione modificabile manualmente con trasferimento completo |
| `render` | Esegui il rendering dell'audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Esempio di vendita masterizzato: verifica rispetto alle specifiche audio di ACX |
| `export-chapters` · `podcast` | Foglio di riferimento dei capitoli (ffmetadata/cue/json): feed RSS per podcast |
| `preview` · `batch` · `diagnose` | Clip di controllo della voce: batch/`--manifest`: verifica dell'ambiente (il processo termina con un codice di errore diverso da zero se il sistema non riesce a eseguire il rendering) |
| `load <file>` | Apri un progetto `.audiobooker` esistente |
| `voices` · `chapters` · `speakers` · `speakers merge` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Ispeziona e gestisci (`speakers merge <from> <to>` unisce i nomi duplicati in una singola posizione di assegnazione) |

Ogni comando supporta `-h/--help`. Flag globali: `--silent`, `--debug`. **Codici di uscita:** `0` ok · `1` errore utente (incluso un libro che non può essere compilato o un rendering rifiutato perché l'attribuzione non è riuscita) · `2` errore di runtime · `3` parziale (batch).

## Configurazione

Imposta i valori predefiniti una sola volta invece di passare ripetutamente i flag: `.audiobookerrc` accanto al tuo libro o `[tool.audiobooker]` in `pyproject.toml`. La precedenza è **flag CLI > configurazione del progetto > configurazione utente (`~/.audiobookerrc`) > valori predefiniti integrati**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motori TTS plug-in

Il motore predefinito è `voice-soundboard`, ma il backend di sintesi può essere sostituito tramite i punti di ingresso di setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un plug-in (`pip install audiobooker-piper`) si registra; non è necessario creare una copia.

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
- **Autorizzazioni:** accesso in lettura agli input, accesso in scrittura agli output; facoltativo FFmpeg e un motore TTS nel PATH.
- Consulta [SECURITY.md](SECURITY.md).

## Valutazione

| Controllo | Stato |
|------|--------|
| A. Baseline di sicurezza | PASSATO |
| B. Gestione degli errori | PASSATO |
| C. Documentazione per l'operatore | PASSATO |
| D. Igiene di rilascio | PASSATO |
| E. Identità | PASSATO |

## Licenza

[MIT](LICENSE)

---

Creato da <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
