<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.png" alt="Audiobooker" width="500" />
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

O Audiobooker detecta diálogos, atribui uma voz distinta a cada personagem, infere emoções, permite que você revise e corrija tudo antes de renderizar um único segundo, e então otimiza o resultado para atender às especificações — para que a saída seja um audiolivro *pronto para ser submetido*, e não apenas áudio gerado.

## Instalar

**Instalação zero (Node):**
```bash
npx @mcptoolshop/audiobooker --help
```

**Python (CLI):**
```bash
pipx install audiobooker-ai            # isolated CLI
uvx audiobooker --help                 # zero-install trial
pip install "audiobooker-ai[render]"   # with the TTS voice engine
```

A **renderização de áudio** requer o motor TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (o extra `[render]`) e o **FFmpeg** no PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tudo até a renderização — análise, atribuição de vozes, compilação, revisão — funciona sem eles. Execute `audiobooker diagnose` para verificar sua configuração.

<details>
<summary>From source</summary>

```bash
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e '.[render]'
```
</details>

## Início rápido

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

## Recursos

### Entrada e estrutura
- **EPUB, TXT, Markdown, PDF, DOCX** ou uma **pasta de arquivos por capítulo** (Scrivener/Obsidian/ficção serializada).
- **Divisão de EPUB baseada no TOC** — limites e títulos dos capítulos retirados da própria tabela de conteúdos do livro.
- **DOCX** divide com base nos estilos Word `Heading 1/2`/`Title`; **PDF** detecta cabeçalhos (com uma proteção para PDFs digitalizados); delimitador de capítulo personalizado `--chapter-delimiter`.
- Limpeza inteligente de texto, remoção compatível com Markdown, tratamento de notas de rodapé e um **lexicão de pronúncia reutilizável** (`pronunciation import/export`, CSV/JSON, com passagem de fonemas).

### Atribuição de vozes
- **Síntese multi-voz** com sugestões de voz explicáveis e classificadas e um comando **`audition`** para testar candidatos por personagem.
- **Atribuição de vozes interativa**, **atribuição em massa `cast-fill`** por gênero/papel, **predefinições de elenco nomeadas** reutilizáveis em uma série e **planilhas CSV de elenco** para colaboradores.
- **Detecção de diálogo + atribuição de falantes** (opcionalmente com co-referência **BookNLP**), **descoberta automática de alias** e **inferência de emoção** com intensidade ajustável, humor em nível de cena e pacotes de predefinições de gênero.

### Renderização e saída
- **M4B** (marcadores de capítulo + capa incorporada + metadados da série), **MP3**, **Opus**, **FLAC**; exportação por capítulo; exportação de feed **podcast/RSS**.
- **Masterização ACX/Audible** (`--acx`) + um **`master-check`** que relata PASS/FAIL em relação ao volume, pico e ruído de fundo; clipes de amostra para varejo **`sample`**.
- Renderização paralela, um **cache de renderização persistente** com retomada, progresso dinâmico + ETA e relatórios estruturados de falhas.

### Fluxo de trabalho e ecossistema
- **`make`** pipeline único · **arquivo de configuração** (`.audiobookerrc` / `[tool.audiobooker]`) · modo **`--watch`** · **lote baseado em manifesto** · preenchimento automático do shell.
- **7 perfis de idioma** (en/fr/de/es/ja/it/pt) · **motores TTS plugáveis** (`--engine`, pontos de entrada — traga Piper/Coqui/ElevenLabs) · scriptável `--json` na maioria dos comandos · códigos de saída estruturados.

## Publicação no ACX / Audible

O Audiobooker tem como alvo as especificações mensuráveis de envio do ACX diretamente:

```bash
audiobooker render --acx               # loudnorm -20 LUFS, -3 dBTP peak, 44.1k, 192k
audiobooker master-check book.m4b      # PASS/FAIL: RMS [-23,-18], peak <= -3 dB, floor <= -60 dB
audiobooker sample --duration 180      # a mastered retail sample clip
```

