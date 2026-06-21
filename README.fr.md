<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.md">English</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
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

Audiobooker détecte les dialogues, attribue une voix distincte à chaque personnage, infère les émotions, vous permet de vérifier et de corriger tout avant que la première seconde ne soit rendue, puis optimise le résultat pour répondre aux exigences — ainsi, le produit final est un livre audio *présentable*, et non pas seulement un fichier audio généré.

## Installation

**Installation minimale (Node) :**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python (CLI) :**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

Le **rendu audio** nécessite le moteur de synthèse vocale [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l’option `[render]`) et **FFmpeg** dans le PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tout ce qui précède le rendu — l’analyse, l’attribution des voix, la compilation, la vérification — fonctionne sans ces éléments. Exécutez `audiobooker diagnose` pour vérifier votre configuration.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## Démarrage rapide

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

## Fonctionnalités

### Entrée et structure
- **EPUB, TXT, Markdown, PDF, DOCX**, ou un **dossier contenant des fichiers par chapitre** (Scrivener/Obsidian/fiction sérialisée).
- **Division EPUB basée sur la table des matières** — les limites et les titres des chapitres sont extraits de la propre table des matières du livre.
- **DOCX** divise le texte en fonction des styles Word `Titre 1/2`/`Titre ; PDF` détecte les titres (avec une protection pour les fichiers PDF numérisés) ; délimiteur de chapitre personnalisé `--chapter-delimiter`.
- Nettoyage intelligent du texte, suppression prenant en compte Markdown, gestion des notes de bas de page et **lexique de prononciation réutilisable** (`import/export de la prononciation`, CSV/JSON, avec transmission des phonèmes).

### Attribution des voix et rôles
- **Synthèse vocale multivoice** avec des suggestions de voix explicables et classées, ainsi qu’une commande **`audition`** pour comparer les candidats par personnage.
- **Attribution interactive**, **attribution en masse `cast-fill`** par sexe/rôle, **préréglages d’attribution réutilisables** dans une série et **fiches d’attribution CSV** pour les collaborateurs.
- **Détection des dialogues + attribution des locuteurs** (co-référence optionnelle de **BookNLP**), **découverte automatique des alias** et **inférence des émotions** avec une intensité réglable, une ambiance au niveau de la scène et des packs de préréglages pour différents genres.

### Rendu et sortie
- **M4B** (marqueurs de chapitre + couverture intégrée + métadonnées de série), **MP3**, **Opus**, **FLAC** ; exportation par chapitre ; exportation du flux **podcast/RSS**.
- **Mastering ACX/Audible** (`--acx`) + une fonction **`master-check`** qui indique si le résultat est CONFORME ou NON en termes de volume, de crête et de bruit de fond ; extraits **`sample`** pour la vente au détail.
- Rendu parallèle, **cache de rendu persistant** avec reprise, progression dynamique + ETA et rapports d’échec structurés.

### Flux de travail et écosystème
- **`make`**, pipeline unique · **fichier de configuration** (`.audiobookerrc` / `[tool.audiobooker]`) · mode **`--watch`** · traitement par lots basé sur un manifeste · complétion en ligne de commande.
- **7 profils linguistiques** (en/fr/de/es/ja/it/pt) · **moteurs de synthèse vocale modulaires** (`--engine`, points d’entrée — utilisez Piper/Coqui/ElevenLabs) · scriptable `--json` pour la plupart des commandes · codes de sortie structurés.

## Publication sur ACX / Audible

Audiobooker cible directement les spécifications mesurables d’ACX :

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`master-check` vérifie les exigences mesurables (volume, crête, bruit de fond). ACX a également des critères subjectifs/de contrôle qualité qu’un outil ne peut pas certifier — mais vous ne serez plus jamais rejeté pour un problème de volume.

## Commandes CLI

| Commande | Description |
|---------|-------------|
| `make <file>` | Pipeline unique : nouveau -> compilation -> attribution automatique des voix -> rendu |
| `new <fichier\ | dossier>` | Créer un projet à partir d’un fichier EPUB/TXT/MD/PDF/DOCX ou d’un dossier. |
| `from-stdin` | Créer un projet à partir d’un texte transmis en entrée. |
| `cast <personnage> <voix>` · `cast --interactive` | Attribuer des voix (ou effectuer une attribution guidée par locuteur). |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggérer / appliquer automatiquement / attribuer en masse des voix. |
| `cast-preset save\ | list\ | apply\ | delete` | Préréglages d’attribution réutilisables pour différents livres. |
| `audition <char>` | Comparer les voix candidates classées pour un personnage (`--render`). |
| `compile` | Détecter les dialogues, attribuer les locuteurs, inférer les émotions. |
| `report` | Qualité de la compilation : taux inconnu, nombre de lignes non attribuées, mélange des émotions. |
| `review-export` · `review-import <fichier>` | Cycle de vérification modifiable par l’utilisateur. |
| `render` | Rendre le livre audio (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`). |
| `sample` · `master-check <fichier>` | Extrait de démonstration masterisé · Vérification de la conformité ACX. |
| `export-chapters` · `podcast` | Feuille d’indices des chapitres (ffmetadata/cue/json) · flux RSS du podcast. |
| `preview` · `batch` · `diagnose` | Extrait de test vocal · traitement par lots / `--manifest` · vérification de l’environnement. |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecter et gérer. |

Toutes les commandes prennent en charge `-h/--help`. Indicateurs globaux : `--silent`, `--debug`. **Codes de sortie :** `0` (OK) · `1` (erreur utilisateur) · `2` (erreur d’exécution) · `3` (partiel).

## Configuration

Définir les valeurs par défaut une seule fois au lieu de repasser des indicateurs — `.audiobookerrc` (TOML) à côté de votre livre, ou `[tool.audiobooker]` dans `pyproject.toml`. La priorité est la suivante : **indicateur CLI > configuration du projet > configuration utilisateur (`~/.audiobookerrc`) > valeurs par défaut intégrées**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Moteurs de synthèse vocale modulaires

Le moteur par défaut est `voice-soundboard`, mais le backend de synthèse peut être modifié via les points d’entrée setuptools (`audiobooker.tts_engines`) :

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un module complémentaire (`pip install audiobooker-piper`) s’enregistre ; aucun fork n’est requis.

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

`render(...)` et `compile(...)` acceptent un moteur injecté (`engine=`, tout objet implémentant le protocole `TTSEngine`) et une fonction de rappel pour la progression — intégrez Audiobooker dans une interface graphique ou un service.

## Architecture

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

## Sécurité et étendue des données

- **Réseau :** aucun — aucune télémétrie, aucun stockage de données, aucun identifiant. Lit vos fichiers de livres, écrit l’audio + la mise en cache dans vos répertoires de sortie.
- **Autorisations :** accès en lecture aux entrées, accès en écriture aux sorties ; FFmpeg et un moteur TTS facultatifs sur le PATH.
- Voir [SECURITY.md](SECURITY.md).

## Tableau de bord

| Contrôle d’accès | État |
|------|--------|
| A. Niveau de sécurité de base | RÉUSSI |
| B. Gestion des erreurs | RÉUSSI |
| C. Documentation pour les opérateurs | RÉUSSI |
| D. Bonnes pratiques lors de la distribution | RÉUSSI |
| E. Identité | RÉUSSI |

## Licence

[MIT](LICENSE)

---

Créé par <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
