"""
Audiobooker parsers for various input formats.

Supported formats:
- EPUB (.epub)
- Plain text (.txt)
- Markdown (.md)
"""

from audiobooker.parser.epub import parse_epub
from audiobooker.parser.text import parse_text

__all__ = ["parse_epub", "parse_text"]
