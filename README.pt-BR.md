<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <img src="assets/audiobooker-logo.jpg" alt="Audiobooker" width="400" />
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

### Entrada e Análise
- Análise de fontes **EPUB / TXT / Markdown** com detecção de capítulos.
- Suporte a **PDF** (opcional): Extração de texto de arquivos PDF via PyMuPDF (`pip install -e '.[pdf]'`)
- **Normalização de texto**: Limpeza de aspas, normalização de espaços, limpadores de texto configuráveis.
- **Substituições de pronúncia**: Mapeamentos personalizados de palavras para pronúncias para nomes próprios e jargões.
- **Tratamento de notas de rodapé**: Comportamento de notas de rodapé configurável (`inline`, `end` ou `skip`).

### Diálogo e Atribuição
- **Detecção de diálogo**: Identifica automaticamente diálogos citados versus narração.
- **Detecção avançada de diálogo**: Rastreamento de turnos de conversa para cenas com vários interlocutores.
- **Indicações de cena**: Detecta e trata indicações de cena entre parênteses em roteiros.
- **Integração com BookNLP**: Resolução opcional de referência de falantes baseada em NLP.
- **Apelidos de personagens**: Mapeia nomes alternativos para um personagem principal.

### Voz e Interpretação
- **Síntese de múltiplas vozes**: Atribui vozes únicas a cada personagem.
- **Sugestões de voz**: Recomendações de voz explicáveis e classificadas por falante.
- **Inferência de emoção**: Rotulagem de emoções com base em regras e léxico, com nível de confiança configurável.
- **Parâmetros de voz por personagem**: Velocidade (0.5--2.0) e emoção por falante.
- **Pré-processamento SSML**: Suporte à Linguagem de Marcação para Síntese de Fala para controle detalhado.

### Renderização e Saída
- **Renderização paralela**: Renderização de capítulos com múltiplos processos usando `--jobs N`.
- **Múltiplos formatos de saída**: MP3, M4B, WAV, OGG, FLAC.
- **Normalização de áudio**: Níveis de volume consistentes em todos os capítulos.
- **Incorporação de capa**: Extraída do EPUB ou fornecida pelo usuário, incorporada na saída M4B.
- **Cache de renderização persistente**: Retoma renderizações interrompidas sem re-sintetizar capítulos já concluídos.
- **Progresso e ETA dinâmicos**: Status de renderização em tempo real com tempo estimado de conclusão.
- **Relatórios de falha**: Diagnósticos estruturados em formato JSON em caso de erros de renderização.

### Idioma e Localização
- **5 perfis de idioma**: Inglês, francês, alemão, espanhol, japonês (`--lang en|fr|de|es|ja`).
- **Sistema de perfis extensível**: Adicione novos idiomas através da abstração `LanguageProfile`.

### Fluxo de Trabalho e Produtividade
- **Revisão antes da renderização**: Formato de revisão editável por humanos para corrigir atribuições.
- **Comparação de projetos**: Compare duas versões de um projeto para ver as alterações em capítulos e falas.
- **Processamento em lote**: Processe vários livros em uma única execução com `audiobooker batch`.
- **Modo de teste**: Visualize a renderização ou operações em lote sem executá-las (`--dry-run`).
- **Teste de voz**: Renderize uma pequena amostra para validar as atribuições de voz (`audiobooker preview`).
- **Gerenciamento de capítulos**: Mescle, divida e exclua capítulos antes da renderização.
- **Gerenciamento de emoções**: Liste e substitua emoções por fala após a compilação.
- **Notificações de desktop**: Receba notificações quando renderizações longas forem concluídas.
- **Persistência do projeto**: Salve/retome sessões de renderização.

## Instalação

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

## Recursos Opcionais

| Recurso | Instalar | Config |
|---------|---------|--------|
| **TTS rendering** | `pip install -e '.[render]'` ou instale voice-soundboard | Requerido para `render` |
| **Resolução de falantes do BookNLP** | `pip install -e '.[nlp]'` | `--booknlp on\ | off\ | auto` |
| **PDF input** | `pip install -e '.[pdf]'` | `audiobooker new book.pdf` |
| **Rich progress bars** | `pip install -e '.[rich]'` | Detectado automaticamente em tempo de execução |
| **FFmpeg audio assembly** | Pacote do sistema (winget/brew/apt) | Requerido para saída M4B |

## Início Rápido

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

## Fluxo de Trabalho de Revisão

O fluxo de trabalho de revisão permite que você inspecione e corrija o script compilado antes da renderização:

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

**Formato do arquivo de revisão:**
- `=== Título do Capítulo ===` - Marcadores de capítulo
- `@Orador` ou `@Orador (emoção)` - Tags de orador
- `# comentário` - Comentários (ignorados na importação)
- Exclua blocos para remover trechos indesejados
- Altere `@Desconhecido` para `@NomeReal` para corrigir a atribuição

## API Python

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

## Comandos da Linha de Comando (CLI)

