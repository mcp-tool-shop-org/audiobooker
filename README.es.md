<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
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

## Características

### Entrada y Análisis
- **Análisis de fuentes EPUB / TXT / Markdown** con detección de capítulos.
- **Soporte para PDF** (opcional): Extracción de texto de archivos PDF a través de PyMuPDF (`pip install -e '.[pdf]'`)
- **Normalización de texto**: Eliminación de comillas especiales, normalización de espacios en blanco, limpieza de texto configurable.
- **Sobrescrituras de pronunciación**: Mapeos personalizados de palabras a pronunciaciones para nombres propios y jerga.
- **Manejo de notas al pie**: Comportamiento de notas al pie configurable (`inline`, `end` o `skip`).

### Diálogo y Atribución
- **Detección de diálogo**: Identifica automáticamente el diálogo citado frente a la narración.
- **Detección avanzada de diálogo**: Seguimiento de turnos de conversación para escenas con múltiples hablantes.
- **Indicaciones escénicas**: Detecta y gestiona las indicaciones escénicas entre corchetes en los guiones.
- **Integración con BookNLP**: Resolución opcional de referencias a hablantes basada en procesamiento del lenguaje natural.
- **Alias de personajes**: Asigna nombres alternativos a un personaje principal.

### Voz y Actuación
- **Síntesis de voz múltiple**: Asigna voces únicas a cada personaje.
- **Sugerencias de voz**: Recomendaciones de voz explicables y clasificadas por hablante.
- **Inferencia de emociones**: Etiquetado de emociones basado en reglas y léxico, con un nivel de confianza configurable.
- **Parámetros de voz por personaje**: Velocidad (0.5--2.0) y emoción por hablante.
- **Preprocesamiento SSML**: Soporte para el Lenguaje de Marcado de Síntesis de Voz para un control más preciso.

### Renderizado y Salida
- **Renderizado paralelo**: Renderizado de capítulos con múltiples procesos utilizando `--jobs N`.
- **Múltiples formatos de salida**: MP3, M4B, WAV, OGG, FLAC.
- **Normalización de audio**: Niveles de volumen consistentes en todos los capítulos.
- **Incrustación de portada**: Extraída de EPUB o proporcionada por el usuario, incrustada en la salida M4B.
- **Caché de renderizado persistente**: Reanuda los renderizados fallidos sin volver a sintetizar los capítulos completados.
- **Progreso y ETA dinámicos**: Estado de renderizado en tiempo real con tiempo estimado de finalización.
- **Informes de errores**: Diagnósticos estructurados en formato JSON sobre los errores de renderizado.

### Idioma y Localización
- **5 perfiles de idioma**: Inglés, francés, alemán, español, japonés (`--lang en|fr|de|es|ja`).
- **Sistema de perfiles extensible**: Agrega nuevos idiomas a través de la abstracción `LanguageProfile`.

### Flujo de Trabajo y Productividad
- **Revisión antes del renderizado**: Formato de revisión editable por humanos para corregir las atribuciones.
- **Diferencia de proyectos**: Compara dos versiones de un proyecto para ver los cambios en los capítulos y las líneas.
- **Procesamiento por lotes**: Procesa múltiples libros en una sola ejecución con `audiobooker batch`.
- **Modo de prueba**: Previsualiza las operaciones de renderizado o procesamiento por lotes sin ejecutarlas (`--dry-run`).
- **Audición de voz**: Renderiza una muestra corta para validar las asignaciones de voz (`audiobooker preview`).
- **Gestión de capítulos**: Combina, divide y excluye capítulos antes del renderizado.
- **Gestión de emociones**: Lista y sobrescribe las emociones por línea después de la compilación.
- **Notificaciones de escritorio**: Recibe notificaciones cuando finalizan los renderizados largos.
- **Persistencia del proyecto**: Guarda/reanuda las sesiones de renderizado.

## Instalación

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

## Características Opcionales

| Característica | Instalar | Configuración |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` o instala voice-soundboard | Requerido para `render` |
| **Resolución de hablantes de BookNLP** | `pip install -e '.[nlp]'` | `--booknlp on\ | off\ | auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | Detectado automáticamente en tiempo de ejecución |
| **FFmpeg audio assembly** | Paquete del sistema (winget/brew/apt) | Requerido para la salida M4B |

## Inicio Rápido

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

## Flujo de Trabajo de Revisión

El flujo de trabajo de revisión te permite inspeccionar y corregir el guion compilado antes del renderizado:

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
- `=== Título del capítulo ===` - Marcadores de capítulo
- `@Orador` o `@Orador (emoción)` - Etiquetas de orador
- `# comentario` - Comentarios (se ignoran al importar)
- Elimine los bloques para eliminar las frases no deseadas.
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

## Comandos de la línea de comandos (CLI)

