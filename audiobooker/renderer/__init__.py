"""
Renderer module for Audiobooker.

Handles:
- Chapter-by-chapter audio synthesis
- Progress tracking
- M4B assembly with chapter markers
"""

from audiobooker.renderer.engine import render_project, render_chapter
from audiobooker.renderer.output import assemble_m4b

__all__ = ["render_project", "render_chapter", "assemble_m4b"]
