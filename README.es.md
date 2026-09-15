<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Audiobooker detecta los diálogos, asigna una voz distinta a cada personaje, infiere las emociones, permite revisar y corregir todo antes de renderizar un solo segundo, y luego optimiza el resultado para cumplir con las especificaciones de audio de ACX, de modo que el resultado sea un audiolibro *terminado*, y no solo audio generado.

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
Este montaje es suficiente, y `--rm` es seguro: la caché de renderizado se guarda junto al archivo del proyecto, no en un directorio de inicio, por lo que una nueva ejecución **reanudará** el proceso en lugar de volver a sintetizar el libro.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Etiquetado `latest`, `3`, `3.0` y la versión exacta, publicado en GHCR en cada versión.
- El punto de entrada **es** `audiobooker`, por lo que pase el subcomando inmediatamente después del nombre de la imagen; no repita el nombre del programa.
- La caché se guarda en `<book-dir>/.audiobooker/cache`. Por eso, un único montaje cubre la persistencia; perderlo significa tener que volver a pagar por toda la ejecución de TTS, no solo por volver a mezclar.
- `/ext` es un segundo montaje opcional, solo para proporcionar su propio paquete TTS.
- El contenedor se ejecuta como un UID no root, 1000. En Linux, si el directorio montado no es de escritura para ese UID, no se puede escribir la caché; agregue `--user "$(id -u):$(id -g)"` o `chown` al directorio. Docker Desktop en macOS y Windows se encarga de esto.

</details>

**Renderizar audio** requiere el motor TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (el paquete adicional `[render]`) y **FFmpeg** en PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Todo lo que precede al renderizado (analizar, asignar voces, compilar, revisar) funciona sin ellos. Ejecute `audiobooker diagnose` para verificar su configuración.

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

Cada uno de estos es un caso en el que la versión 2.x aceptaba algo y hacía lo incorrecto en silencio. La versión 3.0 se niega en su lugar. Detalles completos en el [CHANGELOG](CHANGELOG.md).

- **La primera renderización vuelve a renderizar cada capítulo, una vez.** Tres entradas que cambian el audio (preajuste de emoción, intensidad de la expresión, velocidad/tono/énfasis por personaje) faltaban en la clave de la caché, por lo que cambiar el preajuste informaba de "En caché" y devolvía el audio antiguo. Ahora están en la clave, y una entrada de caché de la versión 2.x no puede demostrar qué la produjo.
- **`--format m4a` ya no es una opción para todo el libro.** Siempre significó un archivo por capítulo; solicitar un libro completo en `m4a` anteriormente producía un único archivo M4B con un nombre `.m4a`. Sigue siendo válido en `podcast --format`.
- **`render` se niega a procesar un libro cuyo atributo indica `FAILED`** en lugar de dedicar una ejecución de TTS a ello. `--force` anula esta acción. Ejecute `audiobooker report` para ver qué líneas están causando el problema.
- **`make` se niega cuando el archivo del proyecto ya existe.** Antes sobrescribía las voces asignadas manualmente, las modificaciones de pronunciación y los títulos editados con un nuevo análisis automático. Pase `--overwrite-project` si es lo que desea.
- **`compile()` genera un error cuando todos los capítulos fallan** en lugar de devolver `None`, como lo hace una ejecución correcta. Si lo llama desde Python, ahora puede generar una excepción.

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
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## Características

### Entrada y estructura
- **EPUB, TXT, Markdown, PDF, DOCX** o una **carpeta de archivos por capítulo** (Scrivener/Obsidian/ficción serializada).
- **División de EPUB basada en el TOC** (tabla de contenidos): límites y títulos de los capítulos a partir de la propia tabla de contenidos del libro.
- **DOCX** se divide según los estilos `Heading 1/2`/`Title` de Word; **PDF** detecta los encabezados (con una protección para PDF escaneados); configuración personalizada `--chapter-delimiter`.
- Limpieza inteligente del texto, eliminación compatible con Markdown, manejo de notas al pie y un **diccionario de pronunciación reutilizable** (`pronunciation import/export`, CSV/JSON, con paso de fonemas).

