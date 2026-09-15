<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
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
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks — <strong>M4B / MP3 / Opus / FLAC / WAV</strong>, with chapter markers, cover art, and mastering to the <strong>ACX audio spec</strong>. From one command.
</p>

```bash
npx @mcptoolshop/audiobooker make mybook.epub --acx
```

Audiobooker détecte les dialogues, attribue une voix distincte à chaque personnage, infère les émotions, vous permet de vérifier et de corriger tout avant que la moindre seconde ne soit rendue, puis maîtrise le résultat pour qu'il corresponde aux spécifications audio ACX — de sorte que le résultat est un livre audio *terminé*, et non pas seulement un fichier audio généré.

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

**Docker** — ffmpeg est déjà inclus, publié sur GHCR à chaque version :
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
Ce montage unique suffit, et `--rm` est sûr : le cache de rendu est stocké à côté du fichier du projet, et non dans un répertoire personnel, de sorte qu’une nouvelle exécution **reprend** plutôt que de resynthétiser le livre.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Étiqueté `latest`, `2`, `2.1` et la version exacte, publié sur GHCR à chaque version.
- Le point d’entrée **est** `audiobooker`, donc passez la sous-commande immédiatement après le nom de l’image — ne répétez pas le nom du programme.
- Le cache est stocké à `<book-dir>/.audiobooker/cache`. C’est pourquoi un seul montage permet de garantir la persistance ; sa perte signifie que vous devrez payer à nouveau pour l’ensemble du processus de synthèse vocale, et non pas seulement pour un nouveau multiplexage.
- `/ext` est un deuxième montage facultatif, uniquement pour fournir votre propre module de synthèse vocale.
- Le conteneur s’exécute avec un UID non root de 1000. Sous Linux, si le répertoire monté n’est pas accessible en écriture par cet UID, le cache ne peut pas être écrit — ajoutez `--user "$(id -u):$(id -g)"` ou `chown` au répertoire. Docker Desktop sur macOS et Windows gère cela pour vous.

</details>

**Le rendu audio** nécessite le moteur de synthèse vocale [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l’extra `[render]`) et **FFmpeg** dans le PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tout ce qui précède le rendu — l’analyse, l’attribution des voix, la compilation, la vérification — fonctionne sans eux. Exécutez `audiobooker diagnose` pour vérifier votre configuration.

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
- **Fractionnement EPUB basé sur la table des matières** — les limites et les titres des chapitres sont extraits de la table des matières du livre.
- **DOCX** fractionne en fonction des styles Word `Heading 1/2`/`Title` ; **PDF** détecte les titres (avec une protection pour les PDF numérisés) ; personnalisation `--chapter-delimiter`.
- Nettoyage intelligent du texte, suppression prenant en compte Markdown, gestion des notes de bas de page et un **lexique de prononciation réutilisable** (`pronunciation import/export`, CSV/JSON, avec transmission des phonèmes).

### Attribution des voix et des rôles
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.

### Rendu et sortie
- **M4B** (chapter markers + embedded cover + series metadata), **MP3**, **Opus**, **FLAC**, **WAV**; per-chapter export; **podcast/RSS** feed export.
  WAV has no chapter atom, so a WAV render says so plainly rather than reporting a failed chapter mux — reach for it when the audio is going into an editor.
- **ACX-spec mastering** (`--acx`) + a **`master-check`** that reports PASS/FAIL on RMS loudness, peak, and noise floor; retail **`sample`** clips.
- Parallel rendering, a **persistent render cache** with resume, dynamic progress + ETA, and structured failure reports.

### Flux de travail et écosystème
- **Pipeline unique** `make` · **fichier de configuration** (`.audiobookerrc` / `[tool.audiobooker]`) · **mode** `--watch` · **traitement par lots basé sur un manifeste** · complétion de la ligne de commande.
- **7 profils linguistiques** (en/fr/de/es/ja/it/pt) · **moteurs de synthèse vocale enfichables** (`--engine`, points d’entrée — apportez Piper/Coqui/ElevenLabs) · script `--json` sur la plupart des commandes · codes de sortie structurés.

## Maîtrise conforme aux spécifications audio ACX

ACX publie une cible audio précise et mesurable. C’est l’élément qui se rapproche le plus d’une norme de maîtrise dans le monde des livres audio, et il vaut la peine de l’atteindre, quoi que vous fassiez avec le fichier par la suite.

| Exigence | Spécifications ACX | Ce que `--acx` fait |
|---|---|---|
| Volume | RMS compris entre **−23 et −18 dBFS** | two-pass `loudnorm` at −20 LUFS, which lands inside that window for speech |
| Pic | égal ou inférieur à **−3 dBFS** | appliqué lors du même passage |
| Bruit de fond | égal ou inférieur à **−60 dBFS** | mesuré et signalé — jamais « corrigé » silencieusement |
| Format | **44,1 kHz, 192 kbps CBR MP3** | définit la fréquence d’échantillonnage ; ajoutez `--format mp3 --bitrate 192k` pour le codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Voici deux points importants concernant les chiffres ci-dessus :

**`master-check` mesure le RMS non pondéré, et non les LUFS.** Il s’agit de quantités différentes et ACX se base sur la première. La valeur de −20 LUFS indique comment le passage de maîtrise **atteint** cette valeur — c’est la valeur que `ffmpeg loudnorm` peut cibler — et non pas ce qui est vérifié par la suite.

