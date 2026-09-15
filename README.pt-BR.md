<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.ja.md">日本語</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.zh.md">中文</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.es.md">Español</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.fr.md">Français</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.hi.md">हिन्दी</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.it.md">Italiano</a> | <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/README.pt-BR.md">Português (BR)</a>
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

O Audiobooker detecta diálogos, atribui uma voz distinta a cada personagem, infere emoções, permite que você revise e corrija tudo antes que um único segundo seja renderizado e, em seguida, otimiza o resultado para as especificações de áudio do ACX — para que a saída seja um audiolivro *finalizado*, e não apenas áudio gerado.

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

**Docker** — o ffmpeg já está incluído, publicado no GHCR em cada lançamento:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
Essa montagem é suficiente, e `--rm` é seguro: o cache de renderização fica ao lado
do arquivo do projeto, e não em um diretório pessoal, portanto, uma nova execução **retoma** em vez de
ressintetizar o livro.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Marcado com `latest`, `2`, `2.1` e a versão exata, enviado para o GHCR em cada
lançamento.
- O ponto de entrada **é** `audiobooker`, portanto, passe o subcomando imediatamente após
o nome da imagem — não repita o nome do programa.
- O cache é armazenado em `<book-dir>/.audiobooker/cache`. É por isso que uma montagem
única cobre a persistência; perdê-lo significa pagar novamente por toda a execução do TTS,
e não apenas por uma nova mixagem.
- `/ext` é uma segunda montagem opcional, apenas para fornecer seu próprio pacote TTS.
- O contêiner é executado como um UID não root 1000. No Linux, se o diretório montado não for gravável por esse UID, o cache não poderá ser gravado — adicione
`--user "$(id -u):$(id -g)"` ou `chown` ao diretório. O Docker Desktop no
macOS e no Windows lida com isso para você.

</details>

**Renderizar áudio** requer o mecanismo TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (o extra `[render]`) e o **FFmpeg** no PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tudo até a renderização — análise, atribuição, compilação, revisão — funciona sem eles. Execute `audiobooker diagnose` para verificar sua configuração.

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
- **Divisão de EPUB baseada em TOC** — limites e títulos de capítulos da própria tabela de conteúdos do livro.
- **DOCX** divide-se nos estilos Word `Heading 1/2`/`Title`; **PDF** detecta títulos (com uma proteção para PDFs digitalizados); personalização `--chapter-delimiter`.
- Limpeza inteligente de texto, remoção com reconhecimento de Markdown, tratamento de notas de rodapé e um **lexicão de pronúncia reutilizável** (`pronunciation import/export`, CSV/JSON, com passagem de fonemas).

### Atribuição e seleção de vozes
- **Multi-voice synthesis** with explainable, ranked voice **suggestions** and an **`audition`** command to A/B candidates per character.
- **Interactive casting**, **bulk `cast-fill`** by gender/role, **named cast presets** reusable across a series, and **CSV cast sheets** for collaborators.
- **Dialogue detection + speaker attribution** (optional **BookNLP** co-reference), **alias auto-discovery**, and **emotion inference** with adjustable **intensity**, **scene-level mood**, and genre **preset packs**.

### Renderização e saída
- **M4B** (chapter markers + embedded cover + series metadata), **MP3**, **Opus**, **FLAC**, **WAV**; per-chapter export; **podcast/RSS** feed export.
  WAV has no chapter atom, so a WAV render says so plainly rather than reporting a failed chapter mux — reach for it when the audio is going into an editor.
- **ACX-spec mastering** (`--acx`) + a **`master-check`** that reports PASS/FAIL on RMS loudness, peak, and noise floor; retail **`sample`** clips.
- Parallel rendering, a **persistent render cache** with resume, dynamic progress + ETA, and structured failure reports.

### Fluxo de trabalho e ecossistema
- **Pipeline único** `make` · **arquivo de configuração** (`.audiobookerrc` / `[tool.audiobooker]`) · **modo** `--watch` · **lote baseado em manifesto** · conclusão de shell.
- **7 perfis de idioma** (en/fr/de/es/ja/it/pt) · **mecanismos TTS plugáveis** (`--engine`, pontos de entrada — traga Piper/Coqui/ElevenLabs) · script `--json` na maioria dos comandos · códigos de saída estruturados.

## Otimização para as especificações de áudio do ACX

O ACX publica um alvo de áudio preciso e mensurável. É a coisa mais próxima que o mundo dos audiolivros tem de um padrão de masterização, e vale a pena atingir, independentemente do que você faça com o arquivo depois.

| Requisito | Especificação do ACX | O que `--acx` faz |
|---|---|---|
| Volume | RMS entre **−23 e −18 dBFS** | passagem dupla `loudnorm` em −20 LUFS, que fica dentro dessa janela para fala |
| Pico | em ou abaixo de **−3 dBFS** | aplicado na mesma passagem |
| Ruído de fundo | em ou abaixo de **−60 dBFS** | medido e relatado — nunca "corrigido" silenciosamente |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | define a taxa de amostragem; adicione `--format mp3 --bitrate 192k` para o codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

As duas coisas acima merecem:

**`master-check` mede RMS não ponderado, não LUFS.** São quantidades diferentes e o ACX aplica restrições à primeira. A figura de −20 LUFS é como a passagem de masterização *atinge* esse valor — é o que `ffmpeg loudnorm` pode segmentar — e não o que é verificado depois.

