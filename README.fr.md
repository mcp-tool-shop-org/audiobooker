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

Audiobooker détecte les dialogues, attribue une voix distincte à chaque personnage, infère les émotions, vous permet de vérifier et de corriger tout avant que la moindre seconde ne soit rendue, puis maîtrise le résultat pour répondre aux spécifications audio ACX — de sorte que le résultat est un livre audio *terminé*, et non pas seulement un fichier audio généré.

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

Le **rendu audio** nécessite le moteur TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l’extra `[render]`) et **FFmpeg** dans le PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tout ce qui précède le rendu (analyse, attribution des voix, compilation, vérification) fonctionne sans eux. Exécutez `audiobooker diagnose` pour vérifier votre configuration.

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
- **EPUB, TXT, Markdown, PDF, DOCX**, or a **folder of per-chapter files** (Scrivener/Obsidian/serialized fiction).
- **TOC-driven EPUB splitting** — chapter boundaries and titles from the book's own table of contents.
- **DOCX** splits on Word `Heading 1/2`/`Title` styles; **PDF** detects headings (with a scanned-PDF guard); custom `--chapter-delimiter`.
- Smart text cleaning, Markdown-aware stripping, footnote handling, and a **reusable pronunciation lexicon** (`pronunciation import/export`, CSV/JSON, with phoneme passthrough).

### Attribution des voix et des rôles
- **Synthèse vocale multi-voix** avec des suggestions de voix explicables et classées, ainsi qu’une commande **`audition`** pour comparer les candidats pour chaque personnage.
- **Attribution interactive des voix**, **attribution groupée `cast-fill`** par sexe/rôle, **préréglages d’attribution réutilisables** pour une série, et **fiches d’attribution CSV** pour les collaborateurs.
- **Détection des dialogues + attribution des locuteurs** (co-référence optionnelle **BookNLP**), **détection automatique des alias** et **inférence des émotions** avec une intensité réglable, une ambiance au niveau de la scène et des packs de préréglages de genre.

### Rendu et sortie
- **M4B** (marqueurs de chapitre + couverture intégrée + métadonnées de la série), **MP3**, **Opus**, **FLAC**, **WAV** ; exportation par chapitre ; exportation du flux **podcast/RSS**.
Le fichier WAV ne contient pas de marqueur de chapitre. Par conséquent, un rendu WAV l’indique clairement plutôt que de signaler un échec de multiplexage du chapitre. Utilisez-le lorsque le fichier audio doit être traité dans un logiciel de montage.
- **Mastering conforme aux spécifications ACX** (`--acx`) + un **outil `master-check`** qui indique si le résultat est conforme ou non en fonction du volume RMS, du pic et du bruit de fond ; clips de **référence `sample`**.
- Rendu parallèle, **mémoire cache de rendu persistante** avec reprise, progression dynamique + ETA et rapports d’erreur structurés.

### Flux de travail et écosystème
- **Pipeline `make`** en une seule étape · **fichier de configuration** (`.audiobookerrc` / `[tool.audiobooker]`) · **mode `--watch`** · **traitement par lots basé sur un manifeste** · complétion de la ligne de commande.
- **7 profils linguistiques** (en/fr/de/es/ja/it/pt) · **moteurs TTS modulaires** (`--engine`, points d’entrée — utilisez Piper/Coqui/ElevenLabs) · script `--json` sur la plupart des commandes · codes de sortie structurés.

## Mastering conforme aux spécifications audio ACX

ACX publie une cible audio précise et mesurable. C’est l’élément qui se rapproche le plus d’une norme de mastering dans le monde des livres audio, et il vaut la peine de l’atteindre, quoi que vous fassiez avec le fichier par la suite.

| Exigence | Spécifications ACX | Ce que `--acx` fait |
|---|---|---|
| Volume | RMS entre **−23 et −18 dBFS** | two-pass `loudnorm` at −20 LUFS, which lands inside that window for speech |
| Pic | à ou en dessous de **−3 dBFS** | appliqué lors du même passage |
| Niveau de bruit | à ou en dessous de **−60 dBFS** | mesuré et signalé — jamais « corrigé » silencieusement |
| Format | **44,1 kHz, 192 kbps CBR MP3** | définit la fréquence d’échantillonnage ; ajoutez `--format mp3 --bitrate 192k` pour le codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Voici deux points importants concernant les chiffres ci-dessus :

**`master-check` measures unweighted RMS, not LUFS.** They are different
quantities and ACX gates on the former. The −20 LUFS figure is how the
mastering pass *gets* there — it is what `ffmpeg loudnorm` can target — not
what is checked afterwards.

**Le niveau de bruit est mesuré, et non corrigé.** C’est l’exigence qui échoue le plus souvent, et elle provient de l’audio source. Un outil qui le réduirait silencieusement masquerait le seul chiffre dont vous avez besoin.

### Où un livre audio narré par une IA peut réellement être utilisé

