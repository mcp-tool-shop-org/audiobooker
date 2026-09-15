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

O Audiobooker detecta diálogos, atribui uma voz distinta a cada personagem, infere emoções, permite que você revise e corrija tudo antes que um único segundo seja renderizado e, em seguida, otimiza o resultado para as especificações de áudio da ACX — para que o resultado seja um audiolivro *finalizado*, e não apenas áudio gerado.

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
- **Divisão de EPUB baseada no TOC** — limites e títulos de capítulos da própria tabela de conteúdos do livro.
- **DOCX** divide-se com base nos estilos Word `Heading 1/2`/`Title`; **PDF** detecta títulos (com uma proteção para PDFs digitalizados); personalização `--chapter-delimiter`.
- Limpeza inteligente de texto, remoção com reconhecimento de Markdown, tratamento de notas de rodapé e um **lexicão de pronúncia reutilizável** (`pronunciation import/export`, CSV/JSON, com passagem de fonemas).

### Atribuição de vozes
- **Síntese de várias vozes** com sugestões de voz explicáveis e classificadas e um comando **`audition`** para comparar candidatos por personagem.
- **Atribuição de vozes interativa**, **atribuição em massa `cast-fill`** por gênero/função, **predefinições de elenco nomeadas** reutilizáveis em uma série e **planilhas de elenco CSV** para colaboradores.
- **Detecção de diálogo + atribuição de falantes** (opcionalmente com co-referência **BookNLP**), **descoberta automática de alias** e **inferência de emoção** com intensidade ajustável, humor em nível de cena e pacotes de predefinições de gênero.

### Renderização e saída
- **M4B** (marcadores de capítulo + capa incorporada + metadados da série), **MP3**, **Opus**, **FLAC**, **WAV**; exportação por capítulo; exportação de feed **podcast/RSS**.
O WAV não tem átomo de capítulo, portanto, a renderização em WAV indica isso claramente, em vez de relatar uma falha na multiplexação do capítulo — use-o quando o áudio for para um editor.
- **Masterização com as especificações da ACX** (`--acx`) + um **`master-check`** que relata PASS/FAIL no volume RMS, pico e ruído de fundo; clipes de varejo **`sample`**.
- Renderização paralela, um **cache de renderização persistente** com retomada, progresso dinâmico + ETA e relatórios de falha estruturados.

### Fluxo de trabalho e ecossistema
- **`make`** pipeline de execução única · **arquivo de configuração** (`.audiobookerrc` / `[tool.audiobooker]`) · **modo `--watch`** · **lote baseado em manifesto** · conclusão de shell.
- **7 perfis de idioma** (en/fr/de/es/ja/it/pt) · **motores TTS plugáveis** (`--engine`, pontos de entrada — traga Piper/Coqui/ElevenLabs) · script `--json` na maioria dos comandos · códigos de saída estruturados.

## Masterização para as especificações de áudio da ACX

A ACX publica um alvo de áudio preciso e mensurável. É o mais próximo que o mundo dos audiolivros tem de um padrão de masterização, e vale a pena atingir, independentemente do que você faça com o arquivo depois.

| Requisito | Especificação da ACX | O que `--acx` faz |
|---|---|---|
| Volume | RMS entre **−23 e −18 dBFS** | passagem dupla `loudnorm` em −20 LUFS, que se encaixa nessa faixa para a fala |
| Pico | em ou abaixo de **−3 dBFS** | aplicado na mesma passagem |
| Ruído de fundo | em ou abaixo de **−60 dBFS** | medido e relatado — nunca "corrigido" silenciosamente |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | define a taxa de amostragem; adicione `--format mp3 --bitrate 192k` para o codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

As duas coisas acima merecem:

**`master-check` mede RMS não ponderado, não LUFS.** São quantidades diferentes e a ACX usa a primeira como critério. A figura de −20 LUFS é como a passagem de masterização *atinge* esse valor — é o que `ffmpeg loudnorm` pode visar — e não o que é verificado depois.

**O ruído de fundo é medido, não corrigido.** É o requisito que mais frequentemente falha e vem do áudio de origem. Uma ferramenta que o atenua silenciosamente estaria ocultando o número que você precisa ver.

### Onde um audiolivro narrado por IA pode realmente chegar

Atender às especificações não é o mesmo que ser aceito, e vale a pena deixar isso claro: **o fluxo de envio padrão da ACX é para narração humana.** Seus requisitos de abril de 2026 listam texto-para-voz não autorizado e gravações de IA entre as coisas que não aceita, portanto, um título narrado por IA precisa de autorização prévia da ACX, em vez de um envio normal.