### Asignación de voces y atribución
- **Síntesis multivoz** con sugerencias de voz explicables y clasificadas, y un comando **`audition`** para comparar candidatos por personaje.
- **Asignación de voces interactiva**, **asignación masiva `cast-fill`** por género/rol, **preajustes de asignación de voces con nombre** reutilizables en toda una serie y **hojas de cálculo de asignación de voces en CSV** para colaboradores.
- **Detección de diálogos + atribución de hablantes** (opcionalmente con co-referencia de **BookNLP**), **detección automática de alias** e **inferencia de emociones** con intensidad ajustable, estado de ánimo a nivel de escena y paquetes de preajustes de género.
- **Atribución que puede auditar.** Cada línea registra *cómo* se decidió el hablante: una etiqueta de discurso, una modificación en línea, co-referencia, su propia corrección o una simple suposición de turno alternado, y `report` cuenta las suposiciones por separado de las líneas que no pudo atribuir en absoluto. Una suposición no puede mejorar la puntuación, por lo que el número disminuye cuando la atribución empeora, que es la única dirección que es útil.

### Renderizado y salida
- **M4B** (marcadores de capítulo + portada incrustada + metadatos de la serie), **MP3**, **Opus**, **FLAC**, **WAV**; exportación por capítulo; exportación de **podcast/RSS**.
WAV no tiene un átomo de capítulo, por lo que un renderizado WAV lo indica claramente en lugar de informar de un error en la mezcla del capítulo; utilícelo cuando el audio vaya a un editor.
- **Masterización según las especificaciones de audio de ACX** (`--acx`) + una herramienta **`master-check`** que informa de PASS/FAIL en cuanto a la sonoridad RMS, el pico y el ruido de fondo; clips de **`sample`** para la venta al por menor.
- Renderizado paralelo, una **caché de renderizado persistente** con reanudación, progreso dinámico + ETA e informes de errores estructurados.
La clave de la caché cubre todo lo que cambia el audio: texto, asignación de voces, voces, motor y versión, perfil, preajuste de emoción e intensidad, por lo que un nuevo renderizado que indica "En caché" significa que es así. Una **caché por expresión** opcional (`utterance_cache`) limita un nuevo renderizado a las líneas que realmente editó.

### Flujo de trabajo y ecosistema
- **`make`** proceso de un solo paso · **archivo de configuración** (`.audiobookerrc` / `[tool.audiobooker]`) · **modo `--watch`** · **proceso por lotes basado en manifiesto** · finalización de la línea de comandos.
- **7 perfiles de idioma** (en/fr/de/es/ja/it/pt) · **motores TTS conectables** (`--engine`, puntos de entrada: proporcione Piper/Coqui/ElevenLabs) · scriptable `--json` en la mayoría de los comandos · códigos de salida estructurados.

## Masterización según las especificaciones de audio de ACX

ACX publica una especificación de audio precisa y medible. Es lo más parecido a un estándar de masterización que existe en el mundo de los audiolibros, y vale la pena cumplirla, sea lo que sea que hagas con el archivo después.

| Requisito | Especificación de ACX | Qué hace `--acx` |
|---|---|---|
| Intensidad sonora | RMS entre **−23 y −18 dBFS** | proceso de dos pasos de `loudnorm` a −20 LUFS, lo que se ajusta a ese rango para el habla |
| Pico | en o por debajo de **−3 dBFS** | se aplica en el mismo paso |
| Nivel de ruido | en o por debajo de **−60 dBFS** | se mide y se informa; nunca se "corrige" en silencio |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | establece la frecuencia de muestreo; agrega `--format mp3 --bitrate 192k` para el códec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Dos cosas que merecen los números anteriores:

**`master-check` mide el RMS sin ponderar, no los LUFS.** Son cantidades diferentes y ACX se basa en la primera. La cifra de −20 LUFS es cómo el proceso de masterización *alcanza* ese valor; es el objetivo que puede establecer `ffmpeg loudnorm`, no lo que se comprueba después.

**El nivel de ruido se mide, no se corrige.** Es el requisito que con mayor frecuencia no se cumple, y proviene del audio de origen. Una herramienta que lo redujera en silencio estaría ocultando el número que necesitas ver.

### Dónde un audiolibro narrado por IA puede llegar