| Comando | Descripción |
|---------|-------------|
| `audiobooker new <file>` | Crear proyecto a partir de EPUB/TXT/MD/PDF |
| `audiobooker load <project>` | Cargar proyecto existente `.audiobooker` |
| `audiobooker from-stdin` | Crear proyecto a partir de texto en flujo (pipe) |
| `audiobooker cast <char> <voice>` | Asignar voz a un personaje |
| `audiobooker cast-suggest` | Sugerir voces para oradores sin voz asignada |
| `audiobooker cast-apply --auto` | Aplicar automáticamente las mejores sugerencias de voz |
| `audiobooker compile` | Compilar capítulos en frases |
| `audiobooker review-export` | Exportar el guion para revisión humana |
| `audiobooker review-import <file>` | Importar el archivo de revisión editado |
| `audiobooker render` | Generar el audiolibro (soporta `--dry-run`, `--jobs N`, `--format`, `--cover`) |
| `audiobooker preview` | Generar una muestra corta para la validación de la voz (`--chapter N`, `--seconds S`) |
| `audiobooker batch <files...>` | Procesar por lotes múltiples libros (soporta `--dry-run`) |
| `audiobooker info` | Mostrar información del proyecto |
| `audiobooker status` | Mostrar el estado de la generación/caché |
| `audiobooker voices` | Listar voces disponibles (soporta `--gender`, `--search`) |
| `audiobooker chapters` | Listar títulos y índices de los capítulos |
| `audiobooker speakers` | Listar oradores detectados |
| `audiobooker cache info` | `clean` | `clean-failed` | Administrar el caché de generación |
| `audiobooker diagnose` | Verificar el entorno (dependencias, motor de voz, FFmpeg) |

## Referencia completa de la línea de comandos

Cada comando soporta `-h` / `--help` para obtener información detallada sobre su uso.  Flags principales:

- **`new`**: `-o <proyecto>`, `--lang <código>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <emoción>`, `--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`, `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`, `--jobs N`, `-o <ruta>`, `--format mp3|m4b|wav|ogg|flac`, `--cover <imagen>`
- **`preview`**: `--chapter N`, `--seconds S`, `-o <ruta>`
- **`batch`**: `--dry-run`, `--jobs N`, `--format <formato>`, `--lang <código>`, `--output-dir <directorio>`
- **`voices`**: `--gender <masculino|femenino>`, `--search <consulta>`
- **`info`**: `--verbose`

## Arquitectura

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

**Flujo:**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Problemas comunes

| Problema | Solución |
|---------|-----|
| **FFmpeg not found** | Instale a través de su administrador de paquetes: `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `apt install ffmpeg` (Linux). FFmpeg debe estar en la variable PATH. |
| **No se ha instalado voice-soundboard** | Clone e instale el repositorio relacionado: `git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`. O instale con `pip install -e '.[render]'`. |
| **Errores de BookNLP o inicio lento** | BookNLP es opcional. Si no necesita la resolución de oradores mediante NLP, establezca `--booknlp off` o déjelo en `auto` (recaída segura). Instale con `pip install -e '.[nlp]'` solo si es necesario. |

Consulte el [manual](docs/handbook.md#15-troubleshooting) para obtener una guía completa de solución de problemas.

## Solución de problemas

**Informe de fallo de generación**: En caso de cualquier error de generación, Audiobooker escribe `render_failure_report.json` en el directorio del caché. Este archivo contiene:
- Índice y título del capítulo donde ocurrió el error
- Índice de la frase, orador y vista previa del texto
- ID de la voz y emoción que se estaban sintetizando
- Trazado de pila completo
- Rutas del caché y del manifiesto

**Problemas comunes de FFmpeg**:
- `FFmpeg no encontrado`: Instale a través de su administrador de paquetes (winget/brew/apt)
- `Error al incrustar el capítulo`: Audiobooker recurre a M4A sin marcadores de capítulo
- Calidad de audio: El valor predeterminado es AAC de 128 kbps a 24 kHz (configurable en ProjectConfig)

**Problemas de caché:**
- `audiobooker render --clean-cache` — Borra toda la caché de audio y vuelve a renderizar.
- `audiobooker render --no-resume` — Ignora la caché solo para esta ejecución.
- `audiobooker render --from-chapter 5` — Comienza desde un capítulo específico.

## Hoja de ruta

- [x] Canal de procesamiento principal (análisis, conversión, compilación, renderizado)
- [x] Flujo de trabajo de revisión antes del renderizado
- [x] Caché de renderizado persistente + reanudación
- [x] Perfiles de idioma + flexibilidad de entrada
- [x] BookNLP, inferencia de emociones, sugerencias de voz, mejoras de la experiencia de usuario
- [x] v1.0.0 - Lanzamiento de producción

## Seguridad y alcance de los datos

- **Datos accedidos:** Lee archivos EPUB/TXT del sistema de archivos local. Escribe archivos de audio y manifiestos de caché en directorios de salida. Opcionalmente, utiliza una tabla de sonidos para la síntesis de voz y FFmpeg para la combinación de audio.
- **Datos NO accedidos:** No hay solicitudes de red. No hay telemetría. No hay almacenamiento de datos del usuario. No hay credenciales ni tokens.
- **Permisos requeridos:** Acceso de lectura a los archivos de libro de entrada. Acceso de escritura a los directorios de salida. Opcional: FFmpeg en la ruta del sistema.

## Cuadro de evaluación

| Puerta | Estado |
|------|--------|
| A. Línea base de seguridad | PASADO |
| B. Manejo de errores | PASADO |
| C. Documentación para operadores | PASADO |
| D. Higiene para el lanzamiento | PASADO |
| E. Identidad | PASADO |

## Licencia

[MIT](LICENSE)

---

Creado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