| Comando | Descrição |
|---------|-------------|
| `audiobooker new <file>` | Criar projeto a partir de EPUB/TXT/MD/PDF |
| `audiobooker load <project>` | Carregar projeto `.audiobooker` existente |
| `audiobooker from-stdin` | Criar projeto a partir de texto em pipeline |
| `audiobooker cast <char> <voice>` | Atribuir voz a um personagem |
| `audiobooker cast-suggest` | Sugerir vozes para oradores não atribuídos |
| `audiobooker cast-apply --auto` | Aplicar automaticamente as melhores sugestões de voz |
| `audiobooker compile` | Compilar capítulos em trechos |
| `audiobooker review-export` | Exportar o script para revisão humana |
| `audiobooker review-import <file>` | Importar arquivo de revisão editado |
| `audiobooker render` | Gerar o audiolivro (suporta `--dry-run`, `--jobs N`, `--format`, `--cover`) |
| `audiobooker preview` | Gerar uma amostra curta para validação da voz (`--chapter N`, `--seconds S`) |
| `audiobooker batch <files...>` | Processar em lote vários livros (suporta `--dry-run`) |
| `audiobooker info` | Mostrar informações do projeto |
| `audiobooker status` | Mostrar o status de renderização/cache |
| `audiobooker voices` | Listar vozes disponíveis (suporta `--gender`, `--search`) |
| `audiobooker chapters` | Listar títulos e índices dos capítulos |
| `audiobooker speakers` | Listar oradores detectados |
| `audiobooker cache info` | `clean` | `clean-failed` | Gerenciar o cache de renderização |
| `audiobooker diagnose` | Verificar o ambiente (dependências, motor de voz, FFmpeg) |

## Referência Completa da Linha de Comando

Cada comando suporta `-h` / `--help` para obter informações detalhadas sobre o uso. Principais opções:

- **`new`**: `-o <projeto>`, `--lang <código>` (en/fr/de/es/ja)
- **`cast`**: `--emotion <emoção>`, `--speed <0.5-2.0>`
- **`compile`**: `--booknlp on|off|auto`
- **`render`**: `--dry-run`, `--no-resume`, `--from-chapter N`, `--allow-partial`, `--clean-cache`, `--jobs N`, `-o <caminho>`, `--format mp3|m4b|wav|ogg|flac`, `--cover <imagem>`
- **`preview`**: `--chapter N`, `--seconds S`, `-o <caminho>`
- **`batch`**: `--dry-run`, `--jobs N`, `--format <fmt>`, `--lang <código>`, `--output-dir <diretório>`
- **`voices`**: `--gender <masculino|feminino>`, `--search <consulta>`
- **`info`**: `--verbose`

## Arquitetura

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

**Fluxo:**
```
Source File (EPUB/TXT/PDF) -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Problemas Comuns

| Problema | Solução |
|---------|-----|
| **FFmpeg not found** | Instale via seu gerenciador de pacotes: `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `apt install ffmpeg` (Linux). O FFmpeg deve estar no PATH. |
| **Motor de voz não instalado** | Clone e instale o repositório relacionado: `git clone https://github.com/mcp-tool-shop-org/voice-soundboard.git ../voice-soundboard && pip install -e ../voice-soundboard`. Ou instale com `pip install -e '.[render]'`. |
| **Erros do BookNLP ou inicialização lenta** | O BookNLP é opcional. Se você não precisar da resolução de oradores por NLP, defina `--booknlp off` ou deixe-o em `auto` (com fallback). Instale com `pip install -e '.[nlp]'` apenas se necessário. |

Consulte o [manual](docs/handbook.md#15-troubleshooting) para obter orientações completas sobre solução de problemas.

## Solução de Problemas

**Relatório de falha de renderização**: Em caso de erro de renderização, o Audiobooker cria um arquivo `render_failure_report.json` no diretório do cache. Este arquivo contém:
- Índice e título do capítulo onde ocorreu o erro
- Índice do trecho, orador e visualização do texto
- ID da voz e emoção que estavam sendo sintetizadas
- Rastreamento completo da pilha
- Caminhos do cache e do manifesto

**Problemas comuns do FFmpeg**:
- `FFmpeg não encontrado`: Instale via seu gerenciador de pacotes (winget/brew/apt)
- `Falha na incorporação do capítulo`: O Audiobooker volta a usar o formato M4A sem marcadores de capítulo
- Qualidade do áudio: O padrão é AAC de 128kbps a 24kHz (configurável no ProjectConfig)

**Problemas de cache:**
- `audiobooker render --clean-cache` — limpa todo o cache de áudio e renderiza novamente.
- `audiobooker render --no-resume` — ignora o cache para esta execução.
- `audiobooker render --from-chapter 5` — inicia a partir de um capítulo específico.

## Roteiro

- [x] Pipeline principal (análise, conversão, compilação, renderização)
- [x] Fluxo de trabalho de revisão antes da renderização
- [x] Cache de renderização persistente + retomada
- [x] Perfis de idioma + flexibilidade de entrada
- [x] BookNLP, inferência de emoções, sugestões de voz, aprimoramento da experiência do usuário
- [x] v1.0.0 - Lançamento para produção

## Segurança e Escopo de Dados

- **Dados acessados:** Lê arquivos EPUB/TXT do sistema de arquivos local. Escreve arquivos de áudio e arquivos de manifesto do cache em diretórios de saída. Opcionalmente, usa um sintetizador de voz e o FFmpeg para montagem de áudio.
- **Dados NÃO acessados:** Sem requisições de rede. Sem telemetria. Sem armazenamento de dados do usuário. Sem credenciais ou tokens.
- **Permissões necessárias:** Acesso de leitura aos arquivos de entrada. Acesso de escrita aos diretórios de saída. Opcional: FFmpeg no PATH.

## Tabela de Avaliação

| Porta | Status |
|------|--------|
| A. Base de Segurança | APROVADO |
| B. Tratamento de Erros | APROVADO |
| C. Documentação para Operadores | APROVADO |
| D. Higiene para Lançamento | APROVADO |
| E. Identidade | APROVADO |

## Licença

[MIT](LICENSE)

---

Criado por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
