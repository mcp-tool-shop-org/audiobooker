<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a>
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

**Docker** — ffmpeg já incluído, publicado no GHCR em cada lançamento:
```bash
docker run --rm -v "$(pwd):/data" ghcr.io/mcp-tool-shop-org/audiobooker \
  make /data/mybook.epub --acx
```
Essa montagem é suficiente, e `--rm` é seguro: o cache de renderização fica ao lado do arquivo do projeto, e não em um diretório pessoal, portanto, uma nova execução **retoma** em vez de ressíntetizar o livro.

<details>
<summary>Container details — tags, the cache, and file ownership</summary>

- Marcado com `latest`, `3`, `3.0` e a versão exata, enviado para o GHCR em cada lançamento.
- O ponto de entrada **é** `audiobooker`, portanto, passe o subcomando imediatamente após o nome da imagem — não repita o nome do programa.
- O cache é armazenado em `<book-dir>/.audiobooker/cache`. É por isso que uma montagem única cobre a persistência; perdê-la significa pagar novamente por toda a execução do TTS, e não apenas pela remistura.
- `/ext` é uma segunda montagem opcional, apenas para fornecer seu próprio pacote TTS.
- O contêiner é executado como um UID não raiz 1000. No Linux, se o diretório montado não for gravável por esse UID, o cache não poderá ser gravado — adicione `--user "$(id -u):$(id -g)"` ou `chown` ao diretório. O Docker Desktop em macOS e no Windows lida com isso para você.

</details>