**O ruído de fundo é medido, não corrigido.** É o requisito que mais frequentemente falha e vem do áudio de origem. Uma ferramenta que o atenua silenciosamente estaria ocultando o número que você precisa ver.

### Onde um audiolivro narrado por IA pode realmente chegar

Atender às especificações não é o mesmo que ser aceito, e vale a pena ser claro sobre isso: **o fluxo de envio padrão do ACX é para narração humana.** Seus requisitos de abril de 2026 listam texto-para-voz não autorizado e gravações de IA entre as coisas que não aceita, portanto, um título narrado por IA precisa de autorização prévia do ACX, em vez de um envio normal.

As rotas que aceitam narração por IA geralmente o fazem com uma declaração de que a narração é feita por IA, e incluem:
**Virtual Voice** da Amazon, por meio do KDP (distribuição exclusiva da Amazon) e agregadores como **Spotify Audiobooks for Authors**, **Author's Republic** e **Kobo Writing Life**. A política dos varejistas nessa área muda rapidamente — verifique os termos atuais você mesmo, em vez de confiar neste parágrafo.

Portanto: `--acx` é sobre o áudio. Se um varejista aceita um título narrado por IA é decisão dele, e não uma característica do arquivo que você acabou de produzir.

## Comandos da linha de comando (CLI)

| Comando | Descrição |
|---------|-------------|
| `make <file>` | Processamento em uma única etapa: novo → compilar → atribuição automática → renderização |
| `new <arquivo\ | pasta>` | Cria um projeto a partir de arquivos EPUB/TXT/MD/PDF/DOCX ou de uma pasta |
| `from-stdin` | Cria um projeto a partir de texto fornecido |
| `cast <char> <voice>` · `cast-interactive` | Atribui vozes (ou atribuição guiada por personagem; também `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugere / aplica automaticamente / atribui em massa as vozes |
| `cast-preset save\ | list\ | apply\ | delete` | Predefinições de atribuição reutilizáveis em diferentes livros |
| `cast-export` · `cast-import <file>` | Permite a troca completa da atribuição em formato JSON/CSV — edição manual ou reutilização em diferentes edições |
| `audition <char>` | Vozes candidatas classificadas (A/B) para um personagem (`--render`) |
| `compile` | Detecta diálogos, atribui falantes, infere emoções |
| `report` | Qualidade da compilação: taxa desconhecida, principais linhas não atribuídas, mistura de emoções |
| `review-export` · `review-import <file>` | Revisão editável por humanos, com possibilidade de troca completa |
| `render` | Renderiza o audiolivro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Amostra de varejo masterizada · verificação em relação às especificações de áudio do ACX |
| `export-chapters` · `podcast` | Folha de marcação de capítulos (ffmetadata/cue/json) · feed RSS para podcast |
| `preview` · `batch` · `diagnose` | Clipe de teste de voz · lote/`--manifest` · verificação do ambiente (encerra com código de erro diferente de zero quando o sistema não consegue renderizar) |
| `load <file>` | Abre um projeto `.audiobooker` existente |
| `voices` · `chapters` · `speakers` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspeciona e gerencia |

Cada comando suporta `-h/--help`. Flags globais: `--silent`, `--debug`. **Códigos de saída:** `0` ok · `1` erro do usuário (incluindo um livro que não pode ser compilado ou uma renderização recusada porque a atribuição falhou) · `2` erro de execução · `3` parcial (lote).

## Configuração

Define os valores padrão uma vez, em vez de passar as flags repetidamente — `.audiobookerrc` (TOML) ao lado do seu livro ou `[tool.audiobooker]` em `pyproject.toml`. A precedência é: **flag da linha de comando > configuração do projeto > configuração do usuário (`~/.audiobookerrc`) > valores padrão integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Mecanismos TTS (Text-to-Speech) plugáveis

O mecanismo padrão é `voice-soundboard`, mas o backend de síntese pode ser alterado por meio de entry-points do setuptools (`audiobooker.tts_engines`):

```bash
audiobooker render --engine piper      # or set AUDIOBOOKER_ENGINE=piper
```

Um plugin (`pip install audiobooker-piper`) se registra; não é necessário criar um fork.

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

`render(...)` e `compile(...)` aceitam um `engine=` injetado (qualquer objeto que implemente o protocolo `TTSEngine`) e uma função de retorno de progresso — incorpore o audiobooker em uma GUI ou serviço.

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

- **Rede:** nenhuma — sem telemetria, sem armazenamento de dados, sem credenciais. Lê seus arquivos de livro, grava áudio + cache em seus diretórios de saída.
- **Permissões:** acesso de leitura às entradas, acesso de gravação às saídas; FFmpeg opcional + um mecanismo TTS no PATH.
- Consulte [SECURITY.md](SECURITY.md).

## Avaliação

| Portão | Status |
|------|--------|
| A. Linha de base de segurança | APROVADO |
| B. Tratamento de erros | APROVADO |
| C. Documentação do operador | APROVADO |
| D. Boas práticas de lançamento | APROVADO |
| E. Identidade | APROVADO |

## Licença

[MIT](LICENSE)

---

Criado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
