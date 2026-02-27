<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

## Caratteristiche

- **Sintesi vocale multi-voce**: Assegnare voci uniche a ciascun personaggio.
- **Rilevamento del dialogo**: Identifica automaticamente i dialoghi citati rispetto alla narrazione.
- **Inferenza delle emozioni**: Etichettatura delle emozioni basata su regole e lessico, con livello di confidenza configurabile.
- **Suggerimenti vocali**: Raccomandazioni vocali spiegate e ordinate per ogni personaggio.
- **Integrazione con BookNLP**: Risoluzione facoltativa dei riferimenti ai personaggi tramite NLP.
- **Anteprima e modifica**: Formato di anteprima modificabile per correggere gli attributi.
- **Cache di rendering persistente**: Riprendere i rendering interrotti senza dover risintetizzare i capitoli già completati.
- **Progresso e ETA dinamici**: Stato di rendering in tempo reale con tempo di completamento stimato.
- **Report di errore**: Diagnostica strutturata in formato JSON per gli errori di rendering.
- **Profili linguistici**: Astrazione delle regole specifiche per la lingua, estendibile.
- **Output M4B**: Formato professionale per audiolibri con navigazione dei capitoli.
- **Persistenza del progetto**: Salvare e riprendere le sessioni di rendering.

## Installazione

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

## Funzionalità opzionali

| Funzionalità | Installa | Configurazione |
|---------|---------|--------|
| **TTS rendering** | `pip install audiobooker-ai[render]` oppure installa voice-soundboard | Richiesto per `render` |
| **Risoluzione dei personaggi con BookNLP** | `pip install audiobooker-ai[nlp]` | `--booknlp on\ | off\ | auto` |
| **FFmpeg audio assembly** | Pacchetto di sistema (winget/brew/apt) | Richiesto per l'output M4B |

## Guida rapida

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

## Flusso di lavoro di revisione

Il flusso di lavoro di revisione consente di esaminare e correggere lo script compilato prima del rendering:

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
- `@Speaker` oppure `@Speaker (emozione)` - Tag del personaggio
- `# commento` - Commenti (ignorati durante l'importazione)
- Eliminare i blocchi per rimuovere le frasi indesiderate
- Modificare `@Unknown` in `@ActualName` per correggere gli attributi

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
| `audiobooker new <file>` | Crea progetto da EPUB/TXT |
| `audiobooker cast <char> <voice>` | Assegna una voce a un personaggio |
| `audiobooker cast-suggest` | Suggerisci voci per personaggi senza voce assegnata |
| `audiobooker cast-apply --auto` | Applica automaticamente i migliori suggerimenti vocali |
| `audiobooker compile` | Compila i capitoli in frasi |
| `audiobooker review-export` | Esporta lo script per la revisione umana |
| `audiobooker review-import <file>` | Importa il file di revisione modificato |
| `audiobooker render` | Esegui il rendering dell'audiolibro |
| `audiobooker info` | Mostra le informazioni del progetto |
| `audiobooker voices` | Elenca le voci disponibili |
| `audiobooker chapters` | Elenca i capitoli |
| `audiobooker speakers` | Elenca i personaggi rilevati |
| `audiobooker from-stdin` | Crea progetto da testo in input |

## Architettura

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

**Flusso:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Risoluzione dei problemi

**Report di errore di rendering**: In caso di errore di rendering, Audiobooker scrive `render_failure_report.json` nella directory della cache. Questo contiene:
- Indice e titolo del capitolo in cui si è verificato l'errore
- Indice della frase, personaggio e anteprima del testo
- ID della voce e dell'emozione che stavano venendo sintetizzate
- Stack trace completo
- Percorsi della cache e del manifest

**Problemi comuni con FFmpeg**:
- `FFmpeg non trovato`: Installare tramite il gestore di pacchetti (winget/brew/apt)
- `Errore nell'incorporamento del capitolo`: Audiobooker utilizza M4A senza marcatori di capitolo
- Qualità audio: Il valore predefinito è AAC a 128 kbps a 24 kHz (configurabile in ProjectConfig)

**Problemi con la cache**:
- `audiobooker render --clean-cache` — Pulisce tutta la cache audio e ri-esegue il rendering
- `audiobooker render --no-resume` — Ignora la cache per questa esecuzione
- `audiobooker render --from-chapter 5` — Inizia dal capitolo 5

## Roadmap

- [x] v0.1.0 - Pipeline principale (analisi, assegnazione, compilazione, rendering)
- [x] v0.2.0 - Flusso di lavoro di revisione prima del rendering
- [x] v0.3.0 - Cache di rendering persistente + ripresa
- [x] v0.4.0 - Profili linguistici + maggiore flessibilità nell'input
- [x] v0.5.0 - BookNLP, inferenza delle emozioni, suggerimenti vocali, miglioramenti dell'interfaccia utente

## Sicurezza e ambito dei dati

- **Dati a cui si accede:** Legge i file EPUB/TXT dal file system locale. Scrive i file audio e i manifest dei file temporanei nelle directory di output. Facoltativamente, utilizza una tastiera vocale per la sintesi vocale e FFmpeg per l'assemblaggio audio.
- **Dati a cui NON si accede:** Nessuna richiesta di rete. Nessuna telemetria. Nessun salvataggio di dati utente. Nessuna credenziale o token.
- **Autorizzazioni richieste:** Accesso in lettura ai file del libro di input. Accesso in scrittura alle directory di output. Facoltativo: FFmpeg presente nel percorso di sistema.

## Tabella di valutazione

| Verifica | Stato |
|------|--------|
| A. Linee guida di sicurezza | PASS (Superato) |
| B. Gestione degli errori | PASS (Superato) |
| C. Documentazione per gli operatori | PASS (Superato) |
| D. Pratiche di sviluppo | PASS (Superato) |
| E. Identità | PASS (Superato) |

## Licenza

[MIT](LICENSE)

---

Creato da <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a