**Renderizar áudio** requer o mecanismo TTS [`voice-soundboard`](https://pypi.org/project/voice-soundboard/) (o extra `[render]`) e **FFmpeg** no PATH (`winget install ffmpeg` · `brew install ffmpeg` · `apt install ffmpeg`). Tudo até a renderização — análise, atribuição, compilação, revisão — funciona sem eles. Execute `audiobooker diagnose` para verificar sua configuração.

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

Cada um desses é um caso em que a versão 2.x aceitava algo e fazia a coisa errada silenciosamente. A versão 3.0 recusa em vez disso. Detalhes completos em [CHANGELOG](CHANGELOG.md).

- **Sua primeira renderização renderiza novamente todos os capítulos, uma vez.** Três entradas que alteram o áudio — predefinição de emoção, intensidade da fala, velocidade/tom/ênfase por personagem — estavam faltando da chave do cache, portanto, a alteração da predefinição relatava "Em cache" e retornava o áudio antigo. Agora, elas estão na chave, e uma entrada de cache da versão 2.x não pode provar o que a produziu.
- **`--format m4a` não é mais uma opção para todo o livro.** Sempre significou um arquivo por capítulo; solicitar um livro inteiro em `m4a` anteriormente produzia um único M4B sob um nome `.m4a`. Ainda é válido em `podcast --format`.
- **`render` recusa um livro cuja atribuição diz `FAILED`** em vez de gastar uma execução de TTS nele. `--force` substitui. Execute `audiobooker report` para ver quais linhas ele está rejeitando.
- **`make` recusa quando o arquivo do projeto já existe.** Ele costumava substituir vozes atribuídas manualmente, substituições de pronúncia e títulos editados por uma nova análise automática. Passe `--overwrite-project` se for isso que você deseja.
- **`compile()` gera um erro quando todos os capítulos falham** em vez de retornar `None` da maneira que uma execução limpa faz. Se você o chamar do Python, agora ele pode gerar um erro.

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
audiobooker speakers                   # who did compile find?
audiobooker speakers --suggest-aliases # Dr. Merrin / Merrin / The Doctor?
audiobooker speakers merge "Dr. Merrin" Merrin   # fold those slots into one voice
audiobooker report                     # what's weak? unattributed + guessed rates, top lines
audiobooker review-export              # human-editable script — fix attributions
audiobooker review-import mybook_review.txt
audiobooker render --acx               # render + master to ACX spec
audiobooker master-check mybook.m4b    # PASS/FAIL vs ACX loudness/peak/noise-floor
```

## Recursos

### Entrada e estrutura
- **EPUB, TXT, Markdown, PDF, DOCX** ou uma **pasta de arquivos por capítulo** (Scrivener/Obsidian/ficção serializada).
- **Divisão de EPUB baseada em TOC** — limites e títulos de capítulos da própria tabela de conteúdos do livro.
- **DOCX** divide-se em estilos Word `Heading 1/2`/`Title`; **PDF** detecta títulos (com uma proteção de PDF digitalizado); personalização `--chapter-delimiter`.
- Limpeza inteligente de texto, remoção com reconhecimento de Markdown, tratamento de notas de rodapé e um **lexicão de pronúncia reutilizável** (`pronunciation import/export`, CSV/JSON, com passagem de fonema).

### Atribuição e elenco
- **Síntese de várias vozes** com sugestões de voz explicáveis e classificadas e um comando **`audition`** para comparar candidatos por personagem.
- **Atribuição interativa**, **atribuição em massa `cast-fill`** por gênero/função, **predefinições de elenco nomeadas** reutilizáveis em uma série e **planilhas de elenco CSV** para colaboradores.
- **Detecção de diálogo + atribuição de falante** (co-referência **BookNLP** opcional), **descoberta automática de alias** e **inferência de emoção** com intensidade ajustável, humor em nível de cena e pacotes de predefinição de gênero.
- **Atribuição que você pode auditar.** Cada linha registra *como* seu falante foi determinado — uma tag de fala, uma substituição embutida, co-referência, sua própria correção ou um palpite de alternância pura — e `report` conta os palpites separadamente das linhas que não conseguiu atribuir. Um palpite não pode melhorar a pontuação, portanto, o número diminui quando a atribuição piora, o que é a única direção que é útil.

### Renderização e saída
- **M4B** (marcadores de capítulo + capa incorporada + metadados da série), **MP3**, **Opus**, **FLAC**, **WAV**; exportação por capítulo; exportação de feed **podcast/RSS**.
O WAV não tem um átomo de capítulo, portanto, uma renderização WAV diz isso claramente, em vez de relatar uma falha na mistura do capítulo — use-o quando o áudio for para um editor.
- **Otimização para as especificações de áudio do ACX** (`--acx`) + um **`master-check`** que relata PASS/FAIL em relação à intensidade sonora RMS, pico e ruído de fundo; clipes de varejo **`sample`**.
- Renderização paralela, um **cache de renderização persistente** com retomada, progresso dinâmico + ETA e relatórios de falha estruturados.
A chave do cache cobre tudo o que altera o áudio — texto, elenco, vozes, mecanismo e versão, perfil, predefinição de emoção e intensidade — portanto, uma nova renderização que diz "Em cache" significa isso. Um cache **por fala** opcional (`utterance_cache`) restringe uma nova renderização às linhas que você realmente editou.

### Fluxo de trabalho e ecossistema
- **Pipeline único `make`** · **arquivo de configuração** (`.audiobookerrc` / `[tool.audiobooker]`) · **modo `--watch`** · **lote baseado em manifesto** · conclusão de shell.
- **7 perfis de idioma** (en/fr/de/es/ja/it/pt) · **mecanismos TTS plugáveis** (`--engine`, pontos de entrada — traga Piper/Coqui/ElevenLabs) · script `--json` na maioria dos comandos · códigos de saída estruturados.

## Otimização para as especificações de áudio do ACX

A ACX publica um alvo de áudio preciso e mensurável. É a coisa mais próxima que o mundo dos audiolivros tem de um padrão de masterização, e vale a pena atingir, independentemente do que você fizer com o arquivo depois.

| Requisito | Especificação ACX | O que `--acx` faz |
|---|---|---|
| Volume | RMS entre **−23 e −18 dBFS** | processamento em duas etapas `loudnorm` em −20 LUFS, o que se enquadra nessa faixa para a fala |
| Pico | em ou abaixo de **−3 dBFS** | aplicado na mesma etapa |
| Nível de ruído | em ou abaixo de **−60 dBFS** | medido e relatado — nunca "corrigido" silenciosamente |
| Formato | **44,1 kHz, 192 kbps CBR MP3** | define a taxa de amostragem; adicione `--format mp3 --bitrate 192k` para o codec |

```bash
audiobooker render --acx --format mp3 --bitrate 192k
audiobooker master-check book.mp3      # PASS/FAIL against the three measured limits
audiobooker sample --duration 180      # a mastered retail sample clip
```

Dois pontos que os números acima merecem:

**`master-check` mede o RMS não ponderado, não os LUFS.** São quantidades diferentes
e os limites do ACX são baseados no primeiro. O valor de −20 LUFS é como o
processamento final *atinge* esse valor — é o que `ffmpeg loudnorm` pode visar — não
o que é verificado posteriormente.

**O nível de ruído é medido, não corrigido.** É o requisito que
mais frequentemente não é atendido, e vem do áudio de origem. Uma ferramenta que o
reduzisse silenciosamente estaria ocultando o número que você precisa ver.

### Onde um audiolivro narrado por IA pode realmente chegar

Atender às especificações não é o mesmo que ser aceito, e vale a pena deixar isso claro: **o fluxo de envio padrão do ACX é para narração humana.** Em sua lista de requisitos de abril de 2026, ele inclui texto para fala não autorizado e gravações de IA
entre as coisas que não aceita, portanto, um título narrado por IA precisa de autorização prévia do ACX em vez de um envio comum.

As opções que aceitam narração de IA, geralmente com divulgação, incluem
o **Virtual Voice** da Amazon, por meio do KDP (distribuição exclusiva da Amazon) e
agregadores como **Spotify Audiobooks for Authors**, **Author's Republic**
e **Kobo Writing Life**. A política dos varejistas nessa área muda rapidamente —
verifique os termos atuais você mesmo, em vez de confiar neste parágrafo.

Portanto: `--acx` diz respeito ao áudio. Se um varejista aceita ou não um título narrado por IA é decisão dele, não uma propriedade do arquivo que você acabou de produzir.

## Comandos da linha de comando

| Comando | Descrição |
|---------|-------------|
| `make <file>` | Execução única: novo → compilar → atribuição automática → renderizar |
| `new <file\|folder>` | Crie um projeto a partir de EPUB/TXT/MD/PDF/DOCX ou de uma pasta |
| `from-stdin` | Crie um projeto a partir de texto transmitido |
| `cast <char> <voice>` · `cast-interactive` | Atribua vozes (ou atribuição guiada por personagem; também `cast -i`) |
| `cast-suggest` · `cast-apply --auto` · `cast-fill` | Sugira / aplique automaticamente / atribua em massa as vozes |
| `cast-preset save\|list\|apply\|delete` | Predefinições de elenco reutilizáveis em diferentes livros |
| `cast-export` · `cast-import <file>` | Transfira o elenco como JSON/CSV — edite manualmente ou reutilize em diferentes edições |
| `audition <char>` | Vozes candidatas classificadas em A/B para um personagem (`--render`) |
| `compile` | Detecte diálogos, atribua falantes, infira emoções |
| `report` | Qualidade da compilação: taxa de não atribuição, taxa estimada, piores frases, mistura de emoções |
| `review-export` · `review-import <file>` | Revisão editável pelo usuário |
| `render` | Renderize o audiolivro (`--acx`, `--format`, `--split`, `--bitrate`, `--engine`, `--watch`, `--cover`, `-j N`) |
| `sample` · `master-check <file>` | Amostra de varejo masterizada · verifique em relação às especificações de áudio do ACX |
| `export-chapters` · `podcast` | Folha de dicas de capítulo (ffmetadata/cue/json) · feed RSS de podcast |
| `preview` · `batch` · `diagnose` | Clipe de teste de voz · lote/`--manifest` · verificação de ambiente (encerra com código de erro diferente de zero quando a renderização não é possível) |
| `load <file>` | Abra um projeto `.audiobooker` existente |
| `voices` · `chapters` · `speakers` · `speakers merge` · `info` · `status` · `cache` · `emotions` · `pronunciation` · `completion` | Inspecione e gerencie (`speakers merge <from> <to>` agrupa nomes duplicados em um único slot de elenco) |

Cada comando suporta `-h/--help`. Sinalizadores globais: `--silent`, `--debug`. **Códigos de saída:** `0` ok · `1` erro do usuário (incluindo um livro que não seria compilado ou uma renderização recusada porque a atribuição falhou) · `2` erro de tempo de execução · `3` parcial (lote).

## Configuração

Defina os padrões uma vez, em vez de passar os sinalizadores repetidamente — `.audiobookerrc` (TOML) ao lado do seu livro ou `[tool.audiobooker]` em `pyproject.toml`. A precedência é **sinalizador da linha de comando > configuração do projeto > configuração do usuário (`~/.audiobookerrc`) > padrões integrados**.

```toml
# .audiobookerrc
output_format = "m4b"
output_profile = "acx"
lang = "en"
jobs = 4
booknlp_mode = "auto"
```

## Mecanismos TTS plugáveis

O mecanismo padrão é `voice-soundboard`, mas o back-end de síntese pode ser alterado por meio de pontos de entrada setuptools (`audiobooker.tts_engines`):

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

`render(...)` e `compile(...)` aceitam um `engine=` injetado (qualquer objeto que implemente o protocolo `TTSEngine`) e um retorno de chamada de progresso — incorpore o audiobooker em uma GUI ou serviço.

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
- **Permissões:** acesso de leitura às entradas, acesso de gravação às saídas; opcional FFmpeg + um mecanismo TTS no PATH.
- Consulte [SECURITY.md](SECURITY.md).

## Avaliação

| Limite | Status |
|------|--------|
| A. Linha de base de segurança | APROVADO |
| B. Tratamento de erros | APROVADO |
| C. Documentação do operador | APROVADO |
| D. Higiene de envio | APROVADO |
| E. Identidade | APROVADO |

## Licença

[MIT](LICENSE)

---

Criado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
