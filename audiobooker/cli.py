# PYTHON_ARGCOMPLETE_OK
"""
Command-Line Interface for Audiobooker.

Usage:
    audiobooker new book.epub              # Create project from EPUB
    audiobooker new book.docx              # Create project from Word (.docx)
    audiobooker new book.pdf               # Create project from PDF
    audiobooker new book.txt               # Create project from text
    audiobooker new chapters/              # Create project from a folder of chapter files
    audiobooker new book.pdf --force-text  # Force text extraction (scanned PDFs)
    audiobooker new book.txt --chapter-delimiter "^Scene [0-9]+"  # Custom chapter split
    audiobooker cast narrator af_bella     # Assign voice to character
    audiobooker cast-export cast.json      # Export casting table (JSON)
    audiobooker cast-export cast.csv       # Export casting table (CSV cast sheet)
    audiobooker cast-import cast.csv       # Import casting table (CSV or JSON)
    audiobooker cast-fill --voices af_sky,am_liam --narrator af_heart  # Bulk-cast
    audiobooker cast-preset save mycast    # Save current cast as a preset
    audiobooker cast-preset apply mycast   # Apply a saved casting preset
    audiobooker speakers --suggest-aliases # Propose aliases per character
    audiobooker emotions presets           # List emotion preset packs + vocab
    audiobooker emotions mood-span 0 0 500 tense  # Mark a chapter span's mood
    audiobooker compile --emotion-preset dramatic # Compile with a preset pack
    audiobooker compile                    # Compile chapters to utterances
    audiobooker compile --dry-run          # Preview speaker/line summary
    audiobooker render                     # Render audiobook
    audiobooker render --dry-run           # Preview render without executing
    audiobooker render --cover cover.jpg   # Render with cover art
    audiobooker render --acx               # Master for ACX retail (-20 LUFS)
    audiobooker render --split             # One file per chapter
    audiobooker sample --duration 120      # Render a mastered retail sample
    audiobooker master-check book.m4b      # Check ACX loudness/peak compliance
    audiobooker export-chapters --format cue  # Export chapter markers
    audiobooker batch *.epub               # Batch process multiple files
    audiobooker batch *.epub --dry-run     # Preview batch without rendering
    audiobooker emotions list              # List emotion summary per chapter
    audiobooker emotions override 0 5 sad  # Override emotion on utterance
    audiobooker chapters                   # List chapters
    audiobooker chapters merge 0 2         # Merge chapters 0-2
    audiobooker chapters split 3 5         # Split chapter 3 at paragraph 5
    audiobooker chapters exclude 4         # Exclude chapter from render
    audiobooker chapters include 4         # Re-include excluded chapter
    audiobooker pronunciation add word rep # Add pronunciation override
    audiobooker pronunciation remove word  # Remove pronunciation override
    audiobooker pronunciation list         # List all overrides
    audiobooker pronunciation import lex.csv  # Import a pronunciation lexicon
    audiobooker pronunciation export lex.csv  # Export overrides to a lexicon file
    audiobooker status                     # Show render/cache status
    audiobooker cache info                 # Show cache statistics
    audiobooker cache clean                # Delete all cached audio
    audiobooker cache clean-failed         # Reset failed cache entries
    audiobooker info                       # Show project info
    audiobooker voices                     # List available voices
"""

from __future__ import annotations

import argparse
import logging as _logging_mod
import re
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audiobooker.renderer.engine import RenderError
from pathlib import Path
from typing import Optional


# Canonical install hint for the optional TTS backend. voice-soundboard IS on
# PyPI, so always point users at the published package, never a local path.
VOICE_SOUNDBOARD_INSTALL_HINT = (
    "Install with: pip install voice-soundboard  "
    "(or: pip install 'audiobooker-ai[render]'). "
    "Run 'audiobooker diagnose' to check your environment."
)

# Module-level quiet flag. main() sets this from --silent so the _out() wrapper
# can suppress normal progress/success output without touching error paths.
_QUIET = False

# Exit-code taxonomy: these are "the user gave us something wrong" errors
# (missing file, bad index/value, missing key). Handlers catch these and
# return 1. Anything else propagates to main()'s outer handler -> exit 2,
# distinguishing user mistakes from unexpected internal failures.
USER_ERROR_TYPES = (FileNotFoundError, ValueError, IndexError, KeyError)


def _out(*args, **kwargs) -> None:
    """Print normal (non-error) output unless --silent suppressed it.

    Errors and warnings always go through plain print()/stderr so --silent
    never hides a problem the user needs to see.
    """
    if not _QUIET:
        print(*args, **kwargs)


def _report_error(e: BaseException, args: "argparse.Namespace | None" = None) -> None:
    """Print a structured, user-facing error message.

    Prints "Error: {e}", then a "Hint: {hint}" line if the exception carries a
    structured .hint attribute, and the full traceback when --debug is set.
    Errors always print (never suppressed by --silent).
    """
    print(f"Error: {e}")
    hint = getattr(e, "hint", None)
    if hint:
        print(f"Hint: {hint}")
    if getattr(args, "debug", False):
        import traceback
        traceback.print_exc()


def _audiobooker_file_completer(prefix, **kwargs):
    """FT-CLI-004: argcomplete completer suggesting *.audiobooker files.

    Returns project files in the current directory whose name starts with the
    typed prefix. Imported lazily / used only when argcomplete is installed.
    """
    try:
        return [
            str(p)
            for p in Path(".").glob("*.audiobooker")
            if str(p).startswith(prefix)
        ]
    except OSError:
        return []


# Patterns that look like secrets/tokens — redacted in all log output.
# Require an explicit "=" or ":" assignment separator (e.g. token=abc,
# api_key: xyz) so ordinary prose like "unknown config key 'foo'" — a bare word
# followed by whitespace — is NOT mistaken for a secret. Matching on whitespace
# alone produced false positives that clobbered legitimate log messages.
_SECRET_PATTERNS = re.compile(
    r"((?:token|key|secret|password|credential|auth)\s*[=:]\s*)\S+",
    re.IGNORECASE,
)


