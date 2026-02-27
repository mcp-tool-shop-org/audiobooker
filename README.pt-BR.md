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
  AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.
</p>

## Características

- **Síntese de múltiplas vozes**: Atribua vozes únicas a cada personagem.
- **Detecção de diálogo**: Identifica automaticamente diálogos em relação à narração.
- **Inferência de emoção**: Rotulagem de emoções com base em regras e léxico, com nível de confiança configurável.
- **Sugestões de voz**: Recomendações de voz explicáveis e classificadas para cada orador.
- **Integração com BookNLP**: Resolução opcional de referência de oradores com tecnologia de processamento de linguagem natural (PNL).
- **Revisão antes da renderização**: Formato de revisão editável por humanos para corrigir atribuições.
- **Cache de renderização persistente**: Retoma renderizações interrompidas sem precisar re-sintetizar os capítulos já concluídos.
- **Progresso e tempo estimado dinâmicos**: Status de renderização em tempo real com tempo estimado de conclusão.
- **Relatórios de falhas**: Diagnósticos estruturados em formato JSON para erros de renderização.
- **Perfis de idioma**: Abstração de regras específicas para cada idioma, que podem ser expandidas.
- **Saída em formato M4B**: Formato profissional para audiolivros, com navegação por capítulos.
- **Persistência do projeto**: Salva e retoma sessões de renderização.

## Instalação

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

## Recursos Opcionais

| Recurso | Instalar | Configuração |
|---------|---------|--------|
| **TTS rendering** | `pip install audiobooker-ai[render]` ou instale o voice-soundboard | Necessário para `render` |
| **Resolução de oradores do BookNLP** | `pip install audiobooker-ai[nlp]` | `--booknlp on\ | off\ | auto` |
| **FFmpeg audio assembly** | Pacote do sistema (winget/brew/apt) | Necessário para a saída em formato M4B |

## Início Rápido

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

## Fluxo de Revisão

O fluxo de revisão permite que você inspecione e corrija o script compilado antes da renderização:

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
| `audiobooker new <file>` | Criar projeto a partir de EPUB/TXT |
| `audiobooker cast <char> <voice>` | Atribuir voz a um personagem |
| `audiobooker cast-suggest` | Sugerir vozes para oradores sem voz atribuída |
| `audiobooker cast-apply --auto` | Aplicar automaticamente as melhores sugestões de voz |
| `audiobooker compile` | Compilar capítulos em trechos |
| `audiobooker review-export` | Exportar o script para revisão humana |
| `audiobooker review-import <file>` | Importar o arquivo de revisão editado |
| `audiobooker render` | Renderizar o audiolivro |
| `audiobooker info` | Mostrar informações do projeto |
| `audiobooker voices` | Listar vozes disponíveis |
| `audiobooker chapters` | Listar capítulos |
| `audiobooker speakers` | Listar oradores detectados |
| `audiobooker from-stdin` | Criar projeto a partir de texto via pipe |

## Arquitetura

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

**Fluxo:**
```
Source File -> Parser -> Chapters -> Dialogue Detection ->
Speaker Resolution (BookNLP optional) -> Emotion Inference ->
Utterances -> Review/Edit -> TTS (voice-soundboard) ->
Chapter Audio (cached) -> FFmpeg -> M4B with Chapters
```

## Solução de Problemas

**Relatório de falha de renderização**: Em caso de erro de renderização, o Audiobooker cria um arquivo `render_failure_report.json` no diretório de cache. Este arquivo contém:
- Índice e título do capítulo onde ocorreu o erro
- Índice, orador e trecho de texto
- ID da voz e emoção que estavam sendo sintetizadas
- Rastreamento completo da pilha de erros
- Caminhos do cache e do manifesto

**Problemas comuns com o FFmpeg**:
- `FFmpeg não encontrado`: Instale através do seu gerenciador de pacotes (winget/brew/apt)
- `Falha na incorporação do capítulo`: O Audiobooker volta a usar o formato M4A sem marcadores de capítulo
- Qualidade do áudio: O padrão é AAC a 128kbps a 24kHz (configurável no ProjectConfig)

**Problemas com o cache**:
- `audiobooker render --clean-cache` — limpa todo o cache de áudio e re-renderiza
- `audiobooker render --no-resume` — ignora o cache para esta execução
- `audiobooker render --from-chapter 5` — inicia a partir de um capítulo específico

## Próximos Passos (Roadmap)

- [x] v0.1.0 - Pipeline principal (análise, atribuição, compilação, renderização)
- [x] v0.2.0 - Fluxo de revisão antes da renderização
- [x] v0.3.0 - Cache de renderização persistente + retomada
- [x] v0.4.0 - Perfis de idioma + flexibilidade de entrada
- [x] v0.5.0 - BookNLP, inferência de emoção, sugestões de voz, aprimoramentos na interface do usuário

## Segurança e Escopo de Dados

- **Dados acessados:** Lê arquivos EPUB/TXT do sistema de arquivos local. Escreve arquivos de áudio e arquivos de manifesto de cache em diretórios de saída. Opcionalmente, utiliza um painel de sons para síntese de voz e FFmpeg para montagem de áudio.
- **Dados NÃO acessados:** Sem requisições de rede. Sem telemetria. Sem armazenamento de dados do usuário. Sem credenciais ou tokens.
- **Permissões necessárias:** Acesso de leitura aos arquivos de entrada. Acesso de escrita aos diretórios de saída. Opcional: FFmpeg no PATH.

## Painel de Avaliação

| Critério | Status |
|------|--------|
| A. Base de Segurança | APROVADO |
| B. Tratamento de Erros | APROVADO |
| C. Documentação para Operadores | APROVADO |
| D. Boas Práticas de Desenvolvimento | APROVADO |
| E. Identidade | APROVADO |

## Licença

[MIT](LICENSE)

---

Desenvolvido por <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a
