<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
</p>

<h1 align="center">Audiobooker</h1>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/audiobooker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## Características

- **Síntesis de voz múltiple**: Asigna voces únicas a cada personaje.
- **Detección de diálogo**: Identifica automáticamente el diálogo citado frente a la narración.
- **Inferencia de emociones**: Etiquetado de emociones basado en reglas y léxico, con un nivel de confianza configurable.
- **Sugerencias de voz**: Recomendaciones de voz explicables y clasificadas para cada hablante.
- **Integración con BookNLP**: Resolución opcional de referencias a hablantes mediante procesamiento del lenguaje natural (PNL).
- **Revisión antes de la renderización**: Formato de revisión editable por humanos para corregir las atribuciones.
- **Caché de renderización persistente**: Permite reanudar la renderización interrumpida sin volver a sintetizar los capítulos ya completados.
- **Progreso y ETA dinámicos**: Estado de renderización en tiempo real con tiempo estimado de finalización.
- **Informes de errores**: Diagnósticos estructurados en formato JSON sobre los errores de renderización.
- **Perfiles de idioma**: Abstracción de reglas específicas del idioma, extensible.
- **Salida en formato M4B**: Formato profesional para audiolibros con navegación por capítulos.
- **Persistencia del proyecto**: Guarda y permite reanudar las sesiones de renderización.

## Instalación

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

## Características Opcionales

| Función | Instalar | Configuración |
| --------- | --------- | -------- |
| **TTS rendering** | `pip install audiobooker-ai[render]` o instala voice-soundboard | Requerido para `render` |
| **Resolución de hablantes de BookNLP** | `pip install audiobooker-ai[nlp]` | `--booknlp on` |off\|auto` |
| **FFmpeg audio assembly** | Paquete del sistema (winget/brew/apt) | Requerido para la salida en formato M4B |

## Cómo empezar

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

## Flujo de Revisión

El flujo de revisión le permite inspeccionar y corregir el script compilado antes de la renderización:

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

**Formato del archivo de revisión:**
- `=== Título del Capítulo ===` - Marcadores de capítulo
- `@Hablante` o `@Hablante (emoción)` - Etiquetas de hablante
- `# comentario` - Comentarios (ignorados durante la importación)
- Elimine bloques para eliminar las expresiones no deseadas.
- Cambie `@Desconocido` a `@NombreReal` para corregir la atribución.

## API de Python

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

## Comandos de la Interfaz de Línea de Comandos (CLI)

| Comando | Descripción |
| --------- | ------------- |
| `audiobooker new <file>` | Crear proyecto desde EPUB/TXT |
| `audiobooker cast <char> <voice>` | Asignar voz a un personaje |
| `audiobooker cast-suggest` | Sugerir voces para hablantes sin voz asignada |
| `audiobooker cast-apply --auto` | Aplicar automáticamente las mejores sugerencias de voz |
| `audiobooker compile` | Compilar capítulos en expresiones |
| `audiobooker review-export` | Exportar el script para revisión humana |
| `audiobooker review-import <file>` | Importar el archivo de revisión editado |
| `audiobooker render` | Renderizar el audiolibro |
| `audiobooker info` | Mostrar información del proyecto |
| `audiobooker voices` | Listar voces disponibles |
| `audiobooker chapters` | Listar capítulos |
| `audiobooker speakers` | Listar hablantes detectados |
| `audiobooker from-stdin` | Crear proyecto desde texto en la entrada estándar |

## Arquitectura

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

**Flujo:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Solución de Problemas

**Informe de error de renderización**: En caso de cualquier error de renderización, Audiobooker escribe `render_failure_report.json` en el directorio de caché. Este archivo contiene:
- Índice y título del capítulo donde ocurrió el error.
- Índice de la expresión, hablante y vista previa del texto.
- ID de la voz y la emoción que se estaban sintetizando.
- Rastreo completo de la pila de llamadas.
- Rutas del caché y del manifiesto.

**Problemas comunes de FFmpeg**:
- `FFmpeg no encontrado`: Instale a través de su administrador de paquetes (winget/brew/apt).
- `Error al incrustar el capítulo`: Audiobooker recurre a M4A sin marcadores de capítulo.
- Calidad de audio: El valor predeterminado es AAC a 128 kbps a 24 kHz (configurable en ProjectConfig).

**Problemas del caché**:
- `audiobooker render --clean-cache` — Limpia todo el caché de audio y vuelve a renderizar.
- `audiobooker render --no-resume` — Ignora el caché para esta ejecución.
- `audiobooker render --from-chapter 5` — Comienza desde un capítulo específico.

## Hoja de ruta

- [x] v0.1.0: Canalización principal (análisis, conversión, compilación, renderizado).
- [x] v0.2.0: Flujo de trabajo de revisión antes del renderizado.
- [x] v0.3.0: Caché de renderizado persistente + función de reanudación.
- [x] v0.4.0: Perfiles de idioma + mayor flexibilidad en la entrada de datos.
- [x] v0.5.0: Integración de BookNLP, inferencia de emociones, sugerencias de voz, mejoras en la experiencia de usuario.

## Licencia

MIT
