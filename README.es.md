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

Audiobooker detecta los diálogos, asigna una voz distinta a cada personaje, infiere las emociones, permite revisar y corregir todo antes de que se genere un solo segundo, y luego optimiza el resultado para cumplir con las especificaciones de audio de ACX, de modo que el resultado sea un audiolibro *terminado*, y no solo audio generado.

## Instalar

**Instalación cero (Node):**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python (CLI):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

**Docker:** ffmpeg ya incluido, publicado en GHCR en cada versión:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
Este montaje es suficiente, y `--rm` es seguro: la caché de renderizado se guarda junto al archivo del proyecto, no en un directorio de inicio, por lo que, al volver a ejecutar, **se reanuda** en lugar de volver a sintetizar el libro.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Etiquetado `latest`, `2`, `2.1` y la versión exacta, publicado en GHCR en cada versión.
- El punto de entrada **es** `audiobooker`, por lo que pase el subcomando inmediatamente después del nombre de la imagen; no repita el nombre del programa.
- La caché se guarda en `<book-dir>/.audiobooker/cache`. Por eso, un único montaje cubre la persistencia; perderlo significa tener que pagar de nuevo por toda la ejecución de TTS, no solo por volver a multiplexar.
- `/ext` es un segundo montaje opcional, solo para proporcionar su propio motor TTS.
- El contenedor se ejecuta como un UID no root, 1000. En Linux, si el directorio montado no es de escritura para ese UID, no se puede escribir la caché; agregue `--user "$(id -u):$(id -g)"` o `chown` al directorio. Docker Desktop en macOS y Windows se encarga de esto.

</details>

**Renderizar audio** requiere el motor TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (el paquete adicional `[render]`) y **FFmpeg** en PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Todo hasta el renderizado (analizar, asignar voces, compilar, revisar) funciona sin ellos. Ejecute `audiobooker diagnose` para verificar su configuración.

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
- **División de EPUB basada en el TOC:** límites y títulos de los capítulos del propio índice del libro.
- **DOCX** se divide según los estilos `Heading 1/2`/`Title` de Word; **PDF** detecta los encabezados (con una protección para PDF escaneados); configuración personalizada `--chapter-delimiter`.
- Limpieza inteligente del texto, eliminación compatible con Markdown, manejo de notas al pie y un **diccionario de pronunciación reutilizable** (`pronunciation import/export`, CSV/JSON, con paso de fonemas).

### Asignación de voces y atribución
- **Síntesis multivoz** con sugerencias de voz explicables y clasificadas, y un comando **`audition`** para comparar candidatos por personaje.
- **Asignación de voces interactiva**, **asignación masiva `cast-fill`** por género/rol, **preajustes de voces con nombre** reutilizables en toda una serie y **hojas de cálculo de voces en CSV** para colaboradores.
- **Detección de diálogos + atribución de hablantes** (opcional, co-referencia de **BookNLP**), **detección automática de alias** e **inferencia de emociones** con intensidad ajustable, estado de ánimo a nivel de escena y paquetes de configuración de género.

### Renderizado y salida
- **M4B** (marcadores de capítulo + portada incrustada + metadatos de la serie), **MP3**, **Opus**, **FLAC**, **WAV**; exportación por capítulo; exportación de **podcast/RSS**.
WAV no tiene un átomo de capítulo, por lo que un renderizado en WAV lo indica claramente en lugar de informar sobre un multiplexado de capítulo fallido; utilícelo cuando el audio vaya a un editor.
- **Masterización según las especificaciones de ACX** (`--acx`) + una **herramienta `master-check`** que informa si cumple o no con la sonoridad RMS, el pico y el nivel de ruido; clips de **masterización `sample`** para la venta al por menor.
- Renderizado paralelo, una **caché de renderizado persistente** con reanudación, progreso dinámico + ETA e informes de fallos estructurados.

### Flujo de trabajo y ecosistema
- **Pipeline `make`** de una sola ejecución · **archivo de configuración** (`.audiobookerrc` / `[tool.audiobooker]`) · **modo `--watch`** · **procesamiento por lotes basado en manifiesto** · finalización de la línea de comandos.
- **7 perfiles de idioma** (en/fr/de/es/ja/it/pt) · **motores TTS conectables** (`--engine`, puntos de entrada: proporcione Piper/Coqui/ElevenLabs) · script `--json` en la mayoría de los comandos · códigos de salida estructurados.

## Masterización según las especificaciones de audio de ACX

ACX publica un objetivo de audio preciso y medible. Es lo más parecido a un estándar de masterización que tiene el mundo de los audiolibros, y vale la pena alcanzarlo, independientemente de lo que haga con el archivo después.

| Requisito | Especificaciones de ACX | Qué hace `--acx` |
|---|---|---|
| Sonoridad | RMS entre **−23 y −18 dBFS** | two-pass `loudnorm` at −20 LUFS, which lands inside that window for speech |
| Pico | en o por debajo de **−3 dBFS** | aplicado en la misma pasada |
| Nivel de ruido | en o por debajo de **−60 dBFS** | medido e informado; nunca "corregido" en silencio |
| Formato | **44.1 kHz, 192 kbps CBR MP3** | establece la frecuencia de muestreo; agregue `--format mp3 --bitrate 192k` para el códec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Hay dos cosas que merecen una explicación sobre los números anteriores:

