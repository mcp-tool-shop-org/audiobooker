<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
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

## Caratteristiche

### Input e Analisi
- Analisi di sorgenti **EPUB / TXT / Markdown** con rilevamento dei capitoli
- Supporto **PDF** (opzionale): Estrazione del testo dai file PDF tramite PyMuPDF (`pip install -e '.[pdf]'`)
- **Normalizzazione del testo**: Pulizia degli apici, normalizzazione degli spazi, strumenti di pulizia del testo configurabili
- **Sovrascritture della pronuncia**: Mappature personalizzate da parole a pronunce per nomi propri e termini tecnici
- **Gestione delle note a piè di pagina**: Comportamento delle note a piè di pagina configurabile (`inline`, `end` o `skip`)

### Dialoghi e Attribuzioni
- **Rilevamento dei dialoghi**: Identifica automaticamente i dialoghi citati rispetto alla narrazione
- **Rilevamento avanzato dei dialoghi**: Tracciamento dei turni di conversazione per scene con più personaggi
- **Indicazioni di scena**: Rileva e gestisce le indicazioni di scena racchiuse tra parentesi negli script
- **Integrazione con BookNLP**: Risoluzione facoltativa dei riferimenti ai personaggi basata sull'elaborazione del linguaggio naturale (NLP)
- **Alias dei personaggi**: Associa nomi alternativi a un personaggio principale

### Voce e Doppiaggio
- **Sintesi vocale multi-voce**: Assegna voci uniche a ciascun personaggio
- **Suggerimenti vocali**: Raccomandazioni vocali spiegate e ordinate per ogni personaggio
- **Inferenza delle emozioni**: Etichettatura delle emozioni basata su regole e lessico, con livello di confidenza configurabile
- **Parametri vocali per personaggio**: Velocità (0.5--2.0) ed emozione per ogni personaggio
- **Pre-elaborazione SSML**: Supporto per il linguaggio di markup per la sintesi vocale (SSML) per un controllo più preciso

### Rendering e Output
- **Rendering parallelo**: Rendering dei capitoli con più processi in parallelo con `--jobs N`
- **Formati di output multipli**: MP3, M4B, WAV, OGG, FLAC
- **Normalizzazione dell'audio**: Livelli di volume coerenti tra i capitoli
- **Incorporamento della copertina**: Estratta dal file EPUB o fornita dall'utente, incorporata nell'output M4B
- **Cache di rendering persistente**: Riprende i rendering interrotti senza dover risintetizzare i capitoli completati
- **Stato di avanzamento e ETA dinamici**: Stato di rendering in tempo reale con tempo di completamento stimato
- **Report di errore**: Diagnostica strutturata in formato JSON in caso di errori di rendering

### Lingua e Localizzazione
- **5 profili linguistici**: Inglese, francese, tedesco, spagnolo, giapponese (`--lang en|fr|de|es|ja`)
- **Sistema di profili estendibile**: Aggiungi nuove lingue tramite l'astrazione `LanguageProfile`

### Flusso di Lavoro e Produttività
- **Anteprima prima del rendering**: Formato di anteprima modificabile per correggere le attribuzioni
- **Confronto di progetti**: Confronta due versioni di un progetto per vedere le modifiche ai capitoli e alle battute
- **Elaborazione batch**: Elabora più libri in un'unica esecuzione con `audiobooker batch`
- **Modalità di prova**: Anteprima del rendering o delle operazioni batch senza eseguirle (`--dry-run`)
- **Anteprima della voce**: Esegue un breve campione per validare le assegnazioni vocali (`audiobooker preview`)
- **Gestione dei capitoli**: Unisci, dividi ed escludi i capitoli prima del rendering
- **Gestione delle emozioni**: Elenca e sovrascrivi le emozioni per ogni battuta dopo la compilazione
- **Notifiche desktop**: Ricevi notifiche quando i rendering lunghi sono completati
- **Persistenza del progetto**: Salva/riprendi le sessioni di rendering

## Installazione

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

## Funzionalità Opzionali

| Funzionalità | Installazione | Configurazione |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` oppure installa voice-soundboard | Richiesto per `render` |
| **Risoluzione dei personaggi di BookNLP** | `pip install -e '.[nlp]'` | `--booknlp on\ | off\ | auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | Rilevato automaticamente durante l'esecuzione |
| **FFmpeg audio assembly** | Pacchetto di sistema (winget/brew/apt) | Richiesto per l'output M4B |

## Guida Rapida

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

## Flusso di Lavoro di Revisione

Il flusso di lavoro di revisione ti consente di esaminare e correggere lo script compilato prima del rendering:

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