class _SecretRedactFilter(_logging_mod.Filter):
    """Redact anything that looks like a secret from log records.

    Redacts the FULLY-RENDERED message (after %-arg substitution) and clears
    ``record.args`` so the logging machinery does not re-apply %-formatting.
    Redacting the raw format string instead would corrupt %-placeholders when a
    secret-like word (e.g. "key %r") sits next to one, raising a TypeError at
    format time — so always render first, then redact.
    """

    def filter(self, record: _logging_mod.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            # Never let redaction break logging; pass the record through.
            return True
        record.msg = _SECRET_PATTERNS.sub(r"\1[REDACTED]", rendered)
        record.args = None
        return True


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    from audiobooker import __version__

    parser = argparse.ArgumentParser(
        prog="audiobooker",
        description="AI Audiobook Generator - Convert books to narrated audiobooks",
    )
    parser.add_argument(
        "--version", action="version", version=f"audiobooker {__version__}"
    )

    # Global logging-level flags (silent < normal < verbose < debug)
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "--silent", action="store_true", help="Suppress all output except errors"
    )
    log_group.add_argument(
        "--debug", action="store_true",
        help="Enable debug output including stack traces",
    )

    # Shared parent parser so --silent/--debug also work AFTER the subcommand
    # (e.g. `audiobooker render --debug`, not only `audiobooker --debug render`).
    # default=SUPPRESS so a subparser's copy of these flags only lands in the
    # namespace when actually passed — otherwise it would clobber a value set
    # by the top-level parser (making `audiobooker --debug render` silently
    # drop --debug).
    common = argparse.ArgumentParser(add_help=False)
    common_group = common.add_mutually_exclusive_group()
    common_group.add_argument(
        "--silent", action="store_true", default=argparse.SUPPRESS,
        help="Suppress all output except errors",
    )
    common_group.add_argument(
        "--debug", action="store_true", default=argparse.SUPPRESS,
        help="Enable debug output including stack traces",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Every top-level subcommand inherits --silent/--debug from `common`.
    # Wrap add_parser so each subparser gets parents=[common] automatically
    # (sub-subparsers like `cache info` inherit through their own parent).
    _orig_add_parser = subparsers.add_parser

    def _add_parser(name, **kwargs):
        parents = list(kwargs.pop("parents", []))
        if common not in parents:
            parents.append(common)
        return _orig_add_parser(name, parents=parents, **kwargs)

    subparsers.add_parser = _add_parser  # type: ignore[assignment]

    # --- new ---
    new_parser = subparsers.add_parser(
        "new", help="Create new project from source file"
    )
    new_parser.add_argument(
        "source", help="Source file (EPUB, DOCX, TXT, MD, PDF) or a folder of chapter files"
    )
    new_parser.add_argument("-o", "--output", help="Output project file path")
    new_parser.add_argument(
        "--lang", default="en", metavar="CODE", help="Language code (default: en)"
    )
    new_parser.add_argument(
        "--booknlp",
        default="auto",
        choices=["on", "off", "auto"],
        help="BookNLP speaker resolution (default: auto)",
    )
    # INPUT (v2.1): custom chapter-split regex for TXT/MD sources.
    new_parser.add_argument(
        "--chapter-delimiter",
        metavar="REGEX",
        dest="chapter_delimiter",
        help="Custom regex to split chapters (TXT/MD sources)",
    )
    # INPUT (v2.1): force plain-text extraction for image-only/scanned PDFs.
    new_parser.add_argument(
        "--force-text",
        action="store_true",
        dest="force_text",
        help="Force text extraction for PDFs that look scanned/image-only",
    )

    # --- load ---
    load_parser = subparsers.add_parser("load", help="Load existing project")
    load_parser.add_argument("project", help="Project file (.audiobooker)")

    # --- cast ---
    cast_parser = subparsers.add_parser("cast", help="Assign voice to character")
    # FT-CLI-003: with --interactive, character/voice are optional (the command
    # walks every uncast speaker), so make the positionals nargs="?".
    cast_parser.add_argument("character", nargs="?", help="Character name")
    cast_parser.add_argument(
        "voice", nargs="?", help="Voice ID (e.g., af_bella, bm_george)"
    )
    cast_parser.add_argument("-e", "--emotion", help="Default emotion")
    cast_parser.add_argument("-d", "--description", help="Character description")
    cast_parser.add_argument(
        "-p", "--project", help="Project file (auto-detected if omitted)"
    )
    # FT-CLI-003: interactive casting walkthrough for uncast speakers.
    cast_parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Interactively cast each uncast speaker (prompts per speaker)",
    )

    # --- cast-suggest ---
    suggest_parser = subparsers.add_parser(
        "cast-suggest", help="Suggest voices for uncast speakers"
    )
    suggest_parser.add_argument("-p", "--project", help="Project file")
    suggest_parser.add_argument(
        "-n", "--top", type=int, default=3, help="Show top N suggestions per speaker"
    )

    # --- cast-apply ---
    apply_parser = subparsers.add_parser(
        "cast-apply", help="Auto-apply voice suggestions"
    )
    apply_parser.add_argument("-p", "--project", help="Project file")
    apply_parser.add_argument(
        "--auto",
        action="store_true",
        help="Apply top suggestion for all uncast speakers",
    )

    # --- compile ---
    compile_parser = subparsers.add_parser(
        "compile", help="Compile chapters to utterances"
    )
    compile_parser.add_argument("-p", "--project", help="Project file")
    compile_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview speaker/line/sample summary without compiling",
    )
    # CASTING-DEPTH (v2.1): pick an emotion preset pack for this compile.
    compile_parser.add_argument(
        "--emotion-preset",
        choices=["neutral", "literary", "dramatic", "children"],
        default=None,
        dest="emotion_preset",
        help="Emotion preset pack (sets project emotion_preset; default: keep current)",
    )

    # --- render ---
    render_parser = subparsers.add_parser("render", help="Render audiobook")
    render_parser.add_argument("-p", "--project", help="Project file")
    render_parser.add_argument("-o", "--output", help="Output file path")
    render_parser.add_argument(
        "-c", "--chapter", type=int, help="Render single chapter (0-indexed)"
    )
    render_parser.add_argument(
        "--no-resume", action="store_true", help="Force full re-render (ignore cache)"
    )
    render_parser.add_argument(
        "--from-chapter",
        type=int,
        metavar="N",
        help="Start rendering from chapter N (0-indexed)",
    )
    render_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Assemble even if some chapters failed",
    )
    render_parser.add_argument(
        "--clean-cache", action="store_true", help="Delete render cache before starting"
    )
    # FT-RENDER-001: Parallel chapter rendering
    render_parser.add_argument(
        "-j", "--jobs", "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel render workers (default: 1)",
    )
    # FT-RENDER-003: Output format selection
    render_parser.add_argument(
        "--format",
        choices=["m4b", "mp3", "wav"],
        default=None,
        dest="output_format",
        help="Output format (default: from project config, usually m4b)",
    )
    # FT-RENDER-011: Force past casting validation
    render_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass casting completeness validation",
    )
    # FT-RENDER-011: Convenience auto-cast before render
    render_parser.add_argument(
        "--cast-suggest",
        action="store_true",
        help="Auto-apply voice suggestions for uncast speakers before render",
    )
    # FT-RENDER-004: Dry-run render mode
    render_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be rendered without actually rendering",
    )
    # FT-RENDER-006: Cover art embedding
    render_parser.add_argument(
        "--cover",
        metavar="PATH",
        help="Cover art image to embed in output (JPG/PNG)",
    )
    # FT-RENDER-017: Chapter selection
    render_parser.add_argument(
        "--chapters",
        metavar="RANGES",
        help="Chapter ranges to render, e.g. '1-14,21-30' (1-based)",
    )
    render_parser.add_argument(
        "--exclude-chapters",
        metavar="RANGES",
        help="Chapter ranges to exclude, e.g. '15-20' (1-based)",
    )
    # FT-RENDER-019: Audio normalization
    render_parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply EBU R128 loudness normalization (-16 LUFS) to final audio",
    )
    # FT-RENDER-020: Desktop notification
    render_parser.add_argument(
        "--notify",
        action="store_true",
        help="Send desktop notification on render completion or failure",
    )
    # OUTPUT-F1: ACX / output-profile mastering
    render_parser.add_argument(
        "--acx",
        action="store_true",
        help="Master for ACX/audiobook retail (loudnorm -20 LUFS, 192k); "
             "sets output_profile=acx",
    )
    render_parser.add_argument(
        "--bitrate",
        metavar="RATE",
        help="Encoder bitrate override, e.g. 192k (default: profile-dependent)",
    )
    render_parser.add_argument(
        "--split",
        action="store_true",
        help="Emit one file per chapter instead of a single combined file",
    )
    # OUTPUT-F1: Per-render metadata overrides (filled onto project.metadata)
    render_parser.add_argument(
        "--narrator",
        metavar="NAME",
        help="Set the narrator credit embedded in the output",
    )
    render_parser.add_argument(
        "--genre",
        metavar="GENRE",
        help="Set the genre tag embedded in the output",
    )
    render_parser.add_argument(
        "--series",
        metavar="NAME",
        help="Set the series name embedded in the output",
    )
    # FT-CLI-008: watch mode — re-render on source-file change.
    render_parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the source file and re-render (resume) whenever it changes",
    )

    # --- info ---
    info_parser = subparsers.add_parser("info", help="Show project information")
    info_parser.add_argument("-p", "--project", help="Project file")
    info_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed info"
    )
    info_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- voices ---
    voices_parser = subparsers.add_parser("voices", help="List available voices")
    voices_parser.add_argument("-g", "--gender", help="Filter by gender (male/female)")
    voices_parser.add_argument("-s", "--search", help="Search by name/description")

    # --- chapters ---
    chapters_parser = subparsers.add_parser("chapters", help="List chapters")
    chapters_parser.add_argument("-p", "--project", help="Project file")

    # --- speakers ---
    speakers_parser = subparsers.add_parser("speakers", help="List detected speakers")
    speakers_parser.add_argument("-p", "--project", help="Project file")
    # CASTING-DEPTH (v2.1): rank alias suggestions per character.
    speakers_parser.add_argument(
        "--suggest-aliases",
        action="store_true",
        dest="suggest_aliases",
        help="Propose ranked alias suggestions per character",
    )
    speakers_parser.add_argument(
        "--apply",
        action="store_true",
        help="With --suggest-aliases: apply the proposed aliases to the cast",
    )
    speakers_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- from-stdin ---
    stdin_parser = subparsers.add_parser(
        "from-stdin",
        help="Create project from stdin text",
    )
    stdin_parser.add_argument("-t", "--title", default="Untitled", help="Book title")
    stdin_parser.add_argument("-a", "--author", default="", help="Author name")
    stdin_parser.add_argument(
        "--lang", default="en", metavar="CODE", help="Language code (default: en)"
    )
    # INPUT (v2.1): custom chapter-split regex for piped text.
    stdin_parser.add_argument(
        "--chapter-delimiter",
        metavar="REGEX",
        dest="chapter_delimiter",
        help="Custom regex to split chapters",
    )
    stdin_parser.add_argument("-o", "--output", help="Output project file path")

    # --- review-export ---
    review_export_parser = subparsers.add_parser(
        "review-export",
        help="Export compiled script for human review",
    )
    review_export_parser.add_argument("-p", "--project", help="Project file")
    review_export_parser.add_argument("-o", "--output", help="Output file path")

    # --- review-import ---
    review_import_parser = subparsers.add_parser(
        "review-import",
        help="Import edited review file back into project",
    )
    review_import_parser.add_argument("review_file", help="Edited review file")
    review_import_parser.add_argument("-p", "--project", help="Project file")

    # --- status (FT-RENDER-002) ---
    status_parser = subparsers.add_parser(
        "status", help="Show render cache status and project overview"
    )
    status_parser.add_argument("-p", "--project", help="Project file")
    status_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- cache (FT-RENDER-009) ---
    cache_parser = subparsers.add_parser(
        "cache", help="Cache management commands"
    )
    cache_sub = cache_parser.add_subparsers(dest="cache_command", help="Cache sub-commands")

    cache_info_parser = cache_sub.add_parser("info", help="Show cache statistics")
    cache_info_parser.add_argument("-p", "--project", help="Project file")

    cache_clean_parser = cache_sub.add_parser("clean", help="Delete all cached audio")
    cache_clean_parser.add_argument("-p", "--project", help="Project file")

    cache_clean_failed_parser = cache_sub.add_parser(
        "clean-failed", help="Delete failed cache entries and reset them"
    )
    cache_clean_failed_parser.add_argument("-p", "--project", help="Project file")

    # --- report (FT-CAST-014 wiring) ---
    report_parser = subparsers.add_parser(
        "report",
        help="Show compile quality report (unknown rate, unattributed lines, emotions)",
    )
    report_parser.add_argument("-p", "--project", help="Project file")
    report_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- diagnose ---
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Check environment: dependencies, voice engine, ffmpeg",
    )
    diagnose_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- FT-RENDER-012: batch ---
    batch_parser = subparsers.add_parser(
        "batch",
        help="Batch process multiple source files (EPUB/DOCX/TXT/PDF or chapter folders)",
    )
    batch_parser.add_argument(
        "files",
        nargs="*",
        help="Source files or glob patterns (e.g. '*.epub')",
    )
    # FT-CLI-006: manifest-driven batch (per-book title/author/cover/cast/...).
    batch_parser.add_argument(
        "--manifest",
        metavar="FILE",
        help="Manifest file (.toml or .json) describing per-book metadata + casting",
    )
    batch_parser.add_argument(
        "--format",
        choices=["m4b", "mp3", "wav"],
        default=None,
        dest="output_format",
        help="Output format (default: m4b)",
    )
    batch_parser.add_argument(
        "-j", "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel render workers per book (default: 1)",
    )
    batch_parser.add_argument(
        "--lang",
        default="en",
        metavar="CODE",
        help="Language code (default: en)",
    )
    batch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without rendering",
    )
    batch_parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit the per-book results array as JSON",
    )

    # --- FT-RENDER-007: preview ---
    preview_parser = subparsers.add_parser(
        "preview",
        help="Render a short sample for voice validation",
    )
    preview_parser.add_argument("-p", "--project", help="Project file")
    preview_parser.add_argument(
        "--chapter",
        type=int,
        default=0,
        metavar="N",
        help="Chapter index to preview (0-based, default: 0)",
    )
    preview_parser.add_argument(
        "--seconds",
        type=int,
        default=30,
        metavar="S",
        help="Approximate sample length in seconds (default: 30)",
    )
    preview_parser.add_argument(
        "-o", "--output",
        help="Output file path (default: preview.wav)",
    )

    # --- OUTPUT-F1: sample (retail sample clip) ---
    sample_parser = subparsers.add_parser(
        "sample",
        help="Render a mastered retail sample clip (distinct from 'preview')",
    )
    sample_parser.add_argument("-p", "--project", help="Project file")
    sample_parser.add_argument(
        "--from-chapter",
        type=int,
        default=0,
        metavar="N",
        help="Chapter index to sample from (0-based, default: 0)",
    )
    sample_parser.add_argument(
        "--start-seconds",
        type=float,
        default=0.0,
        metavar="S",
        help="Offset into the chapter to start the sample (default: 0)",
    )
    sample_parser.add_argument(
        "--duration",
        type=float,
        default=180.0,
        metavar="S",
        help="Sample length in seconds (default: 180)",
    )
    sample_parser.add_argument(
        "--acx",
        action="store_true",
        help="Master the sample for ACX (sets output_profile=acx)",
    )
    sample_parser.add_argument(
        "--bitrate",
        metavar="RATE",
        help="Encoder bitrate override, e.g. 192k",
    )
    sample_parser.add_argument(
        "-o", "--output",
        help="Output file path (default: sample.<ext>)",
    )

    # --- OUTPUT-F1: master-check (ACX compliance check) ---
    master_check_parser = subparsers.add_parser(
        "master-check",
        help="Check an audio file against ACX loudness/peak/noise-floor limits",
    )
    master_check_parser.add_argument(
        "file", help="Audio file to check (WAV/MP3/M4B/etc.)"
    )
    master_check_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- OUTPUT-F1: export-chapters (chapter metadata sidecar) ---
    export_chapters_parser = subparsers.add_parser(
        "export-chapters",
        help="Export chapter markers as ffmetadata, CUE, or JSON",
    )
    export_chapters_parser.add_argument("-p", "--project", help="Project file")
    export_chapters_parser.add_argument(
        "--format",
        choices=["ffmetadata", "cue", "json"],
        default="ffmetadata",
        dest="chapter_format",
        help="Chapter metadata format (default: ffmetadata)",
    )
    export_chapters_parser.add_argument(
        "-o", "--output",
        help="Output file path (default: stdout)",
    )

    # --- cast-export ---
    cast_export_parser = subparsers.add_parser(
        "cast-export", help="Export casting table to a JSON or CSV file"
    )
    cast_export_parser.add_argument("path", help="Output file path (.json or .csv)")
    cast_export_parser.add_argument("-p", "--project", help="Project file")
    # CASTING-DEPTH (v2.1): CSV cast sheets. Default None -> infer from the
    # file extension (.csv -> CSV, else JSON).
    cast_export_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default=None,
        dest="cast_format",
        help="Cast sheet format (default: infer from file extension)",
    )

    # --- cast-import ---
    cast_import_parser = subparsers.add_parser(
        "cast-import", help="Import casting table from a JSON or CSV file"
    )
    cast_import_parser.add_argument("path", help="Input file path (.json or .csv)")
    cast_import_parser.add_argument("-p", "--project", help="Project file")
    cast_import_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default=None,
        dest="cast_format",
        help="Cast sheet format (default: infer from file extension)",
    )

    # --- cast-preset (CASTING-DEPTH v2.1) ---
    cast_preset_parser = subparsers.add_parser(
        "cast-preset",
        help="Save / list / apply / delete reusable casting presets",
    )
    cast_preset_sub = cast_preset_parser.add_subparsers(
        dest="cast_preset_command", help="cast-preset sub-commands"
    )

    cp_save_parser = cast_preset_sub.add_parser(
        "save", help="Save the current casting table as a named preset"
    )
    cp_save_parser.add_argument("name", help="Preset name")
    cp_save_parser.add_argument("-p", "--project", help="Project file")
    cp_save_parser.add_argument(
        "--from-project",
        metavar="PATH",
        dest="from_project",
        help="Seed the preset from another project file instead of the current one",
    )

    cp_list_parser = cast_preset_sub.add_parser(
        "list", help="List saved casting presets"
    )
    cp_list_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    cp_apply_parser = cast_preset_sub.add_parser(
        "apply", help="Apply a saved preset to the project, merging by name/alias"
    )
    cp_apply_parser.add_argument("name", help="Preset name")
    cp_apply_parser.add_argument("-p", "--project", help="Project file")

    cp_delete_parser = cast_preset_sub.add_parser(
        "delete", help="Delete a saved casting preset"
    )
    cp_delete_parser.add_argument("name", help="Preset name")

    # --- cast-fill (CASTING-DEPTH v2.1) ---
    cast_fill_parser = subparsers.add_parser(
        "cast-fill",
        help="Bulk-assign voices to uncast speakers from explicit voice pools",
    )
    cast_fill_parser.add_argument("-p", "--project", help="Project file")
    cast_fill_parser.add_argument(
        "--gender",
        choices=["male", "female"],
        help="Restrict the round-robin pool to one gender",
    )
    cast_fill_parser.add_argument(
        "--voices",
        metavar="a,b,c",
        help="Comma-separated voice pool to round-robin across uncast speakers",
    )
    cast_fill_parser.add_argument(
        "--narrator",
        metavar="VOICE",
        help="Voice to assign to the narrator",
    )
    cast_fill_parser.add_argument(
        "--minor-voice",
        metavar="VOICE",
        dest="minor_voice",
        help="Voice for minor speakers (fewer than --minor-threshold lines)",
    )
    cast_fill_parser.add_argument(
        "--minor-threshold",
        type=int,
        default=5,
        metavar="N",
        dest="minor_threshold",
        help="Line count at/under which a speaker counts as minor (default: 5)",
    )
    cast_fill_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reassign speakers that are already cast",
    )

    # --- emotions ---
    emotions_parser = subparsers.add_parser(
        "emotions", help="Emotion management commands"
    )
    emotions_sub = emotions_parser.add_subparsers(
        dest="emotions_command", help="Emotions sub-commands"
    )

    emotions_list_parser = emotions_sub.add_parser(
        "list", help="List emotion summary per chapter"
    )
    emotions_list_parser.add_argument("-p", "--project", help="Project file")

    emotions_override_parser = emotions_sub.add_parser(
        "override", help="Override emotion on a specific utterance"
    )
    emotions_override_parser.add_argument(
        "chapter", type=int, help="Chapter index (0-based)"
    )
    emotions_override_parser.add_argument(
        "line", type=int, help="Utterance/line index (0-based)"
    )
    emotions_override_parser.add_argument("emotion", help="New emotion label")
    emotions_override_parser.add_argument("-p", "--project", help="Project file")

    # CASTING-DEPTH (v2.1): mark a chapter character-span with a mood.
    emotions_mood_span_parser = emotions_sub.add_parser(
        "mood-span",
        help="Apply an emotion across a character span of a chapter (scene mood)",
    )
    emotions_mood_span_parser.add_argument(
        "chapter", type=int, help="Chapter index (0-based)"
    )
    emotions_mood_span_parser.add_argument(
        "start", type=int, help="Start character offset into the chapter (inclusive)"
    )
    emotions_mood_span_parser.add_argument(
        "end", type=int, help="End character offset (exclusive)"
    )
    emotions_mood_span_parser.add_argument("emotion", help="Mood/emotion label")
    emotions_mood_span_parser.add_argument("-p", "--project", help="Project file")

    # CASTING-DEPTH (v2.1): list emotion preset packs + the known vocabulary.
    emotions_presets_parser = emotions_sub.add_parser(
        "presets",
        help="List emotion preset packs and the known emotion vocabulary",
    )
    emotions_presets_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- chapters subcommands ---
    chapters_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed chapter info"
    )
    chapters_sub = chapters_parser.add_subparsers(
        dest="chapters_command", help="Chapter management sub-commands"
    )

    ch_merge_parser = chapters_sub.add_parser(
        "merge", help="Merge a range of chapters"
    )
    ch_merge_parser.add_argument("start", type=int, help="Start chapter index (0-based)")
    ch_merge_parser.add_argument("end", type=int, help="End chapter index (0-based, inclusive)")
    ch_merge_parser.add_argument("-p", "--project", help="Project file")

    ch_split_parser = chapters_sub.add_parser(
        "split", help="Split a chapter at a paragraph boundary"
    )
    ch_split_parser.add_argument("index", type=int, help="Chapter index (0-based)")
    ch_split_parser.add_argument(
        "paragraph", type=int, help="Paragraph number to split at (0-based)"
    )
    ch_split_parser.add_argument("-p", "--project", help="Project file")

    ch_exclude_parser = chapters_sub.add_parser(
        "exclude", help="Exclude a chapter from rendering"
    )
    ch_exclude_parser.add_argument("index", type=int, help="Chapter index (0-based)")
    ch_exclude_parser.add_argument("-p", "--project", help="Project file")

    ch_include_parser = chapters_sub.add_parser(
        "include", help="Re-include a previously excluded chapter"
    )
    ch_include_parser.add_argument("index", type=int, help="Chapter index (0-based)")
    ch_include_parser.add_argument("-p", "--project", help="Project file")

    # FT-PARSE-006: rename / reorder chapters.
    ch_rename_parser = chapters_sub.add_parser(
        "rename", help="Rename a chapter by index"
    )
    ch_rename_parser.add_argument("index", type=int, help="Chapter index (0-based)")
    ch_rename_parser.add_argument("title", help="New chapter title")
    ch_rename_parser.add_argument("-p", "--project", help="Project file")

    ch_reorder_parser = chapters_sub.add_parser(
        "reorder", help="Reorder chapters by a comma-separated permutation"
    )
    ch_reorder_parser.add_argument(
        "order",
        help="New order as comma-separated 0-based indices, e.g. '2,0,1' "
             "(must be a permutation of all chapters)",
    )
    ch_reorder_parser.add_argument("-p", "--project", help="Project file")

    # --- pronunciation ---
    pronunciation_parser = subparsers.add_parser(
        "pronunciation", help="Pronunciation override management"
    )
    pronunciation_sub = pronunciation_parser.add_subparsers(
        dest="pronunciation_command", help="Pronunciation sub-commands"
    )

    pron_add_parser = pronunciation_sub.add_parser(
        "add", help="Add a pronunciation override"
    )
    pron_add_parser.add_argument("word", help="Word or phrase to replace")
    pron_add_parser.add_argument("replacement", help="Replacement pronunciation")
    pron_add_parser.add_argument("-p", "--project", help="Project file")

    pron_remove_parser = pronunciation_sub.add_parser(
        "remove", help="Remove a pronunciation override"
    )
    pron_remove_parser.add_argument("word", help="Word to remove override for")
    pron_remove_parser.add_argument("-p", "--project", help="Project file")

    pron_list_parser = pronunciation_sub.add_parser(
        "list", help="List all pronunciation overrides"
    )
    pron_list_parser.add_argument("-p", "--project", help="Project file")

    # INPUT (v2.1): import/export a pronunciation lexicon (CSV or JSON).
    pron_import_parser = pronunciation_sub.add_parser(
        "import", help="Import a pronunciation lexicon (CSV or JSON)"
    )
    pron_import_parser.add_argument("file", help="Lexicon file to import (.csv or .json)")
    pron_import_parser.add_argument("-p", "--project", help="Project file")

    pron_export_parser = pronunciation_sub.add_parser(
        "export", help="Export pronunciation overrides to a lexicon file"
    )
    pron_export_parser.add_argument("file", help="Output lexicon file (.csv or .json)")
    pron_export_parser.add_argument("-p", "--project", help="Project file")

    # --- FT-CLI-001: make (one-command new -> compile -> auto-cast -> render) ---
    make_parser = subparsers.add_parser(
        "make",
        help="One command: create + compile + auto-cast + render a source file",
    )
    make_parser.add_argument(
        "source",
        help="Source file (EPUB/DOCX/TXT/MD/PDF) or a folder of chapter files",
    )
    make_parser.add_argument(
        "--format",
        choices=["m4b", "mp3", "wav"],
        default=None,
        dest="output_format",
        help="Output format (default: from config, usually m4b)",
    )
    make_parser.add_argument(
        "-j", "--jobs", "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel render workers (default: 1)",
    )
    make_parser.add_argument(
        "--lang", default="en", metavar="CODE", help="Language code (default: en)"
    )
    # CASTING-DEPTH (v2.1): emotion preset pack for make's compile step.
    make_parser.add_argument(
        "--emotion-preset",
        choices=["neutral", "literary", "dramatic", "children"],
        default=None,
        dest="emotion_preset",
        help="Emotion preset pack (sets project emotion_preset; default: neutral)",
    )
    make_parser.add_argument(
        "--cover", metavar="PATH", help="Cover art image to embed (JPG/PNG)"
    )
    make_parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply EBU R128 loudness normalization to the final audio",
    )
    make_parser.add_argument(
        "--acx",
        action="store_true",
        help="Master for ACX/audiobook retail (sets output_profile=acx)",
    )
    make_parser.add_argument(
        "--bitrate", metavar="RATE", help="Encoder bitrate override, e.g. 192k"
    )
    make_parser.add_argument("-o", "--output", help="Output audio file path")
    make_parser.add_argument(
        "--chapter-delimiter",
        metavar="REGEX",
        dest="chapter_delimiter",
        help="Custom regex to split chapters (TXT/MD sources)",
    )
    make_parser.add_argument(
        "--force-text",
        action="store_true",
        dest="force_text",
        help="Force text extraction for scanned/image-only PDFs",
    )
    # FT-CLI-008: watch mode also available on make.
    make_parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the source file and re-render (resume) whenever it changes",
    )

    # --- FT-CAST-019: audition (rank candidate voices for one speaker) ---
    audition_parser = subparsers.add_parser(
        "audition",
        help="Show ranked candidate voices for a speaker (optionally render samples)",
    )
    audition_parser.add_argument("character", help="Speaker/character name to audition")
    audition_parser.add_argument("-p", "--project", help="Project file")
    audition_parser.add_argument(
        "-n", "--top", type=int, default=5, help="Show top N candidate voices (default: 5)"
    )
    audition_parser.add_argument(
        "--render",
        action="store_true",
        help="Render a short sample line through each top-N candidate voice",
    )
    audition_parser.add_argument(
        "--line",
        metavar="TEXT",
        help="Sample line to render (default: the speaker's first detected line)",
    )
    audition_parser.add_argument(
        "-o", "--output-dir",
        dest="output_dir",
        help="Directory for rendered audition WAVs (default: audition/)",
    )
    audition_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- FT-CLI-003: cast-interactive (alias for `cast --interactive`) ---
    cast_interactive_parser = subparsers.add_parser(
        "cast-interactive",
        help="Interactively cast each uncast speaker (prompts per speaker)",
    )
    cast_interactive_parser.add_argument("-p", "--project", help="Project file")
    cast_interactive_parser.add_argument(
        "-n", "--top", type=int, default=5, help="Suggestions to show per speaker (default: 5)"
    )

    # --- FT-CLI-004: completion (shell completion activation snippet) ---
    completion_parser = subparsers.add_parser(
        "completion",
        help="Print a shell-completion activation snippet (bash/zsh/fish)",
    )
    completion_parser.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        help="Target shell",
    )

    # FT-CLI-004: attach the *.audiobooker completer to -p/--project args and
    # enable argcomplete. Both are no-ops when argcomplete isn't installed.
    _attach_completers(subparsers)
    _enable_argcomplete(parser)

    return parser


