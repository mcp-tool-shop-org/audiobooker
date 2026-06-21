"""
Audiobooker parsers for various input formats.

Supported formats:
- EPUB (.epub)
- PDF (.pdf)
- DOCX (.docx)
- Plain text (.txt)
- Markdown (.md)
- Folder of per-chapter text/Markdown files
"""

# F-CORE-B-016: Lazy import for epub to avoid hard dependency on ebooklib
from audiobooker.parser.text import parse_text, read_folder_chapters
from audiobooker.parser.text_cleaners import (
    clean_text,
    apply_pronunciation_overrides,
    strip_page_numbers,
    strip_markdown_inline,
    normalize_whitespace,
    expand_common_abbreviations,
    decode_html_entities,
    load_lexicon,
    save_lexicon,
    Lexicon,
)


def __getattr__(name: str):
    if name == "parse_epub":
        from audiobooker.parser.epub import parse_epub
        return parse_epub
    if name == "parse_pdf":
        from audiobooker.parser.pdf import parse_pdf
        return parse_pdf
    if name == "parse_docx":
        from audiobooker.parser.docx import parse_docx
        return parse_docx
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "parse_epub",
    "parse_pdf",
    "parse_docx",
    "parse_text",
    "read_folder_chapters",
    "clean_text",
    "apply_pronunciation_overrides",
    "strip_page_numbers",
    "strip_markdown_inline",
    "normalize_whitespace",
    "expand_common_abbreviations",
    "decode_html_entities",
    "load_lexicon",
    "save_lexicon",
    "Lexicon",
]