**Formato del file di revisione:**
- `=== Titolo del capitolo ===` - Marcatori di capitolo
- `@Speaker` o `@Speaker (emozione)` - Tag del relatore
- `# commento` - Commenti (ignorati durante l'importazione)
- Eliminare i blocchi per rimuovere le frasi indesiderate
- Modificare `@Unknown` in `@ActualName` per correggere l'attribuzione

## API Python

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

## Comandi CLI

| Comando | Descrizione |
|---------|-------------|
| `audiobooker new <file>` | Crea un progetto da EPUB/TXT/MD/PDF |
| `audiobooker load <project>` | Carica un progetto `.audiobooker` esistente |
| `audiobooker from-stdin` | Crea un progetto da testo in input |
| `audiobooker cast <char> <voice>` | Assegna una voce a un personaggio |
| `audiobooker cast-suggest` | Suggerisci voci per relatori non ancora assegnati |
| `audiobooker cast-apply --auto` | Applica automaticamente le migliori suggerimenti di voce |
| `audiobooker compile` | Compila i capitoli in frasi |
| `audiobooker review-export` | Esporta lo script per la revisione umana |
| `audiobooker review-import <file>` | Importa il file di revisione modificato |
| `audiobooker render` | Genera l'audiolibro (supporta `--dry-run`, `--jobs N`, `--format`, `--cover`) |
| `audiobooker preview` | Genera un breve campione per la validazione della voce (`--chapter N`, `--seconds S`) |
| `audiobooker batch <files...>` | Elabora in batch più libri (supporta `--dry-run`) |
| `audiobooker info` | Mostra le informazioni del progetto |
| `audiobooker status` | Mostra lo stato della generazione/cache |
| `audiobooker voices` | Elenca le voci disponibili (supporta `--gender`, `--search`) |
| `audiobooker chapters` | Elenca i titoli e gli indici dei capitoli |
| `audiobooker speakers` | Elenca i relatori rilevati |
| `audiobooker cache info` | `clean` | `clean-failed` | Gestisci la cache di generazione |
| `audiobooker diagnose` | Verifica l'ambiente (dipendenze, motore vocale, FFmpeg) |

## Riferimento completo della CLI

Ogni comando supporta `-h` / `--help` per un utilizzo dettagliato. Flag principali:

- **`new`**: `-o <project>`, `--lang <code>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <emozione>`, `--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`, `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`, `--jobs N`, `-o <path>`, `--format mp3|m4b|wav|ogg|flac`, `--cover <immagine>`
- **`preview`**: `--chapter N`, `--seconds S`, `-o <path>`
- **`batch`**: `--dry-run`, `--jobs N`, `--format <fmt>`, `--lang <code>`, `--output-dir <dir>`
- **`voices`**: `--gender <maschio|femmina>`, `--search <query>`
- **`info`**: `--verbose`

## Architettura

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

**Flusso:**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Problemi comuni

| Problema | Soluzione |
|---------|-----|
| **FFmpeg not found** | Installa tramite il tuo gestore di pacchetti: `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `apt install ffmpeg` (Linux). FFmpeg deve essere nel PATH. |
| **voice-soundboard non installato** | Clona e installa il repository correlato: `git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`. Oppure installa con `pip install -e '.[render]'`. |
| **Errori di BookNLP o avvio lento** | BookNLP è opzionale. Se non hai bisogno della risoluzione dei relatori tramite NLP, imposta `--booknlp off` o lascialo su `auto` (fallback). Installa con `pip install -e '.[nlp]'` solo se necessario. |

Consulta il [manuale](docs/handbook.md#15-troubleshooting) per una guida completa alla risoluzione dei problemi.

## Risoluzione dei problemi

**Report di errore di generazione**: In caso di errore di generazione, Audiobooker scrive `render_failure_report.json` nella directory della cache. Questo contiene:
- Indice e titolo del capitolo in cui si è verificato l'errore
- Indice della frase, relatore e anteprima del testo
- ID della voce e dell'emozione che stavano per essere sintetizzate
- Stack trace completo
- Percorsi della cache e del manifest

**Problemi comuni di FFmpeg**:
- `FFmpeg non trovato`: Installa tramite il tuo gestore di pacchetti (winget/brew/apt)
- `Impossibile incorporare il capitolo`: Audiobooker esegue il fallback su M4A senza marcatori di capitolo
- Qualità audio: Il valore predefinito è AAC a 128 kbps a 24 kHz (configurabile in ProjectConfig)

**Problemi di cache:**
- `audiobooker render --clean-cache` — svuota la cache audio e rigenera i file.
- `audiobooker render --no-resume` — ignora la cache per questa esecuzione.
- `audiobooker render --from-chapter 5` — inizia da un capitolo specifico.

## Roadmap (Piano di sviluppo)

- [x] Pipeline principale (analisi, conversione, compilazione, rendering)
- [x] Flusso di lavoro di anteprima prima del rendering
- [x] Cache di rendering persistente + ripresa
- [x] Profili di lingua + flessibilità di input
- [x] BookNLP, inferenza emotiva, suggerimenti vocali, miglioramenti dell'interfaccia utente
- [x] v1.0.0 - Rilascio in produzione

## Sicurezza e ambito dei dati

- **Dati accessibili:** Legge file EPUB/TXT dal file system locale. Scrive file audio e manifest dei file della cache nelle directory di output. Facoltativamente, utilizza una libreria di suoni vocali per la sintesi vocale e FFmpeg per l'assemblaggio audio.
- **Dati NON accessibili:** Nessuna richiesta di rete. Nessuna telemetria. Nessun archivio di dati utente. Nessuna credenziale o token.
- **Permessi richiesti:** Accesso in lettura ai file del libro di input. Accesso in scrittura alle directory di output. Facoltativo: FFmpeg presente nel percorso di sistema.

## Scorecard (Tabella di valutazione)

| Gate (Fase di controllo) | Status (Stato) |
|------|--------|
| A. Security Baseline (Base di sicurezza) | PASS (Superato) |
| B. Error Handling (Gestione degli errori) | PASS (Superato) |
| C. Operator Docs (Documentazione per gli operatori) | PASS (Superato) |
| D. Shipping Hygiene (Standard di qualità) | PASS (Superato) |
| E. Identity (Identità) | PASS (Superato) |

## License (Licenza)

[MIT](LICENSE)

---

Creato da <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
