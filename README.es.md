<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.md">English</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
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

Audiobooker detecta los diálogos, asigna una voz distinta a cada personaje, infiere las emociones, permite revisar y corregir todo antes de que se genere un solo segundo, y luego optimiza el resultado para cumplir con las especificaciones, de modo que la salida sea un audiolibro *que se pueda enviar*, y no simplemente audio generado.

## Instalar

**Sin instalación (Node):**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python (CLI):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

La **generación de audio** requiere el motor TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (la opción `[render]`) y **FFmpeg** en la variable PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Todo lo anterior a la generación (análisis, asignación de voces, compilación, revisión) funciona sin ellos. Ejecute `audiobooker diagnose` para verificar su configuración.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## Comenzar rápidamente

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

## Características

### Entrada y estructura
- **EPUB, TXT, Markdown, PDF, DOCX** o una **carpeta de archivos por capítulo** (Scrivener/Obsidian/ficción serializada).
- **División de EPUB basada en el índice**; los límites y títulos de los capítulos se obtienen del propio índice del libro.
- **DOCX** divide según los estilos de Word `Heading 1/2`/`Title`; **PDF** detecta los encabezados (con una protección para archivos PDF escaneados); delimitador de capítulo personalizado `--chapter-delimiter`.
- Limpieza inteligente del texto, eliminación compatible con Markdown, gestión de notas al pie y un **diccionario de pronunciación reutilizable** (`pronunciation import/export`, CSV/JSON, con transmisión de fonemas).

### Asignación de voces y atribución
- **Síntesis multivoz** con sugerencias de voz explicables y clasificadas, y un comando **`audition`** para comparar candidatos por personaje.
- **Asignación de voces interactiva**, **asignación masiva `cast-fill`** por género/rol, **preajustes de asignación reutilizables** en toda una serie y **hojas de cálculo CSV** para colaboradores.
- **Detección de diálogos + atribución de hablantes** (opcionalmente con la co-referencia de **BookNLP**), **detección automática de alias** e **inferencia de emociones** con intensidad ajustable, estado de ánimo a nivel de escena y paquetes preestablecidos por género.

### Generación y salida
- **M4B** (marcadores de capítulo + portada incrustada + metadatos de la serie), **MP3**, **Opus**, **FLAC**; exportación por capítulo; exportación de feed **podcast/RSS**.
- **Masterización ACX/Audible** (`--acx`) + una verificación **`master-check`** que informa si cumple o no con los requisitos de volumen, pico y nivel de ruido; clips de muestra para la venta.
- Generación en paralelo, una **caché de generación persistente** con reanudación, progreso dinámico + tiempo estimado restante e informes estructurados de fallos.

### Flujo de trabajo y ecosistema
- **`make`**: flujo de trabajo único; **archivo de configuración** (`.audiobookerrc` / `[tool.audiobooker]`); modo **`--watch`**; procesamiento por lotes basado en un manifiesto; finalización automática para la terminal.
- **7 perfiles de idioma** (en/fr/de/es/ja/it/pt); **motores TTS conectables** (`--engine`, puntos de entrada: agregue Piper/Coqui/ElevenLabs); comandos `--json` para scripting en la mayoría de los casos; códigos de salida estructurados.

## Publicación en ACX / Audible

Audiobooker se enfoca directamente en las especificaciones medibles de envío de ACX:

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`master-check` verifica los requisitos medibles (volumen, pico, nivel de ruido). ACX también tiene criterios subjetivos/de control de calidad que una herramienta no puede certificar, pero nunca volverá a tener problemas por una violación del volumen.

## Comandos CLI

| Comando | Descripción |
|---------|-------------|
| `make <file>` | Flujo de trabajo único: nuevo → compilar → asignación automática de voces → generar |
| `new <archivo\ | carpeta>` | Crear un proyecto a partir de EPUB/TXT/MD/PDF/DOCX o una carpeta. |
| `from-stdin` | Crear un proyecto a partir de texto canalizado. |
| `cast <personaje> <voz>` · `cast --interactive` | Asignar voces (o asignación guiada por personaje). |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugerir / aplicar automáticamente / asignar en masa las voces. |
| `cast-preset save\ | list\ | apply\ | delete` | Preajustes de asignación reutilizables en varios libros. |
| `audition <char>` | Voces candidatas clasificadas para un personaje (`--render`). |
| `compile` | Detectar diálogos, atribuir hablantes, inferir emociones. |
| `report` | Calidad de la compilación: tasa desconocida, líneas no atribuidas principales, mezcla de emociones. |
| `review-export` · `review-import <archivo>` | Ciclo de revisión editable por humanos. |
| `render` | Generar el audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`). |
| `sample` · `master-check <archivo>` | Muestra maestra para la venta; verificación del cumplimiento de ACX. |
| `export-chapters` · `podcast` | Hoja de señales de capítulo (ffmetadata/cue/json); feed RSS de podcast. |
| `preview` · `batch` · `diagnose` | Clip de prueba de voz; procesamiento por lotes / `--manifest`; verificación del entorno. |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspeccionar y administrar. |

Cada comando admite `-h/--help`. Banderas globales: `--silent`, `--debug`. **Códigos de salida:** `0` correcto; `1` error de usuario; `2` error en tiempo de ejecución; `3` parcial (por lotes).

## Configuración

Establezca los valores predeterminados una vez en lugar de volver a pasar las banderas: `.audiobookerrc` (TOML) junto con su libro, o `[tool.audiobooker]` en `pyproject.toml`. La precedencia es **bandera CLI > configuración del proyecto > configuración del usuario (`~/.audiobookerrc`) > valores predeterminados integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motores TTS conectables

El motor predeterminado es `voice-soundboard`, pero el backend de síntesis se puede cambiar mediante puntos de entrada setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un complemento (`pip install audiobooker-piper`) se registra a sí mismo; no se requiere una bifurcación.

## API de Python

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` y `compile(...)` aceptan un motor inyectado (`engine=`, cualquier objeto que implemente el protocolo `TTSEngine`) y una función de devolución de llamada de progreso; incorpore Audiobooker en una GUI o servicio.

## Arquitectura

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

## Seguridad y alcance de los datos

- **Red:** ninguna — sin telemetría, sin almacenamiento de datos, sin credenciales. Lee sus archivos de libros, escribe audio + caché en sus directorios de salida.
- **Permisos:** acceso de lectura a las entradas, acceso de escritura a las salidas; FFmpeg opcional + un motor TTS en la variable PATH.
- Consulte [SECURITY.md](SECURITY.md).

## Evaluación

| Control | Estado |
|------|--------|
| A. Línea de base de seguridad | APROBADO |
| B. Manejo de errores | APROBADO |
| C. Documentación para operadores | APROBADO |
| D. Buenas prácticas de desarrollo | APROBADO |
| E. Identidad | APROBADO |

## Licencia

[MIT](LICENSE)

---

Creado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
