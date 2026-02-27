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
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## Caractéristiques

- **Synthèse vocale multi-voix** : Attribuez des voix uniques à chaque personnage.
- **Détection du dialogue** : Identifie automatiquement les dialogues par rapport à la narration.
- **Inférence émotionnelle** : Étiquetage des émotions basé sur des règles et un lexique, avec un niveau de confiance configurable.
- **Suggestions de voix** : Recommandations de voix expliquées et classées pour chaque locuteur.
- **Intégration BookNLP** : Résolution optionnelle des références aux locuteurs grâce à la technologie NLP de BookNLP.
- **Vérification avant la génération** : Format de révision modifiable par l'utilisateur pour corriger les attributions.
- **Cache de génération persistant** : Reprenez les générations interrompues sans refaire les chapitres déjà générés.
- **Progression et ETA dynamiques** : Statut de génération en temps réel avec une estimation du temps de fin.
- **Rapports d'erreur** : Diagnostics structurés au format JSON en cas d'erreur de génération.
- **Profils de langue** : Abstraction des règles spécifiques à chaque langue, extensible.
- **Sortie M4B** : Format de livre audio professionnel avec navigation par chapitre.
- **Persistance du projet** : Enregistrez et reprenez les sessions de génération.

## Installation

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

## Fonctionnalités optionnelles

| Fonctionnalité | Installation | Configuration |
|---------|---------|--------|
| **TTS rendering** | `pip install audiobooker-ai[render]` ou installez voice-soundboard | Nécessaire pour `render` |
| **Résolution des locuteurs BookNLP** | `pip install audiobooker-ai[nlp]` | `--booknlp on\ | off\ | auto` |
| **FFmpeg audio assembly** | Paquet système (winget/brew/apt) | Nécessaire pour la sortie M4B |

## Premiers pas

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

## Flux de travail de révision

Le flux de travail de révision vous permet d'examiner et de corriger le script compilé avant la génération :

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

**Format du fichier de révision :**
- `=== Titre du chapitre ===` - Marqueurs de chapitre
- `@Locuteur` ou `@Locuteur (émotion)` - Balises de locuteur
- `# commentaire` - Commentaires (ignorés lors de l'importation)
- Supprimez les blocs pour supprimer les énoncés indésirables.
- Remplacez `@Inconnu` par `@NomRéel` pour corriger les attributions.

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

## Commandes CLI

| Commande | Description |
|---------|-------------|
| `audiobooker new <file>` | Créer un projet à partir d'un fichier EPUB/TXT |
| `audiobooker cast <char> <voice>` | Attribuer une voix à un personnage |
| `audiobooker cast-suggest` | Suggérer des voix pour les locuteurs non attribués |
| `audiobooker cast-apply --auto` | Appliquer automatiquement les meilleures suggestions de voix |
| `audiobooker compile` | Compiler les chapitres en énoncés |
| `audiobooker review-export` | Exporter le script pour la révision humaine |
| `audiobooker review-import <file>` | Importer le fichier de révision modifié |
| `audiobooker render` | Générer le livre audio |
| `audiobooker info` | Afficher les informations du projet |
| `audiobooker voices` | Lister les voix disponibles |
| `audiobooker chapters` | Lister les chapitres |
| `audiobooker speakers` | Lister les locuteurs détectés |
| `audiobooker from-stdin` | Créer un projet à partir d'un texte en entrée standard |

## Architecture

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

**Flux :**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Dépannage

**Rapport d'erreur de génération :** En cas d'erreur de génération, Audiobooker écrit `render_failure_report.json` dans le répertoire du cache. Il contient :
- L'index et le titre du chapitre où l'erreur s'est produite.
- L'index de l'énoncé, le locuteur et un aperçu du texte.
- L'ID de la voix et l'émotion qui étaient en cours de synthèse.
- La trace de la pile complète.
- Les chemins du cache et du manifeste.

**Problèmes courants de FFmpeg :**
- `FFmpeg introuvable` : Installez via votre gestionnaire de paquets (winget/brew/apt).
- `L'intégration du chapitre a échoué` : Audiobooker revient à M4A sans marqueurs de chapitre.
- Qualité audio : Par défaut, AAC 128 kbps à 24 kHz (configurable dans ProjectConfig).

**Problèmes de cache :**
- `audiobooker render --clean-cache` — efface tous les fichiers audio mis en cache et relance la génération.
- `audiobooker render --no-resume` — ignore le cache pour cette exécution uniquement.
- `audiobooker render --from-chapter 5` — démarre à partir d'un chapitre spécifique.

## Feuille de route

- [x] v0.1.0 - Pipeline de base (analyse, attribution, compilation, génération)
- [x] v0.2.0 - Flux de travail de révision avant la génération
- [x] v0.3.0 - Cache de génération persistant + reprise
- [x] v0.4.0 - Profils de langue + flexibilité de l'entrée
- [x] v0.5.0 - BookNLP, inférence émotionnelle, suggestions de voix, amélioration de l'interface utilisateur

## Sécurité et portée des données

- **Données accessibles :** Lecture de fichiers EPUB/TXT à partir du système de fichiers local. Écriture de fichiers audio et de manifestes de cache dans les répertoires de sortie. Utilisation optionnelle d'une table de sons pour la synthèse vocale et de FFmpeg pour l'assemblage audio.
- **Données non accessibles :** Aucune requête réseau. Aucune télémétrie. Aucun stockage de données utilisateur. Aucune information d'identification ou jeton.
- **Autorisations requises :** Accès en lecture aux fichiers de livre d'entrée. Accès en écriture aux répertoires de sortie. Optionnel : FFmpeg doit être présent dans le PATH.

## Tableau de bord

| Étape | Statut |
|------|--------|
| A. Base de sécurité | PASSÉ |
| B. Gestion des erreurs | PASSÉ |
| C. Documentation pour les utilisateurs | PASSÉ |
| D. Bonnes pratiques de déploiement | PASSÉ |
| E. Identification | PASSÉ |

## Licence

[MIT](LICENSE)

---

Créé par <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a
