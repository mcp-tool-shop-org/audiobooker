<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Audiobooker détecte les dialogues, attribue une voix distincte à chaque personnage, infère les émotions, vous permet de vérifier et de corriger tout avant que la première seconde ne soit rendue, puis optimise le résultat pour répondre aux spécifications audio ACX — de sorte que le résultat est un livre audio *terminé*, et non pas seulement un fichier audio généré.

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

**Docker** — ffmpeg est déjà inclus, et publié sur GHCR à chaque version :
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
Ce montage unique suffit, et `--rm` est sûr : le cache de rendu se trouve à côté du fichier du projet, et non dans un répertoire personnel, de sorte qu’une nouvelle exécution **reprend** plutôt que de resynthétiser le livre.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Étiqueté `latest`, `3`, `3.0` et la version exacte, publié sur GHCR à chaque version.
- Le point d’entrée **est** `audiobooker`, donc passez la sous-commande immédiatement après le nom de l’image — ne répétez pas le nom du programme.
- Le cache se trouve à `<book-dir>/.audiobooker/cache`. C’est pourquoi un seul montage permet de garantir la persistance ; sa perte signifie que vous devrez payer à nouveau pour l’ensemble de l’exécution TTS, et non pas seulement pour un nouveau multiplexage.
- `/ext` est un deuxième montage facultatif, uniquement pour fournir votre propre module TTS.
- Le conteneur s’exécute avec un UID non root de 1000. Sous Linux, si le répertoire monté n’est pas accessible en écriture par cet UID, le cache ne peut pas être écrit — ajoutez `--user "$(id -u):$(id -g)"` ou `chown` au répertoire. Docker Desktop sur macOS et Windows gère cela pour vous.

</details>

**Le rendu audio** nécessite le moteur TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (l’extra `[render]`) et **FFmpeg** dans le PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tout ce qui précède le rendu — l’analyse, l’attribution, la compilation, la vérification — fonctionne sans eux. Exécutez `audiobooker diagnose` pour vérifier votre configuration.

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

Chacun de ces cas représente une situation où la version 2.x acceptait quelque chose et agissait incorrectement en silence. La version 3.0 refuse à la place. Tous les détails dans le [JOURNAL DES MODIFICATIONS](CHANGELOG.md).

- **Votre premier rendu re-rend chaque chapitre, une seule fois.** Trois paramètres qui modifient l’audio — le préréglage des émotions, l’intensité de l’énoncé et la vitesse/le ton/l’emphase par personnage — étaient absents de la clé du cache, de sorte que le changement de préréglage affichait « En cache » et renvoyait l’audio précédent. Ils sont maintenant inclus dans la clé, et une entrée de cache 2.x ne peut pas prouver ce qui l’a produit.
- **`--format m4a` n’est plus une option pour l’ensemble du livre.** Cela signifiait toujours un fichier par chapitre ; la demande d’un livre entier dans `m4a` produisait auparavant un seul fichier M4B avec un nom `.m4a`. Cela reste valide dans `podcast --format`.
- **`render` refuse un livre dont l’attribution indique `FAILED`** au lieu de lancer une exécution TTS. `--force` permet de remplacer cela. Exécutez `audiobooker report` pour voir les lignes auxquelles il s’oppose.
- **`make` refuse lorsque le fichier du projet existe déjà.** Il avait l’habitude de remplacer les voix attribuées manuellement, les remplacements de prononciation et les titres modifiés par une nouvelle analyse automatique. Passez `--overwrite-project` si c’est ce que vous voulez.
- **`compile()` génère une erreur lorsque chaque chapitre échoue** au lieu de renvoyer `None` comme le ferait une exécution réussie. Si vous l’appelez depuis Python, il peut maintenant générer une exception.

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
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## Fonctionnalités

### Entrée et structure
- **EPUB, TXT, Markdown, PDF, DOCX**, ou un **dossier de fichiers par chapitre** (Scrivener/Obsidian/fiction sérialisée).
- **Fractionnement EPUB basé sur la table des matières** — les limites et les titres des chapitres sont extraits de la table des matières du livre.
- **DOCX** fractionne en fonction des styles Word `Heading 1/2`/`Title` ; **PDF** détecte les titres (avec une protection pour les PDF numérisés) ; personnalisation `--chapter-delimiter`.
- Nettoyage intelligent du texte, suppression prenant en compte Markdown, gestion des notes de bas de page et **lexique de prononciation réutilisable** (`pronunciation import/export`, CSV/JSON, avec transmission des phonèmes).