Le fait de respecter les spécifications n’est pas la même chose qu’être accepté, et il est important de le préciser : **le flux de soumission standard d’ACX est destiné aux narrations humaines.** Sa liste d’exigences d’avril 2026 inclut la synthèse vocale et les enregistrements d’IA non autorisés parmi les éléments qu’elle n’accepte pas. Par conséquent, un livre audio narré par une IA nécessite une autorisation préalable d’ACX plutôt qu’une soumission ordinaire.

Les canaux qui acceptent généralement la narration par une IA, avec une mention, incluent **Virtual Voice** d’Amazon via KDP (distribution uniquement sur Amazon) et les agrégateurs tels que **Spotify Audiobooks for Authors**, **Author’s Republic** et **Kobo Writing Life**. Les politiques des détaillants dans ce domaine évoluent rapidement : vérifiez vous-même les conditions actuelles plutôt que de vous fier à ce paragraphe.

Ainsi : `--acx` concerne l’audio. Le fait qu’un détaillant accepte ou non un livre audio narré par une IA est sa décision, et non une propriété du fichier que vous venez de créer.

## Commandes CLI

| Commande | Description |
|---------|-------------|
| `make <file>` | Pipeline en une seule étape : nouveau → compilation → attribution automatique des voix → rendu |
| `new <fichier\ | dossier>` | Créer un projet à partir d’un fichier EPUB/TXT/MD/PDF/DOCX ou d’un dossier |
| `from-stdin` | Créer un projet à partir d’un texte transmis |
| `cast <char> <voice>` · `cast-interactive` | Attribuer des voix (ou attribution guidée des voix par locuteur ; également `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggérer / appliquer automatiquement / attribuer en masse des voix |
| `cast-preset save\ | list\ | apply\ | delete` | Préréglages d’attribution réutilisables pour plusieurs livres |
| `cast-export` · `cast-import <file>` | Effectuer un aller-retour pour modifier les données au format JSON/CSV — modification manuelle ou réutilisation dans différentes versions. |
| `audition <char>` | Évaluer et classer différentes voix pour un même personnage (`--render`). |
| `compile` | Détecter les dialogues, attribuer les locuteurs, déduire les émotions. |
| `report` | Qualité de la compilation : taux inconnu, meilleures lignes sans attribution, mélange des émotions. |
| `review-export` · `review-import <file>` | Cycle de révision modifiable par l’utilisateur. |
| `render` | Générer le livre audio (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`). |
| `sample` · `master-check <file>` | Exemple de version finale pour la vente au détail ; vérifier la conformité aux spécifications audio ACX. |
| `export-chapters` · `podcast` | Feuille de repères des chapitres (ffmetadata/cue/json) ; flux RSS du podcast. |
| `preview` · `batch` · `diagnose` | Extrait de test de la qualité de la voix ; traitement par lots/`--manifest` ; vérification de l’environnement (renvoie un code différent de zéro si le système ne peut pas effectuer le rendu). |
| `load <file>` | Ouvrir un projet `.audiobooker` existant. |
| `voices` ; `chapters` ; `speakers` ; `info` ; `status` ; `cache` ; `emotions` ; `pronunciation` ; `completion`. | Inspecter et gérer. |

Chaque commande prend en charge `-h/--help`. Options globales : `--silent`, `--debug`. **Codes de sortie :** `0` (ok) ; `1` (erreur utilisateur, y compris un livre qui ne peut pas être compilé ou un rendu refusé en raison d’une attribution incorrecte) ; `2` (erreur d’exécution) ; `3` (partiel, traitement par lots).

## Configuration

Définir les valeurs par défaut une seule fois au lieu de répéter les options — `.audiobookerrc` (TOML) à côté de votre livre, ou `[tool.audiobooker]` dans `pyproject.toml`. La priorité est la suivante : **option en ligne de commande > configuration du projet > configuration de l’utilisateur (`~/.audiobookerrc`) > valeurs par défaut intégrées**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Moteurs TTS modulaires

Le moteur par défaut est `voice-soundboard`, mais le moteur de synthèse peut être modifié via les points d’entrée setuptools (`audiobooker.tts_engines`).

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un module (`pip install audiobooker-piper`) s’enregistre lui-même ; aucun fork n’est requis.

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

`render(...)` et `compile(...)` acceptent un objet `engine=` injecté (tout objet implémentant le protocole `TTSEngine`) et une fonction de rappel de progression — intégrer audiobooker dans une interface graphique ou un service.

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## Sécurité et portée des données

- **Réseau :** aucun — pas de télémétrie, pas de stockage de données, pas d’identifiants. Lit vos fichiers de livre, écrit l’audio + la mise en cache dans vos répertoires de sortie.
- **Autorisations :** accès en lecture aux entrées, accès en écriture aux sorties ; FFmpeg + un moteur TTS sur le PATH en option.
- Voir [SECURITY.md](SECURITY.md).

## Tableau de bord

| Contrôle. | État. |
|------|--------|
| A. Base de référence de sécurité. | OK. |
| B. Gestion des erreurs. | OK. |
| C. Documentation pour l’opérateur. | OK. |
| D. Bonnes pratiques de livraison. | OK. |
| E. Identité. | OK. |

## Licence

[MIT](LICENSE).

---

Créé par <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.