Cumplir con la especificación no es lo mismo que ser aceptado, y vale la pena ser claro al respecto: **el flujo de envío estándar de ACX es para la narración humana.** Su lista de requisitos de abril de 2026 incluye la conversión de texto a voz no autorizada y las grabaciones de IA entre las cosas que no acepta, por lo que un título narrado por IA necesita una autorización previa de ACX en lugar de una presentación ordinaria.

Las vías que sí aceptan la narración de IA, generalmente con una declaración, incluyen el **Virtual Voice** de Amazon a través de KDP (distribución solo en Amazon) y agregadores como **Spotify Audiobooks for Authors**, **Author's Republic** y **Kobo Writing Life**. La política de los minoristas en esta área cambia rápidamente; verifica los términos actuales tú mismo en lugar de confiar en este párrafo.

Por lo tanto: `--acx` se refiere al audio. Si un minorista acepta un título narrado por IA es su decisión, no una propiedad del archivo que acabas de producir.

## Comandos de la CLI

| Comando | Descripción |
|---------|-------------|
| `make <file>` | Un solo paso: nuevo → compilar → asignar automáticamente → renderizar |
| `new <archivo\ | carpeta>` | Crea un proyecto a partir de EPUB/TXT/MD/PDF/DOCX o una carpeta |
| `from-stdin` | Crea un proyecto a partir de texto canalizado |
| `cast <char> <voice>` · `cast-interactive` | Asigna voces (o asignación guiada por personaje; también `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugiere / aplica automáticamente / asigna en masa voces |
| `cast-preset save\ | list\ | apply\ | delete` | Presets de asignación reutilizables entre libros |
| `cast-export` · `cast-import <file>` | Transfiere la asignación como JSON/CSV: edítala manualmente o reutilízala entre ediciones |
| `audition <char>` | Voces candidatas clasificadas A/B para un personaje (`--render`) |
| `compile` | Detecta diálogos, atribuye a los hablantes, infiere la emoción |
| `report` | Calidad de la compilación: tasa de no atribución, tasa estimada, líneas peores, mezcla de emociones |
| `review-export` · `review-import <file>` | Revisión editable por humanos |
| `render` | Renderiza el audiolibro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Muestra de venta maestra · verifica que cumpla con la especificación de audio de ACX |
| `export-chapters` · `podcast` | Hoja de indicaciones de capítulos (ffmetadata/cue/json) · flujo RSS de podcast |
| `preview` · `batch` · `diagnose` | Clip de control de calidad de la voz · lote/`--manifest` · verificación del entorno (se cierra con un código distinto de cero cuando la caja no puede renderizar) |
| `load <file>` | Abre un proyecto `.audiobooker` existente |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecciona y administra |

Cada comando admite `-h/--help`. Banderas globales: `--silent`, `--debug`. **Códigos de salida:** `0` correcto · `1` error de usuario (incluido un libro que no se compilaría, o una renderización rechazada porque falló la atribución) · `2` tiempo de ejecución · `3` parcial (lote).

## Configuración

Establece los valores predeterminados una vez en lugar de volver a pasar las banderas: `.audiobookerrc` (TOML) junto a tu libro, o `[tool.audiobooker]` en `pyproject.toml`. La prioridad es **bandera de la CLI > configuración del proyecto > configuración del usuario (`~/.audiobookerrc`) > valores predeterminados integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motores TTS conectables

El motor predeterminado es `voice-soundboard`, pero el backend de síntesis se puede cambiar mediante puntos de entrada de setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Un complemento (`pip install audiobooker-piper`) se registra; no se requiere una bifurcación.

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

`render(...)` y `compile(...)` aceptan un `engine=` inyectado (cualquier objeto que implemente el protocolo `TTSEngine`) y una función de devolución de llamada de progreso: integra audiobooker en una GUI o servicio.

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

- **Red:** ninguna: sin telemetría, sin almacenamiento de datos, sin credenciales. Lee tus archivos de libro, escribe audio + caché en tus directorios de salida.
- **Permisos:** acceso de lectura a las entradas, acceso de escritura a las salidas; FFmpeg y un motor TTS en PATH son opcionales.
- Consulta [SECURITY.md](SECURITY.md).

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
