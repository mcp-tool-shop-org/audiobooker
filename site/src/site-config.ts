import type { SiteConfig } from '@mcptoolshop/site-theme';

export const config: SiteConfig = {
  title: 'Audiobooker',
  description: 'Convert EPUB/TXT/PDF/DOCX books into professionally narrated, multi-voice audiobooks (M4B/MP3/Opus/FLAC) with ACX/Audible-ready mastering.',
  logoBadge: 'AB',
  brandName: 'Audiobooker',
  repoUrl: 'https://github.com/mcp-tool-shop-org/audiobooker',
  footerText: 'MIT Licensed — built by <a href="https://github.com/mcp-tool-shop-org" style="color:var(--color-muted);text-decoration:underline">mcp-tool-shop-org</a>',

  hero: {
    badge: 'Open source',
    headline: 'Books deserve',
    headlineAccent: 'a voice.',
    description: 'Convert EPUB, PDF, DOCX, and text into professionally narrated, multi-voice audiobooks — with dialogue detection, emotion, and ACX/Audible-ready mastering.',
    primaryCta: { href: '#usage', label: 'Get started' },
    secondaryCta: { href: 'handbook/', label: 'Read the Handbook' },
    previews: [
      { label: 'One-shot', code: 'audiobooker make mybook.epub --acx' },
      { label: 'Audition', code: 'audiobooker audition Sarah --render' },
      { label: 'Master-check', code: 'audiobooker master-check book.m4b' },
    ],
  },

  sections: [
    {
      kind: 'features',
      id: 'features',
      title: 'Features',
      subtitle: 'Everything you need to turn text into audiobooks.',
      features: [
        { title: 'Multi-voice synthesis', desc: 'A distinct voice per character, with ranked suggestions and an audition command to A/B candidates before you commit.' },
        { title: 'Dialogue & emotion', desc: 'Detects quoted dialogue, attributes speakers (optional BookNLP co-reference), and infers emotion with adjustable intensity.' },
        { title: 'Many inputs', desc: 'EPUB, PDF, DOCX, Markdown, or a folder of per-chapter files — with TOC-driven chapter splitting and 7 language profiles.' },
        { title: 'ACX/Audible mastering', desc: 'render --acx masters to spec; master-check reports PASS/FAIL on loudness, peak, and noise floor.' },
        { title: 'Review before render', desc: 'A human-editable review format lets you correct attributions and emotions before a second of audio is rendered.' },
        { title: 'Pro output', desc: 'M4B (chapters + cover + series tags), MP3, Opus, FLAC; podcast RSS; persistent cache with resume.' },
      ],
    },
    {
      kind: 'code-cards',
      id: 'usage',
      title: 'Usage',
      cards: [
        {
          title: 'Install',
          code: `# Zero-install (Node)
npx @mcptoolshop/audiobooker --help

# Python
pipx install audiobooker-ai
pip install "audiobooker-ai[render]"   # with the TTS voice engine

# FFmpeg for audio assembly
# Windows: winget install ffmpeg
# macOS: brew install ffmpeg | Linux: apt install ffmpeg`,
        },
        {
          title: 'Quick workflow',
          code: `# One command: parse -> cast -> compile -> render -> master
audiobooker make mybook.epub --acx

# ...or staged, with control at each step:
audiobooker new mybook.epub
audiobooker cast --interactive
audiobooker compile
audiobooker render --acx
audiobooker master-check mybook.m4b`,
        },
      ],
    },
    {
      kind: 'code-cards',
      id: 'python-api',
      title: 'Python API',
      cards: [
        {
          title: 'From EPUB',
          code: `from audiobooker import AudiobookProject

project = AudiobookProject.from_epub("mybook.epub")
project.cast("narrator", "bm_george", emotion="calm")
project.cast("Alice", "af_bella", emotion="warm")
project.compile()
project.render("mybook.m4b")`,
        },
        {
          title: 'From text',
          code: `from audiobooker import AudiobookProject

project = AudiobookProject.from_string(
    "Chapter 1\\n\\nHello world.",
    title="My Book"
)
project.compile()
project.render("mybook.m4b")`,
        },
      ],
    },
    {
      kind: 'data-table',
      id: 'cli',
      title: 'CLI Commands',
      columns: ['Command', 'Description'],
      rows: [
        ['audiobooker make <file>', 'One-shot: new -> compile -> cast -> render'],
        ['audiobooker new <file|folder>', 'Create from EPUB/PDF/DOCX/TXT/MD or a folder'],
        ['audiobooker cast --interactive', 'Guided per-character casting'],
        ['audiobooker audition <char>', 'A/B candidate voices for one character'],
        ['audiobooker cast-fill / cast-preset', 'Bulk-assign / reusable cast presets'],
        ['audiobooker compile', 'Detect dialogue, attribute speakers, infer emotion'],
        ['audiobooker report', 'Compile quality: unknown rate + weak attributions'],
        ['audiobooker review-export / -import', 'Human-editable review round-trip'],
        ['audiobooker render --acx', 'Render + master to ACX/Audible spec'],
        ['audiobooker master-check <file>', 'PASS/FAIL vs ACX loudness/peak/noise'],
        ['audiobooker podcast / export-chapters', 'Podcast RSS / chapter cue sheet'],
        ['audiobooker diagnose', 'Check environment (deps, engine, FFmpeg)'],
      ],
    },
  ],
};