`master-check` verifica os requisitos mensuráveis (volume, pico, ruído de fundo). O ACX também possui critérios subjetivos/de controle de qualidade que uma ferramenta não pode certificar — mas você nunca mais será rejeitado por uma violação de volume.

## Comandos CLI

| Comando | Descrição |
|---------|-------------|
| `make <file>` | Pipeline único: novo → compilar → atribuição automática de vozes → renderizar |
| `new <arquivo\ | pasta>` | Crie um projeto a partir de EPUB/TXT/MD/PDF/DOCX ou uma pasta |
| `from-stdin` | Crie um projeto a partir de texto transmitido por pipe |
| `cast <personagem> <voz>` · `cast --interactive` | Atribua vozes (ou atribuição guiada por falante) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugira / aplique automaticamente / atribua em massa as vozes |
| `cast-preset save\ | list\ | apply\ | delete` | Predefinições de elenco reutilizáveis em livros |
| `audition <char>` | Teste A/B das vozes candidatas para um personagem (`--render`) |
| `compile` | Detecte diálogos, atribua falantes, infira emoção |
| `report` | Qualidade da compilação: taxa desconhecida, principais linhas não atribuídas, mistura de emoções |
| `review-export` · `review-import <arquivo>` | Ciclo de revisão editável por humanos |
| `render` | Renderize o audiolivro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <arquivo>` | Amostra de masterização para varejo · Verificação de conformidade com o ACX |
| `export-chapters` · `podcast` | Folha de dicas do capítulo (ffmetadata/cue/json) · feed RSS de podcast |
| `preview` · `batch` · `diagnose` | Clipe de teste de voz · lote / `--manifest` · verificação do ambiente |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecione e gerencie |

Cada comando suporta `-h/--help`. Flags globais: `--silent`, `--debug`. **Códigos de saída:** `0` ok · `1` erro do usuário · `2` erro em tempo de execução · `3` parcial (lote).

## Configuração

Defina os padrões uma vez, em vez de repassar as flags — `.audiobookerrc` (TOML) ao lado do seu livro ou `[tool.audiobooker]` em `pyproject.toml`. A precedência é **flag CLI > configuração do projeto > configuração do usuário (`~/.audiobookerrc`) > padrões integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Motores TTS plugáveis

O motor padrão é `voice-soundboard`, mas o backend de síntese pode ser alterado por meio de pontos de entrada setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Um plugin (`pip install audiobooker-piper`) se registra; não é necessário bifurcar.

## API Python

```python
from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")   # or from_docx / from_pdf / from_folder / from_string
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()                                     # dialogue, speakers, emotion
project.render("mybook.m4b")                          # resumes from cache on re-run
project.save("mybook.audiobooker")
```

`render(...)` e `compile(...)` aceitam um `engine=` injetado (qualquer objeto que implemente o protocolo `TTSEngine`) e uma função de retorno de progresso — incorpore o Audiobooker em uma GUI ou serviço.

## Arquitetura

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

## Segurança e âmbito dos dados

- **Rede:** nenhuma — sem telemetria, sem armazenamento de dados, sem credenciais. Lê os seus arquivos de livro, grava áudio + cache nos diretórios de saída.
- **Permissões:** acesso de leitura aos arquivos de entrada, acesso de escrita aos arquivos de saída; FFmpeg opcional + um motor TTS no PATH.
- Consulte [SECURITY.md](SECURITY.md).

## Quadro de avaliação

| Barreira | Estado |
|------|--------|
| A. Linha de base de segurança | APROVADO |
| B. Tratamento de erros | APROVADO |
| C. Documentação para operadores | APROVADO |
| D. Boas práticas de lançamento | APROVADO |
| E. Identidade | APROVADO |

## Licença

[MIT](LICENSE)

---

Criado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
