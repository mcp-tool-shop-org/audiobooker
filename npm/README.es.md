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

This is the **`npx` wrapper** for [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). It bootstraps a private Python environment on first run, installs the pinned version from PyPI, and runs the real CLI — no manual `pip`, no changes to your system Python.

## Pruébalo

```bash
npx @mcptoolshop/audiobooker --help
```

O instálalo globalmente:

```bash
npm install -g @mcptoolshop/audiobooker
```

La primera ejecución configura un entorno virtual administrado en el directorio de datos de tu usuario (`~/.local/share/audiobooker` o `%LOCALAPPDATA%\audiobooker` en Windows) e instala `audiobooker-ai`. Cada ejecución posterior se inicia instantáneamente.

**Requiere Python 3.10+** en la variable PATH (el envoltorio busca `python3` / `py`). Si falta, el envoltorio te indica exactamente cómo instalarlo para tu sistema operativo.

## Inicio rápido

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

El análisis, la asignación de voces, la compilación y el flujo de trabajo de revisión funcionan de inmediato. El **renderizado de audio** requiere el motor TTS, que implica dependencias más pesadas; actívalo cuando estés listo:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

El renderizado también requiere **FFmpeg** en la variable PATH para el ensamblaje de archivos M4B/MP3 (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Ejecuta `audiobooker diagnose` para verificar tu configuración.

## Qué hace

- **Asignación de múltiples voces** con sugerencias de voz explicables y clasificadas; `audiobooker audition <character>` te permite probar diferentes voces antes de decidirte.
- **Detección de diálogos + atribución de hablantes** (opcional, con co-referencia de BookNLP), inferencia de emociones y léxicos de pronunciación reutilizables.
- **Revisión antes del renderizado**: exporta un guion editable por humanos, corrige las atribuciones, vuelve a importarlo; nada se cambia silenciosamente.
- **Masterización según las especificaciones de ACX**: `render --acx` realiza la masterización para cumplir con los requisitos de audio de ACX: RMS entre −23 y −18 dBFS, pico en o por debajo de −3, nivel de ruido en o por debajo de −60; y `master-check` informa si cumple o no con esos tres límites medidos.
Ten en cuenta que cumplir con las especificaciones no es lo mismo que ser aceptado: el flujo de envío estándar de ACX es para narraciones humanas. Consulta el [README principal](https://github.com/mcp-tool-shop-org/audiobooker#where-an-ai-narrated-audiobook-can-actually-go) para conocer las vías que sí aceptan audiolibros narrados por IA.
- **Formatos**: M4B (marcadores de capítulo + portada incrustada + metadatos de la serie), MP3, Opus, FLAC; exportación por capítulo; clips de muestra para la venta.
- **7 perfiles de idioma** (en/fr/de/es/ja/it/pt) y un archivo de configuración por libro para establecer valores predeterminados que se mantendrán.

## Variables de entorno

| Variable | Efecto |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Proporciona el entorno virtual administrado **con** el motor de voz (para el renderizado) |
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