def _attach_completers(subparsers) -> None:
    """FT-CLI-004: attach the project-file completer to relevant arguments.

    Walks every registered subparser and tags any ``-p/--project`` option (and
    the ``project`` positional of `load`) with ``_audiobooker_file_completer``
    so argcomplete suggests *.audiobooker files. The attribute argcomplete reads
    is ``.completer``; setting it is harmless when argcomplete is absent.
    """
    choices = getattr(subparsers, "choices", {}) or {}
    for sub in choices.values():
        for action in getattr(sub, "_actions", []):
            opts = getattr(action, "option_strings", [])
            dest = getattr(action, "dest", "")
            if "--project" in opts or dest == "project":
                action.completer = _audiobooker_file_completer  # type: ignore[attr-defined]


def _enable_argcomplete(parser) -> None:
    """FT-CLI-004: guarded argcomplete.autocomplete(parser).

    argcomplete is an optional dependency. When it isn't installed this is a
    no-op so normal CLI use is unaffected. When it IS installed and the shell is
    driving completion, argcomplete handles the request and exits.
    """
    try:
        import argcomplete
    except ImportError:
        return
    try:
        argcomplete.autocomplete(parser)
    except Exception:  # pragma: no cover - completion is best-effort
        pass


def find_project_file(specified: Optional[str] = None) -> Path:
    """
    Find project file in current directory or use specified path.

    Args:
        specified: Explicitly specified path

    Returns:
        Path to project file

    Raises:
        FileNotFoundError: If no project file found
    """
    if specified:
        path = Path(specified)
        if not path.exists():
            raise FileNotFoundError(f"Project file not found: {path}")
        return path

    # Look for .audiobooker files in current directory
    project_files = list(Path(".").glob("*.audiobooker"))
    if len(project_files) == 1:
        return project_files[0]
    elif len(project_files) > 1:
        raise ValueError(
            "Multiple project files found. Specify one with -p:\n"
            + "\n".join(f"  {p}" for p in project_files)
        )
    else:
        raise FileNotFoundError(
            "No project file found in current directory. "
            "Create one with: audiobooker new <source_file>"
        )


# ---------------------------------------------------------------------------
# FT-CLI-002: config-file merge (CLI flag > config-file value > built-in default)
# ---------------------------------------------------------------------------

# Section keys that config_file.load_config() may return alongside flat
# ProjectConfig fields. These are NOT ProjectConfig fields — they seed
# BookMetadata or point at auxiliary files — so they must be stripped before
# ProjectConfig(**mapped).
_CONFIG_SECTION_KEYS = frozenset({"book", "casting", "lexicon"})


def _load_config_file(source_path: Optional[str] = None) -> dict:
    """Resolve the on-disk config (project-local > user) for ``source_path``.

    Thin wrapper around config_file.load_config that never raises: a broken
    config module or filesystem error degrades to an empty config so the run
    continues with built-in defaults. Returns the flat dict as-is (section
    keys included).
    """
    try:
        from audiobooker import config_file
        return config_file.load_config(source_path) or {}
    except Exception as e:  # pragma: no cover - defensive; load_config is pure-read
        print(f"WARNING: ignoring config file ({e})")
        return {}


def _build_config_from(
    file_config: dict,
    cli_overrides: dict,
    *,
    base_kwargs: Optional[dict] = None,
):
    """Build a ProjectConfig from config-file values under CLI overrides.

    Precedence (highest first): explicit CLI flag > config-file value > the
    ProjectConfig built-in default. ``cli_overrides`` should contain ONLY flags
    the user actually passed (None / absent values are dropped so they never
    clobber a config-file value). ``base_kwargs`` are unconditional seeds (e.g.
    a language already validated by the caller) applied above the config file
    but below explicit CLI overrides.

    Section keys (book/casting/lexicon) are stripped before construction.
    Validation happens in ProjectConfig.__post_init__, which raises structured
    ValueErrors on bad values — those propagate to the caller's error handler.
    """
    from audiobooker.models import ProjectConfig

    mapped = {
        k: v for k, v in file_config.items() if k not in _CONFIG_SECTION_KEYS
    }
    if base_kwargs:
        mapped.update(base_kwargs)
    # Only let CLI flags the user actually set win over the config file.
    for key, value in cli_overrides.items():
        if value is not None:
            mapped[key] = value
    return ProjectConfig(**mapped)


def _apply_config_sections(project, file_config: dict, *, base_dir: Path) -> None:
    """Apply book/casting/lexicon sections from a config file onto a project.

    NEVER mutates a saved project file — the caller is responsible for deciding
    whether to persist. Paths in the casting/lexicon sections are resolved
    relative to ``base_dir`` (the source directory) when not absolute. Best
    effort: a missing/invalid aux file warns and is skipped rather than failing
    the whole run.
    """
    from audiobooker.models import BookMetadata

    book = file_config.get("book")
    if isinstance(book, dict):
        meta: BookMetadata = project.metadata
        if book.get("title"):
            project.title = str(book["title"])
        if book.get("author"):
            project.author = str(book["author"])
        if book.get("genre"):
            meta.genre = str(book["genre"])
        if book.get("series"):
            meta.series = str(book["series"])
        if book.get("series_index") is not None:
            try:
                meta.series_index = int(book["series_index"])
            except (TypeError, ValueError):
                print(f"WARNING: ignoring non-integer series_index: {book['series_index']!r}")
        if book.get("year") is not None:
            try:
                meta.year = int(book["year"])
            except (TypeError, ValueError):
                print(f"WARNING: ignoring non-integer year: {book['year']!r}")
        if book.get("narrator"):
            meta.narrator_name = str(book["narrator"])
        if book.get("publisher"):
            meta.publisher = str(book["publisher"])

    def _resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (base_dir / path)

    casting_ref = file_config.get("casting")
    if isinstance(casting_ref, str) and casting_ref:
        casting_path = _resolve(casting_ref)
        try:
            project.import_casting(casting_path)
        except (FileNotFoundError, ValueError) as e:
            print(f"WARNING: could not import casting from config ({e})")

    lexicon_ref = file_config.get("lexicon")
    if isinstance(lexicon_ref, str) and lexicon_ref:
        lexicon_path = _resolve(lexicon_ref)
        try:
            project.import_lexicon(lexicon_path)
        except (FileNotFoundError, ValueError) as e:
            print(f"WARNING: could not import lexicon from config ({e})")


def cmd_new(args) -> int:
    """Create new project from source file."""
    from audiobooker import AudiobookProject

    source = Path(args.source)
    if not source.exists():
        print(f"Error: Source file not found: {source}")
        return 1

    suffix = source.suffix.lower()
    is_dir = source.is_dir()

    _out(f"Creating project from: {source}")

    try:
        from audiobooker.language.profile import get_profile, available_profiles

        lang = getattr(args, "lang", "en")
        try:
            get_profile(lang)
        except ValueError:
            print(f"Error: Unsupported language: {lang!r}")
            print(f"Available: {', '.join(available_profiles())}")
            return 1

        booknlp_mode = getattr(args, "booknlp", "auto")

        # FT-CLI-002: seed config from the on-disk config file, then let
        # explicit CLI flags win (CLI flag > config-file value > default).
        file_config = _load_config_file(str(source))
        config = _build_config_from(
            file_config,
            cli_overrides={"booknlp_mode": getattr(args, "booknlp", None)},
            base_kwargs={"language_code": lang},
        )
        # booknlp default is "auto"; only treat it as an explicit override when
        # the user passed something other than the parser default.
        if booknlp_mode != "auto":
            config.booknlp_mode = booknlp_mode

        # INPUT (v2.1): custom chapter delimiter (TXT/MD/stdin) + force-text (PDF).
        chapter_delimiter = getattr(args, "chapter_delimiter", None)
        force_text = getattr(args, "force_text", False)

        if is_dir:
            # INPUT (v2.1): a folder of per-chapter text files.
            project = AudiobookProject.from_folder(source, config=config)
        elif suffix == ".epub":
            project = AudiobookProject.from_epub(source, config=config)
        elif suffix == ".docx":
            project = AudiobookProject.from_docx(source, config=config)
        elif suffix == ".pdf":
            project = AudiobookProject.from_pdf(
                source, config=config, force_text=force_text
            )
        elif suffix in (".txt", ".md", ".markdown"):
            project = AudiobookProject.from_text(
                source, config=config, chapter_delimiter=chapter_delimiter
            )
        else:
            print(f"Error: Unsupported file format: {suffix}")
            print("Supported: .epub, .docx, .txt, .md, .pdf, or a folder of chapter files")
            return 1

        # FT-CLI-002: apply book/casting/lexicon sections from the config file
        # onto the freshly-created project (paths resolved next to the source).
        _apply_config_sections(
            project,
            file_config,
            base_dir=source if is_dir else source.parent,
        )

        # Save project. For a folder source there is no source file to derive
        # the project path from, so default to <folder-name>.audiobooker.
        if args.output:
            output_path = args.output
        elif is_dir:
            output_path = source.parent / f"{source.name}.audiobooker"
        else:
            output_path = source.with_suffix(".audiobooker")
        project.save(output_path)

        _out(f"\nProject created: {output_path}")
        _out(f"  Title: {project.title}")
        _out(f"  Chapters: {len(project.chapters)}")
        _out(f"  Words: ~{project.total_words:,}")
        _out(
            f"  Estimated duration: ~{project.estimated_duration_minutes:.0f} min (at {project.config.estimated_wpm} wpm, varies by voice)"
        )
        _out("\nNext steps:")
        _out("  1. Cast voices: audiobooker cast narrator af_heart")
        _out("  2. Compile: audiobooker compile")
        _out("  3. Render: audiobooker render")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cast(args) -> int:
    """Assign voice to character."""
    from audiobooker import AudiobookProject

    # FT-CLI-003: `cast --interactive` walks every uncast speaker.
    if getattr(args, "interactive", False):
        return _cast_interactive(args)

    if not args.character or not args.voice:
        print(
            "Error: cast requires a character and a voice "
            "(or use --interactive to cast all uncast speakers)."
        )
        print("Usage: audiobooker cast <character> <voice>")
        return 1

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        project.cast(
            name=args.character,
            voice=args.voice,
            emotion=args.emotion,
            description=args.description,
        )

        project.save()

        _out(f"Cast {args.character} as {args.voice}")
        if args.emotion:
            _out(f"  Default emotion: {args.emotion}")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def _gather_speaker_utterances(project, limit: int = 5) -> dict:
    """Collect up to ``limit`` sample lines per speaker from compiled chapters.

    Mirrors the gathering loop in cmd_cast_suggest so audition/interactive
    casting see the same per-speaker sample set the suggester uses.
    """
    speaker_utterances: dict[str, list[str]] = {}
    for chapter in project.chapters:
        for utt in chapter.utterances:
            key = utt.speaker
            bucket = speaker_utterances.setdefault(key, [])
            if len(bucket) < limit:
                bucket.append(utt.text)
    return speaker_utterances


def _cast_interactive(args) -> int:
    """
    FT-CLI-003: Interactively cast each uncast speaker.

    For each uncast speaker: print a representative utterance + the top-N
    VoiceSuggester candidates, then prompt for a choice (number / voice id /
    's' to skip / 'p' to preview). Guards sys.stdin.isatty(): when stdin is not
    a TTY it falls back to printing the suggestions (no prompt) so piping is
    safe.
    """
    from audiobooker import AudiobookProject
    from audiobooker.casting.voice_suggester import VoiceSuggester

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed so speakers are detected.
        if not any(c.is_compiled for c in project.chapters):
            _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        uncast = sorted(project.get_uncast_speakers())
        if not uncast:
            _out("All speakers are already cast.")
            return 0

        top_n = getattr(args, "top", 5) or 5
        speaker_utterances = _gather_speaker_utterances(project)
        already_cast = project.casting.get_voice_mapping()
        suggester = VoiceSuggester(max_suggestions=top_n)
        results = suggester.suggest_all(uncast, speaker_utterances, already_cast)

        interactive = sys.stdin.isatty()
        if not interactive:
            _out(
                "Non-interactive stdin — printing suggestions only "
                "(run in a terminal to cast interactively):\n"
            )

        applied = 0
        for result in results:
            speaker = result.speaker
            samples = speaker_utterances.get(speaker, [])
            sample = samples[0][:80] if samples else "(no sample line)"
            _out(f"\nSpeaker: {speaker}")
            _out(f"  Sample: {sample!r}")
            if not result.suggestions:
                _out("  (no voice suggestions available)")
                continue
            for i, s in enumerate(result.suggestions, 1):
                marker = ">>>" if i == 1 else "   "
                _out(f"    {marker} [{i}] {s.voice_id} (score: {s.score:.2f}) - {s.reason}")

            if not interactive:
                continue

            # Prompt loop for this speaker.
            chosen = _prompt_for_voice(speaker, result.suggestions, project)
            if chosen is None:
                _out(f"  Skipped {speaker}.")
                continue
            project.cast(speaker, chosen)
            _out(f"  Cast {speaker} as {chosen}")
            applied += 1

        if applied:
            project.save()
            _out(f"\nApplied {applied} voice assignment(s).")
        elif interactive:
            _out("\nNo voices assigned.")
        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def _prompt_for_voice(speaker, suggestions, project):
    """Prompt the user for a voice choice for one speaker.

    Accepts: a number (1..N from the suggestion list), a raw voice id, 's' to
    skip, 'p' to preview the top suggestion (best-effort; skipped if rendering
    is unavailable). Returns the chosen voice id, or None to skip. EOF / empty
    input also skips.
    """
    valid_numbers = {str(i): s.voice_id for i, s in enumerate(suggestions, 1)}
    while True:
        try:
            raw = input(
                f"  Choose voice for {speaker} "
                f"[1-{len(suggestions)} / voice-id / s=skip / p=preview]: "
            ).strip()
        except EOFError:
            return None
        if not raw or raw.lower() == "s":
            return None
        if raw in valid_numbers:
            return valid_numbers[raw]
        if raw.lower() == "p":
            top = suggestions[0].voice_id if suggestions else None
            if top:
                _preview_voice_line(speaker, top, project)
            continue
        # Treat anything else as a raw voice id.
        return raw


def _preview_voice_line(speaker, voice_id, project) -> None:
    """Best-effort: render the speaker's first line through ``voice_id``.

    Prints a short status line. Never raises — a missing engine just prints a
    note so the interactive loop continues.
    """
    from audiobooker.models import CastingTable, Chapter, Character, Utterance

    samples = _gather_speaker_utterances(project, limit=1).get(speaker, [])
    line = samples[0] if samples else "This is a preview of the selected voice."
    try:
        from audiobooker.renderer.engine import render_chapter

        casting = CastingTable()
        casting.characters[casting.normalize_key(speaker)] = Character(
            name=speaker, voice=voice_id
        )
        chapter = Chapter(index=0, title=f"Preview {voice_id}", raw_text="")
        chapter.utterances = [Utterance(speaker=speaker, text=line)]
        out = Path(f"preview_{voice_id}.wav")
        render_chapter(chapter, casting, out)
        _out(f"    Preview rendered: {out}")
    except Exception as e:  # pragma: no cover - depends on TTS backend
        _out(f"    (preview unavailable: {e})")


def cmd_cast_interactive(args) -> int:
    """FT-CLI-003: `cast-interactive` — thin alias for cast --interactive."""
    return _cast_interactive(args)


