<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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
  AI Audiobook Generator — Convert EPUB/TXT/PDF books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## Fonctionnalités

### Entrée et Analyse
- Analyse des sources **EPUB / TXT / Markdown** avec détection des chapitres.
- Prise en charge de **PDF** (optionnelle) : Extraction du texte des fichiers PDF via PyMuPDF (`pip install -e '.[pdf]'`)
- **Normalisation du texte** : Nettoyage des guillemets, normalisation des espaces, outils de nettoyage du texte configurables.
- **Surcharge de la prononciation** : Mappages personnalisés de mots à leur prononciation pour les noms propres et le jargon.
- **Gestion des notes de bas de page** : Comportement des notes de bas de page configurable (`inline`, `end` ou `skip`).

### Dialogue et Attribution
- **Détection du dialogue** : Identification automatique des dialogues cités par rapport à la narration.
- **Détection avancée du dialogue** : Suivi des interventions dans les scènes avec plusieurs locuteurs.
- **Indications scéniques** : Détection et gestion des indications scéniques entre parenthèses dans les scripts.
- **Intégration BookNLP** : Résolution optionnelle des références aux locuteurs basée sur le traitement du langage naturel (NLP).
- **Alias de personnages** : Association de noms alternatifs à un personnage principal.

### Voix et Interprétation
- **Synthèse vocale multi-voix** : Attribution de voix uniques à chaque personnage.
- **Suggestions de voix** : Recommandations de voix classées et expliquées pour chaque locuteur.
- **Inférence émotionnelle** : Étiquetage des émotions basé sur des règles et un lexique, avec un niveau de confiance configurable.
- **Paramètres vocaux par personnage** : Vitesse (0,5 à 2,0) et émotion par locuteur.
- **Prétraitement SSML** : Prise en charge du langage de balisage de synthèse vocale (SSML) pour un contrôle précis.

### Rendu et Sortie
- **Rendu parallèle** : Rendu des chapitres avec plusieurs processus en parallèle avec `--jobs N`.
- **Formats de sortie multiples** : MP3, M4B, WAV, OGG, FLAC.
- **Normalisation audio** : Niveaux de volume constants sur tous les chapitres.
- **Intégration de la couverture** : Extraite de l'EPUB ou fournie par l'utilisateur, intégrée dans la sortie M4B.
- **Cache de rendu persistant** : Reprise des rendus interrompus sans refaire la synthèse des chapitres déjà terminés.
- **Barre de progression et ETA dynamiques** : Statut du rendu en temps réel avec une estimation du temps de fin.
- **Rapports d'erreur** : Diagnostics structurés en JSON en cas d'erreur de rendu.

### Langue et Localisation
- **5 profils de langue** : Anglais, français, allemand, espagnol, japonais (`--lang en|fr|de|es|ja`).
- **Système de profils extensible** : Ajout de nouvelles langues via l'abstraction `LanguageProfile`.

### Flux de travail et Productivité
- **Vérification avant le rendu** : Format de révision modifiable par l'utilisateur pour corriger les attributions.
- **Comparaison de projets** : Comparaison de deux versions d'un projet pour voir les modifications des chapitres et des répliques.
- **Traitement par lots** : Traitement de plusieurs livres en une seule exécution avec `audiobooker batch`.
- **Mode de test** : Prévisualisation du rendu ou des opérations par lots sans exécution (`--dry-run`).
- **Écoute de la voix** : Rendu d'un court extrait pour valider les attributions vocales (`audiobooker preview`).
- **Gestion des chapitres** : Fusion, division et exclusion des chapitres avant le rendu.
- **Gestion des émotions** : Liste et modification des émotions par réplique après la compilation.
- **Notifications de bureau** : Recevez des notifications lorsque les rendus longs sont terminés.
- **Persistance du projet** : Sauvegarde/reprise des sessions de rendu.

## Installation

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

## Fonctionnalités optionnelles

| Fonctionnalité | Installation | Configuration |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` ou installation de voice-soundboard | Requis pour `render` |
| **Résolution des locuteurs BookNLP** | `pip install -e '.[nlp]'` | `--booknlp on\ | off\ | auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | Détecté automatiquement à l'exécution |
| **FFmpeg audio assembly** | Paquet système (winget/brew/apt) | Requis pour la sortie M4B |

## Démarrage rapide

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

## Flux de travail de révision

Le flux de travail de révision vous permet d'examiner et de corriger le script compilé avant le rendu :

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

