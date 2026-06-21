<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Il s’agit du **« wrapper `npx` »** pour [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). Il met en place un environnement Python privé lors de la première exécution, installe la version spécifiée à partir de PyPI et exécute l’interface en ligne de commande réelle : pas besoin d’utiliser `pip` manuellement, ni de modifier votre installation Python.

## Essayez-le

```bash
npx @mcptoolshop/audiobooker --help
```

Ou installez-le globalement :

```bash
npm install -g @mcptoolshop/audiobooker
```

Lors de la première exécution, un environnement virtuel géré est mis en place dans le répertoire des données de votre utilisateur (`~/.local/share/audiobooker`, ou `%LOCALAPPDATA%\audiobooker` sous Windows), et `audiobooker-ai` est installé. Toutes les exécutions suivantes démarrent instantanément.

**Nécessite Python 3.10+** dans le PATH (le wrapper recherche `python3` / `py`). S’il manque, le wrapper vous indique exactement comment l’installer pour votre système d’exploitation.

## Démarrage rapide

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## Rendu audio (synthèse vocale)

L’analyse syntaxique, la sélection des voix, la compilation et le flux de travail d’examen fonctionnent immédiatement. Le **rendu audio** nécessite le moteur TTS, qui implique l’installation de dépendances plus importantes : activez-le lorsque vous serez prêt :

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

Le rendu nécessite également **FFmpeg** dans le PATH pour l’assemblage des fichiers M4B/MP3 (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Exécutez `audiobooker diagnose` pour vérifier votre configuration.

## Fonctionnalités

- **Sélection de plusieurs voix** avec des suggestions de voix classées et explicables ; `audiobooker audition <character>` vous permet de tester différentes voix avant de faire votre choix.
- **Détection des dialogues + attribution des locuteurs** (co-référence BookNLP facultative), inférence émotionnelle et lexiques de prononciation réutilisables.
- **Relecture avant le rendu :** exportez un script modifiable, corrigez les attributions, réimportez-le : rien n’est modifié silencieusement.
- **Mastering ACX / Audible :** `render --acx` plus `master-check` affiche PASS/FAIL pour le volume sonore, le pic et le bruit de fond.
- **Formats :** M4B (marqueurs de chapitres + couverture intégrée + métadonnées de série), MP3, Opus, FLAC ; exportation par chapitre ; extraits d’échantillons pour la vente au détail.
- **7 profils linguistiques** (en/fr/de/es/ja/it/pt) et un fichier de configuration par livre pour des paramètres par défaut faciles à configurer et à oublier.

## Variables d’environnement

| Variable. | Effet. |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Provisionner l’environnement virtuel géré **avec** le moteur vocal (pour le rendu). |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | Reconstruire l’environnement géré à partir de zéro. |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | Remplacer l’emplacement de l’environnement virtuel géré. |

## Préférez-vous utiliser pip ?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## Liens

- **Documentation et manuel :** <https://mcp-tool-shop-org.github.io/audiobooker/>
- **Code source :** <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI :** <https://pypi.org/project/audiobooker-ai/>

## Licence

[MIT](LICENSE) © mcp-tool-shop.