def cmd_audition(args) -> int:
    """
    FT-CAST-019: Print the ranked candidate-voice table for one speaker.

    Uses voice_suggester.audition_voices() for the ranking. With --render,
    renders the chosen sample line through each top-N candidate voice to
    separate WAVs under an audition/ directory (one one-utterance Chapter per
    voice via engine.render_chapter).
    """
    from audiobooker import AudiobookProject
    from audiobooker.casting.voice_suggester import audition_voices

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed so the speaker's lines exist.
        if not any(c.is_compiled for c in project.chapters):
            _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        speaker = args.character
        top_n = getattr(args, "top", 5) or 5
        json_output = getattr(args, "json_output", False)

        # Gather the speaker's sample utterances (like cmd_cast_suggest).
        samples = _gather_speaker_utterances(project).get(speaker, [])

        candidates = audition_voices(speaker, project.casting, samples)
        candidates = candidates[:top_n]

        # Pick the sample line: explicit --line, else first detected line.
        sample_line = getattr(args, "line", None) or (
            samples[0] if samples else "This is a sample of the selected voice."
        )

        if json_output and not getattr(args, "render", False):
            import json as json_mod
            print(json_mod.dumps(
                {"speaker": speaker, "candidates": candidates},
                indent=2,
                ensure_ascii=False,
            ))
            return 0

        _out(f"Audition for speaker '{speaker}' (top {len(candidates)}):\n")
        _out(f"  {'#':<3} {'Voice':<14} {'Gender':<8} {'Style':<12} {'Score':<7}")
        _out(f"  {'-'*3} {'-'*14} {'-'*8} {'-'*12} {'-'*7}")
        for i, c in enumerate(candidates, 1):
            flag = " (low confidence)" if c.get("low_confidence") else ""
            _out(
                f"  {i:<3} {c['voice_id']:<14} {c.get('gender', '?'):<8} "
                f"{c.get('style', '?'):<12} {c.get('score', 0.0):<7.2f}{flag}"
            )

        if not getattr(args, "render", False):
            _out(
                "\nRe-run with --render to hear each candidate, or cast one with: "
                f"audiobooker cast {speaker} <voice-id>"
            )
            return 0

        # --render: one WAV per candidate voice into the audition dir.
        from audiobooker.models import CastingTable, Chapter, Character, Utterance
        from audiobooker.renderer.engine import render_chapter

        out_dir = Path(getattr(args, "output_dir", None) or "audition")
        out_dir.mkdir(parents=True, exist_ok=True)

        rendered: list[dict] = []
        _out(f"\nRendering {len(candidates)} sample(s) to {out_dir}/ ...")
        for c in candidates:
            voice_id = c["voice_id"]
            casting = CastingTable()
            casting.characters[casting.normalize_key(speaker)] = Character(
                name=speaker, voice=voice_id
            )
            chapter = Chapter(index=0, title=f"Audition {voice_id}", raw_text="")
            chapter.utterances = [Utterance(speaker=speaker, text=sample_line)]
            out_path = out_dir / f"{voice_id}.wav"
            try:
                path = render_chapter(chapter, casting, out_path)
                rendered.append({"voice_id": voice_id, "path": str(path)})
                _out(f"  {voice_id} -> {path}")
            except Exception as e:
                _out(f"  {voice_id}: render failed ({e})")

        if json_output:
            import json as json_mod
            print(json_mod.dumps(
                {"speaker": speaker, "rendered": rendered},
                indent=2,
                ensure_ascii=False,
            ))
        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_completion(args) -> int:
    """
    FT-CLI-004: Print a shell-completion activation snippet.

    Emits the register-python-argcomplete activation for the chosen shell. The
    user eval's/sources it (e.g. `eval "$(audiobooker completion bash)"`).
    Output goes to stdout via print() so --silent never suppresses the snippet
    the user is capturing.
    """
    shell = args.shell
    if shell == "bash":
        print('eval "$(register-python-argcomplete audiobooker)"')
        print("# Add the line above to ~/.bashrc to enable tab-completion.")
    elif shell == "zsh":
        print("autoload -U bashcompinit && bashcompinit")
        print('eval "$(register-python-argcomplete audiobooker)"')
        print("# Add the lines above to ~/.zshrc to enable tab-completion.")
    elif shell == "fish":
        print("register-python-argcomplete --shell fish audiobooker | source")
        print(
            "# Add the line above to ~/.config/fish/config.fish "
            "to enable tab-completion."
        )
    else:  # pragma: no cover - argparse choices prevent this
        print(f"Error: unsupported shell: {shell}")
        return 1

    # Remind the user the optional dependency must be installed.
    try:
        import argcomplete  # noqa: F401
    except ImportError:
        print(
            "# NOTE: install the optional dependency first: "
            "pip install argcomplete"
        )
    return 0


def cmd_compile(args) -> int:
    """Compile chapters to utterances."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # CASTING-DEPTH v2.1: --emotion-preset sets the project's emotion_preset
        # before compile so the inferencer uses the chosen preset pack. Validated
        # by ProjectConfig (structured ValueError on a bad value).
        emotion_preset = getattr(args, "emotion_preset", None)
        if emotion_preset:
            project.config.emotion_preset = emotion_preset
            _out(f"Emotion preset: {emotion_preset}")

        # --dry-run: compile in dry-run mode, print speaker summary table
        if getattr(args, "dry_run", False):
            dry_result = project.compile(dry_run=True)
            if dry_result is None:
                _out("No chapters to compile.")
                return 0

            # Gather speaker stats from dry-run result
            speaker_stats: dict[str, dict] = {}
            for ch_idx, utterances in dry_result.items():
                for utt in utterances:
                    key = utt.speaker
                    if key not in speaker_stats:
                        speaker_stats[key] = {"lines": 0, "sample": ""}
                    speaker_stats[key]["lines"] += 1
                    if not speaker_stats[key]["sample"]:
                        speaker_stats[key]["sample"] = utt.text[:60]

            _out(f"\nDRY RUN — Compile preview for {project.title}")
            _out(f"{'='*70}")
            _out(f"  {'Speaker':<20} {'Lines':<8} {'Sample'}")
            _out(f"  {'-'*20} {'-'*8} {'-'*40}")
            for speaker in sorted(speaker_stats.keys()):
                info = speaker_stats[speaker]
                sample = info["sample"]
                if len(sample) > 40:
                    sample = sample[:37] + "..."
                _out(f"  {speaker:<20} {info['lines']:<8} {sample}")
            total = sum(s["lines"] for s in speaker_stats.values())
            _out(f"  {'-'*20} {'-'*8}")
            _out(f"  {'TOTAL':<20} {total:<8}")
            _out(f"{'='*70}")
            return 0

        _out(f"Compiling {len(project.chapters)} chapters...")

        def progress(current, total, title):
            _out(f"  [{current}/{total}] {title}")

        project.compile(progress_callback=progress)
        project.save()

        # FT-CORE-022: Surface compile observability summary.
        summary = getattr(project, "compile_summary", {}) or {}
        total_utterances = sum(len(c.utterances) for c in project.chapters)
        _out(
            f"\nCompiled {total_utterances} utterances: "
            f"{summary.get('speakers_resolved', 0)} speakers resolved, "
            f"{summary.get('low_confidence', 0)} low-confidence, "
            f"{summary.get('emotions_inferred', 0)} emotions inferred"
        )

        near_miss = summary.get("emotions_near_miss", 0)
        if near_miss:
            _out(
                f"  ({near_miss} more utterance(s) were just below the emotion "
                "confidence threshold — run 'audiobooker report' to review them.)"
            )

        # NLP errors are warnings, not failures — but the user should know
        # which chapters fell back to heuristic attribution.
        nlp_errors = summary.get("nlp_errors") or []
        if nlp_errors:
            print(
                f"WARNING: speaker resolution had problems on "
                f"{len(nlp_errors)} chapter(s); kept heuristic attribution. "
                "Run 'audiobooker report' for details."
            )

        # Show uncast speakers
        uncast = project.get_uncast_speakers()
        if uncast:
            _out("\nDetected speakers without voice assignments:")
            for speaker in sorted(uncast):
                _out(f"  - {speaker}")
            _out("\nAssign voices with: audiobooker cast <speaker> <voice>")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_render(args) -> int:
    """Render audiobook.

    FT-CLI-008: with --watch, polls the project file's mtime and re-renders
    (resume=True so only changed chapters re-render) whenever it changes.
    """
    if getattr(args, "watch", False):
        try:
            project_path = find_project_file(getattr(args, "project", None))
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1
        # Watching re-renders with resume on each change; ignore per-run codes.
        return _watch_loop(project_path, lambda: _cmd_render_once(args))
    return _cmd_render_once(args)


def _cmd_render_once(args) -> int:
    """Render audiobook (single pass — the body shared by cmd_render/watch)."""
    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import RenderError

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # OUTPUT-F1: Apply per-render metadata overrides onto project.metadata
        # before rendering so they get embedded in the output tags. These are
        # transient render-time overrides; they ARE persisted with the project
        # on save() (same as cover art), which is the expected behavior.
        narrator_override = getattr(args, "narrator", None)
        genre_override = getattr(args, "genre", None)
        series_override = getattr(args, "series", None)
        if narrator_override:
            project.metadata.narrator_name = narrator_override
        if genre_override:
            project.metadata.genre = genre_override
        if series_override:
            project.metadata.series = series_override

        # Handle --clean-cache before rendering
        if getattr(args, "clean_cache", False):
            from audiobooker.renderer.cache_manifest import get_cache_root
            import shutil

            cache_dir = get_cache_root(project_path.parent)
            if cache_dir.exists():
                # F-RENDER-B-020: Check for lockfile before rmtree
                lock_path = cache_dir / ".render.lock"
                if lock_path.exists():
                    print(
                        f"WARNING: Cache appears to be in use (lockfile exists: {lock_path}).\n"
                        f"Another render may be running. If you are sure no render is active,\n"
                        f"delete the lockfile manually and retry:\n"
                        f"  del \"{lock_path}\""
                    )
                    return 1
                shutil.rmtree(cache_dir)
                _out(f"Cache cleared: {cache_dir}")
            else:
                _out("No cache to clean.")

        # FT-RENDER-011: Auto-apply voice suggestions if --cast-suggest
        if getattr(args, "cast_suggest", False):
            from audiobooker.casting.voice_suggester import VoiceSuggester

            uncast = project.get_uncast_speakers()
            if uncast:
                _out(f"Auto-casting {len(uncast)} uncast speakers...")
                already_cast = project.casting.get_voice_mapping()
                suggester = VoiceSuggester(max_suggestions=1)
                results = suggester.suggest_all(sorted(uncast), already_cast=already_cast)
                for result in results:
                    if result.top:
                        project.cast(result.speaker, result.top.voice_id)
                        _out(f"  Cast {result.speaker} as {result.top.voice_id}")
                project.save()

        # OUTPUT-A-006: Validate cover path early so a typo doesn't silently
        # produce a coverless book.
        cover_flag = getattr(args, "cover", None)
        if cover_flag and not Path(cover_flag).exists():
            print(f"Error: Cover art file not found: {cover_flag}")
            return 1

        # FT-RENDER-017: Chapter selection filtering.
        # CLI-A-001: --chapters/--exclude-chapters is a TRANSIENT render filter.
        # We must never persist a reduced chapter list back to the source
        # project file. Keep the full list on `project` and only swap in the
        # filtered subset for the render call; restore before any save().
        full_chapters = project.chapters
        chapters_flag = getattr(args, "chapters", None)
        exclude_chapters_flag = getattr(args, "exclude_chapters", None)
        if chapters_flag or exclude_chapters_flag:
            from audiobooker.renderer.engine import filter_chapters_by_selection
            original_count = len(project.chapters)
            project.chapters = filter_chapters_by_selection(
                project.chapters,
                include_ranges=chapters_flag,
                exclude_ranges=exclude_chapters_flag,
            )
            _out(f"Chapter selection: {len(project.chapters)} of {original_count} chapters")

        if args.chapter is not None:
            # Render single chapter
            _out(f"Rendering chapter {args.chapter}...")
            output = args.output or f"chapter_{args.chapter:03d}.wav"
            path = project.render_chapter(args.chapter, output)
            _out(f"Output: {path}")
        else:
            # Render full audiobook
            fmt = getattr(args, "output_format", None) or project.config.output_format
            if args.output:
                output = args.output
            else:
                from audiobooker.project import _sanitize_filename
                output = f"{_sanitize_filename(project.title)}.{fmt}"
            resume = not getattr(args, "no_resume", False)
            from_chapter = getattr(args, "from_chapter", None)
            allow_partial = getattr(args, "allow_partial", False)
            jobs = getattr(args, "jobs", 1)
            force = getattr(args, "force", False)
            cover = getattr(args, "cover", None)
            normalize = getattr(args, "normalize", False)
            notify = getattr(args, "notify", False)
            # OUTPUT-F1: ACX / output-profile + bitrate + split
            output_profile = "acx" if getattr(args, "acx", False) else project.config.output_profile
            bitrate = getattr(args, "bitrate", None)
            split = getattr(args, "split", False)

            # FT-RENDER-004: Dry-run mode
            if getattr(args, "dry_run", False):
                from audiobooker.renderer.engine import dry_run_render
                dry_run_render(project, resume=resume, from_chapter=from_chapter)
                return 0

            # FT-RENDER-018: Audiobook playback-length estimate.
            # This is PLAYBACK length (words/wpm), NOT render wall-clock, which
            # depends entirely on the TTS backend and hardware — relabel so the
            # user isn't misled into expecting the render to take this long.
            total_words = sum(ch.word_count for ch in project.chapters)
            wpm = project.config.estimated_wpm or 150
            est_minutes = total_words / wpm
            if est_minutes >= 60:
                est_str = f"~{est_minutes / 60:.1f} hours"
            else:
                est_str = f"~{est_minutes:.0f} minutes"
            _out(
                f"Audiobook length: {est_str} ({total_words:,} words). "
                "Render time depends on your TTS backend and hardware."
            )

            _out(f"Rendering audiobook to: {output}")
            if not resume:
                _out("  (cache disabled — full re-render)")
            if jobs > 1:
                _out(f"  (parallel rendering: {jobs} workers)")
            if output_profile == "acx":
                _out("  (ACX mastering profile: loudnorm -20 LUFS, peak -3 dBTP)")
            if bitrate:
                _out(f"  (bitrate: {bitrate})")
            if split:
                _out("  (split: one file per chapter)")

            # FT-RENDER-005: Rich progress bar (conditional import)
            progress_bar = None
            progress_task = None
            try:
                from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
                progress_bar = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeRemainingColumn(),
                    transient=False,
                )
                progress_bar.start()
                progress_task = progress_bar.add_task("Rendering...", total=len(project.chapters))

                def progress(current, total, status):
                    progress_bar.update(progress_task, completed=current, description=status[:60])

            except ImportError:
                progress_bar = None

                def progress(current, total, status):
                    print(f"  [{current}/{total}] {status}")

            try:
                # OUTPUT-F1: Any of cover/normalize/acx/bitrate/split requires a
                # direct render_project call so we can thread the extra kwargs.
                # The plain case still goes through project.render() (which now
                # also forwards profile/bitrate/split) to keep that path simple.
                needs_direct = bool(
                    cover or normalize or output_profile != "podcast" or bitrate or split
                )
                if needs_direct:
                    from audiobooker.renderer.engine import render_project
                    # Ensure compiled
                    uncompiled = [c for c in project.chapters if not c.is_compiled and not c.skip]
                    if uncompiled:
                        project.compile()
                    # Call defensively: a concurrently-evolving renderer with an
                    # older signature may not yet accept the v2.1 kwargs.
                    direct_kwargs = dict(
                        progress_callback=progress,
                        resume=resume,
                        from_chapter=from_chapter,
                        allow_partial=allow_partial,
                        jobs=jobs,
                        force=force,
                        output_format=getattr(args, "output_format", None),
                        cover_art=cover,
                        normalize=normalize,
                        output_profile=output_profile,
                        bitrate=bitrate,
                        split=split,
                    )
                    try:
                        path = render_project(project, Path(output), **direct_kwargs)
                    except TypeError as te:
                        if not any(
                            k in str(te) for k in ("output_profile", "bitrate", "split")
                        ):
                            raise
                        for k in ("output_profile", "bitrate", "split"):
                            direct_kwargs.pop(k, None)
                        path = render_project(project, Path(output), **direct_kwargs)
                else:
                    path = project.render(
                        output,
                        progress_callback=progress,
                        resume=resume,
                        from_chapter=from_chapter,
                        allow_partial=allow_partial,
                        jobs=jobs,
                        force=force,
                        output_format=getattr(args, "output_format", None),
                        output_profile=output_profile,
                        bitrate=bitrate,
                        split=split,
                    )
            finally:
                if progress_bar is not None:
                    progress_bar.stop()

            # CLI-A-001: Restore the full chapter list before persisting so a
            # transient render filter never deletes chapters from the saved file.
            project.chapters = full_chapters
            project.save()

            _out(f"\nAudiobook created: {path}")
            _out(f"Duration: {project.total_duration_seconds / 60:.1f} minutes")

            # FT-RENDER-020: Desktop notification on success
            if notify:
                _send_notification(
                    title="Audiobooker",
                    message=f"Render complete: {project.title}",
                )

        return 0

    except RenderError as e:
        _print_render_failure(e)
        # FT-RENDER-020: Desktop notification on failure
        if getattr(args, "notify", False):
            _send_notification(
                title="Audiobooker",
                message=f"Render FAILED: {e}",
            )
        return 1

    except Exception as e:
        _report_error(e, args)
        if getattr(args, "notify", False):
            _send_notification(
                title="Audiobooker",
                message=f"Render error: {e}",
            )
        return 2


def _print_render_failure(e: "RenderError") -> None:
    """Print user-friendly render failure message with recovery hints."""
    print(f"\nRender failed: {e}")

    summary = e.summary
    if summary is None:
        return

    if summary.failed_chapters:
        print("\nFailed chapters:")
        for ch in summary.failed_chapters:
            print(f"  Chapter {ch['index']}: {ch['title']}")
            print(f"    Error: {ch['error']}")

    print(
        f"\nRender summary: {summary.rendered} rendered, "
        f"{summary.skipped_cached} cached, {summary.failed} failed "
        f"(of {summary.total} total)"
    )

    if summary.cache_dir:
        print(f"\nCached chapter audio: {summary.cache_dir}")

        # FT-RENDER-013: Surface failure report if it exists
        report_path = Path(summary.cache_dir) / "render_failure_report.json"
        if report_path.exists():
            print(f"Failure report: {report_path}")
            try:
                from audiobooker.renderer.failure_report import RenderFailureReport
                report = RenderFailureReport.load(report_path)
                if report.failed_chapters:
                    first_fail = report.failed_chapters[0]
                    if first_fail.failed_utterance and first_fail.failed_utterance.speaker:
                        fu = first_fail.failed_utterance
                        preview = fu.text_preview[:80] if fu.text_preview else "(no text)"
                        print(f"  First failure: speaker={fu.speaker}, text={preview!r}")
            except Exception:
                pass  # Don't fail on report parsing

    if summary.manifest_path:
        print(f"Manifest: {summary.manifest_path}")

    # Prefer the structured hint carried on the RenderError (it names the
    # exact resume flag, e.g. --from-chapter) over the generic resume text.
    hint = getattr(e, "hint", None)
    if hint:
        print(f"\nHint: {hint}")
    else:
        print("\nTo resume: audiobooker render")
        print("To force:  audiobooker render --no-resume")


def _sanitize_notification_text(text: str) -> str:
    """
    CLI-A-002: Strip control characters from untrusted notification text.

    Project titles come from EPUB/PDF metadata and must never carry newlines,
    carriage returns, or other control characters into a shell/notification
    command. Removing them closes the most common injection avenues before any
    per-target quoting is applied.
    """
    return "".join(ch for ch in text if ch.isprintable())


def _ps_single_quote(text: str) -> str:
    """
    CLI-A-002: Quote untrusted text as a PowerShell single-quoted literal.

    In PowerShell a single-quoted string is literal: the only character with
    special meaning is the single quote, which is escaped by doubling. The
    returned value INCLUDES the surrounding quotes, so the text is never
    interpreted as code.
    """
    return "'" + _sanitize_notification_text(text).replace("'", "''") + "'"


def _osascript_double_quote(text: str) -> str:
    """
    CLI-A-002: Quote untrusted text as an AppleScript double-quoted literal.

    Backslashes and double quotes are escaped so the text cannot break out of
    the string literal in the osascript source. The returned value INCLUDES the
    surrounding quotes.
    """
    cleaned = _sanitize_notification_text(text).replace("\\", "\\\\").replace('"', '\\"')
    return '"' + cleaned + '"'


def _send_notification(title: str, message: str) -> None:
    """
    FT-RENDER-020: Send desktop notification.

    Strategy:
    1. Try plyer (cross-platform) if available.
    2. On Windows, try PowerShell BurntToast or fallback to msg.
    3. Skip silently if nothing works.
    """
    # Truncate message to avoid shell/notification issues
    message = message[:200]

    # Attempt 1: plyer
    try:
        from plyer import notification as plyer_notify
        plyer_notify.notify(title=title, message=message, timeout=10)
        return
    except (ImportError, Exception):
        pass

    # Attempt 2: Windows-specific
    if sys.platform == "win32":
        import subprocess
        # Try BurntToast.
        # CLI-A-002: title/message are untrusted (EPUB/PDF metadata). Embed
        # them as PowerShell single-quoted literals so they are treated as
        # data, never as code.
        try:
            ps_command = (
                f"New-BurntToastNotification -Text "
                f"{_ps_single_quote(title)}, {_ps_single_quote(message)}"
            )
            subprocess.run(
                ["powershell", "-Command", ps_command],
                capture_output=True,
                timeout=10,
            )
            return
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: msg command (may not work on all editions)
        try:
            import getpass
            user = getpass.getuser()
            subprocess.run(
                ["msg", user, f"{title}: {message}"],
                capture_output=True,
                timeout=10,
            )
            return
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # On macOS/Linux, try notify-send or osascript
    if sys.platform == "darwin":
        import subprocess
        # CLI-A-002: escape untrusted title/message as AppleScript string
        # literals so they cannot break out of the osascript source.
        try:
            script = (
                f"display notification {_osascript_double_quote(message)} "
                f"with title {_osascript_double_quote(title)}"
            )
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=10,
            )
            return
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    elif sys.platform.startswith("linux"):
        import subprocess
        try:
            subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                timeout=10,
            )
            return
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    # Silent failure — notification is best-effort


def cmd_info(args) -> int:
    """Show project information."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        info = project.info()

        # --json: project.info() already returns a dict.
        if getattr(args, "json_output", False):
            import json as json_mod
            print(json_mod.dumps(info, indent=2, ensure_ascii=False))
            return 0

        _out(f"Title: {info['title']}")
        if info["author"]:
            _out(f"Author: {info['author']}")
        _out(f"Source: {info['source']}")
        _out(f"Chapters: {info['chapters']}")
        _out(f"Words: ~{info['total_words']:,}")
        _out(
            f"Estimated duration: ~{info['estimated_duration_minutes']:.0f} min (varies by voice)"
        )
        _out(f"Characters cast: {info['characters_cast']}")
        _out(f"Compiled: {'Yes' if info['compiled'] else 'No'}")
        _out(f"Rendered: {'Yes' if info['rendered'] else 'No'}")

        if info["uncast_speakers"]:
            _out(f"\nUncast speakers: {', '.join(info['uncast_speakers'])}")

        if args.verbose and project.casting.characters:
            _out("\nCasting:")
            for name, char in project.casting.characters.items():
                _out(f"  {char.name}: {char.voice} ({char.line_count} lines)")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_load(args) -> int:
    """
    Load an existing project and show its info.

    CLI-A-003: The `load` subcommand was registered in the parser but never
    wired into the dispatch table, so it printed "Unknown command: load".
    It behaves like `info` on the explicitly given project file.
    """
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        info = project.info()
        _out(f"Loaded project: {project_path}")
        _out(f"Title: {info['title']}")
        if info["author"]:
            _out(f"Author: {info['author']}")
        _out(f"Source: {info['source']}")
        _out(f"Chapters: {info['chapters']}")
        _out(f"Words: ~{info['total_words']:,}")
        _out(
            f"Estimated duration: ~{info['estimated_duration_minutes']:.0f} min (varies by voice)"
        )
        _out(f"Characters cast: {info['characters_cast']}")
        _out(f"Compiled: {'Yes' if info['compiled'] else 'No'}")
        _out(f"Rendered: {'Yes' if info['rendered'] else 'No'}")

        if info["uncast_speakers"]:
            _out(f"\nUncast speakers: {', '.join(info['uncast_speakers'])}")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_voices(args) -> int:
    """List available voices."""
    try:
        from voice_soundboard.config import VOICES
    except ImportError:
        print("Error: voice-soundboard not installed")
        print(VOICE_SOUNDBOARD_INSTALL_HINT)
        return 1

    _out("Available voices:\n")

    for voice_id, info in sorted(VOICES.items()):
        # Filter by gender if specified
        if args.gender:
            voice_gender = (
                "female"
                if voice_id.startswith("af_") or voice_id.startswith("bf_")
                else "male"
            )
            if voice_gender != args.gender.lower():
                continue

        # Filter by search term
        if args.search:
            search_lower = args.search.lower()
            if (
                search_lower not in voice_id.lower()
                and search_lower not in str(info).lower()
            ):
                continue

        _out(f"  {voice_id}")

    return 0