**Le bruit de fond est mesuré, et non corrigé.** C’est l’exigence qui échoue le plus souvent, et elle provient de l’audio source. Un outil qui le réduirait silencieusement masquerait le seul chiffre dont vous avez besoin.

### Où un livre audio narré par une IA peut réellement aller

Respecter les spécifications n’est pas la même chose qu’être accepté, et il est important d’être clair à ce sujet : **le flux de soumission standard d’ACX est destiné aux narrations humaines.** Ses exigences d’avril 2026 listent la synthèse vocale et les enregistrements d’IA non autorisés parmi les éléments qu’elle n’accepte pas, de sorte qu’un livre audio narré par une IA nécessite une autorisation préalable d’ACX plutôt qu’une soumission ordinaire.

Les plateformes qui acceptent la narration par l’IA incluent généralement une mention à ce sujet :
**Virtual Voice** d’Amazon, via KDP (distribution exclusivement Amazon), et des agrégateurs tels que **Spotify Audiobooks for Authors**, **Author’s Republic** et **Kobo Writing Life**. Les politiques des détaillants dans ce domaine évoluent rapidement. Vérifiez les conditions actuelles vous-même plutôt que de vous fier à ce paragraphe.

Ainsi : `--acx` concerne l’audio. Le fait qu’un détaillant accepte ou non un titre narré par une IA est sa décision, et non une caractéristique du fichier que vous venez de créer.

## Commandes CLI

| Commande | Description |
|---------|-------------|
| `make <file>` | Traitement en une seule étape : nouveau → compilation → attribution automatique → rendu |
| `new <fichier\ | dossier>` | Créer un projet à partir d’un fichier EPUB/TXT/MD/PDF/DOCX ou d’un dossier |
| `from-stdin` | Créer un projet à partir d’un texte transmis en entrée |
| `cast <char> <voice>` · `cast-interactive` | Attribuer des voix (ou effectuer une attribution guidée par personnage ; également `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggérer / appliquer automatiquement / attribuer en masse des voix |
| `cast-preset save\ | list\ | apply\ | delete` | Ensembles d’attribution réutilisables pour différents livres |
| `cast-export` · `cast-import <file>` | Effectuer un échange complet de l’attribution au format JSON/CSV : modifier manuellement ou réutiliser pour différentes éditions |
| `audition <char>` | Voix candidates classées par ordre de préférence pour un personnage (`--render`) |
| `compile` | Détecter les dialogues, attribuer les personnages, déduire les émotions |
| `report` | Qualité de la compilation : taux inconnu, meilleures lignes non attribuées, mélange des émotions |
| `review-export` · `review-import <file>` | Révision avec possibilité de modification par un humain, puis échange complet |
| `render` | Rendre le livre audio (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Échantillon de vente maîtrisé : vérifier par rapport aux spécifications audio d’ACX |
| `export-chapters` · `podcast` | Feuille de repères des chapitres (ffmetadata/cue/json) : flux RSS pour podcast |
| `preview` · `batch` · `diagnose` | Extrait de test de la voix : traitement par lots / `--manifest` : vérification de l’environnement (le programme se termine avec un code d’erreur différent de zéro si le rendu n’est pas possible) |
| `load <file>` | Ouvrir un projet `.audiobooker` existant |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecter et gérer |

Chaque commande prend en charge `-h/--help`. Indicateurs globaux : `--silent`, `--debug`. **Codes de sortie :** `0` (ok) ; `1` (erreur utilisateur, y compris un livre qui ne peut pas être compilé, ou un rendu refusé car l’attribution a échoué) ; `2` (erreur d’exécution) ; `3` (partiel, pour le traitement par lots).

## Configuration

Définir les valeurs par défaut une seule fois au lieu de repasser les indicateurs à chaque fois : `.audiobookerrc` (TOML) à côté de votre livre, ou `[tool.audiobooker]` dans `pyproject.toml`. La priorité est la suivante : **indicateur CLI > configuration du projet > configuration utilisateur (`~/.audiobookerrc`) > valeurs par défaut intégrées**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Moteurs TTS modulaires

Le moteur par défaut est `voice-soundboard`, mais le moteur de synthèse peut être modifié via les points d’entrée setuptools (`audiobooker.tts_engines`) :

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un module (`pip install audiobooker-piper`) s’enregistre ; aucun fork n’est requis.

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

`render(...)` et `compile(...)` acceptent un `engine=` injecté (tout objet implémentant le protocole `TTSEngine`) et une fonction de rappel de progression : intégrer audiobooker dans une interface graphique ou un service.

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

- **Réseau :** aucun : pas de télémétrie, pas de stockage de données, pas d’identifiants. Lit vos fichiers de livre, écrit l’audio + la mise en cache dans vos répertoires de sortie.
- **Autorisations :** accès en lecture aux fichiers d’entrée, accès en écriture aux fichiers de sortie ; FFmpeg et un moteur TTS sur le PATH sont facultatifs.
- Voir [SECURITY.md](SECURITY.md).

## Tableau de bord

| Étape | Statut |
|------|--------|
| A. Base de sécurité | OK |
| B. Gestion des erreurs | OK |
| C. Documentation pour l’opérateur | OK |
| D. Bonnes pratiques de développement | OK |
| E. Identité | OK |

## Licence

[MIT](LICENSE)

---

Créé par <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
