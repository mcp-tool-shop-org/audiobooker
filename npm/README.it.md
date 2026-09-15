<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="420" />
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm version"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI version"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks (<strong>M4B / MP3 / Opus / FLAC</strong>) — from one command.
</p>

Questa è la **`npx` wrapper** per [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). Alla prima esecuzione, crea un ambiente Python privato, installa la versione specifica da PyPI ed esegue la vera CLI: niente configurazioni manuali `pip`, nessuna modifica al tuo Python di sistema.

## Provalo

```bash
npx @mcptoolshop/audiobooker --help
```

Oppure installalo a livello globale:

```bash
npm install -g @mcptoolshop/audiobooker
```

Alla prima esecuzione, viene configurato un ambiente virtuale gestito nella directory dei dati dell'utente (`~/.local/share/audiobooker` o `%LOCALAPPDATA%\audiobooker` su Windows) e viene installato `audiobooker-ai`. Tutte le esecuzioni successive si avviano istantaneamente.

**Richiede Python 3.10+** nel PATH (la wrapper individua `python3` / `py`). Se non è presente, la wrapper ti indica esattamente come installarlo per il tuo sistema operativo.

## Guida rapida

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## Elaborazione audio (sintesi vocale)

L'analisi, la selezione, la compilazione e il flusso di lavoro di revisione funzionano immediatamente. **L'elaborazione audio** richiede il motore TTS, che comporta l'installazione di dipendenze più pesanti: abilita questa funzione quando sei pronto:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

L'elaborazione richiede anche **FFmpeg** nel PATH per l'assemblaggio in formato M4B/MP3 (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Esegui `audiobooker diagnose` per verificare la configurazione.

## Cosa fa

- **Selezione di voci multiple** con suggerimenti di voci classificati e spiegabili; `audiobooker audition <character>` ti consente di confrontare le voci candidate prima di scegliere.
- **Rilevamento dei dialoghi + attribuzione del parlante** (opzionale co-riferimento BookNLP), inferenza delle emozioni e lessici di pronuncia riutilizzabili.
- **Revisione prima dell'elaborazione**: esporta uno script modificabile manualmente, correggi le attribuzioni, reimporta: nulla viene modificato in silenzio.
- **Mastering conforme alle specifiche ACX**: `render --acx` esegue il mastering per raggiungere i parametri audio di ACX: RMS tra −23 e −18 dBFS, picco a o inferiore a −3, livello di rumore a o inferiore a −60; `master-check` segnala PASS/FAIL rispetto a questi tre limiti misurati.
Tieni presente che il rispetto delle specifiche non è la stessa cosa dell'essere accettati: il flusso di invio standard di ACX è per la narrazione umana. Consulta il [README principale](https://github.com/mcp-tool-shop-org/audiobooker#where-an-ai-narrated-audiobook-can-actually-go) per le opzioni che accettano titoli narrati dall'IA.
- **Formati**: M4B (marcatori di capitolo + copertina incorporata + metadati della serie), MP3, Opus, FLAC; esportazione per capitolo; clip di esempio per la vendita al dettaglio.
- **7 profili linguistici** (en/fr/de/es/ja/it/pt) e un file di configurazione per libro per impostare valori predefiniti che non richiedono ulteriori modifiche.

## Variabili d'ambiente

| Variabile | Effetto |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Crea l'ambiente virtuale gestito **con** il motore vocale (per l'elaborazione) |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | Ricostruisci l'ambiente gestito da zero |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | Sovrascrivi la posizione dell'ambiente virtuale gestito |

## Preferisci pip?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## Link

- **Documentazione e manuale:** <https://mcp-tool-shop-org.github.io/audiobooker/>
- **Codice sorgente:** <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI:** <https://pypi.org/project/audiobooker-ai/>

## Licenza

[MIT](LICENSE) © mcp-tool-shop