**Format du fichier de relecture :**
- `=== Titre du chapitre ===` - Marqueurs de chapitre
- `@Orateur` ou `@Orateur (émotion)` - Balises d'orateur
- `# commentaire` - Commentaires (ignorés lors de l'importation)
- Supprimez les blocs pour supprimer les énoncés indésirables.
- Remplacez `@Inconnu` par `@NomRéel` pour corriger l'attribution.

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

## Commandes de l'interface en ligne de commande (CLI)

| Commande | Description |
|---------|-------------|
| `audiobooker new <file>` | Créer un projet à partir de EPUB/TXT/MD/PDF |
| `audiobooker load <project>` | Charger un projet `.audiobooker` existant |
| `audiobooker from-stdin` | Créer un projet à partir d'un texte en entrée |
| `audiobooker cast <char> <voice>` | Attribuer une voix à un personnage |
| `audiobooker cast-suggest` | Suggérer des voix pour les orateurs non attribués |
| `audiobooker cast-apply --auto` | Appliquer automatiquement les meilleures suggestions de voix |
| `audiobooker compile` | Compiler les chapitres en énoncés |
| `audiobooker review-export` | Exporter le script pour une relecture humaine |
| `audiobooker review-import <file>` | Importer le fichier de relecture modifié |
| `audiobooker render` | Générer le livre audio (prend en charge `--dry-run`, `--jobs N`, `--format`, `--cover`) |
| `audiobooker preview` | Générer un court extrait pour la validation de la voix (`--chapter N`, `--seconds S`) |
| `audiobooker batch <files...>` | Traiter par lots plusieurs livres (prend en charge `--dry-run`) |
| `audiobooker info` | Afficher les informations du projet |
| `audiobooker status` | Afficher l'état de la génération/du cache |
| `audiobooker voices` | Lister les voix disponibles (prend en charge `--gender`, `--search`) |
| `audiobooker chapters` | Lister les titres et les indices des chapitres |
| `audiobooker speakers` | Lister les orateurs détectés |
| `audiobooker cache info` | `clean` | `clean-failed` | Gérer le cache de génération |
| `audiobooker diagnose` | Vérifier l'environnement (dépendances, moteur de voix, FFmpeg) |

## Référence complète de l'interface en ligne de commande

Toute commande prend en charge `-h` / `--help` pour un affichage détaillé de l'utilisation. Principaux paramètres :

- **`new`**: `-o <project>`, `--lang <code>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <émotion>`, `--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`, `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`, `--jobs N`, `-o <path>`, `--format mp3|m4b|wav|ogg|flac`, `--cover <image>`
- **`preview`**: `--chapter N`, `--seconds S`, `-o <path>`
- **`batch`**: `--dry-run`, `--jobs N`, `--format <fmt>`, `--lang <code>`, `--output-dir <dir>`
- **`voices`**: `--gender <male|female>`, `--search <query>`
- **`info`**: `--verbose`

## Architecture

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

**Flux :**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Problèmes courants

| Problème | Solution |
|---------|-----|
| **FFmpeg not found** | Installation via votre gestionnaire de paquets : `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `apt install ffmpeg` (Linux). FFmpeg doit être dans le PATH. |
| **voix-soundboard non installé** | Clonez et installez le dépôt associé : `git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`. Ou installez avec `pip install -e '.[render]'`. |
| **Erreurs de BookNLP ou démarrage lent** | BookNLP est facultatif. Si vous n'avez pas besoin de la résolution d'orateur par NLP, définissez `--booknlp off` ou laissez-le à `auto` (repli gracieux). Installez avec `pip install -e '.[nlp]'` uniquement si nécessaire. |

Consultez le [manuel](docs/handbook.md#15-troubleshooting) pour obtenir des conseils de dépannage complets.

## Dépannage

**Rapport de défaillance de génération :** En cas d'erreur de génération, Audiobooker écrit `render_failure_report.json` dans le répertoire du cache. Il contient :
- L'index et le titre du chapitre où l'erreur s'est produite
- L'index de l'énoncé, l'orateur et l'aperçu du texte
- L'ID de la voix et l'émotion qui étaient en cours de synthèse
- La trace de pile complète
- Les chemins du cache et du manifeste

**Problèmes courants de FFmpeg :**
- `FFmpeg introuvable` : Installez via votre gestionnaire de paquets (winget/brew/apt)
- `L'intégration du chapitre a échoué` : Audiobooker revient à M4A sans marqueurs de chapitre
- Qualité audio : Par défaut, AAC 128 kbps à 24 kHz (configurable dans ProjectConfig)

**Problèmes de cache :**
- `audiobooker render --clean-cache` : efface tous les fichiers mis en cache et relance le rendu.
- `audiobooker render --no-resume` : ignore le cache pour cette exécution uniquement.
- `audiobooker render --from-chapter 5` : commence à partir d'un chapitre spécifique.

## Feuille de route

- [x] Pipeline principal (analyse, conversion, compilation, rendu)
- [x] Flux de travail de vérification avant le rendu
- [x] Cache de rendu persistant + reprise
- [x] Profils de langue + flexibilité de l'entrée
- [x] BookNLP, inférence émotionnelle, suggestions de voix, amélioration de l'interface utilisateur
- [x] v1.0.0 - Version de production

## Sécurité et portée des données

- **Données accessibles :** Lit les fichiers EPUB/TXT à partir du système de fichiers local. Écrit les fichiers audio et les manifestes de cache dans les répertoires de sortie. Utilise éventuellement une table de voix pour la synthèse vocale et FFmpeg pour l'assemblage audio.
- **Données NON accessibles :** Aucune requête réseau. Aucune télémétrie. Aucun stockage de données utilisateur. Aucun identifiant ou jeton.
- **Autorisations requises :** Accès en lecture aux fichiers de livre d'entrée. Accès en écriture aux répertoires de sortie. Facultatif : FFmpeg doit être présent dans le PATH.

## Tableau de bord

| Portail | Statut |
|------|--------|
| A. Base de sécurité | PASSÉ |
| B. Gestion des erreurs | PASSÉ |
| C. Documentation pour les utilisateurs | PASSÉ |
| D. Hygiène de production | PASSÉ |
| E. Identité | PASSÉ |

## Licence

[MIT](LICENSE)

---

Créé par <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
