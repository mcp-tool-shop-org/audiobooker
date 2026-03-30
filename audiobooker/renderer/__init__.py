"""
Renderer module for Audiobooker.

Handles:
- Chapter-by-chapter audio synthesis
- Progress tracking
- M4B assembly with chapter markers
"""

from audiobooker.renderer.engine import (
    render_project, render_chapter, RenderError, RenderSummary,
    validate_casting_completeness, dry_run_render,
    preprocess_ssml, should_use_ssml,
    parse_chapter_ranges, filter_chapters_by_selection,
)
from audiobooker.renderer.output import assemble_m4b, assemble_mp3, AssemblyResult
from audiobooker.renderer.protocols import TTSEngine, SynthesisResult, AssemblerProtocol
from audiobooker.renderer.cache_manifest import CacheManifest, load_manifest, save_manifest

__all__ = [
    "render_project",
    "render_chapter",
    "RenderError",
    "RenderSummary",
    "validate_casting_completeness",
    "dry_run_render",
    "preprocess_ssml",
    "should_use_ssml",
    "parse_chapter_ranges",
    "filter_chapters_by_selection",
    "assemble_m4b",
    "assemble_mp3",
    "AssemblyResult",
    "TTSEngine",
    "SynthesisResult",
    "AssemblerProtocol",
    "CacheManifest",
    "load_manifest",
    "save_manifest",
]
