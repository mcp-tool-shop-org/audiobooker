<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/audiobooker/main/assets/audiobooker-logo.png" alt="Audiobooker" width="420" />
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@mcptoolshop/audiobooker"><img src="https://img.shields.io/npm/v/@mcptoolshop/audiobooker" alt="npm version"></a>
  <a href="https://pypi.org/project/audiobooker-ai/"><img src="https://img.shields.io/pypi/v/audiobooker-ai" alt="PyPI version"></a>
  <a href="https://github.com/mcp-tool-shop-org/audiobooker/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://mcp-tool-shop-org.github.io/audiobooker/"><img src="https://img.shields.io/badge/Landing_Page-live-blue" alt="Landing Page"></a>
</p>

<p align="center">
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks (<strong>M4B / MP3 / Opus / FLAC</strong>) — from one command.
</p>

Este é o wrapper **`npx`** para [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). Ele configura um ambiente Python privado na primeira execução, instala a versão especificada do PyPI e executa a CLI real — sem necessidade de `pip` manual, sem alterações no seu sistema Python.

## Experimente

```bash
npx @mcptoolshop/audiobooker --help
```

Ou instale globalmente:

```bash
npm install -g @mcptoolshop/audiobooker
```

Na primeira execução, é configurado um ambiente virtual gerenciado na pasta de dados do usuário (`~/.local/share/audiobooker` ou `%LOCALAPPDATA%\audiobooker` no Windows) e `audiobooker-ai` é instalado. Em todas as execuções subsequentes, o processo inicia instantaneamente.

**Requer Python 3.10+** no PATH (o wrapper procura por `python3` / `py`). Se não estiver presente, o wrapper informa exatamente como instalá-lo para o seu sistema operacional.

## Início rápido

```bash
# One command: parse -> auto-cast voices -> compile -> render
npx @mcptoolshop/audiobooker make mybook.epub --acx

# Or the staged workflow, with control at each step
npx @mcptoolshop/audiobooker new mybook.epub
npx @mcptoolshop/audiobooker cast --interactive
npx @mcptoolshop/audiobooker compile
npx @mcptoolshop/audiobooker render --format m4b
```

## Renderização de áudio (síntese de voz)

Análise sintática, seleção de vozes, compilação e o fluxo de trabalho de revisão funcionam imediatamente. A **renderização de áudio** requer o motor TTS, que inclui dependências mais pesadas — ative quando estiver pronto:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

A renderização também requer o **FFmpeg** no PATH para a montagem de arquivos M4B/MP3 (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Execute `audiobooker diagnose` para verificar sua configuração.

## O que ele faz

- **Seleção de múltiplas vozes** com sugestões de voz explicáveis e classificadas; `audiobooker audition <character>` permite testar as vozes candidatas antes de decidir.
- **Detecção de diálogo + atribuição de falante** (opcionalmente, co-referência BookNLP), inferência de emoção e léxicos de pronúncia reutilizáveis.
- **Revisão antes da renderização**: exporte um script editável por humanos, corrija as atribuições, reimporte — nada é alterado silenciosamente.
- **Masterização ACX / Audible**: `render --acx` mais `master-check` relata PASS/FAIL em relação ao volume, pico e ruído de fundo.
- **Formatos**: M4B (marcadores de capítulo + capa incorporada + metadados da série), MP3, Opus, FLAC; exportação por capítulo; clipes de amostra para varejo.
- **7 perfis de idioma** (en/fr/de/es/ja/it/pt) e um arquivo de configuração por livro para configurações padrão que são aplicadas automaticamente.

## Variáveis de ambiente

| Variável | Efeito |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Provisiona o ambiente virtual gerenciado **com** o motor de voz (para renderização) |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | Reconstrói o ambiente gerenciado do zero |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | Substitui o local onde o ambiente virtual gerenciado está armazenado |

## Prefere usar pip?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## Links

- **Documentação e manual:** <https://mcp-tool-shop-org.github.io/audiobooker/>
- **Código fonte:** <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI:** <https://pypi.org/project/audiobooker-ai/>

## Licença

[MIT](LICENSE) © mcp-tool-shop
