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
  Turn <strong>EPUB / TXT / PDF / DOCX</strong> books into professionally narrated, multi-voice audiobooks (<strong>M4B / MP3 / Opus / FLAC / WAV</strong>) — from one command.
</p>

Este é o **`npx` wrapper** para [`audiobooker-ai`](https://pypi.org/project/audiobooker-ai/) (Python). Ele configura um ambiente Python privado na primeira execução, instala a versão especificada do PyPI e executa a CLI real — sem configuração manual `pip`, sem alterações no seu Python do sistema.

## Experimente

```bash
npx @mcptoolshop/audiobooker --help
```

Ou instale globalmente:

```bash
npm install -g @mcptoolshop/audiobooker
```

Na primeira execução, é configurado um ambiente virtual gerenciado no diretório de dados do seu usuário (`~/.local/share/audiobooker` ou `%LOCALAPPDATA%\audiobooker` no Windows) e `audiobooker-ai` é instalado. Todas as execuções subsequentes iniciam instantaneamente.

**Requer Python 3.10+** no PATH (o wrapper encontra `python3` / `py`). Se estiver faltando, o wrapper informa exatamente como instalá-lo para o seu sistema operacional.

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

Análise, seleção, compilação e o fluxo de trabalho de revisão funcionam imediatamente. A **renderização de áudio** requer o motor TTS, que traz dependências mais pesadas — ative quando estiver pronto:

```bash
AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render
```

A renderização também requer **FFmpeg** no PATH para a montagem de M4B/MP3 (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). Execute `audiobooker diagnose` para verificar sua configuração.

## O que ele faz

- **Seleção de múltiplas vozes** com sugestões de vozes classificadas e explicáveis; `audiobooker audition <character>` permite testar diferentes vozes candidatas antes de tomar uma decisão.
- **Detecção de diálogo + atribuição de locutor** (opcional, com co-referência BookNLP), inferência de emoções e léxicos de pronúncia reutilizáveis.
- **Revisão antes da renderização**: exporte um script editável, corrija as atribuições, reimporte — nada é alterado silenciosamente.
- **Masterização compatível com ACX**: `render --acx` realiza a masterização para o padrão de áudio ACX — RMS entre −23 e −18 dBFS, pico em ou abaixo de −3, ruído de fundo em ou abaixo de −60 — e `master-check` indica se o resultado está APROVADO/REPROVADO em relação a esses três limites medidos.
Observe que cumprir o padrão não é o mesmo que ser aceito: o fluxo de envio padrão da ACX é para narrações humanas. Consulte o [arquivo README principal](https://github.com/mcp-tool-shop-org/audiobooker#where-an-ai-narrated-audiobook-can-actually-go) para conhecer os caminhos que aceitam títulos narrados por IA.
- **Atribuição auditável**: cada linha registra *como* o locutor foi determinado — uma etiqueta de fala, sua própria correção ou uma simples suposição de alternância — e `audiobooker report` conta as suposições separadamente das linhas para as quais não foi possível atribuir um locutor. Uma suposição não pode melhorar a pontuação.
- **Formatos**: M4B (marcadores de capítulo + capa incorporada + metadados da série), MP3, Opus, FLAC, WAV; exportação por capítulo; clipes de amostra para venda.
- **7 perfis de idioma** (en/fr/de/es/ja/it/pt) e um arquivo de configuração por livro para definir configurações padrão e esquecer.

## Variáveis de ambiente

| Variável | Efeito |
|---|---|
| `AUDIOBOOKER_INSTALL_EXTRAS=render` | Provisione o ambiente virtual gerenciado **com** o motor de voz (para renderização) |
| `AUDIOBOOKER_FORCE_REINSTALL=1` | Reconstrua o ambiente gerenciado do zero |
| `AUDIOBOOKER_BOOTSTRAP_ROOT=<dir>` | Substitua o local onde o ambiente virtual gerenciado está |

## Prefere pip?

```bash
pipx install audiobooker-ai            # isolated CLI install
pip install "audiobooker-ai[render]"   # with the voice engine
```

## Links

- **Documentação e manual:** <https://mcp-tool-shop-org.github.io/audiobooker/>
- **Código-fonte:** <https://github.com/mcp-tool-shop-org/audiobooker>
- **PyPI:** <https://pypi.org/project/audiobooker-ai/>

## Licença

[MIT](LICENSE) © mcp-tool-shop
