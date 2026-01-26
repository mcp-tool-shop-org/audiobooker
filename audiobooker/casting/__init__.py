"""
Casting module for Audiobooker.

Handles:
- Dialogue detection (quoted text vs narration)
- Speaker attribution
- Compiling chapters to utterances
"""

from audiobooker.casting.dialogue import (
    compile_chapter,
    detect_dialogue,
    parse_inline_override,
)

__all__ = ["compile_chapter", "detect_dialogue", "parse_inline_override"]