### Attribution et sélection des voix
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.
- **Attribution you can audit.** Every line records *how* its speaker was decided — a speech tag, an inline override, co-reference, your own correction, or a bare alternating-turn guess — and `report` counts the guesses separately from the lines it could not attribute at all. A guess cannot improve the score, so the number goes down when the attribution gets worse, which is the only direction that is useful.

### Rendu et sortie
- **M4B** (chapter markers + embedded cover + series metadata), **MP3**, **Opus**, **FLAC**, **WAV**; per-chapter export; **podcast/RSS** feed export.
  WAV has no chapter atom, so a WAV render says so plainly rather than reporting a failed chapter mux — reach for it when the audio is going into an editor.
- **ACX-spec mastering** (`--acx`) + a **`master-check`** that reports PASS/FAIL on RMS loudness, peak, and noise floor; retail **`sample`** clips.
- Parallel rendering, a **persistent render cache** with resume, dynamic progress + ETA, and structured failure reports.
  The cache key covers everything that changes the audio — text, cast, voices, engine and version, profile, emotion preset and intensity — so a re-render that says "Cached" means it. An opt-in **per-utterance cache** (`utterance_cache`) narrows a re-render to the lines you actually edited.

### Flux de travail et écosystème
- **Pipeline unique** `make` · **fichier de configuration** (`.audiobookerrc` / `[tool.audiobooker]`) · **mode** `--watch` · **traitement par lots basé sur un manifeste** · complétion de la ligne de commande.
- **7 profils linguistiques** (en/fr/de/es/ja/it/pt) · **moteurs TTS modulaires** (`--engine`, points d’entrée — apportez Piper/Coqui/ElevenLabs) · script `--json` sur la plupart des commandes · codes de sortie structurés.

## Maîtrise conforme aux spécifications audio ACX

ACX publie une spécification audio précise et mesurable. C'est ce qui se rapproche le plus d'une norme de maîtrise dans le monde des livres audio, et il est important de la respecter, quoi que vous fassiez avec le fichier par la suite.

| Exigence | Spécifications ACX | Ce que `--acx` fait |
|---|---|---|
| Niveau sonore | RMS entre **−23 et −18 dBFS** | traitement en deux passes `loudnorm` à −20 LUFS, ce qui se situe dans cette plage pour la parole |
| Crête | à ou en dessous de **−3 dBFS** | appliqué lors de la même passe |
| Niveau de bruit | à ou en dessous de **−60 dBFS** | mesuré et signalé — jamais « corrigé » silencieusement |
| Format | **44,1 kHz, 192 kbps CBR MP3** | définit la fréquence d'échantillonnage ; ajoutez `--format mp3 --bitrate 192k` pour le codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Deux éléments que les chiffres ci-dessus méritent :

**`master-check` mesure le RMS non pondéré, et non les LUFS.** Ce sont des quantités différentes, et ACX se base sur la première. La valeur de −20 LUFS indique comment la passe de maîtrise *atteint* ce niveau ; c'est la cible que `ffmpeg loudnorm` peut atteindre, et non ce qui est vérifié par la suite.

**Le niveau de bruit est mesuré, et non corrigé.** C'est l'exigence qui échoue le plus souvent, et elle provient de l'audio source. Un outil qui le réduirait silencieusement masquerait le seul chiffre que vous devez voir.

### Là où un livre audio narré par une IA peut réellement aller

Le respect des spécifications n'est pas la même chose qu'être accepté, et il est important d'être clair à ce sujet : **le processus de soumission standard d'ACX est destiné à la narration humaine.** Sa liste d'exigences d'avril 2026 inclut la synthèse vocale et les enregistrements d'IA non autorisés parmi les éléments qu'elle n'accepte pas. Par conséquent, un livre narré par une IA nécessite une autorisation préalable d'ACX plutôt qu'une soumission ordinaire.

