<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Este es el **`npx wrapper`** para [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). Crea un entorno Python privado la primera vez que se ejecuta, instala la versión especificada desde PyPI y ejecuta la interfaz de línea de comandos real; no requiere `pip` manual ni cambios en tu instalación de Python del sistema.

## Pruébalo

```bash
npx @mcptoolshop/audiobooker --help
```

O instálalo globalmente:

```bash
npm install -g @mcptoolshop/audiobooker
```

La primera ejecución configura un entorno virtual administrado dentro del directorio de datos de tu usuario (`~/.local/share/audiobooker` o `%LOCALAPPDATA%\audiobooker` en Windows) e instala `audiobooker-ai`. Cada ejecución posterior se inicia instantáneamente.

**Requiere Python 3.10+** en la variable PATH (el wrapper busca `python3` / `py`). Si falta, el wrapper te indica exactamente cómo instalarlo para tu sistema operativo.

## Guía de inicio rápido

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## Renderizado de audio (síntesis de voz)

El análisis, la asignación de voces, la compilación y el flujo de trabajo de revisión funcionan directamente. El **renderizado de audio** requiere el motor TTS, que implica dependencias más pesadas; actívalo cuando estés listo:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

El renderizado también requiere **FFmpeg** en la variable PATH para el ensamblaje de archivos M4B/MP3 (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Ejecuta `audiobooker diagnose` para verificar tu configuración.

## Qué hace

- **Asignación de múltiples voces** con sugerencias de voz clasificadas y explicables; `audiobooker audition <character>` te permite probar diferentes voces antes de decidirte.
- **Detección de diálogos + atribución de hablantes** (opcional, co-referencia de BookNLP), inferencia de emociones y léxicos de pronunciación reutilizables.
- **Revisión antes del renderizado**: exporta un guion editable por humanos, corrige las atribuciones, vuelve a importarlo; nada se cambia silenciosamente.
- **Masterización ACX / Audible**: `render --acx` más `master-check` informa si cumple o no con los requisitos de volumen, pico y nivel de ruido.
- **Formatos**: M4B (marcadores de capítulo + portada incrustada + metadatos de la serie), MP3, Opus, FLAC; exportación por capítulo; clips de muestra para venta al público.
- **7 perfiles de idioma** (en/fr/de/es/ja/it/pt) y un archivo de configuración por libro para establecer valores predeterminados que se mantendrán.

## Variables de entorno

| Variable | Efecto |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Proporciona el entorno virtual administrado **con** el motor de voz (para renderizado) |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | Reconstruye el entorno administrado desde cero |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | Anula la ubicación del entorno virtual administrado |

## ¿Prefieres pip?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## Enlaces

- **Documentación y manual:** <https://mcp-tool-shop-org.github.io/audiobooker/>
- **Código fuente:** <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI:** <https://pypi.org/project/audiobooker-ai/>

## Licencia

[MIT](LICENSE) © mcp-tool-shop
