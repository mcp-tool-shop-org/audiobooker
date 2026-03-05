import type { SiteConfig } from '@mcptoolshop/site-theme';

export const config: SiteConfig = {
  title: 'Audiobooker',
  description: 'AI Audiobook Generator — Convert EPUB/TXT books into professionally narrated audiobooks using multi-voice synthesis.',
  logoBadge: 'AB',
  brandName: 'Audiobooker',
  repoUrl: 'https://github.com/mcp-tool-shop-org/audiobooker',
  footerText: 'MIT Licensed — built by <a href="https://github.com/mcp-tool-shop-org" style="color:var(--color-muted);text-decoration:underline">mcp-tool-shop-org</a>',

  hero: {
    badge: 'Open source',
    headline: 'Books deserve',
    headlineAccent: 'a voice.',
    description: 'Convert EPUB and TXT books into professionally narrated audiobooks with multi-voice synthesis, dialogue detection, and emotion inference.',
    primaryCta: { href: '#usage', label: 'Get started' },
    secondaryCta: { href: 'handbook/', label: 'Read the Handbook' },
    previews: [
      { label: 'Create', code: 'audiobooker new mybook.epub' },
      { label: 'Cast', code: 'audiobooker cast narrator bm_george --emotion calm' },
      { label: 'Render', code: 'audiobooker render' },
    ],
  },

  sections: [
    {
      kind: 'features',
      id: 'features',
      title: 'Features',
      subtitle: 'Everything you need to turn text into audiobooks.',
      features: [
        { title: 'Multi-voice synthesis', desc: 'Assign unique voices to each character. Narration, dialogue, and inner monologue each get their own voice.' },
        { title: 'Dialogue detection', desc: 'Automatically identifies quoted dialogue vs narration and attributes speech to the correct speaker.' },
        { title: 'Emotion inference', desc: 'Rule-based and lexicon-powered emotion labeling gives each line the right tone and delivery.' },
        { title: 'Voice suggestions', desc: 'Explainable, ranked voice recommendations for every speaker based on character traits and context.' },
        { title: 'Review before render', desc: 'Human-editable review format lets you correct attributions and emotions before committing to audio.' },
        { title: 'Persistent cache', desc: 'Resume failed renders without re-synthesizing completed chapters. Pick up right where you left off.' },
      ],
    },
    {
      kind: 'code-cards',
      id: 'usage',
      title: 'Usage',
      cards: [
        {
          title: 'Install',
          code: `# Clone and install
git clone https://github.com/mcp-tool-shop-org/audiobooker
cd audiobooker
pip install -e .

# Required: voice-soundboard for TTS
pip install -e ../voice-soundboard

# Required: FFmpeg for audio assembly
# Windows: winget install ffmpeg
# Mac: brew install ffmpeg`,
        },
        {
          title: 'Quick workflow',
          code: `# Create project from EPUB
audiobooker new mybook.epub

# Get voice suggestions & auto-apply
audiobooker cast-suggest
audiobooker cast-apply --auto

# Compile, review, render
audiobooker compile
audiobooker review-export
audiobooker render`,
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
        ['audiobooker new <file>', 'Create project from EPUB/TXT'],
        ['audiobooker cast <char> <voice>', 'Assign voice to character'],
        ['audiobooker cast-suggest', 'Suggest voices for uncast speakers'],
        ['audiobooker cast-apply --auto', 'Auto-apply top voice suggestions'],
        ['audiobooker compile', 'Compile chapters to utterances'],
        ['audiobooker review-export', 'Export script for human review'],
        ['audiobooker review-import <file>', 'Import edited review file'],
        ['audiobooker render', 'Render audiobook to M4B'],
        ['audiobooker info', 'Show project information'],
        ['audiobooker voices', 'List available voices'],
        ['audiobooker chapters', 'List chapters'],
        ['audiobooker speakers', 'List detected speakers'],
      ],
    },
  ],
};
