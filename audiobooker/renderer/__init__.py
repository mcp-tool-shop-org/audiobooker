"""
Renderer module for Audiobooker.

Handles:
- Chapter-by-chapter audio synthesis
- Progress tracking
- M4B assembly with chapter markers
"""

from audiobooker.renderer.engine import render_project, render_chapter, RenderError, RenderSummary
from audiobooker.renderer.output import assemble_m4b, AssemblyResult
from audiobooker.renderer.protocols import TTSEngine, SynthesisResult
from audiobooker.renderer.cache_manifest import CacheManifest, load_manifest, save_manifest

__all__ = [
    "render_project",
    "render_chapter",
    "RenderError",
    "RenderSummary",
    "assemble_m4b",
    "AssemblyResult",
    "TTSEngine",
    "SynthesisResult",
    "CacheManifest",
    "load_manifest",
    "save_manifest",
]