def cmd_chapters(args) -> int:
    """List chapters or manage chapter operations."""
    from audiobooker import AudiobookProject

    chapters_command = getattr(args, "chapters_command", None)

    # Handle subcommands: merge, split, exclude, include
    if chapters_command == "merge":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            merged = project.merge_chapters(args.start, args.end)
            project.save()
            _out(f"Merged chapters {args.start}-{args.end} into: {merged.title}")
            _out(f"  New chapter count: {len(project.chapters)}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    elif chapters_command == "split":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            first, second = project.split_chapter(args.index, args.paragraph)
            project.save()
            _out(f"Split chapter {args.index} at paragraph {args.paragraph}:")
            _out(f"  [{first.index}] {first.title} ({first.word_count} words)")
            _out(f"  [{second.index}] {second.title} ({second.word_count} words)")
            _out(f"  New chapter count: {len(project.chapters)}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    elif chapters_command == "exclude":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            project.exclude_chapter(args.index)
            project.save()
            ch = project.chapters[args.index]
            _out(f"Excluded chapter {args.index}: {ch.title}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    elif chapters_command == "include":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            project.include_chapter(args.index)
            project.save()
            ch = project.chapters[args.index]
            _out(f"Included chapter {args.index}: {ch.title}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    elif chapters_command == "rename":
        # FT-PARSE-006: rename a chapter by index.
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            old_title = project.chapters[args.index].title if 0 <= args.index < len(project.chapters) else "?"
            project.rename_chapter(args.index, args.title)
            project.save()
            _out(f"Renamed chapter {args.index}: {old_title!r} -> {args.title!r}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    elif chapters_command == "reorder":
        # FT-PARSE-006: reorder chapters by a comma-separated permutation.
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)

            raw = args.order.replace(" ", "")
            try:
                new_order = [int(tok) for tok in raw.split(",") if tok != ""]
            except ValueError:
                print(
                    "Error: --order must be comma-separated integers, "
                    f"e.g. '2,0,1'. Got: {args.order!r}"
                )
                return 1

            project.reorder_chapters(new_order)
            project.save()
            _out(f"Reordered {len(project.chapters)} chapters: new order {new_order}")
            for ch in project.chapters:
                _out(f"  [{ch.index}] {ch.title}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    # Default: list chapters
    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        _out(f"Chapters in {project.title}:\n")

        for chapter in project.chapters:
            status = ""
            if chapter.skip:
                status = " [excluded]"
            elif chapter.is_rendered:
                status = " [rendered]"
            elif chapter.is_compiled:
                status = " [compiled]"

            _out(
                f"  {chapter.index + 1}. {chapter.title} ({chapter.word_count} words){status}"
            )

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_speakers(args) -> int:
    """List detected speakers (or, with --suggest-aliases, propose aliases)."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        # CASTING-DEPTH v2.1: alias suggestion mode.
        if getattr(args, "suggest_aliases", False):
            return _speakers_suggest_aliases(project, args)

        speakers = project.get_detected_speakers()
        cast_speakers = set(project.casting.characters.keys())

        _out(f"Speakers in {project.title}:\n")

        for speaker in sorted(speakers):
            normalized = project.casting.normalize_key(speaker)
            if normalized in cast_speakers:
                char = project.casting.characters[normalized]
                _out(f"  {speaker}: {char.voice} ({char.line_count} lines)")
            else:
                _out(f"  {speaker}: [uncast]")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def _speakers_suggest_aliases(project, args) -> int:
    """CASTING-DEPTH v2.1: rank alias suggestions per character.

    Calls the casting alias-discovery proposal function and prints ranked alias
    suggestions per character. With --apply, the proposed aliases are added to
    each matching Character and the project is saved. Aliases are never applied
    silently — without --apply this only reports.

    The proposal function lives in casting (casting-owned). It returns a mapping
    of canonical character name -> list of proposals; each proposal is either a
    bare alias string or a dict with at least an "alias" key and an optional
    "score"/"confidence". Both shapes are handled so the printed/applied result
    is stable regardless of the exact return shape the casting side settles on.
    """
    from audiobooker.nlp.speaker_resolver import suggest_aliases

    json_output = getattr(args, "json_output", False)
    apply = getattr(args, "apply", False)

    # suggest_aliases returns a flat list[AliasProposal] (candidate/speaker/
    # score/source); group by the speaker each descriptor most co-occurs with
    # so the rest of this handler can display/apply per character.
    raw = suggest_aliases(project.chapters, project.casting) or []
    proposals: dict = {}
    for _p in raw:
        proposals.setdefault(_p.speaker, []).append(
            {"alias": _p.candidate, "score": _p.score, "source": _p.source}
        )

    if json_output:
        import json as json_mod
        print(json_mod.dumps(
            {"proposals": proposals, "applied": apply},
            indent=2,
            ensure_ascii=False,
        ))
        if apply:
            _apply_alias_proposals(project, proposals)
            project.save()
        return 0

    if not proposals:
        _out("No alias suggestions found.")
        return 0

    _out(f"Alias suggestions for {project.title}:\n")
    for name in sorted(proposals.keys()):
        items = proposals[name] or []
        if not items:
            continue
        _out(f"  {name}:")
        for item in items:
            alias, score = _alias_proposal_parts(item)
            score_str = f" (score: {score:.2f})" if score is not None else ""
            _out(f"    - {alias}{score_str}")

    if apply:
        applied = _apply_alias_proposals(project, proposals)
        project.save()
        _out(f"\nApplied {applied} alias(es).")
    else:
        _out("\nRe-run with --apply to add these aliases to the cast.")

    return 0


def _alias_proposal_parts(item) -> tuple[str, Optional[float]]:
    """Normalize one alias proposal to (alias, score|None).

    Tolerates a bare string proposal or a dict carrying "alias" plus an optional
    "score"/"confidence" so the alias-discovery side can evolve its shape.
    """
    if isinstance(item, dict):
        alias = str(item.get("alias", "")).strip()
        score = item.get("score", item.get("confidence"))
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        return alias, score
    return str(item).strip(), None


def _apply_alias_proposals(project, proposals: dict) -> int:
    """Add proposed aliases onto matching characters; return count applied."""
    applied = 0
    casting = project.casting
    for name, items in proposals.items():
        key = casting.normalize_key(name)
        char = casting.characters.get(key)
        if char is None:
            char = casting.resolve_alias(name)
        if char is None:
            continue
        for item in items or []:
            alias, _ = _alias_proposal_parts(item)
            if alias and alias not in char.aliases:
                char.aliases.append(alias)
                applied += 1
    if applied:
        from datetime import datetime as _dt
        project.modified_at = _dt.now().isoformat()
    return applied


def cmd_review_export(args) -> int:
    """Export compiled script for human review."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        output = args.output
        if output:
            output = Path(output)

        _out("Exporting review file...")

        review_path = project.export_for_review(output)
        project.save()

        # Count stats
        total_utterances = sum(len(c.utterances) for c in project.chapters)
        speakers = project.get_detected_speakers()

        _out(f"\nReview file created: {review_path}")
        _out(f"  Chapters: {len(project.chapters)}")
        _out(f"  Utterances: {total_utterances}")
        _out(f"  Speakers: {', '.join(sorted(speakers))}")
        _out("\nEdit the file to:")
        _out("  - Change speaker names: @OldName -> @NewName")
        _out("  - Add/change emotions: @Name -> @Name (emotion)")
        _out("  - Delete unwanted lines by removing the block")
        _out(f"\nThen import: audiobooker review-import {review_path.name}")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_review_import(args) -> int:
    """Import edited review file back into project."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        review_path = Path(args.review_file)
        if not review_path.exists():
            print(f"Error: Review file not found: {review_path}")
            return 1

        _out(f"Importing review file: {review_path}")

        stats = project.import_reviewed(review_path)
        project.save()

        _out("\nImport complete:")
        _out(f"  Chapters updated: {stats['chapters_updated']}")
        _out(f"  Utterances imported: {stats['utterances_imported']}")
        _out(f"  Speakers: {', '.join(sorted(stats['speakers_found']))}")

        # Warn loudly if any edited blocks did not match a chapter. A silent
        # skip means the user's edits were dropped without their knowledge.
        skipped = stats.get("chapters_skipped", 0)
        if skipped:
            skipped_titles = stats.get("skipped_titles") or []
            print(
                f"\nWARNING: {skipped} edited block(s) did not match any chapter "
                "and were NOT applied:"
            )
            for title in skipped_titles:
                print(f"  - {title}")
            print(
                'Hint: These blocks did not match any chapter by id or title — '
                'restore the original "=== Title === [id:...]" header to apply '
                "your edits."
            )

        _out("\nProject saved. Ready to render: audiobooker render")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cast_suggest(args) -> int:
    """Suggest voices for uncast speakers."""
    from audiobooker import AudiobookProject
    from audiobooker.casting.voice_suggester import VoiceSuggester

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        # Get speakers and their utterances
        speakers = sorted(project.get_detected_speakers())
        already_cast = project.casting.get_voice_mapping()

        # Gather sample utterances per speaker
        speaker_utterances: dict[str, list[str]] = {}
        for chapter in project.chapters:
            for utt in chapter.utterances:
                key = utt.speaker
                if key not in speaker_utterances:
                    speaker_utterances[key] = []
                if len(speaker_utterances[key]) < 5:
                    speaker_utterances[key].append(utt.text)

        suggester = VoiceSuggester(max_suggestions=getattr(args, "top", 3))
        results = suggester.suggest_all(speakers, speaker_utterances, already_cast)

        _out(f"Voice suggestions for {project.title}:\n")
        for result in results:
            cast_key = project.casting.normalize_key(result.speaker)
            is_cast = cast_key in project.casting.characters
            status = (
                f" (cast: {project.casting.characters[cast_key].voice})"
                if is_cast
                else " [uncast]"
            )
            _out(f"  {result.speaker}{status}")
            for i, s in enumerate(result.suggestions):
                marker = ">>>" if i == 0 else "   "
                _out(f"    {marker} {s.voice_id} (score: {s.score:.2f}) - {s.reason}")
            _out()

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cast_apply(args) -> int:
    """Auto-apply voice suggestions."""
    from audiobooker import AudiobookProject
    from audiobooker.casting.voice_suggester import VoiceSuggester

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if not getattr(args, "auto", False):
            _out("Use --auto to apply top suggestions for all uncast speakers.")
            return 0

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            _out("Compiling to detect speakers...")
            project.compile()

        uncast = project.get_uncast_speakers()
        if not uncast:
            _out("All speakers are already cast.")
            return 0

        already_cast = project.casting.get_voice_mapping()
        suggester = VoiceSuggester(max_suggestions=1)
        results = suggester.suggest_all(sorted(uncast), already_cast=already_cast)

        applied = 0
        for result in results:
            if result.top:
                project.cast(result.speaker, result.top.voice_id)
                _out(
                    f"  Cast {result.speaker} as {result.top.voice_id} ({result.top.reason})"
                )
                applied += 1

        project.save()
        _out(f"\nApplied {applied} voice assignments.")
        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cast_export(args) -> int:
    """Export casting table to JSON file."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        path = Path(args.path)
        # CASTING-DEPTH v2.1: honor --format (json|csv); None infers from suffix.
        project.export_casting(path, fmt=getattr(args, "cast_format", None))
        project.save()

        count = len(project.casting.characters)
        fmt = (getattr(args, "cast_format", None) or path.suffix.lstrip(".") or "json").lower()
        _out(f"Exported {count} character(s) to {path} ({fmt})")
        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cast_import(args) -> int:
    """Import casting table from JSON file."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        path = Path(args.path)
        # CASTING-DEPTH v2.1: honor --format (json|csv); None infers from suffix.
        project.import_casting(path, fmt=getattr(args, "cast_format", None))
        project.save()

        count = len(project.casting.characters)
        fmt = (getattr(args, "cast_format", None) or path.suffix.lstrip(".") or "json").lower()
        _out(f"Imported casting table from {path} ({fmt})")
        _out(f"  Total characters: {count}")
        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cast_preset(args) -> int:
    """
    CASTING-DEPTH v2.1: save / list / apply / delete reusable casting presets.

    Presets are stored by casting.presets (casting-owned) in a user config dir.
    Each preset is a list-of-dicts in the same shape as export_casting().

    Subcommands:
      save <name>   — save the current (or --from-project) casting table.
      list          — list saved preset names.
      apply <name>  — merge a preset into the project by normalized name/alias,
                      reporting matched vs unmatched entries.
      delete <name> — remove a saved preset.
    """
    from audiobooker.casting import presets as cast_presets

    sub = getattr(args, "cast_preset_command", None)
    if sub is None:
        print("Usage: audiobooker cast-preset {save|list|apply|delete}")
        return 1

    try:
        if sub == "save":
            return _cast_preset_save(args, cast_presets)
        if sub == "list":
            return _cast_preset_list(args, cast_presets)
        if sub == "apply":
            return _cast_preset_apply(args, cast_presets)
        if sub == "delete":
            return _cast_preset_delete(args, cast_presets)
    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1

    print(f"Unknown cast-preset subcommand: {sub}")
    return 1


def _cast_preset_save(args, cast_presets) -> int:
    """cast-preset save <name> [--from-project PATH]."""
    from audiobooker import AudiobookProject

    seed = getattr(args, "from_project", None)
    project_path = find_project_file(seed or getattr(args, "project", None))
    project = AudiobookProject.load(project_path)

    casting_list = project._casting_as_list()
    if not casting_list:
        _out("No characters to save — the casting table is empty.")
        return 0

    cast_presets.save_preset(args.name, casting_list)
    _out(
        f"Saved preset '{args.name}' with {len(casting_list)} character(s) "
        f"(source: {project_path})."
    )
    return 0


def _cast_preset_list(args, cast_presets) -> int:
    """cast-preset list."""
    names = cast_presets.list_presets() or []

    if getattr(args, "json_output", False):
        import json as json_mod
        print(json_mod.dumps({"presets": names}, indent=2, ensure_ascii=False))
        return 0

    if not names:
        _out("No casting presets saved.")
        _out(f"Preset directory: {cast_presets.preset_dir()}")
        return 0

    _out(f"Saved casting presets ({len(names)}):\n")
    for name in sorted(names):
        _out(f"  {name}")
    _out(f"\nPreset directory: {cast_presets.preset_dir()}")
    return 0


def _cast_preset_apply(args, cast_presets) -> int:
    """cast-preset apply <name> — merge by normalized name/alias.

    Matched: an entry whose name (or one of its aliases) resolves to a speaker
    detected in the project. Unmatched entries are still added to the cast (so
    the preset is fully applied) but reported separately so the user sees which
    preset characters did not correspond to a detected speaker.
    """
    from audiobooker import AudiobookProject

    project_path = find_project_file(getattr(args, "project", None))
    project = AudiobookProject.load(project_path)

    entries = cast_presets.load_preset(args.name) or []
    if not entries:
        _out(f"Preset '{args.name}' is empty — nothing to apply.")
        return 0

    # Compile (if needed) so we can report matched-vs-unmatched against the
    # speakers actually detected in the book.
    if not any(c.is_compiled for c in project.chapters):
        _out("Compiling to detect speakers...")
        project.compile()

    detected = {
        project.casting.normalize_key(s) for s in project.get_detected_speakers()
    }

    matched: list[str] = []
    unmatched: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or "name" not in entry or "voice" not in entry:
            continue
        name = entry["name"]
        keys = {project.casting.normalize_key(name)}
        for alias in entry.get("aliases", []) or []:
            keys.add(project.casting.normalize_key(alias))

        project.cast(
            name=name,
            voice=entry["voice"],
            emotion=entry.get("emotion"),
            description=entry.get("description"),
            speed=entry.get("speed", 1.0),
        )
        if keys & detected:
            matched.append(name)
        else:
            unmatched.append(name)

    project.save()

    _out(f"Applied preset '{args.name}' to {project.title}:")
    _out(f"  Matched detected speakers: {len(matched)}")
    if matched:
        _out(f"    {', '.join(sorted(matched))}")
    _out(f"  Added but not detected:    {len(unmatched)}")
    if unmatched:
        _out(f"    {', '.join(sorted(unmatched))}")
    return 0


def _cast_preset_delete(args, cast_presets) -> int:
    """cast-preset delete <name>."""
    cast_presets.delete_preset(args.name)
    _out(f"Deleted preset '{args.name}'.")
    return 0


def cmd_cast_fill(args) -> int:
    """
    CASTING-DEPTH v2.1: bulk-assign voices to uncast speakers.

    Requires explicit voice pools — no silent magic. Routes the work to the
    casting voice_suggester bulk helper (casting-owned) and prints a summary
    table of what was assigned.

    Pools:
      --voices a,b,c   round-robin pool for ordinary speakers.
      --narrator       voice for the narrator role.
      --minor-voice    voice for minor speakers (<= --minor-threshold lines).
      --gender         restrict the round-robin to one gender (passed through).
      --overwrite      also reassign already-cast speakers.
    """
    from audiobooker import AudiobookProject

    try:
        voices = _parse_voice_pool(getattr(args, "voices", None))
        narrator = getattr(args, "narrator", None)
        minor_voice = getattr(args, "minor_voice", None)

        # Require an explicit pool: at least one of --voices / --narrator /
        # --minor-voice must be given so the fill is never magic. Checked BEFORE
        # loading the project or importing the bulk helper so a bare invocation
        # fails fast with guidance.
        if not voices and not narrator and not minor_voice:
            print(
                "Error: cast-fill needs an explicit voice pool. Provide at least "
                "one of --voices a,b,c / --narrator <voice> / --minor-voice <voice>."
            )
            return 1

        # Imported here (after validation) — casting-owned helper.
        from audiobooker.casting.voice_suggester import bulk_fill_voices

        project_path = find_project_file(getattr(args, "project", None))
        project = AudiobookProject.load(project_path)

        # Compile so speakers + line counts exist for minor/major routing.
        if not any(c.is_compiled for c in project.chapters):
            _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        assignments = bulk_fill_voices(
            project,
            voices=voices,
            narrator=narrator,
            minor_voice=minor_voice,
            minor_threshold=getattr(args, "minor_threshold", 5),
            gender=getattr(args, "gender", None),
            overwrite=getattr(args, "overwrite", False),
        )
        assignments = assignments or {}

        project.save()

        if not assignments:
            _out("No speakers were assigned (all already cast? use --overwrite).")
            return 0

        _out(f"cast-fill assigned {len(assignments)} speaker(s):\n")
        _out(f"  {'Speaker':<24} {'Voice'}")
        _out(f"  {'-'*24} {'-'*16}")
        for speaker in sorted(assignments.keys()):
            _out(f"  {speaker:<24} {assignments[speaker]}")
        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def _parse_voice_pool(raw: Optional[str]) -> list[str]:
    """Parse a comma-separated --voices pool into a clean list."""
    if not raw:
        return []
    return [v.strip() for v in raw.split(",") if v.strip()]


def cmd_emotions(args) -> int:
    """Emotion management commands."""
    from audiobooker import AudiobookProject

    emotions_command = getattr(args, "emotions_command", None)
    if emotions_command is None:
        print("Usage: audiobooker emotions {list|override|mood-span|presets}")
        return 1

    # CASTING-DEPTH v2.1: `emotions presets` lists static pack info and needs no
    # project file, so handle it before find_project_file().
    if emotions_command == "presets":
        return _emotions_presets(args)

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if emotions_command == "mood-span":
            # CASTING-DEPTH v2.1: mark a chapter character-span with a mood.
            fragment = project.set_mood_span(
                args.chapter, args.start, args.end, args.emotion
            )
            project.save()
            preview = fragment[:60] + ("..." if len(fragment) > 60 else "")
            _out(
                f"Applied mood '{args.emotion}' to chapter {args.chapter} "
                f"span [{args.start}, {args.end}):"
            )
            _out(f"  {preview!r}")
            _out("  (re-compile to apply the mood to that span's lines)")
            return 0

        if emotions_command == "list":
            emotions = project.list_emotions()
            if not emotions:
                _out("No compiled chapters with emotion data. Run compile first.")
                return 0

            _out(f"Emotion summary for {project.title}:\n")
            for ch_idx in sorted(emotions.keys()):
                chapter = project.chapters[ch_idx]
                counts = emotions[ch_idx]
                total = sum(counts.values())
                emotion_parts = ", ".join(
                    f"{e}: {c}" for e, c in sorted(counts.items(), key=lambda x: -x[1])
                )
                _out(f"  [{ch_idx}] {chapter.title} ({total} lines): {emotion_parts}")
            return 0

        elif emotions_command == "override":
            project.override_emotion(args.chapter, args.line, args.emotion)
            project.save()
            ch = project.chapters[args.chapter]
            utt = ch.utterances[args.line]
            _out(
                f"Set emotion to '{args.emotion}' on chapter {args.chapter}, "
                f"line {args.line} (speaker: {utt.speaker})"
            )
            return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1

    return 1


def _known_emotion_vocabulary() -> list[str]:
    """CASTING-DEPTH v2.1: best-effort list of the known emotion labels.

    Prefers a vocabulary published by the emotion module (casting-owned); falls
    back to the built-in baseline labels so the command always lists something
    even before the casting side exposes a richer vocabulary.
    """
    try:
        from audiobooker.nlp import emotion as _emotion_mod

        for attr in ("EMOTION_VOCABULARY", "KNOWN_EMOTIONS", "_EMOTION_LEXICON"):
            vocab = getattr(_emotion_mod, attr, None)
            if isinstance(vocab, dict) and vocab:
                return sorted(vocab.keys())
            if isinstance(vocab, (list, tuple, set, frozenset)) and vocab:
                return sorted(str(v) for v in vocab)
    except Exception:
        pass
    # Baseline fallback (matches the built-in lexicon's labels).
    return ["angry", "excited", "fearful", "happy", "neutral", "sad", "whisper"]


def _emotion_presets() -> list[str]:
    """CASTING-DEPTH v2.1: the available emotion preset packs.

    Sourced from ProjectConfig's validated set so the CLI and the model never
    drift. Falls back to the known names if the attribute is unavailable.
    """
    from audiobooker.models import ProjectConfig

    packs = getattr(ProjectConfig, "_VALID_EMOTION_PRESETS", None)
    if packs:
        return list(packs)
    return ["neutral", "literary", "dramatic", "children"]


def _emotions_presets(args) -> int:
    """CASTING-DEPTH v2.1: `emotions presets` — list packs + emotion vocabulary."""
    packs = _emotion_presets()
    vocab = _known_emotion_vocabulary()

    if getattr(args, "json_output", False):
        import json as json_mod
        print(json_mod.dumps(
            {"presets": packs, "emotions": vocab},
            indent=2,
            ensure_ascii=False,
        ))
        return 0

    _out("Emotion preset packs:\n")
    for pack in packs:
        marker = " (default)" if pack == "neutral" else ""
        _out(f"  {pack}{marker}")
    _out("\nKnown emotion vocabulary:\n")
    _out(f"  {', '.join(vocab)}")
    _out(
        "\nSet a preset on compile/make with --emotion-preset <pack>, "
        "or per project via the emotion_preset config field."
    )
    return 0


def cmd_pronunciation(args) -> int:
    """Pronunciation override management."""
    from audiobooker import AudiobookProject

    pronunciation_command = getattr(args, "pronunciation_command", None)
    if pronunciation_command is None:
        print("Usage: audiobooker pronunciation {add|remove|list|import|export}")
        return 1

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if pronunciation_command == "add":
            # CLI-A-008: Go through add_pronunciation() so empty input is
            # rejected and surrounding whitespace is stripped (validation that
            # writing to the dict directly would bypass).
            project.add_pronunciation(args.word, args.replacement)
            project.save()
            _out(
                f"Added pronunciation override: "
                f"'{args.word.strip()}' -> '{args.replacement.strip()}'"
            )
            return 0

        elif pronunciation_command == "remove":
            if args.word in project.config.pronunciation_overrides:
                del project.config.pronunciation_overrides[args.word]
                project.save()
                _out(f"Removed pronunciation override for '{args.word}'")
            else:
                _out(f"No override found for '{args.word}'")
                # List existing ones for reference
                if project.config.pronunciation_overrides:
                    _out("\nExisting overrides:")
                    for w, r in sorted(project.config.pronunciation_overrides.items()):
                        _out(f"  '{w}' -> '{r}'")
            return 0

        elif pronunciation_command == "list":
            overrides = project.config.pronunciation_overrides
            phonemes = getattr(project.config, "phoneme_overrides", {}) or {}
            if not overrides and not phonemes:
                _out("No pronunciation overrides configured.")
                return 0
            if overrides:
                _out(f"Pronunciation overrides ({len(overrides)}):\n")
                for word, replacement in sorted(overrides.items()):
                    _out(f"  '{word}' -> '{replacement}'")
            if phonemes:
                _out(f"\nPhoneme overrides ({len(phonemes)}):\n")
                for word, replacement in sorted(phonemes.items()):
                    _out(f"  '{word}' -> '{replacement}' [phoneme]")
            return 0

        elif pronunciation_command == "import":
            # INPUT (v2.1): merge a lexicon file (CSV/JSON) into the project.
            lexicon_path = Path(args.file)
            project.import_lexicon(lexicon_path)
            project.save()
            spelling = len(project.config.pronunciation_overrides)
            phoneme = len(getattr(project.config, "phoneme_overrides", {}) or {})
            _out(f"Imported lexicon from {lexicon_path}")
            _out(f"  Total overrides: {spelling} spelling, {phoneme} phoneme")
            return 0

        elif pronunciation_command == "export":
            # INPUT (v2.1): write current overrides to a lexicon file (CSV/JSON).
            lexicon_path = Path(args.file)
            project.export_lexicon(lexicon_path)
            project.save()
            spelling = len(project.config.pronunciation_overrides)
            phoneme = len(getattr(project.config, "phoneme_overrides", {}) or {})
            _out(f"Exported {spelling + phoneme} override(s) to {lexicon_path}")
            return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1

    return 1


def cmd_from_stdin(args) -> int:
    """Create project from stdin text."""
    from audiobooker import AudiobookProject

    if sys.stdin.isatty():
        print("Error: No input on stdin. Pipe text in, e.g.:")
        print('  cat book.txt | audiobooker from-stdin --title "My Book"')
        return 1

    text = sys.stdin.read()
    if not text.strip():
        print("Error: stdin was empty")
        return 1

    try:
        # FT-CLI-002: seed config from the cwd-anchored config file (stdin has
        # no source path). CLI --lang wins over a config language.
        file_config = _load_config_file(None)
        config = _build_config_from(
            file_config,
            cli_overrides={},
            base_kwargs={"language_code": args.lang},
        )
        project = AudiobookProject.from_string(
            text,
            title=args.title,
            author=args.author,
            lang=args.lang,
            config=config,
            chapter_delimiter=getattr(args, "chapter_delimiter", None),
        )

        # FT-CLI-002: book/casting/lexicon sections (paths relative to cwd).
        _apply_config_sections(project, file_config, base_dir=Path.cwd())

        # Route the title through the filename sanitizer so titles with
        # slashes/colons/etc. don't produce an invalid default output path.
        from audiobooker.project import _sanitize_filename
        output_path = args.output or f"{_sanitize_filename(args.title)}.audiobooker"
        project.save(output_path)

        _out(f"Project created: {output_path}")
        _out(f"  Title: {project.title}")
        _out(f"  Chapters: {len(project.chapters)}")
        _out(f"  Words: ~{project.total_words:,}")
        _out(f"  Language: {args.lang}")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_status(args) -> int:
    """Show render cache status and project overview (FT-RENDER-002)."""
    from audiobooker import AudiobookProject
    from audiobooker.renderer.cache_manifest import (
        get_cache_root, get_manifest_path, load_manifest,
    )

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        total_words = sum(ch.word_count for ch in project.chapters)
        json_output = getattr(args, "json_output", False)

        # Cache info
        cache_root = get_cache_root(project_path.parent)
        cache_exists = cache_root.exists()

        ok_count = 0
        failed_count = 0
        last_render = ""
        total_size = 0
        if cache_exists:
            manifest_path = get_manifest_path(cache_root)
            manifest = load_manifest(manifest_path)
            if manifest:
                ok_count = len(manifest.ok_chapters())
                failed_count = len(manifest.failed_chapters())
                last_render = manifest.last_updated or "(unknown)"
            for f in cache_root.rglob("*"):
                if f.is_file():
                    total_size += f.stat().st_size

        pending = len(project.chapters) - ok_count - failed_count

        if json_output:
            import json as json_mod
            payload = {
                "title": project.title,
                "author": project.author,
                "format": project.config.output_format,
                "chapters": len(project.chapters),
                "words": total_words,
                "cache_exists": cache_exists,
                "rendered_cached": ok_count,
                "failed": failed_count,
                "pending": pending,
                "cache_bytes": total_size,
                "last_render": last_render or None,
            }
            print(json_mod.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        _out(f"Project: {project.title}")
        if project.author:
            _out(f"Author:  {project.author}")
        _out(f"Format:  {project.config.output_format}")
        _out(f"Chapters: {len(project.chapters)}")
        _out(f"Words:   ~{total_words:,}")

        if not cache_exists:
            _out("\nCache: not created yet (no renders)")
            return 0

        if total_size >= 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024):.1f} MB"
        elif total_size >= 1024:
            size_str = f"{total_size / 1024:.1f} KB"
        else:
            size_str = f"{total_size} bytes"

        _out(f"\nRender Cache: {cache_root}")
        _out(f"  Rendered (cached): {ok_count}")
        _out(f"  Failed:            {failed_count}")
        _out(f"  Pending:           {pending}")
        _out(f"  Disk usage:        {size_str}")
        if last_render:
            _out(f"  Last render:       {last_render}")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_cache(args) -> int:
    """Cache management commands (FT-RENDER-009)."""
    cache_command = getattr(args, "cache_command", None)
    if cache_command is None:
        print("Usage: audiobooker cache {info|clean|clean-failed}")
        return 1

    from audiobooker import AudiobookProject
    from audiobooker.renderer.cache_manifest import (
        get_cache_root, get_manifest_path, load_manifest, save_manifest,
    )
    import shutil

    try:
        project_path = find_project_file(args.project)
        AudiobookProject.load(project_path)  # validate project is loadable
        cache_root = get_cache_root(project_path.parent)

        if cache_command == "info":
            if not cache_root.exists():
                _out("No cache directory found.")
                return 0

            manifest_path = get_manifest_path(cache_root)
            manifest = load_manifest(manifest_path)

            total_size = 0
            file_count = 0
            for f in cache_root.rglob("*"):
                if f.is_file():
                    total_size += f.stat().st_size
                    file_count += 1

            if total_size >= 1024 * 1024:
                size_str = f"{total_size / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{total_size / 1024:.1f} KB"

            _out(f"Cache directory: {cache_root}")
            _out(f"  Files: {file_count}")
            _out(f"  Total size: {size_str}")
            if manifest:
                _out(f"  OK chapters: {len(manifest.ok_chapters())}")
                _out(f"  Failed chapters: {len(manifest.failed_chapters())}")
                _out(f"  Last updated: {manifest.last_updated}")
            return 0

        elif cache_command == "clean":
            if not cache_root.exists():
                _out("No cache to clean.")
                return 0
            # Safety check for lockfile
            lock_path = cache_root / ".render.lock"
            if lock_path.exists():
                print(
                    f"WARNING: Cache appears to be in use (lockfile: {lock_path}).\n"
                    f"If no render is active, delete the lockfile manually."
                )
                return 1
            shutil.rmtree(cache_root)
            _out(f"Cache deleted: {cache_root}")
            return 0

        elif cache_command == "clean-failed":
            if not cache_root.exists():
                _out("No cache directory found.")
                return 0

            manifest_path = get_manifest_path(cache_root)
            manifest = load_manifest(manifest_path)
            if manifest is None:
                _out("No manifest found.")
                return 0

            failed = manifest.failed_chapters()
            if not failed:
                _out("No failed entries to clean.")
                return 0

            cleaned = 0
            for entry in failed:
                # Remove WAV if it exists
                if entry.wav_path:
                    wav = Path(entry.wav_path)
                    if wav.exists():
                        wav.unlink()
                # Reset entry in manifest — remove it so it will be re-rendered
                idx = entry.chapter_index
                pos = manifest._index.get(idx)
                if pos is not None:
                    manifest.chapters[pos].status = "pending"
                    manifest.chapters[pos].error_summary = ""
                    manifest.chapters[pos].wav_path = ""
                cleaned += 1

            save_manifest(manifest, manifest_path)
            _out(f"Cleaned {cleaned} failed entries. They will be re-rendered on next run.")
            return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1

    return 0


def cmd_report(args) -> int:
    """Show a compile quality report (FT-CAST-014).

    Wires the existing casting.compile_report() into the CLI: unknown
    attribution rate, the top unattributed lines with context, and the
    overall emotion distribution.
    """
    from audiobooker import AudiobookProject
    from audiobooker.casting import compile_report

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        json_output = getattr(args, "json_output", False)

        # Need compiled utterances to report on.
        if not any(c.is_compiled for c in project.chapters):
            # Suppress the prep message under --json so stdout stays pure JSON.
            if not json_output:
                _out("Compiling to generate report...")
            project.compile()
            project.save()

        report = compile_report(project.chapters, project.casting)

        if json_output:
            import json as json_mod
            print(json_mod.dumps(report, indent=2, ensure_ascii=False))
            return 0

        unknown_pct = report["unknown_rate"] * 100
        _out(f"Compile report for {project.title}:\n")
        _out(f"  Total utterances:  {report['total_utterances']}")
        _out(f"  Dialogue / narration: {report['total_dialogue']} / {report['total_narration']}")
        _out(f"  Unattributed rate: {unknown_pct:.1f}%")

        emotion_dist = report.get("emotion_distribution") or {}
        if emotion_dist:
            parts = ", ".join(
                f"{e}: {c}"
                for e, c in sorted(emotion_dist.items(), key=lambda x: -x[1])
            )
            _out(f"  Emotions:          {parts}")

        top = report.get("top_unattributed") or []
        if top:
            _out("\nTop unattributed lines (assign a speaker to fix):")
            for item in top:
                text = item["text"]
                _out(
                    f"  ch{item['chapter_index']} line {item['line_index']}: {text!r}"
                )
                if item.get("context"):
                    _out(f"    context: {item['context']!r}")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_diagnose(args: argparse.Namespace) -> int:
    """Check environment: dependencies, voice engine, ffmpeg."""
    import json as json_mod
    import shutil

    from audiobooker import __version__

    checks: list[dict[str, str | None]] = []
    all_ok = True

    # Python version
    py_ver = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    py_ok = sys.version_info >= (3, 10)
    checks.append(
        {
            "check": "python_version",
            "status": "ok" if py_ok else "fail",
            "value": py_ver,
            "hint": None if py_ok else "audiobooker requires Python 3.10+",
        }
    )
    if not py_ok:
        all_ok = False

    # Core dependency: ebooklib
    try:
        import ebooklib  # noqa: F401

        checks.append(
            {
                "check": "dep.ebooklib",
                "status": "ok",
                "value": "installed",
                "hint": None,
            }
        )
    except ImportError:
        checks.append(
            {
                "check": "dep.ebooklib",
                "status": "fail",
                "value": "missing",
                "hint": "pip install ebooklib",
            }
        )
        all_ok = False

    # Optional: pymupdf (PDF sources)
    try:
        import fitz  # noqa: F401  (pymupdf)

        checks.append(
            {
                "check": "dep.pymupdf",
                "status": "ok",
                "value": "installed",
                "hint": None,
            }
        )
    except ImportError:
        checks.append(
            {
                "check": "dep.pymupdf",
                "status": "info",
                "value": "not installed",
                "hint": "pip install pymupdf — required for PDF sources",
            }
        )

    # Optional: python-docx (DOCX sources)
    try:
        import docx  # noqa: F401  (python-docx)

        checks.append(
            {
                "check": "dep.python-docx",
                "status": "ok",
                "value": "installed",
                "hint": None,
            }
        )
    except ImportError:
        checks.append(
            {
                "check": "dep.python-docx",
                "status": "info",
                "value": "not installed",
                "hint": "pip install python-docx — required for DOCX sources "
                        "(or: pip install 'audiobooker-ai[docx]')",
            }
        )

    # Optional: voice-soundboard
    # Narrowed: a missing package is "info"/not installed, but an unexpected
    # error (broken install, model load failure) should report the ACTUAL
    # error rather than masquerading as "not installed".
    try:
        from audiobooker.casting.voice_registry import get_available_voices

        voices = get_available_voices()
        checks.append(
            {
                "check": "voice_engine",
                "status": "ok",
                "value": f"{len(voices)} voices available",
                "hint": None,
            }
        )
    except ImportError:
        checks.append(
            {
                "check": "voice_engine",
                "status": "info",
                "value": "not installed",
                "hint": VOICE_SOUNDBOARD_INSTALL_HINT,
            }
        )
    except Exception as e:
        checks.append(
            {
                "check": "voice_engine",
                "status": "fail",
                "value": f"error: {e}",
                "hint": "voice-soundboard is installed but failed to load. "
                        "Run with --debug for the full traceback.",
            }
        )
        all_ok = False

    # ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        checks.append(
            {"check": "ffmpeg", "status": "ok", "value": ffmpeg_path, "hint": None}
        )
    else:
        checks.append(
            {
                "check": "ffmpeg",
                "status": "info",
                "value": "not found",
                "hint": "Install ffmpeg for M4B assembly",
            }
        )

    # ffprobe (used for duration/metadata probing during assembly)
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        checks.append(
            {"check": "ffprobe", "status": "ok", "value": ffprobe_path, "hint": None}
        )
    else:
        checks.append(
            {
                "check": "ffprobe",
                "status": "info",
                "value": "not found",
                "hint": "Install ffmpeg (ffprobe ships with it) for audio probing",
            }
        )

    # Package version
    checks.append(
        {
            "check": "audiobooker_version",
            "status": "ok",
            "value": __version__,
            "hint": None,
        }
    )

    if getattr(args, "json_output", False):
        print(json_mod.dumps({"ok": all_ok, "checks": checks}, indent=2))
    else:
        print(f"audiobooker v{__version__} — environment diagnostics\n")
        for c in checks:
            icon = (
                "OK"
                if c["status"] == "ok"
                else ("INFO" if c["status"] == "info" else "FAIL")
            )
            print(f"  [{icon}] {c['check']}: {c['value']}")
            if c["hint"]:
                print(f"         Hint: {c['hint']}")
        print()
        if all_ok:
            print("All checks passed.")
        else:
            print("Some checks failed. See hints above.")

    return 0 if all_ok else 1


def _process_book(
    source: Path,
    *,
    fmt: str,
    jobs: int,
    lang: str,
    overrides: Optional[dict] = None,
    render_overrides: Optional[dict] = None,
    output_path: Optional[Path] = None,
    emotion_preset: Optional[str] = None,
) -> dict:
    """Create + compile + auto-cast + render a single source file.

    This is the canonical per-book sequence shared by `batch` (FT-RENDER-012)
    and `make` (FT-CLI-001) so both run byte-for-byte identical steps:
    config-file merge -> source factory -> config sections -> compile ->
    auto-cast (VoiceSuggester top suggestion) -> save -> render_project.

    Args:
        source: Source file or chapter folder.
        fmt: Output format (m4b/mp3/wav).
        jobs: Parallel render workers.
        lang: Language code.
        overrides: Optional manifest-style per-book metadata (title/author/
            cover/series/series_index/cast) applied on top of config-file
            sections.
        render_overrides: Extra render_project kwargs (cover_art/normalize/
            output_profile/bitrate) — used by `make` for --cover/--acx/etc.
        output_path: Explicit output audio path (default derives from title).

    Returns:
        A result dict: {file, name, status, output, error, duration_s}.
        Never raises — render/parse errors are captured into the dict.
    """
    import time as _time
    from audiobooker import AudiobookProject
    from audiobooker.project import _sanitize_filename
    from audiobooker.renderer.engine import RenderError, render_project

    overrides = overrides or {}
    render_overrides = render_overrides or {}

    book_start = _time.time()
    book_result = {
        "file": str(source),
        "name": source.stem,
        "status": "unknown",
        "output": "",
        "error": "",
        "duration_s": 0.0,
    }

    try:
        # Step 1: Create project. FT-CLI-002: seed config from the on-disk
        # config file next to this source, with the --lang/--format CLI flags
        # winning over config-file values.
        file_config = _load_config_file(str(source))
        config = _build_config_from(
            file_config,
            cli_overrides={
                "output_format": overrides.get("format") or fmt,
                # CASTING-DEPTH v2.1: --emotion-preset flows through make.
                "emotion_preset": emotion_preset,
            },
            base_kwargs={"language_code": overrides.get("lang") or lang},
        )

        suffix = source.suffix.lower()
        if source.is_dir():
            project = AudiobookProject.from_folder(source, config=config)
        elif suffix == ".epub":
            project = AudiobookProject.from_epub(source, config=config)
        elif suffix == ".docx":
            project = AudiobookProject.from_docx(source, config=config)
        elif suffix == ".pdf":
            project = AudiobookProject.from_pdf(source, config=config)
        elif suffix in (".txt", ".md", ".markdown"):
            project = AudiobookProject.from_text(source, config=config)
        else:
            book_result["status"] = "skipped"
            book_result["error"] = f"Unsupported format: {suffix}"
            book_result["duration_s"] = _time.time() - book_start
            return book_result

        base_dir = source if source.is_dir() else source.parent

        # FT-CLI-002: apply book/casting/lexicon sections from the config file
        # before compile (so a config casting table is honored).
        _apply_config_sections(project, file_config, base_dir=base_dir)

        # FT-CLI-006: apply manifest per-book overrides (highest precedence,
        # over both config-file sections and parsed metadata).
        _apply_book_overrides(project, overrides, base_dir=base_dir)

        book_result["name"] = project.title

        # Step 2: Compile
        project.compile()

        # Step 3: Auto-cast with suggestions
        uncast = project.get_uncast_speakers()
        if uncast:
            try:
                from audiobooker.casting.voice_suggester import VoiceSuggester
                already_cast = project.casting.get_voice_mapping()
                suggester = VoiceSuggester(max_suggestions=1)
                suggest_results = suggester.suggest_all(
                    sorted(uncast), already_cast=already_cast
                )
                for sr in suggest_results:
                    if sr.top:
                        project.cast(sr.speaker, sr.top.voice_id)
            except Exception as cast_err:
                _out(f"  Warning: Auto-cast failed ({cast_err}), using fallback voices")

        # Step 4: Save project. A directory source has no file suffix to swap,
        # so place the project file alongside the folder.
        if source.is_dir():
            project_path = source.parent / f"{source.name}.audiobooker"
        else:
            project_path = source.with_suffix(".audiobooker")
        project.save(project_path)

        # Step 5: Render
        out_fmt = overrides.get("format") or fmt
        if output_path is not None:
            final_output = Path(output_path)
        else:
            final_output = source.parent / f"{_sanitize_filename(project.title)}.{out_fmt}"

        # FT-RENDER-M-002: pass cover art + metadata through. render_project
        # auto-defaults cover_art from project.metadata.cover_art_path when None.
        md_cover = None
        if project.metadata.cover_art_path and Path(project.metadata.cover_art_path).exists():
            md_cover = str(project.metadata.cover_art_path)
        render_kwargs = dict(
            jobs=jobs,
            force=True,  # skip casting validation in batch/make
            output_format=out_fmt,
            cover_art=md_cover,
            output_profile=project.config.output_profile,
        )
        # make's --cover/--normalize/--acx/--bitrate land here.
        render_kwargs.update(render_overrides)
        try:
            path = render_project(project, final_output, **render_kwargs)
        except TypeError as te:
            # Older renderer signature: drop the v2.1 kwargs and retry.
            if not any(
                k in str(te) for k in ("output_profile", "bitrate", "normalize")
            ):
                raise
            for k in ("output_profile", "bitrate", "normalize"):
                render_kwargs.pop(k, None)
            path = render_project(project, final_output, **render_kwargs)

        book_result["status"] = "success"
        book_result["output"] = str(path)
        book_result["duration_s"] = _time.time() - book_start

    except RenderError as e:
        book_result["status"] = "failed"
        book_result["error"] = str(e)[:200]
        book_result["duration_s"] = _time.time() - book_start

    except Exception as e:
        book_result["status"] = "error"
        book_result["error"] = str(e)[:200]
        book_result["duration_s"] = _time.time() - book_start

    return book_result


def _apply_book_overrides(project, overrides: dict, *, base_dir: Path) -> None:
    """FT-CLI-006: apply manifest per-book metadata onto a project.

    Recognized keys: title, author, cover, series, series_index, year, genre,
    narrator, cast (path to a casting JSON, resolved relative to base_dir).
    Best effort: a missing cast file warns and is skipped.
    """
    if not overrides:
        return
    meta = project.metadata
    if overrides.get("title"):
        project.title = str(overrides["title"])
    if overrides.get("author"):
        project.author = str(overrides["author"])
    if overrides.get("genre"):
        meta.genre = str(overrides["genre"])
    if overrides.get("series"):
        meta.series = str(overrides["series"])
    if overrides.get("series_index") is not None:
        try:
            meta.series_index = int(overrides["series_index"])
        except (TypeError, ValueError):
            print(f"WARNING: ignoring non-integer series_index: {overrides['series_index']!r}")
    if overrides.get("year") is not None:
        try:
            meta.year = int(overrides["year"])
        except (TypeError, ValueError):
            print(f"WARNING: ignoring non-integer year: {overrides['year']!r}")
    if overrides.get("narrator"):
        meta.narrator_name = str(overrides["narrator"])

    cover = overrides.get("cover")
    if cover:
        cover_path = Path(cover)
        if not cover_path.is_absolute():
            cover_path = base_dir / cover_path
        if cover_path.exists():
            meta.cover_art_path = cover_path
        else:
            print(f"WARNING: cover art not found, skipping: {cover_path}")

    cast_ref = overrides.get("cast")
    if cast_ref:
        cast_path = Path(cast_ref)
        if not cast_path.is_absolute():
            cast_path = base_dir / cast_path
        try:
            project.import_casting(cast_path)
        except (FileNotFoundError, ValueError) as e:
            print(f"WARNING: could not import casting from manifest ({e})")


def _load_manifest(path: Path) -> list[dict]:
    """FT-CLI-006: load a batch manifest (.toml or .json) into a list of dicts.

    Accepts either a top-level list (JSON array) or a table with a "books"
    list. Each entry must carry at least a "source" key. Raises ValueError on
    a malformed manifest and FileNotFoundError when the file is missing.
    """
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        import json as json_mod
        try:
            data = json_mod.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ValueError(f"Could not parse JSON manifest {path}: {e}") from e
    elif suffix == ".toml":
        from audiobooker import config_file as _cf
        if not _cf.have_toml_support():
            raise ValueError(
                "TOML manifest requested but no TOML parser is available "
                "(install 'tomli' on Python 3.10)."
            )
        # Reuse config_file's resolved TOML loader (returns None on bad TOML).
        data = _cf._read_toml(path)
        if data is None:
            raise ValueError(f"Could not parse TOML manifest: {path}")
    else:
        raise ValueError(
            f"Unsupported manifest format: {suffix!r}. Use .toml or .json."
        )

    if isinstance(data, list):
        books = data
    elif isinstance(data, dict) and isinstance(data.get("books"), list):
        books = data["books"]
    else:
        raise ValueError(
            "Manifest must be a list of book entries or a table with a "
            "'books' list."
        )

    cleaned: list[dict] = []
    for entry in books:
        if not isinstance(entry, dict) or not entry.get("source"):
            raise ValueError(
                f"Each manifest entry must be an object with a 'source' key; "
                f"got: {entry!r}"
            )
        cleaned.append(entry)
    return cleaned


def cmd_batch(args) -> int:
    """
    FT-RENDER-012: Batch process multiple source files.

    For each source file: create project -> auto-cast -> compile -> render.
    Logs per-book progress, elapsed time, and summary table at the end.

    FT-CLI-006: with --manifest, reads per-book metadata + casting from a
    TOML/JSON manifest instead of (or in addition to) glob/file arguments.
    """
    import glob as glob_mod
    import time as _time

    # FT-CLI-006: manifest mode builds (source, overrides) pairs; glob mode
    # builds (source, {}) pairs. Both funnel through _process_book.
    manifest_entries: list[dict] = []
    manifest_file = getattr(args, "manifest", None)
    if manifest_file:
        try:
            manifest_entries = _load_manifest(Path(manifest_file))
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    fmt = getattr(args, "output_format", None) or "m4b"
    jobs = getattr(args, "jobs", 1)
    lang = getattr(args, "lang", "en")
    supported = {".epub", ".docx", ".txt", ".md", ".markdown", ".pdf"}

    # FT-CLI-006: manifest mode — each entry is (source path, overrides dict).
    # Glob mode — each entry is (source path, {}). Both funnel through the
    # shared _process_book sequence below.
    book_specs: list[tuple[Path, dict]] = []

    if manifest_entries:
        for entry in manifest_entries:
            src = Path(str(entry["source"]))
            book_specs.append((src, entry))

    # Expand glob patterns (also runs alongside a manifest if files were given).
    if args.files:
        source_files: list[Path] = []
        for pattern in args.files:
            expanded = glob_mod.glob(pattern, recursive=True)
            if expanded:
                source_files.extend(Path(f) for f in expanded)
            else:
                source_files.append(Path(pattern))
        source_files = list(dict.fromkeys(source_files))  # dedupe, keep order
        source_files = [
            f for f in source_files
            if f.exists() and (f.is_dir() or f.suffix.lower() in supported)
        ]
        for f in source_files:
            book_specs.append((f, {}))

    if not book_specs:
        if manifest_file:
            print("Manifest contained no usable book entries.")
        else:
            print("No supported source files found (EPUB/DOCX/TXT/MD/PDF or a chapter folder).")
        return 1

    json_output = getattr(args, "json_output", False)

    # --dry-run: show what would be processed without rendering
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        _out(f"DRY RUN — {len(book_specs)} book(s) would be processed:\n")
        for i, (source, ov) in enumerate(book_specs, 1):
            label = ov.get("title") or source.name
            _out(f"  [{i}/{len(book_specs)}] {label} ({source})")
        _out(f"\nFormat: {fmt}")
        _out(f"Language: {lang}")
        _out(f"Workers: {jobs}")
        return 0

    _out(f"Batch processing {len(book_specs)} book(s)...\n")

    results: list[dict] = []
    batch_start = _time.time()

    for i, (source, overrides) in enumerate(book_specs, 1):
        _out(f"[{i}/{len(book_specs)}] {overrides.get('title') or source.name}")

        if not source.exists():
            results.append({
                "file": str(source),
                "name": source.stem,
                "status": "error",
                "output": "",
                "error": f"Source not found: {source}",
                "duration_s": 0.0,
            })
            _out(f"  ERROR: source not found: {source}")
            continue
        if not source.is_dir() and source.suffix.lower() not in supported:
            results.append({
                "file": str(source),
                "name": source.stem,
                "status": "skipped",
                "output": "",
                "error": f"Unsupported format: {source.suffix}",
                "duration_s": 0.0,
            })
            _out(f"  Skipped: unsupported format {source.suffix}")
            continue

        book_result = _process_book(
            source,
            fmt=fmt,
            jobs=jobs,
            lang=lang,
            overrides=overrides,
        )
        status = book_result["status"]
        if status == "success":
            _out(f"  OK: {book_result['output']} ({book_result['duration_s']:.1f}s)")
        elif status == "failed":
            _out(f"  FAILED: {book_result['error']}")
        elif status == "skipped":
            _out(f"  Skipped: {book_result['error']}")
        else:
            _out(f"  ERROR: {book_result['error']}")
        results.append(book_result)

    # Summary
    total_elapsed = _time.time() - batch_start
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] in ("failed", "error"))
    skipped = sum(1 for r in results if r["status"] == "skipped")

    # --json: emit the results array (machine-readable) instead of the table.
    if json_output:
        import json as json_mod
        print(json_mod.dumps(
            {
                "succeeded": success,
                "failed": failed,
                "skipped": skipped,
                "total_elapsed_s": round(total_elapsed, 2),
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ))
        if failed == 0:
            return 0
        return 3 if success > 0 else 1

    def _fmt_duration(s: float) -> str:
        if s >= 3600:
            return f"{s / 3600:.1f}h"
        elif s >= 60:
            return f"{s / 60:.1f}m"
        return f"{s:.1f}s"

    _out(f"\n{'='*72}")
    _out(f"  BATCH SUMMARY — {success} succeeded, {failed} failed, {skipped} skipped")
    _out(f"  Total elapsed: {_fmt_duration(total_elapsed)}")
    _out(f"{'='*72}")
    _out(f"  {'#':<4} {'Status':<10} {'Duration':<10} {'Title':<28} {'Output'}")
    _out(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*28} {'-'*20}")
    for idx, r in enumerate(results, 1):
        status = r["status"].upper()
        dur = _fmt_duration(r["duration_s"])
        name = r["name"][:27]
        out = r["output"] if r["status"] == "success" else r.get("error", "")[:40]
        _out(f"  {idx:<4} {status:<10} {dur:<10} {name:<28} {out}")
    _out(f"{'='*72}")

    if failed == 0:
        return 0
    elif success > 0:
        return 3  # partial success
    else:
        return 1


def _run_make_once(args) -> dict:
    """FT-CLI-001: run the full make sequence once for args.source.

    Reuses _process_book (the exact per-file sequence cmd_batch uses) and
    threads make's render-time options (cover/normalize/acx/bitrate/output).
    Returns the book_result dict.
    """
    source = Path(args.source)
    fmt = getattr(args, "output_format", None) or "m4b"
    jobs = getattr(args, "jobs", 1)
    lang = getattr(args, "lang", "en")

    render_overrides: dict = {}
    cover = getattr(args, "cover", None)
    if cover:
        render_overrides["cover_art"] = cover
    if getattr(args, "normalize", False):
        render_overrides["normalize"] = True
    if getattr(args, "acx", False):
        render_overrides["output_profile"] = "acx"
    bitrate = getattr(args, "bitrate", None)
    if bitrate:
        render_overrides["bitrate"] = bitrate

    output_path = getattr(args, "output", None)
    return _process_book(
        source,
        fmt=fmt,
        jobs=jobs,
        lang=lang,
        render_overrides=render_overrides,
        output_path=Path(output_path) if output_path else None,
        emotion_preset=getattr(args, "emotion_preset", None),
    )


def cmd_make(args) -> int:
    """
    FT-CLI-001: One command — create + compile + auto-cast + render.

    Runs the exact per-file sequence cmd_batch uses (via _process_book), so a
    single `audiobooker make book.epub` goes from source to a finished, cast,
    rendered audiobook. The staged commands (new/compile/cast/render) remain
    available for users who want manual control of each step.
    """
    source = Path(args.source)
    if not source.exists():
        print(f"Error: Source file not found: {source}")
        return 1

    # FT-CLI-008: watch mode — re-run make whenever the source mtime changes.
    if getattr(args, "watch", False):
        return _watch_loop(source, lambda: _make_summary(_run_make_once(args)))

    return _make_summary(_run_make_once(args))


def _make_summary(book_result: dict) -> int:
    """Print a single-book make result and return the process exit code."""
    status = book_result["status"]
    if status == "success":
        _out(f"\nAudiobook created: {book_result['output']}")
        _out(f"  Source: {book_result['file']}")
        _out(f"  Elapsed: {book_result['duration_s']:.1f}s")
        return 0
    if status == "skipped":
        print(f"Skipped: {book_result['error']}")
        return 1
    # failed / error
    print(f"Make failed: {book_result['error']}")
    return 1


def _watch_loop(source: Path, run_once) -> int:
    """
    FT-CLI-008: poll the source file's mtime and re-run on change.

    Runs ``run_once`` immediately, then watches ``source`` for modifications,
    debouncing rapid successive writes. The callable should re-render with
    resume=True so only changed chapters re-render (handled by the batch/make
    sequence via the render cache). Ctrl-C exits cleanly with code 0.

    ``run_once`` is a zero-arg callable returning an int exit code (ignored
    between iterations; the watch loop itself returns 0 on Ctrl-C).
    """
    debounce_seconds = 1.0
    poll_interval = 1.0

    def _mtime() -> float:
        try:
            return source.stat().st_mtime
        except OSError:
            return 0.0

    _out(f"Watching {source} for changes (Ctrl-C to stop)...")
    run_once()
    last_mtime = _mtime()

    try:
        while True:
            time.sleep(poll_interval)
            current = _mtime()
            if current != last_mtime and current != 0.0:
                # Debounce: wait for writes to settle before re-running.
                time.sleep(debounce_seconds)
                settled = _mtime()
                if settled != current:
                    # Still being written — pick it up on the next poll.
                    last_mtime = current
                    continue
                _out(f"\nChange detected in {source.name} — re-rendering...")
                run_once()
                last_mtime = _mtime()
    except KeyboardInterrupt:
        _out("\nStopped watching.")
        return 0


def cmd_preview(args) -> int:
    """
    FT-RENDER-007: Render a short chapter sample for voice validation.

    Renders the first N utterances (estimated by target seconds) from a
    chapter using the existing pipeline, outputting to a temporary WAV.
    """
    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import render_chapter, RenderError

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        chapter_idx = args.chapter
        target_seconds = args.seconds

        if chapter_idx >= len(project.chapters):
            print(f"Error: Chapter {chapter_idx} not found (only {len(project.chapters)} chapters)")
            return 1

        chapter = project.chapters[chapter_idx]

        # Compile if needed
        if not chapter.is_compiled:
            _out("Compiling chapter...")
            project.compile()
            project.save()
            chapter = project.chapters[chapter_idx]

        if not chapter.utterances:
            print(f"Error: Chapter {chapter_idx} has no utterances after compilation")
            return 1

        # Estimate how many utterances fit in target_seconds
        # Rough heuristic: 150 words per minute, ~5 chars per word
        chars_per_second = (150 * 5) / 60  # ~12.5 chars/sec
        target_chars = int(target_seconds * chars_per_second)

        # Truncate utterances to approximate target duration
        from audiobooker.models import Chapter
        preview_chapter = Chapter(
            title=f"Preview: {chapter.title}",
            raw_text="",
            index=chapter.index,
        )

        accumulated_chars = 0
        for utt in chapter.utterances:
            if accumulated_chars >= target_chars:
                break
            preview_chapter.utterances.append(utt)
            accumulated_chars += len(utt.text)

        if not preview_chapter.utterances:
            preview_chapter.utterances = chapter.utterances[:1]

        output_path = Path(args.output or "preview.wav")

        _out(f"Previewing chapter {chapter_idx}: {chapter.title}")
        _out(f"  Utterances: {len(preview_chapter.utterances)} of {len(chapter.utterances)}")
        _out(f"  Target duration: ~{target_seconds}s")

        path = render_chapter(
            preview_chapter,
            project.casting,
            output_path,
        )

        _out(f"\nPreview saved: {path}")
        return 0

    except RenderError as e:
        _report_error(e, args)
        return 1

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1

    except Exception as e:
        _report_error(e, args)
        return 2


def cmd_sample(args) -> int:
    """
    OUTPUT-F1: Render a mastered retail sample clip.

    Distinct from 'preview' (which is quick voice QA): 'sample' produces a
    trimmed, mastered clip suitable for a retail listing / ACX sample, reusing
    rendered chapter audio from the cache when available.
    """
    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import render_sample, RenderError

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        from_chapter = getattr(args, "from_chapter", 0)
        start_seconds = getattr(args, "start_seconds", 0.0)
        duration = getattr(args, "duration", 180.0)
        output_profile = "acx" if getattr(args, "acx", False) else project.config.output_profile
        bitrate = getattr(args, "bitrate", None)
        output = getattr(args, "output", None)

        if from_chapter < 0 or from_chapter >= len(project.chapters):
            print(
                f"Error: Chapter {from_chapter} not found "
                f"(project has {len(project.chapters)} chapters)"
            )
            return 1

        _out(f"Rendering sample from chapter {from_chapter}...")
        _out(f"  Start: {start_seconds:.0f}s  Duration: {duration:.0f}s  Profile: {output_profile}")

        path = render_sample(
            project,
            from_chapter=from_chapter,
            start_seconds=start_seconds,
            duration=duration,
            output_path=Path(output) if output else None,
            output_profile=output_profile,
            bitrate=bitrate,
        )

        _out(f"\nSample saved: {path}")
        return 0

    except RenderError as e:
        _report_error(e, args)
        return 1

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1

    except Exception as e:
        _report_error(e, args)
        return 2


def cmd_master_check(args) -> int:
    """
    OUTPUT-F1: Check an audio file against ACX loudness/peak/noise-floor limits.

    Prints PASS/FAIL per criterion (human-readable) or the full result dict
    (--json). Exits 0 when the file passes, 1 when it fails the profile checks,
    and 1 on user errors (missing file).
    """
    from audiobooker.renderer.output import master_check

    try:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: Audio file not found: {file_path}")
            return 1

        result = master_check(file_path)

        if getattr(args, "json_output", False):
            import json as json_mod
            print(json_mod.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result.get("passes") else 1

        passes = result.get("passes", False)
        profile = result.get("profile", "acx")
        _out(f"Master check ({profile}) for {file_path.name}:\n")
        _out(f"  RMS:         {result.get('measured_rms_db')} dB")
        _out(f"  Peak:        {result.get('measured_peak_db')} dBTP")
        _out(f"  Noise floor: {result.get('measured_noise_floor_db')} dB")
        failures = result.get("failures") or []
        if passes:
            _out(
                "\nResult: PASS — meets ACX's measurable loudness, peak, and "
                "noise-floor limits.\n"
                "(ACX also has subjective/quality criteria this check can't verify.)"
            )
        else:
            _out("\nResult: FAIL")
            for failure in failures:
                _out(f"  - {failure}")
        return 0 if passes else 1

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_export_chapters(args) -> int:
    """
    OUTPUT-F1: Export chapter markers as ffmetadata, CUE, or JSON.

    Writes to the file given by -o, or to stdout when omitted. Uses each
    chapter's rendered duration_seconds; chapters with no rendered audio
    contribute a 0-length marker (the contract handles formatting).
    """
    from audiobooker import AudiobookProject
    from audiobooker.renderer.output import export_chapter_metadata

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        fmt = getattr(args, "chapter_format", "ffmetadata")

        # Build (title, duration_seconds) pairs from project chapters. The
        # exporter accepts (title, duration) or (path, title, duration) tuples
        # and computes cumulative timings itself.
        chapters_data = [
            (ch.title, ch.duration_seconds)
            for ch in project.chapters
            if not ch.skip
        ]

        contents = export_chapter_metadata(
            chapters_data, fmt=fmt, title=project.title
        )

        output = getattr(args, "output", None)
        if output:
            out_path = Path(output)
            out_path.write_text(contents, encoding="utf-8")
            _out(f"Chapter metadata ({fmt}) written to {out_path}")
        else:
            # Raw contents to stdout (not via _out so --silent still emits the
            # payload, which is the whole point of stdout export).
            print(contents)

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # --- Configure logging levels (silent < normal < verbose < debug) ---
    import logging as _logging

    # Set the module-level quiet flag so _out() suppresses normal output.
    global _QUIET
    _QUIET = getattr(args, "silent", False)

    if getattr(args, "silent", False):
        _logging.basicConfig(level=_logging.CRITICAL)
    elif getattr(args, "debug", False):
        _logging.basicConfig(level=_logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    else:
        _logging.basicConfig(level=_logging.WARNING)

    # Redact secrets in all log output
    for handler in _logging.root.handlers:
        handler.addFilter(_SecretRedactFilter())

    commands = {
        "new": cmd_new,
        "load": cmd_load,
        "cast": cmd_cast,
        "cast-suggest": cmd_cast_suggest,
        "cast-apply": cmd_cast_apply,
        "cast-export": cmd_cast_export,
        "cast-import": cmd_cast_import,
        "cast-preset": cmd_cast_preset,
        "cast-fill": cmd_cast_fill,
        "compile": cmd_compile,
        "render": cmd_render,
        "info": cmd_info,
        "voices": cmd_voices,
        "chapters": cmd_chapters,
        "speakers": cmd_speakers,
        "emotions": cmd_emotions,
        "pronunciation": cmd_pronunciation,
        "from-stdin": cmd_from_stdin,
        "review-export": cmd_review_export,
        "review-import": cmd_review_import,
        "status": cmd_status,
        "cache": cmd_cache,
        "report": cmd_report,
        "diagnose": cmd_diagnose,
        "batch": cmd_batch,
        "preview": cmd_preview,
        "sample": cmd_sample,
        "master-check": cmd_master_check,
        "export-chapters": cmd_export_chapters,
        "make": cmd_make,
        "audition": cmd_audition,
        "cast-interactive": cmd_cast_interactive,
        "completion": cmd_completion,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            return handler(args)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            return 1
        except Exception as e:
            # Unexpected runtime error — exit code 2
            _report_error(e, args)
            return 2
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