**`master-check` mide RMS no ponderado, no LUFS.** Son cantidades diferentes y ACX establece límites en la primera. La cifra de −20 LUFS es cómo la pasada de masterización *alcanza* ese valor; es lo que `ffmpeg loudnorm` puede apuntar, no lo que se comprueba después.

**El nivel de ruido se mide, no se corrige.** Es el requisito que falla con más frecuencia y proviene del audio de origen. Una herramienta que lo eliminara silenciosamente ocultaría el número que necesita ver.

### Dónde puede llegar realmente un audiolibro narrado por IA

Cumplir con las especificaciones no es lo mismo que ser aceptado, y vale la pena ser claro al respecto: **el flujo de envío estándar de ACX es para la narración humana.** Sus requisitos de abril de 2026 enumeran la síntesis de texto a voz no autorizada y las grabaciones de IA entre las cosas que no acepta, por lo que un título narrado por IA necesita una autorización previa de ACX en lugar de un envío ordinario.

Las rutas que sí aceptan la narración con IA, generalmente con la correspondiente indicación, incluyen:
**Virtual Voice** de Amazon, a través de KDP (distribución exclusiva de Amazon) y agregadores como **Spotify Audiobooks for Authors**, **Author's Republic** y **Kobo Writing Life**. La política de los minoristas en esta área cambia rápidamente; consulte los términos actuales usted mismo en lugar de confiar en este párrafo.

Por lo tanto: `--acx` se refiere al audio. Si un minorista acepta un título narrado con IA es su decisión, y no una característica del archivo que acaba de producir.

## Comandos de la línea de comandos

| Comando | Descripción |
|---------|-------------|
| `make <file>` | Proceso de una sola vez: nuevo → compilar → asignación automática → renderizar |
| `new <archivo\ | carpeta>` | Crear un proyecto a partir de EPUB/TXT/MD/PDF/DOCX o una carpeta |
| `from-stdin` | Crear un proyecto a partir de texto transmitido |
| `cast <char> <voice>` · `cast-interactive` | Asignar voces (o asignación guiada por personaje; también `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugerir / aplicar automáticamente / asignar voces de forma masiva |
| `cast-preset save\ | list\ | apply\ | delete` | Conjuntos de asignación reutilizables en diferentes libros |
| `cast-export` · `cast-import <file>` | Realizar un ciclo completo de la asignación como JSON/CSV: editar manualmente o reutilizar en diferentes ediciones |
| `audition <char>` | Voces candidatas clasificadas A/B para un personaje (`--render`) |
| `compile` | Detectar diálogos, asignar personajes, inferir emociones |
| `report` | Calidad de la compilación: tasa desconocida, líneas principales sin atribución, mezcla de emociones |
| `review-export` · `review-import <file>` | Revisión editable por humanos con ciclo completo |
| `render` | Renderizar el audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Muestra comercial maestra · verificar según las especificaciones de audio de ACX |
| `export-chapters` · `podcast` | Hoja de indicaciones de capítulos (ffmetadata/cue/json) · flujo RSS de podcast |
| `preview` · `batch` · `diagnose` | Clip de prueba de voz · lote/`--manifest` · verificación del entorno (se cierra con un código distinto de cero si el sistema no puede renderizar) |
| `load <file>` | Abrir un proyecto `.audiobooker` existente |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspeccionar y administrar |

Cada comando admite `-h/--help`. Banderas globales: `--silent`, `--debug`. **Códigos de salida:** `0` correcto · `1` error de usuario (incluido un libro que no se compilaría o una renderización rechazada porque la atribución falló) · `2` error en tiempo de ejecución · `3` parcial (lote).

## Configuración

Establecer valores predeterminados una sola vez en lugar de volver a pasar las banderas: `.audiobookerrc` (TOML) junto a su libro, o `[tool.audiobooker]` en `pyproject.toml`. La prioridad es **bandera de la línea de comandos > configuración del proyecto > configuración del usuario (`~/.audiobookerrc`) > valores predeterminados integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motores TTS (síntesis de voz) conectables

El motor predeterminado es `voice-soundboard`, pero el backend de síntesis se puede cambiar a través de los puntos de entrada de setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un complemento (`pip install audiobooker-piper`) se registra a sí mismo; no se requiere bifurcación.

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

`render(...)` y `compile(...)` aceptan una `engine=` inyectada (cualquier objeto que implemente el protocolo `TTSEngine`) y una función de devolución de llamada de progreso: incorpore audiobooker en una GUI o servicio.

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## Seguridad y alcance de los datos

- **Red:** ninguna: sin telemetría, sin almacenamiento de datos, sin credenciales. Lee sus archivos de libro, escribe audio + caché en sus directorios de salida.
- **Permisos:** acceso de lectura a las entradas, acceso de escritura a las salidas; FFmpeg opcional + un motor TTS en PATH.
- Consulte [SECURITY.md](SECURITY.md).

## Tabla de resultados

| Puerta de enlace | Estado |
|------|--------|
| A. Línea de base de seguridad | APROBADO |
| B. Manejo de errores | APROBADO |
| C. Documentación del operador | APROBADO |
| D. Higiene de envío | APROBADO |
| E. Identidad | APROBADO |

## Licencia

[MIT](LICENSE)

---

Creado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