Les canaux qui acceptent la narration d'IA, généralement avec une mention, incluent **Virtual Voice** d'Amazon via KDP (distribution uniquement sur Amazon) et des agrégateurs tels que **Spotify Audiobooks for Authors**, **Author's Republic** et **Kobo Writing Life**. La politique des détaillants dans ce domaine évolue rapidement ; vérifiez vous-même les conditions actuelles plutôt que de vous fier à ce paragraphe.

Donc : `--acx` concerne l'audio. Le fait qu'un détaillant accepte ou non un livre narré par une IA est sa décision, et non une propriété du fichier que vous venez de créer.

## Commandes CLI

| Commande | Description |
|---------|-------------|
| `make <file>` | Exécution unique : nouveau → compilation → attribution automatique → rendu |
| `new <fichier\ | dossier>` | Créer un projet à partir d'EPUB/TXT/MD/PDF/DOCX ou d'un dossier |
| `from-stdin` | Créer un projet à partir de texte transmis |
| `cast <char> <voice>` · `cast-interactive` | Attribuer des voix (ou une attribution guidée par locuteur ; également `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Suggérer / appliquer automatiquement / attribuer en masse des voix |
| `cast-preset save\ | list\ | apply\ | delete` | Préréglages d'attribution réutilisables pour différents livres |
| `cast-export` · `cast-import <file>` | Effectuer un aller-retour de l'attribution au format JSON/CSV — modifier manuellement ou réutiliser entre les éditions |
| `audition <char>` | Voix candidates classées par ordre de préférence pour un personnage (`--render`) |
| `compile` | Détecter les dialogues, attribuer les locuteurs, déduire les émotions |
| `report` | Qualité de la compilation : taux d'attribution, taux estimé, pires passages, mélange des émotions |
| `review-export` · `review-import <file>` | Révision modifiable par l'utilisateur, avec possibilité de retour |
| `render` | Rendre le livre audio (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Échantillon de vente au détail maîtrisé · vérification par rapport aux spécifications audio d'ACX |
| `export-chapters` · `podcast` | Feuille de repères des chapitres (ffmetadata/cue/json) · flux RSS de podcast |
| `preview` · `batch` · `diagnose` | Clip de contrôle de la voix · traitement par lots / `--manifest` · vérification de l'environnement (quitte avec un code d'erreur différent de zéro si le système ne peut pas effectuer le rendu) |
| `load <file>` | Ouvrir un projet `.audiobooker` existant |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecter et gérer |

Chaque commande prend en charge `-h/--help`. Indicateurs globaux : `--silent`, `--debug`. **Codes de sortie :** `0` ok · `1` erreur utilisateur (y compris un livre qui ne pourrait pas être compilé, ou un rendu refusé car l'attribution a échoué) · `2` erreur d'exécution · `3` partiel (traitement par lots).

## Configuration

Définir les valeurs par défaut une seule fois au lieu de repasser les indicateurs — `.audiobookerrc` (TOML) à côté de votre livre, ou `[tool.audiobooker]` dans `pyproject.toml`. La priorité est la suivante : **indicateur CLI > configuration du projet > configuration utilisateur (`~/.audiobookerrc`) > valeurs par défaut intégrées**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Moteurs de synthèse vocale (TTS) modulaires

Le moteur par défaut est `voice-soundboard`, mais le backend de synthèse est remplaçable via les points d'entrée setuptools (`audiobooker.tts_engines`) :

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un module (`pip install audiobooker-piper`) s'enregistre ; aucun fork n'est requis.

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

`render(...)` et `compile(...)` acceptent un `engine=` injecté (tout objet implémentant le protocole `TTSEngine`) et un rappel de progression — intégrez audiobooker dans une interface graphique ou un service.

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

- **Réseau :** aucun — pas de télémétrie, pas de stockage de données, pas d'identifiants. Lit vos fichiers de livre, écrit l'audio + la mise en cache dans vos répertoires de sortie.
- **Autorisations :** accès en lecture aux entrées, accès en écriture aux sorties ; FFmpeg + un moteur TTS sur le PATH en option.
- Voir [SECURITY.md](SECURITY.md).

## Tableau de bord

| Critère | Statut |
|------|--------|
| A. Base de sécurité | OK |
| B. Gestion des erreurs | OK |
| C. Documentation pour l'opérateur | OK |
| D. Bonnes pratiques de livraison | OK |
| E. Identité | OK |

## Licence

[MIT](LICENSE)

---

Créé par <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