Os caminhos que aceitam narração de IA, geralmente com divulgação, incluem o **Virtual Voice** da Amazon por meio do KDP (distribuição exclusiva da Amazon) e agregadores como **Spotify Audiobooks for Authors**, **Author's Republic** e **Kobo Writing Life**. A política dos varejistas nesta área muda rapidamente — verifique os termos atuais você mesmo, em vez de confiar neste parágrafo.

Portanto: `--acx` é sobre o áudio. Se um varejista aceita ou não um título narrado por IA é a decisão dele, e não uma propriedade do arquivo que você acabou de produzir.

## Comandos da CLI

| Comando | Descrição |
|---------|-------------|
| `make <file>` | Execução única: novo → compilar → atribuição automática de vozes → renderizar |
| `new <arquivo\ | pasta>` | Crie um projeto a partir de EPUB/TXT/MD/PDF/DOCX ou uma pasta |
| `from-stdin` | Crie um projeto a partir de texto transmitido |
| `cast <char> <voice>` · `cast-interactive` | Atribua vozes (ou atribuição de vozes guiada por falante; também `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugira / aplique automaticamente / atribua em massa vozes |
| `cast-preset save\ | list\ | apply\ | delete` | Predefinições de elenco reutilizáveis em livros |
| `cast-export` · `cast-import <file>` | Faça a conversão completa dos dados no formato JSON/CSV — edite manualmente ou reutilize em diferentes versões. |
| `audition <char>` | Classifique as vozes dos candidatos em uma escala A/B para um único personagem (`--render`). |
| `compile` | Detecte os diálogos, atribua os falantes e infira as emoções. |
| `report` | Qualidade da compilação: taxa desconhecida, principais linhas não atribuídas, mistura de emoções. |
| `review-export` · `review-import <file>` | Ciclo de revisão editável por humanos. |
| `render` | Renderize o audiolivro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`). |
| `sample` · `master-check <file>` | Amostra de varejo finalizada · verifique em relação às especificações de áudio do ACX. |
| `export-chapters` · `podcast` | Folha de marcação de capítulos (ffmetadata/cue/json) · feed RSS do podcast. |
| `preview` · `batch` · `diagnose` | Clipe de teste de qualidade de voz · lote/`--manifest` · verificação do ambiente (retorna um código diferente de zero quando o sistema não consegue renderizar). |
| `load <file>` | Abra um projeto `.audiobooker` existente. |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecione e gerencie. |

Cada comando suporta `-h/--help`. Flags globais: `--silent`, `--debug`. **Códigos de saída:** `0` ok · `1` erro do usuário (incluindo um livro que não pode ser compilado ou uma renderização recusada porque a atribuição falhou) · `2` erro de execução · `3` parcial (lote).

## Configuração

Defina os valores padrão uma vez, em vez de passar as flags repetidamente — `.audiobookerrc` (TOML) ao lado do seu livro ou `[tool.audiobooker]` em `pyproject.toml`. A precedência é: **flag da linha de comando > configuração do projeto > configuração do usuário (`~/.audiobookerrc`) > valores padrão integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Mecanismos TTS (Text-to-Speech) plugáveis

O mecanismo padrão é `voice-soundboard`, mas o backend de síntese pode ser alterado por meio de entry-points do setuptools (`audiobooker.tts_engines`).

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Um plugin (`pip install audiobooker-piper`) se registra automaticamente; não é necessário criar um fork.

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

`render(...)` e `compile(...)` aceitam um `engine=` injetado (qualquer objeto que implemente o protocolo `TTSEngine`) e um callback de progresso — incorpore o audiobooker em uma GUI ou serviço.

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
Casting -> Review/Edit -> TTS (pluggable) -> cached audio -> FFmpeg master -> M4B/MP3/Opus/FLAC/WAV
```

## Segurança e escopo de dados

- **Rede:** nenhuma — sem telemetria, sem armazenamento de dados, sem credenciais. Lê os arquivos do seu livro, grava áudio + cache nos seus diretórios de saída.
- **Permissões:** acesso de leitura às entradas, acesso de gravação às saídas; FFmpeg opcional + um mecanismo TTS no PATH.
- Consulte [SECURITY.md](SECURITY.md).

## Avaliação

| Barreira. | Status. |
|------|--------|
| A. Linha de base de segurança. | APROVADO. |
| B. Tratamento de erros. | APROVADO. |
| C. Documentação do operador. | APROVADO. |
| D. Higiene de lançamento. | APROVADO. |
| E. Identidade. | APROVADO. |

## Licença

[MIT](LICENSE).

---

Criado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.
