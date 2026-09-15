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
    audiobooker compile --json             # Attribution rate as JSON
    audiobooker cast-apply --auto --dry-run  # Preview the auto-cast
    audiobooker make book.epub --review    # Stop after compile+cast for review
    audiobooker render                     # Render audiobook
    audiobooker render --engine my-tts     # Render with a pluggable TTS engine
    audiobooker render --dry-run           # Preview render without executing
    audiobooker podcast --base-url https://cdn/  # Per-chapter render + RSS feed
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
    audiobooker voices --engine my-tts     # List a specific engine's voices
"""

from __future__ import annotations

import argparse
import logging as _logging_mod
import re
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audiobooker.renderer.engine import RenderError, RenderSummary
from pathlib import Path
from typing import Optional

from audiobooker import formats as audio_formats
from audiobooker.shell_quote import quote_arg
from audiobooker.errors import CompilationFailedError


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
# CompilationFailedError is listed explicitly (CH-B-002 handoff). It
# subclasses RuntimeError so every existing `except Exception` site keeps
# working — but that also meant main()'s catch-all owned it and exited 2,
# "audiobooker hit an unexpected error". A book that did not compile is the
# user's book not compiling. The message block was already correct; only the
# exit code was lying about whose fault it was.
USER_ERROR_TYPES = (
    FileNotFoundError, ValueError, IndexError, KeyError,
    CompilationFailedError,
)


def _configure_output_encoding() -> None:
    """Let stdout/stderr DEGRADE, never die, on characters they cannot encode.

    FEAT-IN-001. ``new`` on a book titled in Japanese, Cyrillic or anything
    accented saved a perfectly valid ``.audiobooker`` file and then died
    printing its own success message::

        Error: 'charmap' codec can't encode characters in position 9-13

    — exit 1, traceback on ``_out(f"  Title: {project.title}")``. cp1252 is
    the default Windows console codepage (the same one this suite models in
    ``_encodable_spinner``'s tests), and ``print`` raises rather than
    substituting.

    This is the THIRD instance of this bug here. ``_encodable_spinner()``
    fixed it for rich's braille spinner frames; ``renderer/ffmpeg_runner.py``
    and ``renderer/output.py`` fixed it for decoding ffmpeg's UTF-8 stderr.
    Both fixes were local to their call sites, so neither protected
    ``_out``/``_err`` — the most-used output path in this module, with 60+
    sites echoing a title, a path or a speaker name. Hence one fix at the
    primitive rather than a fourth bespoke guard: reconfiguring the streams
    once at startup covers every current and future call site.

    ``errors="replace"`` and nothing else. Forcing UTF-8 onto a cp1252
    console would trade a crash for mojibake; a run of ``?`` is the honest
    degrade, and it is what ``renderer/*`` already chose for the same reason.

    Best effort by design: ``sys.stdout`` may be a pytest capture object, a
    ``StringIO``, or None under pythonw — none of which need (or support)
    reconfiguring. A cosmetic encoding tweak must never be the thing that
    kills the command.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except Exception:  # pragma: no cover - defensive; see docstring
            continue


def _out(*args, **kwargs) -> None:
    """Print normal (non-error) output unless --silent suppressed it.

    Errors and warnings always go through _err() so --silent never hides a
    problem the user needs to see.
    """
    if not _QUIET:
        print(*args, **kwargs)


# The quoting rule moved to audiobooker/shell_quote.py. `review` prints the
# same next-step command in the header of the file it writes, and `cli`
# imports `review`, so the rule could not stay here without review either
# importing cli back or keeping a second copy that drifts. Re-exported
# under the old private name because the call sites and tests use it.
_quote_arg = quote_arg


def _emit_json(payload: dict) -> None:
    """Write one ``--json`` payload to **stdout**, never suppressed by --silent.

    FEAT-UX-004. stdout is the payload stream — a ``--json`` run's whole
    product — so it bypasses ``_out``'s ``--silent`` gate for the same reason
    ``_err`` does: ``--silent`` is about chatter, not about the thing the user
    asked for. Errors go the other way, as JSON on stderr; see
    ``_report_error``.
    """
    import json as json_mod

    print(json_mod.dumps(payload, indent=2, ensure_ascii=False))


def _err(*parts, args: "argparse.Namespace | None" = None, **kwargs) -> None:
    """Print an error or warning line to **stderr**. Never suppressed by --silent.

    Unconditional, on every command and every output mode. stdout is the
    command's product — a payload, a table, a path — and stderr is where
    anything that went wrong belongs, so that:

    * ``audiobooker status --json -p missing.audiobooker > status.json`` writes
      a parseable payload instead of an "Error: ..." line INTO status.json;
    * ``audiobooker render ... | tee log`` still shows failures on the terminal;
    * ``--silent`` hides the chatter without ever hiding a problem.

    CLI-CROSS (wave 2) made this JSON-only because eight assertions in other
    domains' test files read error text off ``capsys.readouterr().out``. Wave-3
    residual 4 flipped it and amended those assertions, which encoded the old,
    wrong behavior — ``file=sys.stderr`` appeared nowhere in this module before
    wave 2, and this helper is the single chokepoint for it.

    Args:
        args: Accepted (and ignored) so the ~60 existing ``_err(..., args=args)``
            call sites keep their shape. Routing no longer depends on it.
    """
    print(*parts, file=sys.stderr, **kwargs)


def _resolve_engine(args, project=None):
    """FT-ENGINE-001: resolve the TTS engine for a render-shaped command.

    Resolution order (matching engine.get_default_engine):
        explicit --engine NAME > project.config.tts_engine > the env/default
        the renderer applies (AUDIOBOOKER_ENGINE / 'voice-soundboard').

    When neither --engine nor a non-default project tts_engine is set, returns
    None so the renderer keeps its current behavior byte-for-byte (the default
    voice-soundboard engine resolves through the same path). Returns an engine
    INSTANCE otherwise. Never raises here — an unresolved name surfaces as a
    RenderError when the renderer actually tries to synthesize.
    """
    from audiobooker.renderer import engine as engine_mod

    name = getattr(args, "engine", None)
    if not name and project is not None:
        cfg_name = getattr(getattr(project, "config", None), "tts_engine", None)
        # A non-default config engine is an explicit choice worth resolving;
        # the bare default keeps the None fast-path (current behavior).
        if cfg_name and cfg_name != "voice-soundboard":
            name = cfg_name

    if not name:
        return None
    # Per contract get_default_engine accepts name=; call defensively so a
    # concurrently-evolving renderer with the older no-arg signature still
    # works (it only resolves the built-in engine, which is correct for the
    # 'voice-soundboard' default).
    try:
        return engine_mod.get_default_engine(name)
    except TypeError:
        return engine_mod.get_default_engine()


# Stable machine-readable codes for the plain Python exceptions listed in
# USER_ERROR_TYPES. Anything carrying its own ``structured()`` (every class in
# audiobooker/errors.py, plus RenderError/PresetError/VoiceNotFoundError) wins
# over this table — it is only the fallback for exceptions raised by the
# standard library, which have no code of their own. Ordered: the first
# isinstance() match is used, so subclasses must come before their bases.
_FALLBACK_ERROR_CODES: tuple[tuple[type, str], ...] = (
    (FileNotFoundError, "FILE_NOT_FOUND"),
    (IsADirectoryError, "NOT_A_FILE"),
    (PermissionError, "PERMISSION_DENIED"),
    (IndexError, "INDEX_OUT_OF_RANGE"),
    (KeyError, "MISSING_KEY"),
    (ValueError, "INVALID_VALUE"),
    (OSError, "IO_ERROR"),
)


def _error_payload(e: BaseException) -> dict:
    """The canonical machine-readable shape for any exception the CLI reports.

    Always ``{code, message, hint, retryable}`` — a caller can rely on all
    four keys existing whatever went wrong, which is the whole point of a
    machine-readable error. ``cause`` rides along when the exception carries
    one.
    """
    structured = getattr(e, "structured", None)
    if callable(structured):
        try:
            payload = structured()
        except Exception:  # pragma: no cover - never fail reporting an error
            payload = None
        if isinstance(payload, dict) and payload.get("code"):
            payload.setdefault("hint", "")
            payload.setdefault("retryable", False)
            return payload

    code = "UNEXPECTED_ERROR"
    for exc_type, fallback in _FALLBACK_ERROR_CODES:
        if isinstance(e, exc_type):
            code = fallback
            break

    return {
        "code": code,
        "message": str(e),
        "hint": str(getattr(e, "hint", "") or ""),
        "retryable": bool(getattr(e, "retryable", False)),
    }


def _report_error(e: BaseException, args: "argparse.Namespace | None" = None) -> None:
    """Print a structured, user-facing error message.

    Prints "Error: {e}", then the structured ``code``/``retryable`` and
    ``hint`` the exception carries (see audiobooker/errors.py), and the full
    traceback when --debug is set. Errors always print (never suppressed by
    --silent) and always go to stderr (see _err).

    CLI-CROSS: ``code`` and ``retryable`` used to be discarded here, so the
    shipcheck-mandated error shape never reached the user — a retryable
    backend blip looked identical to a permanent misconfiguration.

    FEAT-UX-004: under ``--json`` the SAME information is emitted as one JSON
    object instead of three English lines. errors.py has carried the
    code/message/hint/retryable shape since it was written and this function
    never emitted it, so every ``--json`` caller had a machine-readable
    success path and a prose failure path — "scriptable except when it
    matters".

    The JSON goes to **stderr**, like the prose it replaces. stdout is the
    payload stream: an error object printed there would land inside a
    redirected ``audiobooker status --json > status.json`` and corrupt the
    file the caller is about to parse. Read errors from stderr (or merge the
    streams) and the exit code tells you which to parse.
    """
    if getattr(args, "json_output", False):
        import json as json_mod

        _err(json_mod.dumps(_error_payload(e), indent=2, ensure_ascii=False))
        if getattr(args, "debug", False):
            import traceback
            traceback.print_exc()
        return

    _err(f"Error: {e}", args=args)

    code = getattr(e, "code", None)
    if isinstance(code, str) and code:
        retryable = bool(getattr(e, "retryable", False))
        _err(
            f"Code: {code}" + (" (retryable)" if retryable else ""),
            args=args,
        )

    hint = getattr(e, "hint", None)
    if hint:
        _err(f"Hint: {hint}", args=args)
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
    # CLI-6: default is None, NOT "auto". An argparse default is indistinguishable
    # from a value the user typed, and _build_config_from only drops None — so a
    # literal "auto" default silently beat a config file's booknlp_mode, inverting
    # the documented precedence (CLI flag > config file > built-in default). The
    # built-in default now comes from ProjectConfig, after the merge.
    new_parser.add_argument(
        "--booknlp",
        default=None,
        choices=["on", "off", "auto"],
        help="BookNLP speaker resolution (default: auto, or the config file)",
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
    # CLI-7: escape hatch for voice ids a pluggable engine exposes but the
    # built-in catalog does not know about.
    cast_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the voice-id check (for engines outside the built-in catalog)",
    )

    # --- cast-suggest ---
    suggest_parser = subparsers.add_parser(
        "cast-suggest", help="Suggest voices for uncast speakers"
    )
    suggest_parser.add_argument("-p", "--project", help="Project file")
    suggest_parser.add_argument(
        "-n", "--top", type=int, default=3, help="Show top N suggestions per speaker"
    )
    suggest_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
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
    apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what --auto would cast, and change nothing",
    )
    apply_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
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
    # FEAT-UX-004: `report --json` existed and `compile --json` did not, so the
    # unattributed rate that decides whether to proceed was unreachable from
    # the command that computes it.
    compile_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
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
        choices=list(audio_formats.BOOK_FORMATS),
        default=None,
        dest="output_format",
        help="Output format (default: from project config, usually m4b)",
    )
    # FT-RENDER-011: Force past casting validation
    # PH-B-002: also bypasses the dialogue-attribution quality gate.
    # FEAT-UX-002: and the uncast-speaker gate, which is the one this help
    # text used to promise and no CLI-side check delivered.
    render_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Render anyway when a speaker with dialogue is uncast, when "
            "casting is incomplete, or when attribution quality has failed"
        ),
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
    # FT-CLI-008: watch mode. NOTE the asymmetry with `make --watch`, which
    # genuinely watches the SOURCE file: this one polls the .audiobooker
    # PROJECT file, because a render has no source to re-read. The help string
    # said "source file" for both, so a user editing their .txt in another
    # terminal watched `render --watch` sit there forever with nothing to
    # diagnose — it was working exactly as built and not as documented.
    render_parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the project file and re-render (resume) whenever it changes",
    )
    # FT-ENGINE-001: pluggable TTS engine selection.
    render_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render with (default: voice-soundboard; "
             "overrides AUDIOBOOKER_ENGINE and the project's tts_engine)",
    )
    # FEAT-UX-004: a render is the expensive step — the one a script most
    # needs to inspect before and after.
    render_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
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
    # FT-ENGINE-001: list voices from a specific engine's list_voices().
    voices_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="List voices from this TTS engine (default: voice-soundboard)",
    )
    voices_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

    # --- chapters ---
    chapters_parser = subparsers.add_parser("chapters", help="List chapters")
    chapters_parser.add_argument("-p", "--project", help="Project file")
    chapters_parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Output as JSON"
    )

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
    # CLIUX-H-010: an unconfirmed rmtree of every rendered chapter.
    cache_clean_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm the deletion (required when stdin is not a terminal)",
    )
    cache_clean_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report what would be deleted and delete nothing",
    )

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
        choices=list(audio_formats.BOOK_FORMATS),
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
    # CLIUX-C-001: `batch *.epub` replaced the project file beside every
    # single source in the directory.
    batch_parser.add_argument(
        "--overwrite-project",
        action="store_true",
        dest="overwrite_project",
        help=(
            "Replace existing .audiobooker projects (default: refuse per "
            "book). Each replacement is staged and only takes effect once "
            "that book's render succeeds."
        ),
    )
    batch_parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit the per-book results array as JSON",
    )
    # FT-ENGINE-001: pluggable TTS engine for every book in the batch.
    batch_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render with (default: voice-soundboard)",
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
    # FT-ENGINE-001: render the preview through a specific TTS engine.
    preview_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render with (default: voice-soundboard)",
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
    # FT-ENGINE-001: render the sample through a specific TTS engine.
    sample_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render with (default: voice-soundboard)",
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

    # --- FT-RENDER-M-008: podcast (iTunes RSS feed for a per-chapter render) ---
    podcast_parser = subparsers.add_parser(
        "podcast",
        help="Render one file per chapter and write an iTunes podcast RSS feed",
    )
    podcast_parser.add_argument("-p", "--project", help="Project file")
    podcast_parser.add_argument(
        "--base-url",
        metavar="URL",
        dest="base_url",
        default="",
        help="Base URL prepended to each episode's audio filename in the feed",
    )
    podcast_parser.add_argument(
        "-o", "--output",
        help="Output RSS file path (default: podcast.xml)",
    )
    podcast_parser.add_argument(
        "--format",
        choices=list(audio_formats.PODCAST_FORMATS),
        default=None,
        dest="output_format",
        help="Per-chapter audio format (default: from config, usually m4b)",
    )
    podcast_parser.add_argument(
        "-j", "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel render workers (default: 1)",
    )
    podcast_parser.add_argument(
        "--no-render",
        action="store_true",
        dest="no_render",
        help="Skip rendering; build the feed from already-rendered chapter audio",
    )
    podcast_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render with (default: voice-soundboard)",
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
        choices=list(audio_formats.BOOK_FORMATS),
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
    # CLIUX-C-001: `make` silently replaced an existing project file — and
    # because save is step 4 and render is step 5, a run that then failed at
    # ffmpeg left no audiobook AND no project.
    make_parser.add_argument(
        "--overwrite-project",
        action="store_true",
        dest="overwrite_project",
        help=(
            "Replace an existing .audiobooker project (default: refuse). The "
            "replacement is staged and only takes effect once the render "
            "succeeds."
        ),
    )
    make_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Show the resolved project path, whether it already exists, the "
            "cast that would be applied and the output path - then stop"
        ),
    )
    # FEAT-UX-003: `make` is the headline command and the one path that could
    # not review. The choice used to be one command with no review, or nine
    # commands with it.
    make_parser.add_argument(
        "--review",
        action="store_true",
        help=(
            "Stop after compile + auto-cast, write the review file and print "
            "the import command (renders nothing)"
        ),
    )
    # FT-CLI-008: watch mode also available on make.
    make_parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the source file and re-render (resume) whenever it changes",
    )
    # FT-ENGINE-001: pluggable TTS engine for the make render step.
    make_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render with (default: voice-soundboard)",
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
    # FT-ENGINE-001: render audition samples through a specific TTS engine.
    audition_parser.add_argument(
        "--engine",
        metavar="NAME",
        help="TTS engine to render audition samples with (with --render)",
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

    # Look for .audiobooker files in current directory.
    #
    # CLIUX-H-002: filter to regular FILES. The renderer's cache root is a
    # DIRECTORY named `.audiobooker` written beside the project, and
    # Path.glob() matches dotted names, so the very first render broke
    # auto-detection PERMANENTLY: every later `-p`-less command raised
    # "Multiple project files found" and listed the cache directory as one of
    # the candidates. Reproducible in this repo's own root.
    project_files = sorted(p for p in Path(".").glob("*.audiobooker") if p.is_file())
    if len(project_files) == 1:
        return project_files[0]
    elif len(project_files) > 1:
        raise ValueError(
            "Multiple project files found. Specify one with -p:\n"
            + "\n".join(f"  {_project_choice_line(p)}" for p in project_files)
        )
    else:
        raise FileNotFoundError(
            "No project file found in current directory. "
            "Create one with: audiobooker new <source_file>"
        )


def _project_choice_line(path: Path) -> str:
    """Describe one candidate project file for the "which one?" error.

    CLIUX-H-002: two bare filenames are not enough to pick from — the user has
    to open both to find out which book is which. Title and mtime make `-p` an
    informed choice. Deliberately best-effort: a project that will not parse
    still has to be listed.
    """
    parts = [str(path)]
    try:
        import json as _json

        data = _json.loads(path.read_text(encoding="utf-8"))
        title = data.get("title")
        if title:
            parts.append(f'"{title}"')
    except Exception:
        parts.append("(unreadable)")
    try:
        from datetime import datetime as _dt

        when = _dt.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        parts.append(f"modified {when}")
    except OSError:
        pass
    return "  -  ".join(parts)


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
        _err(f"WARNING: ignoring config file ({e})")
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
                _err(f"WARNING: ignoring non-integer series_index: {book['series_index']!r}")
        if book.get("year") is not None:
            try:
                meta.year = int(book["year"])
            except (TypeError, ValueError):
                _err(f"WARNING: ignoring non-integer year: {book['year']!r}")
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
            _err(f"WARNING: could not import casting from config ({e})")

    lexicon_ref = file_config.get("lexicon")
    if isinstance(lexicon_ref, str) and lexicon_ref:
        lexicon_path = _resolve(lexicon_ref)
        try:
            project.import_lexicon(lexicon_path)
        except (FileNotFoundError, ValueError) as e:
            _err(f"WARNING: could not import lexicon from config ({e})")


def cmd_new(args) -> int:
    """Create new project from source file."""
    from audiobooker import AudiobookProject

    source = Path(args.source)
    if not source.exists():
        _err(f"Error: Source file not found: {source}")
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
            _err(f"Error: Unsupported language: {lang!r}")
            print(f"Available: {', '.join(available_profiles())}")
            return 1

        # FT-CLI-002: seed config from the on-disk config file, then let
        # explicit CLI flags win (CLI flag > config-file value > default).
        # CLI-6: --booknlp now defaults to None, so getattr() below is either
        # what the user typed or None (dropped by _build_config_from). The old
        # post-merge `if booknlp_mode != "auto"` fixup is gone with it: it could
        # not tell "the user typed --booknlp auto" from "nobody passed it", and
        # the literal default reached _build_config_from either way.
        file_config = _load_config_file(str(source))
        config = _build_config_from(
            file_config,
            cli_overrides={"booknlp_mode": getattr(args, "booknlp", None)},
            base_kwargs={"language_code": lang},
        )

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
            _err(f"Error: Unsupported file format: {suffix}")
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


def _warn_unknown_voice(voice: str, args) -> None:
    """CLI-7: warn (with a close-match suggestion) on an unknown voice id.

    ``get_available_voices()`` is already how `voices` builds its catalog, so
    the lookup costs nothing new. Deliberately non-fatal:

    * a pluggable TTS engine can expose ids the built-in catalog never lists;
    * voice-soundboard is an OPTIONAL dependency, so the registry may raise
      ImportError — that must not block casting.

    ``--force`` skips the check entirely.
    """
    if not voice or getattr(args, "force", False):
        return

    try:
        from audiobooker.casting import voice_registry

        available = voice_registry.get_available_voices()
    except Exception:
        # No catalog available (voice-soundboard not installed, engine error).
        # Casting is still a pure metadata write; never fail on this.
        return

    known = {vid for vid in (_voice_display(v)[0] for v in available or ()) if vid}
    if not known or voice in known:
        return

    import difflib

    suggestions = difflib.get_close_matches(voice, sorted(known), n=3)
    _err(f"WARNING: unknown voice id {voice!r}.", args=args)
    if suggestions:
        _err(f"  Did you mean: {', '.join(suggestions)}?", args=args)
    _err(
        "  Run 'audiobooker voices' to list them, or pass --force if your "
        "engine provides this id.",
        args=args,
    )


def _warn_unknown_character(project, character: str, args) -> None:
    """CLIUX-H-005: warn when the cast target appears nowhere in the book.

    `cast` validated the VOICE id (CLI-7) but never the CHARACTER, so
    ``cast Alicia af_bella`` in a project whose speakers are Alice and Bob
    printed "Cast Alicia as af_bella", exited 0, and left BOTH real speakers
    uncast — ``info`` went on reporting two uncast speakers while the user
    believed they had just cast one of them. The mistake surfaced hours later
    when ``render`` refused, naming a speaker they had been told twice they
    had already cast.

    Same shape as ``_warn_unknown_voice``: non-fatal (an alias or a speaker
    that only appears after a re-compile is legitimate), close matches when we
    have them, and ``--force`` skips it. Skipped entirely when the project is
    not compiled — there are no detected speakers to check against yet, and
    casting ahead of a compile is a normal workflow.
    """
    if not character or getattr(args, "force", False):
        return

    try:
        detected = project.get_detected_speakers()
    except Exception:  # pragma: no cover - defensive; casting must not fail here
        return
    if not detected:
        return

    casting = getattr(project, "casting", None)
    normalize = getattr(casting, "normalize_key", None) or (lambda n: n.casefold().strip())

    known = {normalize(s) for s in detected}
    # A character already in the casting table is always a legitimate re-cast
    # target, even if the current compile no longer produces that speaker.
    known |= set(getattr(casting, "characters", {}) or {})
    if normalize(character) in known:
        return

    import difflib

    suggestions = difflib.get_close_matches(character, sorted(detected), n=3)
    _err(
        f"WARNING: unknown character {character!r} - no speaker by that name "
        "appears in this book.",
        args=args,
    )
    if suggestions:
        _err(f"  Did you mean: {', '.join(suggestions)}?", args=args)
    _err(
        "  Run 'audiobooker speakers' to list the detected speakers, or pass "
        "--force to cast a name the compile has not produced yet.",
        args=args,
    )


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

        # CLI-7: `cast` used to store ANY string as a voice id and report
        # success; a typo like af_bela for af_bella surfaced hours later, mid
        # render. Look it up now. Warn rather than hard-fail: a pluggable
        # engine may legitimately expose ids outside the built-in catalog.
        _warn_unknown_voice(args.voice, args)

        # CLIUX-H-005: the other half of the same mistake — a typo'd CHARACTER
        # was accepted silently and left the real speaker uncast.
        _warn_unknown_character(project, args.character, args)

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
                "Non-interactive stdin - printing suggestions only "
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

        # CLI-8: resolved first — in --json mode stdout carries the payload and
        # nothing else, so every human progress line below is suppressed.
        json_output = getattr(args, "json_output", False)

        # Compile if needed so the speaker's lines exist.
        if not any(c.is_compiled for c in project.chapters):
            if not json_output:
                _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        speaker = args.character
        top_n = getattr(args, "top", 5) or 5

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

        # CLI-8: with --json AND --render the human table used to print to
        # stdout ahead of the payload, so `audition ... --render --json > x.json`
        # produced a file that no JSON parser could read.
        if not json_output:
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

        # FT-ENGINE-001: render audition samples through the resolved engine
        # when one is selected; None keeps the default voice-soundboard path.
        tts_engine = _resolve_engine(args, project)
        engine_kwargs = {"engine": tts_engine} if tts_engine is not None else {}

        rendered: list[dict] = []
        # CLI-8: failures used to go to _out() (suppressed by --silent), were
        # omitted from the --json payload entirely, and never affected the exit
        # code — `audition --render` reported success with zero WAVs on disk.
        failed: list[dict] = []
        if not json_output:
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
                path = render_chapter(chapter, casting, out_path, **engine_kwargs)
                rendered.append({"voice_id": voice_id, "path": str(path)})
                if not json_output:
                    _out(f"  {voice_id} -> {path}")
            except Exception as e:
                failed.append({"voice_id": voice_id, "error": str(e)})
                _err(f"  {voice_id}: render failed ({e})", args=args)

        if json_output:
            import json as json_mod
            print(json_mod.dumps(
                {"speaker": speaker, "rendered": rendered, "failed": failed},
                indent=2,
                ensure_ascii=False,
            ))

        if failed and not rendered:
            _err(
                f"Error: all {len(failed)} sample render(s) failed - no audition "
                f"audio was written to {out_dir}/.",
                args=args,
            )
            return 1
        if failed:
            _err(
                f"WARNING: {len(failed)} of {len(candidates)} sample render(s) "
                "failed; the rest were written.",
                args=args,
            )
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
        _err(f"Error: unsupported shell: {shell}")
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

    json_output = getattr(args, "json_output", False)

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # CASTING-DEPTH v2.1: --emotion-preset sets the project's emotion_preset
        # before compile so the inferencer uses the chosen preset pack. Validated
        # by ProjectConfig (structured ValueError on a bad value).
        emotion_preset = getattr(args, "emotion_preset", None)
        if emotion_preset:
            project.config.emotion_preset = emotion_preset
            if not json_output:
                _out(f"Emotion preset: {emotion_preset}")

        # --dry-run: compile in dry-run mode, print speaker summary table
        if getattr(args, "dry_run", False):
            dry_result = project.compile(dry_run=True)
            if dry_result is None:
                if json_output:
                    _emit_json({
                        "dry_run": True,
                        "title": project.title,
                        "speakers": [],
                        "utterances": 0,
                    })
                else:
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

            if json_output:
                _emit_json({
                    "dry_run": True,
                    "title": project.title,
                    "utterances": sum(s["lines"] for s in speaker_stats.values()),
                    "speakers": [
                        {
                            "speaker": speaker,
                            "lines": speaker_stats[speaker]["lines"],
                            "sample": speaker_stats[speaker]["sample"],
                        }
                        for speaker in sorted(speaker_stats)
                    ],
                })
                return 0

            _out(f"\nDRY RUN - Compile preview for {project.title}")
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

        if not json_output:
            _out(f"Compiling {len(project.chapters)} chapters...")

        def progress(current, total, title):
            if not json_output:
                _out(f"  [{current}/{total}] {title}")

        project.compile(progress_callback=progress)
        project.save()

        # FT-CORE-022: Surface compile observability summary.
        summary = getattr(project, "compile_summary", {}) or {}
        total_utterances = sum(len(c.utterances) for c in project.chapters)
        if not json_output:
            _out(
                f"\nCompiled {total_utterances} utterances: "
                f"{summary.get('speakers_resolved', 0)} speakers resolved, "
                f"{summary.get('low_confidence', 0)} low-confidence, "
                f"{summary.get('emotions_inferred', 0)} emotions inferred"
            )

        near_miss = summary.get("emotions_near_miss", 0)
        if near_miss and not json_output:
            _out(
                f"  ({near_miss} more utterance(s) were just below the emotion "
                "confidence threshold - run 'audiobooker report' to review them.)"
            )

        # NLP errors are warnings, not failures — but the user should know
        # which chapters fell back to heuristic attribution.
        nlp_errors = summary.get("nlp_errors") or []
        if nlp_errors and not json_output:
            print(
                f"WARNING: speaker resolution had problems on "
                f"{len(nlp_errors)} chapter(s); kept heuristic attribution. "
                "Run 'audiobooker report' for details."
            )

        # PH-B-002: surface the dialogue attribution rate. compile_chapter()
        # already computes this per chapter and logs it (PH-B-001/PH-B-002),
        # but a log line is not the same as telling the user: --silent turns
        # logging down to CRITICAL, and a WARNING-level log line is easy to
        # miss among build output either way. This was the actual gap named
        # by PH-B-002 — the number never reached the user until they listened
        # to the finished, mis-cast book.
        from audiobooker.casting import compile_report
        quality_report = compile_report(project.chapters, project.casting)
        quality = quality_report["quality"]
        # FEAT-CAST-001: `quality` counts only lines the tool ADMITS it could
        # not attribute. A turn-tracking guess is recorded as a success, so it
        # LOWERS that number — a chapter whose every speaker was invented
        # reports 0% unattributed. attribution_quality counts the guesses.
        attribution_quality = quality_report["attribution_quality"]
        uncast = project.get_uncast_speakers()

        # FEAT-UX-004: `report --json` existed; `compile --json` did not, so
        # the numbers that decide "proceed or go back and fix attribution"
        # were only ever printed as prose by the command that computes them.
        if json_output:
            _emit_json({
                "title": project.title,
                "chapters": len(project.chapters),
                "utterances": total_utterances,
                "speakers_resolved": summary.get("speakers_resolved", 0),
                "low_confidence": summary.get("low_confidence", 0),
                "emotions_inferred": summary.get("emotions_inferred", 0),
                "emotions_near_miss": near_miss,
                "nlp_errors": list(nlp_errors),
                "total_dialogue": quality_report["total_dialogue"],
                "dialogue_unattributed": quality_report["total_dialogue_unknown"],
                "dialogue_unattributed_rate": quality_report["dialogue_unknown_rate"],
                "quality": quality,
                "dialogue_guessed": quality_report["total_low_confidence"],
                "dialogue_unverified_rate":
                    quality_report["dialogue_unverified_rate"],
                "attribution_quality": attribution_quality,
                "attribution_sources":
                    quality_report["attribution_source_distribution"],
                "uncast_speakers": sorted(uncast),
            })
            return 0

        # A book with no dialogue at all (pure narration) has nothing to
        # attribute — printing "0% unattributed" would just be noise.
        if quality_report["total_dialogue"] > 0:
            _out(
                f"Dialogue attribution: "
                f"{quality_report['total_dialogue_unknown']}/"
                f"{quality_report['total_dialogue']} dialogue lines "
                f"unattributed ({quality_report['dialogue_unknown_rate']:.0%})"
            )
            guessed = quality_report["total_low_confidence"]
            if guessed:
                _out(
                    f"  ...and {guessed} more guessed by alternating turns "
                    f"({quality_report['dialogue_unverified_rate']:.0%} of "
                    "dialogue has no attribution in the text)"
                )
        # Warn on the STRICTER of the two. attribution_quality is the one
        # that can see a guess; quality is the one users already know.
        verdict = (
            "failed"
            if "failed" in (quality, attribution_quality)
            else "degraded"
            if "degraded" in (quality, attribution_quality)
            else "ok"
        )
        if verdict != "ok":
            behavior = project.casting.unknown_character_behavior
            if verdict == "failed":
                urgency = "the book will render as a near-single-voice reading"
            else:
                urgency = "consider reviewing attribution before rendering"
            _err(
                f"WARNING: dialogue attribution is {verdict.upper()} - "
                f"{urgency} (unknown speakers fall back to {behavior!r}).",
                args=args,
            )
            _err(
                "Hint: check --lang, add inline [character] overrides, or "
                "cast the missing speakers. Run 'audiobooker report' for the "
                "worst offending lines - including the ones that were "
                "guessed rather than left unattributed, which the "
                "unattributed count does not show.",
                args=args,
            )
            if verdict == "failed":
                _err(
                    "Hint: 'audiobooker render' will refuse to proceed at "
                    "this quality level unless you pass --force.",
                    args=args,
                )

        # Show uncast speakers
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


# CLI-5: flags `render` advertises that only the FULL-book branch ever read.
# Passing any of them with -c produced a plain, unmastered chapter WAV in the
# wrong container and exit 0 — e.g. `render -c 3 --acx --cover art.jpg
# --format mp3` wrote an unmastered, coverless chapter_003.wav.
_SINGLE_CHAPTER_INCOMPATIBLE = (
    ("acx", "--acx"),
    ("cover", "--cover"),
    ("normalize", "--normalize"),
    ("bitrate", "--bitrate"),
    ("split", "--split"),
    ("output_format", "--format"),
    ("from_chapter", "--from-chapter"),
    ("chapters", "--chapters"),
    ("exclude_chapters", "--exclude-chapters"),
)

# Flags that are simply inert for a one-chapter render (no cache assembly, no
# parallel fan-out). A warning is honest without blocking a harmless command.
_SINGLE_CHAPTER_NO_OP = (
    ("no_resume", "--no-resume"),
    ("allow_partial", "--allow-partial"),
)


def _format_bytes(total: int) -> str:
    """Human-readable byte size, matching `cache info`'s two-tier format."""
    if total >= 1024 * 1024:
        return f"{total / (1024 * 1024):.1f} MB"
    return f"{total / 1024:.1f} KB"


def _cache_stats(cache_root: Path) -> tuple[int, int, int]:
    """(cached chapters, files, total bytes) for a render cache directory.

    CLIUX-H-003 / CLIUX-H-010: both `render --clean-cache` and `cache clean`
    used to delete hours of synthesized audio and report only a path. The
    numbers were never hard to get — `cache info` already computed them — so
    this is the one place that does, and every deletion path quotes it.
    """
    from audiobooker.renderer.cache_manifest import get_chapters_dir

    file_count = 0
    total_size = 0
    for entry in cache_root.rglob("*"):
        if entry.is_file():
            file_count += 1
            try:
                total_size += entry.stat().st_size
            except OSError:  # pragma: no cover - racing deletion
                pass

    chapters_dir = get_chapters_dir(cache_root)
    chapter_count = (
        len([p for p in chapters_dir.glob("*.wav") if p.is_file()])
        if chapters_dir.is_dir()
        else 0
    )
    return chapter_count, file_count, total_size


def _single_chapter_output(args) -> str:
    """Resolve the output path for `render -c N` (one place, both sub-paths)."""
    return args.output or f"chapter_{args.chapter:03d}.wav"


def _check_single_chapter_flags(args, project) -> Optional[int]:
    """Bounds + flag-compatibility guard for `render -c N`.

    Split out of ``_validate_single_chapter_render`` for CLIUX-H-003: the
    validation has to run BEFORE the --clean-cache rmtree, while the --dry-run
    report has to run AFTER it (so the dry run can say what the deletion would
    cost). One function could not sit on both sides of the same statement.

    CLI-5: bounds-checks the index (a negative index used to render the last
    chapter into "chapter_-01.wav") and rejects the advertised flags this path
    cannot honor rather than silently dropping them.
    """
    chapter_index = args.chapter

    # Bounds check covers BOTH sub-paths (the engine path had one, the default
    # project.render_chapter path had none, and neither rejected negatives).
    total = len(project.chapters)
    if chapter_index < 0 or chapter_index >= total:
        where = f"0-{total - 1}" if total else "the project has no chapters"
        _err(
            f"Error: Chapter index {chapter_index} out of range ({where}).",
            args=args,
        )
        return 1

    # Incompatible flags — fail fast and name them all at once.
    conflicts = [
        flag for attr, flag in _SINGLE_CHAPTER_INCOMPATIBLE
        if getattr(args, attr, None)
    ]
    if getattr(args, "jobs", 1) and getattr(args, "jobs", 1) > 1:
        conflicts.append("-j/--jobs")
    if conflicts:
        _err(
            "Error: these flags apply to a full-book render and cannot be "
            f"honored with -c/--chapter: {', '.join(conflicts)}",
            args=args,
        )
        _err(
            "Hint: drop -c to render the whole book with those options, or "
            "drop the options to render one chapter to a plain WAV.",
            args=args,
        )
        return 1

    for attr, flag in _SINGLE_CHAPTER_NO_OP:
        if getattr(args, attr, False):
            _err(
                f"WARNING: {flag} has no effect on a single-chapter render "
                "(it is always rendered fresh); ignoring it.",
                args=args,
            )

    return None


def _dry_run_single_chapter(args, project) -> int:
    """CLI-3: describe exactly what `render -c N` WOULD do, synthesize nothing.

    The old check sat inside the full-book `else:` branch, so `render -c N
    --dry-run` performed a real synthesis — burning a paid/GPU TTS backend and
    overwriting chapter_NNN.wav while claiming to be a preview.
    """
    chapter_index = args.chapter

    # --dry-run: describe exactly what WOULD happen, synthesize nothing.
    chapter = project.chapters[chapter_index]
    output = _single_chapter_output(args)
    engine_name = (
        getattr(args, "engine", None)
        or getattr(getattr(project, "config", None), "tts_engine", None)
        or "voice-soundboard"
    )
    utterances = len(getattr(chapter, "utterances", []) or [])
    utterance_note = (
        f"{utterances} utterance(s)" if utterances
        else "not compiled yet (would compile first)"
    )

    if getattr(args, "json_output", False):
        _emit_json({
            "dry_run": True,
            "title": project.title,
            "chapters": [{
                "index": chapter.index,
                "number": chapter.index + 1,
                "title": chapter.title,
                "words": chapter.word_count,
                "utterances": utterances,
            }],
            "output": str(Path(output)),
            "engine": engine_name,
            "cast": dict(sorted(project.casting.get_voice_mapping().items())),
        })
        return 0

    _out("DRY RUN - nothing was rendered.")
    _out(f"  Chapter:    {_chapter_label(chapter.index)} {chapter.title}")
    _out(f"  Output:     {Path(output)}")
    _out(f"  Utterances: {utterance_note}")
    _out(f"  Engine:     {engine_name}")
    _out("\nRe-run without --dry-run to render this chapter.")
    return 0


def _dry_run_full_book(
    args, project, *, output, fmt, resume, from_chapter, engine_name
) -> int:
    """`render --dry-run` for the whole book: the plan, and the CAST.

    FEAT-UX-002 / FEAT-UX-004 / FEAT-UX-007. The preview used to be
    ``dry_run_render``'s cached-vs-to-render table and nothing else — it
    never mentioned who was going to read the book, which is the one thing a
    mis-cast render gets wrong and the one thing this preview could have
    caught for free. It also had no ``--json``, so the cheap pre-flight check
    was unavailable to any script.

    The human path still calls ``dry_run_render`` for the cache breakdown
    (that lives in the renderer, which owns the cache) and adds the cast
    report after it. The JSON path reports what this module can state
    truthfully on its own — chapters in BOTH numbering schemes, the cast, the
    uncast speakers who own dialogue, and the resolved output — and does not
    invent cache state it did not compute.
    """
    json_output = getattr(args, "json_output", False)

    # The cast report needs utterances. dry_run_render never compiled, and a
    # preview must not write, so compile in memory and do not save.
    for index, chapter in enumerate(project.chapters):
        if not chapter.is_compiled and not chapter.skip:
            try:
                project.compile_chapter(chapter.index)
            except Exception as exc:  # pragma: no cover - preview must not fail
                _logging_mod.getLogger(__name__).debug(
                    "Dry-run could not compile chapter %d (%s); "
                    "cast preview may be incomplete.", index, exc,
                )

    offenders = _uncast_dialogue_speakers(project, project.chapters)
    mapping = project.casting.get_voice_mapping()

    if json_output:
        _emit_json({
            "dry_run": True,
            "title": project.title,
            "output": str(output),
            "format": fmt,
            "engine": engine_name,
            "resume": bool(resume),
            "from_chapter": from_chapter,
            "chapters": [
                {
                    "index": chapter.index,
                    "number": chapter.index + 1,
                    "title": chapter.title,
                    "words": chapter.word_count,
                    "excluded": bool(chapter.skip),
                }
                for chapter in project.chapters
            ],
            "cast": dict(sorted(mapping.items())),
            "uncast_dialogue_speakers": dict(
                sorted(offenders.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            "would_refuse": bool(offenders) and not getattr(args, "force", False),
        })
        return 0

    from audiobooker.renderer.engine import dry_run_render
    dry_run_render(project, resume=resume, from_chapter=from_chapter)

    _out(f"Cast ({len(mapping)} speaker(s)):")
    if mapping:
        for speaker, voice in sorted(mapping.items()):
            _out(f"  {speaker}: {voice}")
    else:
        _out("  (nobody is cast - every line would use the fallback voice)")

    if offenders:
        _err(
            f"WARNING: {len(offenders)} speaker(s) own dialogue with no voice "
            "assigned. A real render will refuse unless you pass --force:",
            args=args,
        )
        for speaker, lines in sorted(offenders.items(), key=lambda kv: (-kv[1], kv[0])):
            _err(f"  {speaker}: {lines} dialogue line(s)", args=args)

    return 0


def _validate_single_chapter_render(args, project, tts_engine) -> Optional[int]:
    """Guard the `render -c N` path. Returns an exit code, or None to proceed.

    Kept as the combined entry point (flags then dry-run) for callers that do
    not need the two halves separated. ``_cmd_render_once`` calls the halves
    directly so `--clean-cache` can sit between them (CLIUX-H-003).
    """
    rc = _check_single_chapter_flags(args, project)
    if rc is not None:
        return rc
    if not getattr(args, "dry_run", False):
        return None
    return _dry_run_single_chapter(args, project)


def _handle_clean_cache(args, project_path: Path) -> Optional[int]:
    """`render --clean-cache`: report under --dry-run, delete otherwise.

    CLIUX-H-003: this used to be the FIRST thing `render` did — above the
    cover check, above the bounds check, above the incompatible-flag
    rejection, and above BOTH --dry-run short-circuits. So
    ``--clean-cache --dry-run`` destroyed the cache and then reported that
    nothing had happened; so did a bad ``-c`` index and a mistyped
    ``--cover``. It now runs only after every guard has passed, and under
    --dry-run it only ever reports.

    Returns an exit code to stop the run, or None to continue.
    """
    if not getattr(args, "clean_cache", False):
        return None

    from audiobooker.renderer.cache_manifest import get_cache_root
    import shutil

    cache_dir = get_cache_root(project_path.parent)
    if not cache_dir.exists():
        _out("No cache to clean.")
        return None

    chapters, files, size = _cache_stats(cache_dir)

    if getattr(args, "dry_run", False):
        _out(
            f"DRY RUN - would delete {chapters} cached chapter(s) "
            f"({files} file(s), {_format_bytes(size)}) from {cache_dir}"
        )
        return None

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
    _out(
        f"Cache cleared: {cache_dir} - deleted {chapters} cached chapter(s) "
        f"({files} file(s), {_format_bytes(size)})"
    )
    return None


def _check_dialogue_attribution_quality(args, chapters, casting) -> Optional[int]:
    """PH-B-002: refuse to render when dialogue attribution has collapsed.

    ``compile_chapter()`` (audiobooker/casting/dialogue.py) already computes
    this per chapter via ``compile_report()`` and logs a warning/error at
    compile time, but deliberately does NOT raise — changing what
    compile_chapter returns would break every existing caller. ``render`` is
    the chokepoint that assembles compile-then-synthesize, so it is the one
    place left that can still refuse to spend a TTS run on a book whose
    speakers are mostly wrong.

    Same shape as ``cmd_podcast`` / the ``export-chapters`` guard: an
    ``_err()`` naming the problem, an ``_err()`` hint, a non-zero return.
    ``--force`` — render's existing flag, previously documented as bypassing
    only casting-completeness validation — also bypasses this gate; that is
    the established override convention in this CLI (see also ``cast
    --force``), so this reuses it rather than adding a new flag.

    Args:
        args: Parsed CLI namespace for this render invocation (reads
            ``args.force``; forwarded to ``_err()`` for consistent formatting).
        chapters: The chapters actually about to be rendered (a single
            chapter for ``render -c N``, the possibly `--chapters`-filtered
            list for a full-book render). NOT necessarily project.chapters —
            scoping to only what will render means an unrelated bad chapter
            elsewhere in the book can never block (or a bad chapter outside
            the filtered range can never silently pass).
        casting: The project's CastingTable (for ``compile_report()`` and to
            name the ``unknown_character_behavior`` fallback in the message).

    Returns:
        1 when quality is 'failed' and --force was not passed (after
        printing the error + hint). None otherwise — including 'degraded',
        which is a caller concern (see cmd_compile) but does not by itself
        justify refusing a render — so the caller proceeds.
    """
    from audiobooker.casting import compile_report

    report = compile_report(chapters, casting)

    # FEAT-CAST-001: gate on attribution_quality, not quality.
    #
    # `quality` counts only dialogue the tool ADMITS it could not attribute.
    # Turn-tracking fills every gap by alternation and each guess is recorded
    # as a successful attribution, so a guess LOWERS that number. The gate was
    # therefore blind to the exact failure it exists to catch: a chapter where
    # every line got a confident wrong speaker has nothing `unknown` in it and
    # sailed straight through. The passage that drove this reads quality "ok"
    # at 52% hand-scored speaker accuracy.
    #
    # `attribution_quality` counts dialogue whose speaker was GUESSED, so it
    # cannot be improved by guessing harder. Both are reported below, because
    # the remedies differ: unattributed lines want casting or --lang, guessed
    # lines want a review pass.
    if report["attribution_quality"] != "failed" or getattr(
        args, "force", False
    ):
        return None

    unverified = report["dialogue_unverified_rate"]
    guessed = report["total_low_confidence"]
    unknown = report["total_dialogue_unknown"]
    total = report["total_dialogue"]

    _err(
        "Error: dialogue attribution failed the quality gate - "
        f"{guessed + unknown}/{total} dialogue lines ({unverified:.0%}) have "
        "no attribution in the text. "
        f"{guessed} were guessed by alternating turns and {unknown} are "
        "unattributed. Rendering now would pay for a full TTS run of a book "
        "whose speakers are largely invented (unknown speakers fall back to "
        f"{casting.unknown_character_behavior!r}).",
        args=args,
    )
    _err(
        "Hint: a guessed line is not visible in the unattributed count - run "
        "'audiobooker report' and check the low-confidence lines, or "
        "'review-export' to fix them by hand. Check --lang if the book is "
        "not English. Pass --force to render anyway (e.g. the book really is "
        "mostly narration).",
        args=args,
    )
    return 1


def _uncast_dialogue_speakers(project, chapters) -> dict[str, int]:
    """Named speakers who OWN DIALOGUE and have no voice: {speaker: lines}.

    FEAT-UX-002. Change one ``@Sarah`` to ``@Sarrah`` in a review file and
    ``review-import`` exits 0 with no warning, ``speakers`` shows
    ``Sarrah: [uncast]``, and the render proceeds. ``info`` already notices
    uncast speakers; it is simply not on the render path.

    ``unknown`` is excluded deliberately. It is not a typo — it is the
    designed sentinel for a line nobody could attribute, it has its own
    fallback (``casting.unknown_character_behavior``) and its own gate
    (``_check_dialogue_attribution_quality``). Counting it here would refuse
    every book with a single unattributable line, which is every real book.

    Narration is excluded too: a speaker who only narrates is covered by the
    narrator voice, so an uncast one is not a wrong-voice defect.

    Keys are the speaker names as they appear in the utterances — the names
    the user would type to fix this — not normalized casting keys.
    """
    from audiobooker.models import UtteranceType

    casting = project.casting
    cast_keys = {
        key for key, char in casting.characters.items() if getattr(char, "voice", None)
    }

    counts: dict[str, int] = {}
    for chapter in chapters:
        for utt in getattr(chapter, "utterances", None) or []:
            if utt.utterance_type != UtteranceType.DIALOGUE:
                continue
            speaker = (utt.speaker or "").strip()
            if not speaker:
                continue
            key = casting.normalize_key(speaker)
            if key == "unknown" or key in cast_keys:
                continue
            counts[speaker] = counts.get(speaker, 0) + 1
    return counts


def _check_uncast_dialogue_speakers(args, project, chapters) -> Optional[int]:
    """FEAT-UX-002: refuse to render dialogue in the wrong voice. Or None.

    ``render --force``'s help text has always promised it bypasses
    "casting-completeness" validation. One did exist — in
    ``renderer/engine.py`` — but it fires only when uncast speakers own more
    than 30% of ALL utterances, and only from inside ``render_project``,
    after the CLI has printed "Rendering audiobook to: ..." and started the
    progress bar. A typo affecting one secondary character sits far under
    that threshold, so the book rendered in full, exit 0, with that character
    read in the fallback voice. That is the expensive failure: you find out
    by listening.

    This gate is absolute rather than proportional (one uncast speaker with
    dialogue is already a wrong voice in the finished book), it runs before
    anything is spent, and it reuses ``--force`` — the established override
    in this CLI — rather than adding a flag.

    Returns 1 after printing the refusal, or None to proceed.
    """
    if getattr(args, "force", False):
        return None

    offenders = _uncast_dialogue_speakers(project, chapters)
    if not offenders:
        return None

    total = sum(offenders.values())
    _err(
        f"Error: {len(offenders)} speaker(s) own {total} dialogue line(s) but "
        "have no voice assigned, so they would be read in the fallback voice "
        f"({project.casting.unknown_character_behavior!r}):",
        args=args,
    )
    for speaker, lines in sorted(offenders.items(), key=lambda kv: (-kv[1], kv[0])):
        _err(f"  {speaker}: {lines} dialogue line(s)", args=args)
    _err(
        "Hint: cast them (audiobooker cast <speaker> <voice>), auto-cast them "
        "(audiobooker cast-apply --auto), or pass --force to render anyway. "
        "A speaker you do not recognise is usually a typo in an imported "
        "review file - check 'audiobooker speakers'.",
        args=args,
    )
    return 1


def _encodable_spinner() -> str:
    """A spinner name whose frames this console can actually encode.

    rich's default "dots" spinner uses braille (U+28xx). cp1252 -- the default
    Windows console codepage -- cannot encode it, and rich does not substitute
    ASCII for spinner frames the way it does for its own box and bar glyphs.
    "line" is plain ASCII (-\\|/) and renders everywhere.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "\u280b".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return "line"
    return "dots"


def _cmd_render_once(args) -> int:
    """Render audiobook (single pass — the body shared by cmd_render/watch).

    FEAT-UX-004: under ``--json`` the progress chatter is suppressed for the
    whole pass so stdout carries exactly one JSON object. ``_QUIET`` is the
    existing mechanism for that (``--silent`` sets it in ``main()``); it is
    saved and restored so ``--watch``'s next pass, and anything else in the
    process, sees it unchanged.
    """
    global _QUIET

    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import RenderError

    quiet_before = _QUIET
    if getattr(args, "json_output", False):
        _QUIET = True
    try:
        return _cmd_render_once_inner(args, AudiobookProject, RenderError)
    finally:
        _QUIET = quiet_before


def _cmd_render_once_inner(args, AudiobookProject, RenderError) -> int:
    """The render body. See ``_cmd_render_once`` for the --json wrapper."""
    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # FT-ENGINE-001: resolve the TTS engine once (explicit --engine >
        # project.config.tts_engine > default). None keeps current behavior.
        tts_engine = _resolve_engine(args, project)

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

        # CLIUX-H-003: --clean-cache is NOT handled here any more. It is an
        # irreversible rmtree of hours of synthesized audio, and running it
        # first meant every validation below it — and both --dry-run paths —
        # happened after the destruction. See _handle_clean_cache below.

        # FT-RENDER-011: Auto-apply voice suggestions if --cast-suggest
        if getattr(args, "cast_suggest", False):
            uncast = project.get_uncast_speakers()
            if uncast:
                _out(f"Auto-casting {len(uncast)} uncast speakers...")
                # Same evidence cast-suggest shows — see _suggest_voices.
                for result in _suggest_voices(project, uncast, max_suggestions=1):
                    if result.top:
                        project.cast(result.speaker, result.top.voice_id)
                        _out(f"  Cast {result.speaker} as {result.top.voice_id}")
                project.save()

        # OUTPUT-A-006: Validate cover path early so a typo doesn't silently
        # produce a coverless book.
        cover_flag = getattr(args, "cover", None)
        if cover_flag and not Path(cover_flag).exists():
            _err(f"Error: Cover art file not found: {cover_flag}")
            return 1

        # CLI-3 / CLI-5: everything below used to live in the `else:` branch of
        # `if args.chapter is not None:`, so `render -c N` ran straight past the
        # dry-run guard and every option below into a REAL synthesis. Validate
        # and short-circuit the single-chapter path BEFORE the split.
        #
        # CLIUX-H-003: the FLAG half runs here (before --clean-cache), the
        # DRY-RUN half below it (after), so a dry run can report the deletion
        # it is not going to perform.
        if args.chapter is not None:
            rc = _check_single_chapter_flags(args, project)
            if rc is not None:
                return rc

        # CLIUX-H-003: every guard above has passed — only now is it safe to
        # destroy the cache. Under --dry-run this only reports.
        rc = _handle_clean_cache(args, project_path)
        if rc is not None:
            return rc

        if args.chapter is not None and getattr(args, "dry_run", False):
            return _dry_run_single_chapter(args, project)

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
            # FEAT-UX-007: name what was selected in BOTH schemes. The
            # count alone left the user to guess whether "1-2,4" had done
            # what they meant, and the dry-run table then renumbered the
            # survivors 0,1,2 — so nothing on screen agreed with the flag
            # they had just typed.
            _out(f"Chapter selection: {len(project.chapters)} of {original_count} chapters")
            for chapter in project.chapters:
                _out(f"  {_chapter_label(chapter.index)} {chapter.title}")

        if args.chapter is not None:
            # Render single chapter. Bounds, flag compatibility and --dry-run
            # were all settled by _validate_single_chapter_render() above.
            _out(f"Rendering chapter {args.chapter}...")
            output = _single_chapter_output(args)

            # Compile on demand — moved ahead of the engine branch below
            # (PH-B-002) so the attribution-quality gate can run before
            # EITHER branch renders, not just the explicit-engine one.
            chapter = project.chapters[args.chapter]
            if not chapter.is_compiled:
                project.compile_chapter(args.chapter)

            # PH-B-002: refuse before spending a TTS run if this chapter's
            # dialogue attribution has collapsed. Scoped to just this
            # chapter — the rest of the book, compiled or not, has no
            # bearing on whether THIS render should proceed.
            rc = _check_dialogue_attribution_quality(args, [chapter], project.casting)
            if rc is not None:
                return rc

            # FEAT-UX-002: and refuse if a named speaker in THIS chapter owns
            # dialogue with no voice — same scoping rationale as above.
            rc = _check_uncast_dialogue_speakers(args, project, [chapter])
            if rc is not None:
                return rc

            if tts_engine is not None:
                # FT-ENGINE-001: thread the resolved engine through the
                # module-level render_chapter (project.render_chapter takes no
                # engine).
                from audiobooker.renderer.engine import render_chapter as _render_chapter
                path = _render_chapter(
                    chapter, project.casting, Path(output), engine=tts_engine
                )
            else:
                path = project.render_chapter(args.chapter, output)
            _out(f"Output: {path}")

            # CLI-5: --notify is advertised on `render` but was read only in
            # the full-book branch, so a single-chapter render never notified.
            if getattr(args, "notify", False):
                _send_notification(
                    title="Audiobooker",
                    message=f"Chapter {args.chapter} rendered: {path}",
                )
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
                return _dry_run_full_book(
                    args,
                    project,
                    output=output,
                    fmt=fmt,
                    resume=resume,
                    from_chapter=from_chapter,
                    engine_name=(
                        getattr(args, "engine", None)
                        or project.config.tts_engine
                        or "voice-soundboard"
                    ),
                )

            # PH-B-002: ensure compiled, then refuse before spending a TTS run
            # if attribution has collapsed. Must run BEFORE the needs_direct /
            # project.render() split below — project.render() would otherwise
            # compile internally as a side effect of rendering, after we
            # would already have committed to proceeding.
            uncompiled = [c for c in project.chapters if not c.is_compiled and not c.skip]
            if uncompiled:
                project.compile()

            rc = _check_dialogue_attribution_quality(args, project.chapters, project.casting)
            if rc is not None:
                return rc

            # FEAT-UX-002: a typo'd speaker name is a wrong voice in the
            # finished book — refuse before the TTS run, not after.
            rc = _check_uncast_dialogue_speakers(args, project, project.chapters)
            if rc is not None:
                return rc

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
                _out("  (cache disabled - full re-render)")
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

            def _plain_progress(current, total, status):
                # --json owns stdout for the payload; rich's bar and these
                # lines both write there, so neither may run.
                if getattr(args, "json_output", False):
                    return
                print(f"  [{current}/{total}] {status}")

            try:
                if getattr(args, "json_output", False):
                    raise ImportError("--json: no progress bar on the payload stream")
                from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
                progress_bar = Progress(
                    # rich's default spinner is "dots", drawn with braille
                    # (U+28xx), which cp1252 cannot encode -- and cp1252 is the
                    # DEFAULT Windows console codepage. The spinner therefore
                    # raised UnicodeEncodeError on a stock Windows console for
                    # every render, healthy book or not, after the user had
                    # already paid for the TTS pass. BarColumn is fine: rich
                    # substitutes ASCII for its own glyphs, but it does not do
                    # that for spinner frames.
                    SpinnerColumn(spinner_name=_encodable_spinner()),
                    TextColumn("[bold]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeRemainingColumn(),
                    transient=False,
                )
                progress_bar.start()
                progress_task = progress_bar.add_task("Rendering...", total=len(project.chapters))

                def progress(current, total, status):
                    # A progress INDICATOR must never be able to abort the
                    # render it is reporting on. If drawing fails for any
                    # reason, drop to plain lines and keep going.
                    try:
                        progress_bar.update(
                            progress_task, completed=current,
                            description=status[:60],
                        )
                    except Exception:
                        _plain_progress(current, total, status)

            except Exception as _progress_err:
                # Deliberately broad, and NOT just ImportError: the original
                # clause caught only a missing `rich`, so an encoding failure
                # while STARTING the bar escaped and killed the render.
                if not isinstance(_progress_err, ImportError):
                    _logging_mod.getLogger(__name__).debug(
                        "Progress bar unavailable (%s); using plain output.",
                        _progress_err,
                    )
                if progress_bar is not None:
                    try:
                        progress_bar.stop()
                    except Exception:
                        pass
                progress_bar = None
                progress_task = None
                progress = _plain_progress

            try:
                # OUTPUT-F1: Any of cover/normalize/acx/bitrate/split requires a
                # direct render_project call so we can thread the extra kwargs.
                # The plain case still goes through project.render() (which now
                # also forwards profile/bitrate/split) to keep that path simple.
                # FT-ENGINE-001: a non-default engine also requires the direct
                # render_project path so we can pass engine= through.
                needs_direct = bool(
                    cover or normalize or output_profile != "podcast"
                    or bitrate or split or tts_engine is not None
                )
                if needs_direct:
                    from audiobooker.renderer.engine import render_project
                    # PH-B-002: compilation now happens unconditionally above,
                    # before the attribution-quality gate — nothing left to
                    # ensure here.
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
                    # FT-ENGINE-001: only pass engine when one was resolved so
                    # the None default stays byte-identical to today.
                    if tts_engine is not None:
                        direct_kwargs["engine"] = tts_engine
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

            # A render that dropped chapters (--allow-partial) still returns a
            # path and still writes a file; announcing "Audiobook created" for
            # it told the user a 29-of-30-chapter book was finished.
            partial = _render_incompleteness(path)
            if getattr(args, "json_output", False):
                # FEAT-UX-004: a render is the expensive step, so a script
                # should be able to read its outcome rather than scrape it.
                _emit_json({
                    "title": project.title,
                    "output": str(path),
                    "complete": partial is None,
                    "duration_minutes": round(
                        project.total_duration_seconds / 60, 2
                    ),
                    "chapters": len(project.chapters),
                    "detail": (
                        _partial_render_message(partial) if partial is not None else ""
                    ),
                })
            elif partial is not None:
                _err(f"\nAudiobook assembled INCOMPLETE: {path}", args=args)
                _err(_partial_render_message(partial), args=args)
                _err(f"Hint: {_PARTIAL_RENDER_HINT}", args=args)
                _out(f"Duration: {project.total_duration_seconds / 60:.1f} minutes")
            else:
                _out(f"\nAudiobook created: {path}")
                _out(f"Duration: {project.total_duration_seconds / 60:.1f} minutes")

            # FT-RENDER-020: Desktop notification on success
            if notify:
                _send_notification(
                    title="Audiobooker",
                    message=(
                        f"Render PARTIAL: {project.title}"
                        if partial is not None
                        else f"Render complete: {project.title}"
                    ),
                )

            if partial is not None:
                # Exit-code taxonomy: 3 = partial (documented in README).
                return 3

        return 0

    except RenderError as e:
        if getattr(args, "json_output", False):
            _report_error(e, args)
        else:
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


def _render_incompleteness(path) -> Optional["RenderSummary"]:
    """Return the RenderSummary when a render did NOT produce a whole book.

    ``render_project`` returns a Path that also carries ``render_summary``
    (see ``renderer.engine.RenderedOutputPath``). A render under
    ``--allow-partial`` that dropped chapters still returns a path and still
    writes a real file, so the summary is the ONLY thing that distinguishes it
    from a finished book — and discarding it is how a 29-of-30-chapter
    audiobook got reported to the user as complete.

    Returns None when the render is complete, when the caller was handed a
    plain Path (an injected/mocked renderer), or when the summary cannot be
    interpreted — i.e. "not provably incomplete" never blocks a report.
    """
    summary = getattr(path, "render_summary", None)
    if summary is None:
        return None
    try:
        if summary.is_complete:
            return None
    except Exception:  # pragma: no cover - never fail a report over metadata
        return None
    return summary


def _partial_render_message(summary) -> str:
    """One user-facing line naming exactly what is missing from the output."""
    missing = list(getattr(summary, "missing_chapters", None) or [])
    failed = int(getattr(summary, "failed", 0) or 0)
    total = int(getattr(summary, "total", 0) or 0)

    parts = []
    if missing:
        indices = ", ".join(str(i) for i in missing)
        parts.append(f"{len(missing)} chapter(s) dropped (indices: {indices})")
    if failed:
        parts.append(f"{failed} chapter(s) failed to render")
    detail = "; ".join(parts) or "some chapters are missing from the output"

    if total:
        included = max(total - len(missing), 0)
        return (
            f"PARTIAL render - {detail}. "
            f"The file contains {included} of {total} chapters."
        )
    return f"PARTIAL render - {detail}."


_PARTIAL_RENDER_HINT = (
    "Re-run `audiobooker render` to retry only the missing chapters "
    "(completed chapters are cached), or `--no-resume` to start clean."
)


def _print_render_failure(e: "RenderError") -> None:
    """Print user-friendly render failure message with recovery hints."""
    _err(f"\nRender failed: {e}")

    summary = e.summary
    if summary is None:
        return

    if summary.failed_chapters:
        _err("\nFailed chapters:")
        for ch in summary.failed_chapters:
            _err(f"  Chapter {ch['index']}: {ch['title']}")
            _err(f"    Error: {ch['error']}")

    _err(
        f"\nRender summary: {summary.rendered} rendered, "
        f"{summary.skipped_cached} cached, {summary.failed} failed "
        f"(of {summary.total} total)"
    )

    if summary.cache_dir:
        _err(f"\nCached chapter audio: {summary.cache_dir}")

        # FT-RENDER-013: Surface failure report if it exists
        report_path = Path(summary.cache_dir) / "render_failure_report.json"
        if report_path.exists():
            _err(f"Failure report: {report_path}")
            try:
                from audiobooker.renderer.failure_report import RenderFailureReport
                report = RenderFailureReport.load(report_path)
                if report.failed_chapters:
                    first_fail = report.failed_chapters[0]
                    if first_fail.failed_utterance and first_fail.failed_utterance.speaker:
                        fu = first_fail.failed_utterance
                        preview = fu.text_preview[:80] if fu.text_preview else "(no text)"
                        _err(f"  First failure: speaker={fu.speaker}, text={preview!r}")
            except Exception:
                pass  # Don't fail on report parsing

    if summary.manifest_path:
        _err(f"Manifest: {summary.manifest_path}")

    # Prefer the structured hint carried on the RenderError (it names the
    # exact resume flag, e.g. --from-chapter) over the generic resume text.
    hint = getattr(e, "hint", None)
    if hint:
        _err(f"\nHint: {hint}")
    else:
        _err("\nTo resume: audiobooker render")
        _err("To force:  audiobooker render --no-resume")


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


def _voice_display(voice) -> tuple[str, str]:
    """Normalize one list_voices() entry to (voice_id, description).

    Tolerates the shapes a third-party engine's list_voices() might return: a
    bare id string, a (id, description) tuple, or a dict carrying an
    id/name/voice_id key plus an optional description/label. Keeps cmd_voices
    engine-agnostic so the printed/filtered output is stable across engines.
    """
    if isinstance(voice, str):
        return voice, ""
    if isinstance(voice, dict):
        vid = str(
            voice.get("voice_id")
            or voice.get("id")
            or voice.get("name")
            or ""
        )
        desc = str(voice.get("description") or voice.get("label") or "")
        return vid, desc
    if isinstance(voice, (tuple, list)) and voice:
        vid = str(voice[0])
        desc = str(voice[1]) if len(voice) > 1 else ""
        return vid, desc
    return str(voice), ""


def cmd_voices(args) -> int:
    """List available voices (optionally from a specific TTS engine).

    FT-ENGINE-001: with --engine NAME, resolve that engine and list its voices
    via voice_registry.get_available_voices(engine=...) — which uses the
    engine's optional list_voices() when present and otherwise falls back to the
    built-in voice-soundboard voice set. Without --engine, the default behavior
    (the built-in voice-soundboard catalog) is preserved.
    """
    from audiobooker.casting.voice_registry import get_available_voices

    engine_name = getattr(args, "engine", None)
    json_output = getattr(args, "json_output", False)

    # Resolve the engine instance when one was named so its list_voices() is
    # used; None lets get_available_voices() fall back to the default catalog.
    engine_obj = None
    if engine_name:
        from audiobooker.renderer import engine as engine_mod
        try:
            try:
                engine_obj = engine_mod.get_default_engine(engine_name)
            except TypeError:
                # Older no-arg signature — resolves the built-in engine.
                engine_obj = engine_mod.get_default_engine()
        except Exception as e:
            _err(f"Error: could not load TTS engine {engine_name!r}: {e}", args=args)
            return 1

    offline = ""
    try:
        # Per contract: get_available_voices(engine=...) uses the engine's
        # list_voices() when present, else the built-in catalog. Call
        # defensively so a concurrently-evolving registry with the older
        # no-arg signature still works (engine=None == today's default).
        try:
            voices = get_available_voices(engine=engine_obj)
        except TypeError:
            voices = get_available_voices()
    except ImportError as exc:
        # `voices` used to stop here with exit 1 — while `cast-suggest` and
        # `audition`, on the very same machine, happily printed voice IDs.
        # They go through DefaultVoiceRegistry, which falls back to the
        # curated catalog when the backend is absent. So you could accept
        # the machine's casting offline but never override it, which
        # contradicts the documented offline workflow. Use the same fallback
        # the suggester uses, and say which catalog this is.
        from audiobooker.casting.voice_registry import VoiceBackendIncompatibleError
        from audiobooker.casting.voice_suggester import DefaultVoiceRegistry

        voices = set(DefaultVoiceRegistry().list_voices())
        offline = (
            "incompatible" if isinstance(exc, VoiceBackendIncompatibleError)
            else "missing"
        )
        if not voices:  # pragma: no cover - the curated list is never empty
            _err("Error: voice-soundboard not installed", args=args)
            _err(VOICE_SOUNDBOARD_INSTALL_HINT, args=args)
            return 1

    # Normalize whatever get_available_voices returns (a set of ids, or a list
    # of richer voice descriptors) into (voice_id, description) pairs.
    pairs = [_voice_display(v) for v in voices]

    rows: list[tuple[str, str]] = []
    for voice_id, desc in pairs:
        if not voice_id:
            continue
        # Filter by gender (voice-soundboard prefix convention).
        if args.gender:
            voice_gender = (
                "female"
                if voice_id.startswith("af_") or voice_id.startswith("bf_")
                else "male"
            )
            if voice_gender != args.gender.lower():
                continue
        # Filter by search term across id + description.
        if args.search:
            search_lower = args.search.lower()
            if (
                search_lower not in voice_id.lower()
                and search_lower not in desc.lower()
            ):
                continue
        rows.append((voice_id, desc))

    rows.sort(key=lambda r: r[0])

    if json_output:
        _emit_json({
            "engine": engine_name or "voice-soundboard",
            "source": "builtin-catalog" if offline else "engine",
            "backend": offline or "available",
            "voices": [
                {"voice_id": vid, "description": desc} if desc else {"voice_id": vid}
                for vid, desc in rows
            ],
        })
        return 0

    if offline:
        reason = (
            "voice-soundboard is installed but its API has drifted"
            if offline == "incompatible"
            else "voice-soundboard is not installed"
        )
        _err(
            f"Note: {reason}, so this is the built-in curated catalog - the "
            "same list cast-suggest and audition rank against. Install (or "
            "repair) the backend to see the voices it actually ships.",
            args=args,
        )
        _err(VOICE_SOUNDBOARD_INSTALL_HINT, args=args)

    label = f" ({engine_name})" if engine_name else ""
    _out(f"Available voices{label}:\n")
    for voice_id, desc in rows:
        _out(f"  {voice_id}{f'  - {desc}' if desc else ''}")

    return 0


def _chapter_label(index: int) -> str:
    """FEAT-UX-007: name a chapter in BOTH numbering schemes, everywhere.

    This CLI carries four: ``-c N`` is 0-based, ``--chapters`` /
    ``--exclude-chapters`` take 1-based ranges, the ``chapters`` listing was
    1-based, and ``render --dry-run`` printed indices relative to the
    SELECTION (so ``--chapters 1-3`` printed ``[0] Chapter 1 / [1] Chapter 2 /
    [2] Chapter 4``). Nothing on screen said which scheme it was using.

    The flags themselves are documented and stay as they are — silently
    changing what ``-c 3`` means would be worse than the ambiguity. Instead
    every printed reference carries both numbers, so no reader has to know
    which command they came from.
    """
    return f"[idx {index}] ch.{index + 1}"


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
            _out(
                f"Merged chapters {_chapter_label(args.start)}-"
                f"{_chapter_label(args.end)} into: {merged.title}"
            )
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
            _out(
                f"Split chapter {_chapter_label(args.index)} at paragraph "
                f"{args.paragraph}:"
            )
            _out(f"  {_chapter_label(first.index)} {first.title} ({first.word_count} words)")
            _out(f"  {_chapter_label(second.index)} {second.title} ({second.word_count} words)")
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
            _out(f"Excluded chapter {_chapter_label(args.index)}: {ch.title}")
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
            _out(f"Included chapter {_chapter_label(args.index)}: {ch.title}")
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
            _out(f"Renamed chapter {_chapter_label(args.index)}: {old_title!r} -> {args.title!r}")
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
                _out(f"  {_chapter_label(ch.index)} {ch.title}")
            return 0
        except USER_ERROR_TYPES as e:
            _report_error(e, args)
            return 1

    # Default: list chapters
    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        rows = [
            {
                # FEAT-UX-007: BOTH numbers, always. `-c N` is 0-based,
                # `--chapters`/`--exclude-chapters` take 1-based ranges, this
                # listing was 1-based-only and `render --dry-run` printed
                # selection-relative indices — four schemes, and an off-by-one
                # here costs a real TTS bill.
                "index": chapter.index,
                "number": chapter.index + 1,
                "title": chapter.title,
                "words": chapter.word_count,
                "excluded": bool(chapter.skip),
                "compiled": bool(chapter.is_compiled),
                "rendered": bool(chapter.is_rendered),
            }
            for chapter in project.chapters
        ]

        if getattr(args, "json_output", False):
            _emit_json({"title": project.title, "chapters": rows})
            return 0

        _out(f"Chapters in {project.title}:\n")

        for row in rows:
            status = ""
            if row["excluded"]:
                status = " [excluded]"
            elif row["rendered"]:
                status = " [rendered]"
            elif row["compiled"]:
                status = " [compiled]"

            _out(f"  {_chapter_label(row['index'])} {row['title']} "
                 f"({row['words']} words){status}")

        _out(
            "\n[idx N] is what -c/--chapter takes (0-based); ch.N is what "
            "--chapters/--exclude-chapters take (1-based)."
        )

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def cmd_speakers(args) -> int:
    """List detected speakers (or, with --suggest-aliases, propose aliases)."""
    from audiobooker import AudiobookProject

    json_output = getattr(args, "json_output", False)

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            # Suppress the prep message under --json so stdout stays pure JSON.
            if not json_output:
                _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        # CASTING-DEPTH v2.1: alias suggestion mode.
        if getattr(args, "suggest_aliases", False):
            return _speakers_suggest_aliases(project, args)

        speakers = project.get_detected_speakers()
        cast_speakers = set(project.casting.characters.keys())

        # Everyone showed "(0 lines)". ``Character.line_count`` is written by
        # compile_chapter with an ASSIGNMENT per chapter, so the last chapter
        # overwrites the rest, it is never written for a speaker cast AFTER
        # the compile, and the parallel compile path loses it entirely.
        # ``report`` has had the real book-wide counts all along, off the same
        # project — so read them from there instead of from a field that
        # cannot hold them.
        from audiobooker.casting import compile_report
        line_counts = compile_report(project.chapters, project.casting)[
            "speaker_line_counts"
        ]

        rows = []
        for speaker in sorted(speakers):
            normalized = project.casting.normalize_key(speaker)
            char = project.casting.characters.get(normalized)
            rows.append({
                "speaker": speaker,
                "key": normalized,
                "voice": char.voice if normalized in cast_speakers else None,
                "lines": line_counts.get(normalized, 0),
            })

        # `speakers` has advertised --json since it was written; only the
        # alias-suggestion branch ever honored it.
        if json_output:
            _emit_json({"title": project.title, "speakers": rows})
            return 0

        _out(f"Speakers in {project.title}:\n")

        for row in rows:
            voice = row["voice"] or "[uncast]"
            _out(f"  {row['speaker']}: {voice} ({row['lines']} lines)")

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
        else:
            # The library default names the file from the book TITLE and
            # resolves it against the CWD, so `review-export` on "The
            # Midnight Garden" wrote "The Midnight Garden_review.txt" into
            # whatever directory you happened to be in — then printed an
            # unquoted command to import it. Default to the PROJECT file's
            # own stem, next to the project: one token, and where the user
            # will look for it.
            output = project_path.with_name(f"{project_path.stem}_review.txt")

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
        # Quoted, because the command we print has to RUN when pasted. An
        # unquoted name with a space made argparse reject it and dump all 34
        # subcommands at a user who had done nothing wrong. See _quote_arg.
        _out(
            "\nThen import: audiobooker review-import "
            f"{_quote_arg(review_path.name)}"
        )

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
            _err(f"Error: Review file not found: {review_path}")
            return 1

        _out(f"Importing review file: {review_path}")

        # CLIUX-H-007: we render our own per-line report below, so silence the
        # module logger's duplicate of every malformed line (it stays at DEBUG
        # for --debug).
        from audiobooker import review as review_mod

        with review_mod.caller_reports_malformed():
            stats = project.import_reviewed(review_path)

        # CLI-2: an @-leading line that is not a valid speaker tag used to be
        # absorbed as BODY TEXT — the finished audiobook then narrated the
        # literal "@Bob, the baker" aloud and lost the character, while the CLI
        # printed "Ready to render" and exited 0. Refuse the import instead:
        # nothing is saved, so the project on disk is untouched.
        malformed = stats.get("malformed_lines") or []
        if malformed:
            _err(
                f"\nError: {len(malformed)} line(s) start with '@' but are not "
                "valid speaker tags. Nothing was imported.",
                args=args,
            )
            # CLIUX-H-007: one hint per line, chosen from the line's actual
            # shape. The old blanket hint ("if the line is body text, escape it
            # with a leading backslash") was wrong for the dominant cause — a
            # second emotion group — and following it made the renderer SPEAK
            # the tag aloud.
            for entry in malformed:
                _err(f"  line {entry['line']}: {entry['text']}", args=args)
                hint = entry.get("hint")
                if hint:
                    _err(f"    Hint: {hint}", args=args)
            return 1

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
            _err(
                f"\nWARNING: {skipped} edited block(s) did not match any chapter "
                "and were NOT applied:",
                args=args,
            )
            for title in skipped_titles:
                _err(f"  - {title}", args=args)
            _err(
                'Hint: These blocks did not match any chapter by id or title - '
                'restore the original "=== Title === [id:...]" header to apply '
                "your edits.",
                args=args,
            )

        # CLI-1: a chapter that had utterances and came back with none renders
        # as silence. Never let that pass unremarked.
        emptied = stats.get("emptied_chapters") or []
        if emptied:
            _err(
                f"\nWARNING: {len(emptied)} chapter(s) lost ALL utterances in "
                "this import and will render SILENT:",
                args=args,
            )
            for title in emptied:
                _err(f"  - {title}", args=args)
            _err(
                "Hint: re-export with 'audiobooker review-export' and re-apply "
                "your edits if this was not intentional.",
                args=args,
            )

        # CLIUX-H-006: the review file's own instruction ("Delete entire
        # speaker blocks to remove them") changes the block count, and import
        # can then only re-derive every utterance type in that chapter from a
        # starts-with-a-quote heuristic. PAUSE and DIRECTION become NARRATION
        # and the renderer reads "[PAUSE]" / "[SFX ...]" aloud as prose. That
        # used to happen with chapters_skipped=0 and exit 0.
        retyped = stats.get("retyped_chapters") or []
        if retyped:
            _err(
                f"\nWARNING: {len(retyped)} chapter(s) changed block count, so "
                "EVERY utterance type in them was re-derived from a text "
                "heuristic:",
                args=args,
            )
            for item in retyped:
                lost = item.get("lost_types") or []
                detail = (
                    f"{item['types_lost']} marker type(s) lost "
                    f"({', '.join(lost)})"
                    if lost
                    else "no marker types were present"
                )
                _err(
                    f"  - {item['title']}: {item['blocks_before']} block(s) -> "
                    f"{item['blocks_after']}; {detail}",
                    args=args,
                )
            _err(
                "Hint: PAUSE / DIRECTION / FOOTNOTE markers are now plain "
                "narration and the renderer will read their marker text aloud. "
                "Re-export and edit in place (rather than deleting blocks) to "
                "keep them.",
                args=args,
            )

        _out("\nProject saved. Ready to render: audiobooker render")

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def _suggest_voices(project, speakers, *, max_suggestions: int = 1):
    """The ONE ranking call behind cast-suggest, cast-apply and --cast-suggest.

    ``cmd_cast_suggest`` gathered ``speaker_utterances`` and passed them to
    ``suggest_all``; ``cmd_cast_apply``, ``render --cast-suggest`` and
    ``make``/``batch``'s auto-cast step all called the same function WITHOUT
    them. The suggester reads those sample lines to infer gender, age and
    archetype, so the commands that ACT ranked on strictly less evidence than
    the command that EXPLAINS — for a male-cued speaker, ``cast-suggest``
    showed ``am_eric`` while ``cast-apply --auto`` assigned ``af_jessica``.

    One helper, so the ranking cannot drift apart again.
    """
    from audiobooker.casting.voice_suggester import VoiceSuggester

    # ``get_detected_speakers()`` yields the raw names as they appear in the
    # utterances; ``get_uncast_speakers()`` yields NORMALIZED casting keys.
    # ``_gather_speaker_utterances`` is keyed by the raw name, so indexing it
    # only one way would hand the suggester an empty sample list for one of
    # the two callers — which is exactly the divergence this helper exists to
    # remove. Index both spellings.
    samples = _gather_speaker_utterances(project)
    lookup: dict[str, list[str]] = dict(samples)
    for raw, lines in samples.items():
        key = project.casting.normalize_key(raw)
        if key not in lookup:
            lookup[key] = list(lines)
        elif key != raw:
            lookup[key] = (lookup[key] + list(lines))[:5]

    suggester = VoiceSuggester(max_suggestions=max_suggestions)
    return suggester.suggest_all(
        sorted(speakers),
        lookup,
        project.casting.get_voice_mapping(),
    )


def cmd_cast_suggest(args) -> int:
    """Suggest voices for uncast speakers."""
    from audiobooker import AudiobookProject

    json_output = getattr(args, "json_output", False)

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            if not json_output:
                _out("Compiling to detect speakers...")
            project.compile()
            project.save()

        results = _suggest_voices(
            project,
            project.get_detected_speakers(),
            max_suggestions=getattr(args, "top", 3),
        )

        if json_output:
            _emit_json({
                "title": project.title,
                "suggestions": [
                    {
                        "speaker": result.speaker,
                        "cast": _cast_voice_for(project, result.speaker),
                        "candidates": [
                            {
                                "voice_id": s.voice_id,
                                "score": round(s.score, 4),
                                "reason": s.reason,
                            }
                            for s in result.suggestions
                        ],
                    }
                    for result in results
                ],
            })
            return 0

        _out(f"Voice suggestions for {project.title}:\n")
        for result in results:
            voice = _cast_voice_for(project, result.speaker)
            status = f" (cast: {voice})" if voice else " [uncast]"
            _out(f"  {result.speaker}{status}")
            for i, s in enumerate(result.suggestions):
                marker = ">>>" if i == 0 else "   "
                _out(f"    {marker} {s.voice_id} (score: {s.score:.2f}) - {s.reason}")
            _out()

        return 0

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def _cast_voice_for(project, speaker: str) -> Optional[str]:
    """The voice already assigned to ``speaker``, or None when uncast."""
    character = project.casting.characters.get(project.casting.normalize_key(speaker))
    return character.voice if character else None


def cmd_cast_apply(args) -> int:
    """Auto-apply voice suggestions."""
    from audiobooker import AudiobookProject

    json_output = getattr(args, "json_output", False)
    dry_run = getattr(args, "dry_run", False)

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if not getattr(args, "auto", False):
            _out("Use --auto to apply top suggestions for all uncast speakers.")
            return 0

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            if not json_output:
                _out("Compiling to detect speakers...")
            project.compile()

        uncast = project.get_uncast_speakers()
        if not uncast:
            if json_output:
                _emit_json({"dry_run": dry_run, "applied": [], "count": 0})
            else:
                _out("All speakers are already cast.")
            return 0

        # Same evidence cast-suggest showed you — see _suggest_voices.
        results = _suggest_voices(project, uncast, max_suggestions=1)

        applied = []
        for result in results:
            if not result.top:
                continue
            applied.append({
                "speaker": result.speaker,
                "voice": result.top.voice_id,
                "reason": result.top.reason,
            })
            if not dry_run:
                project.cast(result.speaker, result.top.voice_id)

        if not dry_run:
            project.save()

        if json_output:
            _emit_json({
                "dry_run": dry_run,
                "applied": applied,
                "count": len(applied),
            })
            return 0

        if dry_run:
            _out("DRY RUN - nothing was cast and the project was not saved.")
        for row in applied:
            verb = "Would cast" if dry_run else "Cast"
            _out(f"  {verb} {row['speaker']} as {row['voice']} ({row['reason']})")

        if dry_run:
            _out(f"\n{len(applied)} voice assignment(s) would be applied.")
            _out("Re-run without --dry-run to apply them.")
        else:
            _out(f"\nApplied {len(applied)} voice assignments.")
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
        _out("No characters to save - the casting table is empty.")
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
        _out(f"Preset '{args.name}' is empty - nothing to apply.")
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
        _err("Error: No input on stdin. Pipe text in, e.g.:")
        print('  cat book.txt | audiobooker from-stdin --title "My Book"')
        return 1

    text = sys.stdin.read()
    if not text.strip():
        _err("Error: stdin was empty")
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

            # CLIUX-H-010: this rmtree is hours of synthesized audio — on a
            # paid or GPU backend, real money and real wall-clock. It ran with
            # no prompt, no --yes, no --dry-run, and reported neither the
            # chapter count nor the size, though `cache info` computes both
            # ten lines above. Say what is at stake, then ask.
            chapters, files, size = _cache_stats(cache_root)
            at_stake = (
                f"{chapters} cached chapter(s), {files} file(s), "
                f"{_format_bytes(size)}"
            )

            if getattr(args, "dry_run", False):
                _out(f"DRY RUN - would delete {at_stake} from {cache_root}")
                _out("Re-run with --yes to delete them.")
                return 0

            if not getattr(args, "yes", False):
                _out(f"About to delete {at_stake} from {cache_root}")
                _out(
                    "  Every chapter would have to be synthesized again. To drop "
                    "only the broken entries instead, use: audiobooker cache "
                    "clean-failed"
                )
                if not sys.stdin.isatty():
                    _err(
                        "Error: refusing to delete the cache without "
                        "confirmation. Pass --yes to confirm in a "
                        "non-interactive shell.",
                        args=args,
                    )
                    return 1
                try:
                    answer = input("Delete the cache? [y/N] ").strip().lower()
                except EOFError:
                    answer = ""
                if answer not in ("y", "yes"):
                    _out("Aborted - nothing was deleted.")
                    return 1

            # Safety check for lockfile
            lock_path = cache_root / ".render.lock"
            if lock_path.exists():
                print(
                    f"WARNING: Cache appears to be in use (lockfile: {lock_path}).\n"
                    f"If no render is active, delete the lockfile manually."
                )
                return 1
            shutil.rmtree(cache_root)
            _out(f"Cache deleted: {cache_root} - removed {at_stake}")
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

        # FEAT-CAST-001: `unknown_rate` is the narration-diluted figure the
        # report dict itself marks secondary -- add narration to a book and
        # it falls without a single speaker being identified. The primary
        # signal divides dialogue by dialogue. `compile` was moved to it;
        # the command actually named `report` was still printing the other.
        unknown_pct = report["dialogue_unknown_rate"] * 100
        _out(f"Compile report for {project.title}:\n")
        _out(f"  Total utterances:  {report['total_utterances']}")
        _out(f"  Dialogue / narration: {report['total_dialogue']} / {report['total_narration']}")
        _out(f"  Unattributed rate: {unknown_pct:.1f}%  (of dialogue)")

        # The other half, and the half a user cannot otherwise discover:
        # lines that DID get a speaker, chosen by alternating turns rather
        # than by anything in the text. These never appear in the
        # unattributed count -- a guess removes a line from it.
        guessed = report["total_low_confidence"]
        if guessed:
            _out(
                # ASCII on purpose. An earlier version of this comment said
                # "cp1252, where an em-dash degrades" — wrong, and worth
                # correcting rather than deleting: cp1252 is the Windows
                # ANSI codepage and encodes the em-dash fine, at 0x97. The
                # codepage a bare cmd.exe actually runs is an OEM one (437
                # in en-US, 850 in western Europe), and neither has it. See
                # tests/test_cli_output_is_console_safe.py for the measured
                # table. _out no longer crashes on an unencodable
                # character, so this now fails silently — which is why the
                # guard is a test rather than a convention.
                f"  Guessed speakers:  {guessed} "
                f"({report['dialogue_low_confidence_rate']:.1%} of dialogue) "
                "- attributed by alternating turns, not by the text"
            )
        _out(
            f"  Attribution:       {report['attribution_quality'].upper()} "
            f"({report['dialogue_unverified_rate']:.1%} of dialogue "
            "unverified)"
        )

        sources = report.get("attribution_source_distribution") or {}
        if sources:
            _SOURCE_LABELS = {
                "tag": "speech tag",
                "turn": "alternating turn",
                "nlp": "co-reference",
                "inline": "inline override",
                "user": "your correction",
            }
            parts = ", ".join(
                f"{_SOURCE_LABELS.get(k, k)}: {v}"
                for k, v in sorted(sources.items(), key=lambda x: -x[1])
            )
            _out(f"  Attributed by:     {parts}")

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

        # compile_report has built this list since FEAT-CAST-001 and nothing
        # printed it. A rate tells a user they have a problem; these lines
        # tell them where it is -- and unlike the unattributed ones, they
        # are invisible in the review export, because they carry a
        # confident-looking speaker name.
        guesses = report.get("low_confidence") or []
        if guesses:
            _out(
                "\nTop guessed lines (a speaker was assigned, but nothing "
                "in the text says so):"
            )
            for item in guesses:
                # No context line here, unlike the unattributed listing
                # above. These lines sit in an unbroken run of dialogue --
                # that IS why they were guessed -- so the surrounding text
                # is the same few quotes every time and reads as noise.
                # The line and the speaker put on it are the actionable part.
                _out(
                    f"  ch{item['chapter_index']} line {item['line_index']}: "
                    f"{item['text']!r} -> {item['speaker']}"
                )
            _out(
                "\nFix these with 'audiobooker review-export', an inline "
                "[character] override, or by casting the missing speakers."
            )

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
    # CLIUX-H-004: a component the machine CANNOT RENDER without. The voice
    # engine and ffmpeg were both recorded as `status: "info"` and never
    # touched `all_ok`, so a fresh box with neither printed two INFO lines and
    # then "All checks passed." with exit 0 — a green light for a machine that
    # cannot produce a single second of audio. Readiness is now its own
    # verdict, and it gates the exit code.
    missing_required: list[str] = []

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
        missing_required.append("Python 3.10+")

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
        missing_required.append("ebooklib")

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
                "hint": "pip install pymupdf - required for PDF sources",
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
                "hint": "pip install python-docx - required for DOCX sources "
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
        voice_engine_ok = True
    except ImportError:
        checks.append(
            {
                "check": "voice_engine",
                "status": "info",
                "value": "not installed",
                "hint": VOICE_SOUNDBOARD_INSTALL_HINT,
            }
        )
        # CLIUX-H-004: "info" is the right severity for the CHECK (a pluggable
        # engine may supply the voices instead), but there is nothing to
        # synthesize with until something does, so it still gates readiness.
        voice_engine_ok = False
        missing_required.append("voice engine (voice-soundboard)")
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
        voice_engine_ok = False
        missing_required.append("voice engine (voice-soundboard)")

    # ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        checks.append(
            {"check": "ffmpeg", "status": "ok", "value": ffmpeg_path, "hint": None}
        )
        ffmpeg_ok = True
    else:
        checks.append(
            {
                "check": "ffmpeg",
                "status": "info",
                "value": "not found",
                "hint": "REQUIRED: every book format is assembled with ffmpeg "
                        "(m4b is the default, and even a multi-chapter WAV is "
                        "concatenated by it). https://ffmpeg.org/download.html",
            }
        )
        ffmpeg_ok = False
        missing_required.append("ffmpeg")

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

    # CLIUX-H-004: which output formats this machine can actually produce.
    # Nothing is synthesizable without a voice engine, and every book format —
    # m4b, mp3 and even a multi-chapter WAV — is assembled by ffmpeg
    # (concatenate_audio_files raises without it), so the set is all-or-nothing.
    if voice_engine_ok and ffmpeg_ok:
        reachable_formats = list(audio_formats.BOOK_FORMATS)
    else:
        reachable_formats = []

    ready = not missing_required

    if getattr(args, "json_output", False):
        print(json_mod.dumps(
            {
                "ok": all_ok,
                "ready": ready,
                "missing_required": missing_required,
                "reachable_formats": reachable_formats,
                "checks": checks,
            },
            indent=2,
        ))
    else:
        print(f"audiobooker v{__version__} - environment diagnostics\n")
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
        if ready:
            print("Ready to render.")
            print(f"  Output formats available: {', '.join(reachable_formats)}")
        else:
            print(
                f"NOT ready to render - {len(missing_required)} required "
                f"component(s) missing: {', '.join(missing_required)}"
            )
            if reachable_formats:
                print(
                    f"  Output formats available: {', '.join(reachable_formats)}"
                )
            elif voice_engine_ok:
                print(
                    "  Output formats available: none - 'render -c N' can still "
                    "write a single-chapter WAV, but no book can be assembled."
                )
            else:
                print(
                    "  Output formats available: none - no audio can be "
                    "synthesized at all."
                )
            print("  See the hints above for each missing component.")
        if not all_ok:
            print("Some checks failed. See hints above.")

    return 0 if (all_ok and ready) else 1


def _resolve_project_path(source: Path) -> Path:
    """Where `make`/`batch` will write the project file for ``source``.

    A directory source has no file suffix to swap, so the project file goes
    beside the folder.
    """
    if source.is_dir():
        return source.parent / f"{source.name}.audiobooker"
    return source.with_suffix(".audiobooker")


def _project_at_risk(path: Path) -> str:
    """Describe the hand work an overwrite of ``path`` would destroy.

    CLIUX-C-001: "this file exists" is not a warning a user can act on. The
    casting table and the pronunciation lexicon are the two things nobody
    wants to redo, and both are one JSON read away.
    """
    try:
        import json as _json

        data = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "an existing project file (unreadable - inspect it before overwriting)"

    config = data.get("config") or {}
    characters = (data.get("casting") or {}).get("characters") or {}
    lexicon = config.get("pronunciation_overrides") or {}
    phonemes = config.get("phoneme_overrides") or {}
    title = data.get("title") or "(untitled)"
    return (
        f'"{title}" - {len(characters)} cast voice(s), '
        f"{len(lexicon) + len(phonemes)} pronunciation override(s), "
        f"{len(data.get('chapters') or [])} chapter(s)"
    )


def _refuse_project_overwrite(project_path: Path, command_label: str) -> None:
    """Print the refusal for CLIUX-C-001 — with both real paths forward."""
    _err(f"  Refusing to overwrite an existing project: {project_path}")
    _err(f"    At risk: {_project_at_risk(project_path)}")
    _err(
        f"    `{command_label}` re-parses and auto-casts the book from scratch, "
        "replacing every one of those."
    )
    _err(f"    To re-render what you already have: audiobooker render -p {project_path}")
    _err("    To discard it and start over:        add --overwrite-project")


def _discard_staged_project(staged_path: "Path | None") -> None:
    """Remove a staged project file left behind by a failed render."""
    if staged_path is None:
        return
    try:
        staged_path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort cleanup
        pass


def _process_book(
    source: Path,
    *,
    fmt: Optional[str],
    jobs: int,
    lang: str,
    overrides: Optional[dict] = None,
    render_overrides: Optional[dict] = None,
    output_path: Optional[Path] = None,
    emotion_preset: Optional[str] = None,
    engine=None,
    chapter_delimiter: Optional[str] = None,
    force_text: bool = False,
    overwrite_project: bool = False,
    dry_run: bool = False,
    review: bool = False,
    phase_log: bool = True,
    label: str = "make",
) -> dict:
    """Create + compile + auto-cast + render a single source file.

    This is the canonical per-book sequence shared by `batch` (FT-RENDER-012)
    and `make` (FT-CLI-001) so both run byte-for-byte identical steps:
    config-file merge -> source factory -> config sections -> compile ->
    auto-cast (VoiceSuggester top suggestion) -> save -> render_project.

    Args:
        source: Source file or chapter folder.
        fmt: Output format (m4b/mp3/wav), or None when the user did not pass
            --format — CLI-6: the built-in default is resolved AFTER the
            config-file merge so a config saying ``format = "mp3"`` is not
            clobbered by argparse's default.
        jobs: Parallel render workers.
        lang: Language code.
        overrides: Optional manifest-style per-book metadata (title/author/
            cover/series/series_index/cast) applied on top of config-file
            sections.
        render_overrides: Extra render_project kwargs (cover_art/normalize/
            output_profile/bitrate) — used by `make` for --cover/--acx/etc.
        output_path: Explicit output audio path (default derives from title).
        chapter_delimiter: CLI-4 — custom chapter-split regex for TXT/MD
            sources. `make`/`batch` advertise --chapter-delimiter; before this
            it was parsed and dropped on the floor, so the default heuristic
            ran instead.
        force_text: CLI-4 — force plain-text extraction for image-only PDFs.
            `make --force-text` is the documented remedy for scanned PDFs; it
            was likewise parsed and never passed to from_pdf, so the user
            burned a whole render to discover the book was empty.
        overwrite_project: CLIUX-C-001 — permit replacing an existing
            ``.audiobooker`` file. Even then the replacement is STAGED and
            only moved into place once the render returns.
        dry_run: CLIUX-C-001 — resolve everything (project path, cast,
            output) and report it without writing or rendering anything.
        review: FEAT-UX-003 — stop after compile + auto-cast, save the
            project, write the review file and report the import command.
            `make` was the one path in the CLI that could not review, so the
            choice was one command with no review or nine commands with it.
        phase_log: FEAT-UX-003 — narrate each phase. On a 40-chapter novel
            `make` printed TWO lines before ffmpeg — no parse, no chapter
            count, no compile, no attribution rate, no cast — while the
            staged commands print all of it for the same work. `batch
            --json` passes False so the phase lines cannot land in the
            payload stream.
        label: the command name to quote back in the refusal message.

    Returns:
        A result dict: {file, name, status, output, error, duration_s}.
        ``status`` is one of success / partial / failed / error / skipped /
        refused / dry_run / review. Never raises — render/parse errors are
        captured into the dict.
    """
    import os as _os
    import time as _time
    from audiobooker import AudiobookProject
    from audiobooker.project import _sanitize_filename
    from audiobooker.renderer.engine import RenderError, render_project

    overrides = overrides or {}
    render_overrides = render_overrides or {}

    # --review stops after the save, so it has four phases, not five.
    total_phases = 4 if review else 5

    def _phase(step: Optional[int], message: str) -> None:
        """FEAT-UX-003: narrate one phase of the sequence (or a detail line)."""
        if not phase_log:
            return
        _out(f"[{step}/{total_phases}] {message}" if step else f"      {message}")

    book_start = _time.time()
    book_result = {
        "file": str(source),
        "name": source.stem,
        "status": "unknown",
        "output": "",
        "error": "",
        "duration_s": 0.0,
    }

    # CLIUX-C-001: resolve the destination BEFORE parsing, so a refusal costs
    # nothing. `make`/`batch` computed this at step 4 and called
    # project.save() on it with no existence check at all, so a project with
    # hand-cast voices, a pronunciation lexicon and edited chapter titles was
    # replaced by a fresh auto-cast parse — and `batch *.epub` did it to every
    # project in the directory.
    project_path = _resolve_project_path(source)
    staged_path: Optional[Path] = None

    if project_path.exists() and not overwrite_project and not dry_run:
        _refuse_project_overwrite(project_path, label)
        book_result["status"] = "refused"
        book_result["error"] = (
            f"project already exists: {project_path} (re-render it with "
            "`audiobooker render -p`, or pass --overwrite-project)"
        )
        book_result["duration_s"] = _time.time() - book_start
        return book_result

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

        # CLI-4: manifest entries may carry the same two input knobs.
        entry_delimiter = overrides.get("chapter_delimiter") or chapter_delimiter
        entry_force_text = bool(overrides.get("force_text") or force_text)

        suffix = source.suffix.lower()
        if source.is_dir():
            project = AudiobookProject.from_folder(source, config=config)
        elif suffix == ".epub":
            project = AudiobookProject.from_epub(source, config=config)
        elif suffix == ".docx":
            project = AudiobookProject.from_docx(source, config=config)
        elif suffix == ".pdf":
            project = AudiobookProject.from_pdf(
                source, config=config, force_text=entry_force_text
            )
        elif suffix in (".txt", ".md", ".markdown"):
            project = AudiobookProject.from_text(
                source, config=config, chapter_delimiter=entry_delimiter
            )
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

        _phase(
            1,
            f"Parsed {project.title!r} - {len(project.chapters)} chapter(s), "
            f"~{project.total_words:,} words",
        )

        # Step 2: Compile
        _phase(2, f"Compiling {len(project.chapters)} chapter(s)...")
        project.compile()

        total_utterances = sum(len(c.utterances) for c in project.chapters)
        from audiobooker.casting import compile_report
        quality_report = compile_report(project.chapters, project.casting)
        if quality_report["total_dialogue"] > 0:
            _phase(
                None,
                f"Compiled {total_utterances} utterance(s); dialogue "
                f"attribution {quality_report['total_dialogue_unknown']}/"
                f"{quality_report['total_dialogue']} unattributed "
                f"({quality_report['dialogue_unknown_rate']:.0%}, "
                f"{quality_report['quality']})",
            )
        else:
            _phase(None, f"Compiled {total_utterances} utterance(s) (no dialogue)")

        # Step 3: Auto-cast with suggestions
        uncast = project.get_uncast_speakers()
        _phase(3, f"Auto-casting {len(uncast)} uncast speaker(s)...")
        if uncast:
            try:
                # FEAT-UX-002 sibling fix: the same evidence cast-suggest
                # shows. This call omitted speaker_utterances too.
                for sr in _suggest_voices(project, uncast, max_suggestions=1):
                    if sr.top:
                        project.cast(sr.speaker, sr.top.voice_id)
                        _phase(None, f"Cast {sr.speaker} as {sr.top.voice_id}")
            except Exception as cast_err:
                _out(f"  Warning: Auto-cast failed ({cast_err}), using fallback voices")

        # CLI-6: `fmt` is None when the user did not type --format, so the
        # config-file value (already merged into project.config.output_format)
        # wins over the built-in default. Resolved before the save so
        # --dry-run can report the real output path.
        out_fmt = overrides.get("format") or fmt or project.config.output_format
        if output_path is not None:
            final_output = Path(output_path)
        else:
            final_output = source.parent / f"{_sanitize_filename(project.title)}.{out_fmt}"

        # CLIUX-C-001: --dry-run reports the whole resolved plan and stops
        # before the first write. `batch`, `compile` and `render` all had one;
        # `make` — the command that silently destroyed projects — did not.
        if dry_run:
            _out(f"DRY RUN - nothing written, nothing rendered ({label}).")
            _out(f"  Source:       {source}")
            _out(f"  Project file: {project_path}")
            if project_path.exists():
                _out(f"                EXISTS - {_project_at_risk(project_path)}")
                _out(
                    "                It would be REPLACED (only with "
                    "--overwrite-project)."
                )
            else:
                _out("                does not exist yet - would be created")
            _out(f"  Output:       {final_output}")
            _out(f"  Format:       {out_fmt}")
            mapping = project.casting.get_voice_mapping()
            if mapping:
                _out(f"  Cast that would be applied ({len(mapping)}):")
                for speaker, voice in sorted(mapping.items()):
                    _out(f"    {speaker}: {voice}")
            else:
                _out("  Cast that would be applied: (none detected)")
            book_result["status"] = "dry_run"
            book_result["output"] = str(final_output)
            book_result["duration_s"] = _time.time() - book_start
            return book_result

        # FEAT-UX-003: --review stops here. There is no render to protect
        # the project from, so it is committed straight to project_path
        # (the overwrite guard at the top of this function has already
        # decided whether that is allowed) and the review file goes beside
        # it under the project's own stem — the same default `review-export`
        # uses, so the printed import command is one pasteable token.
        if review:
            _phase(4, f"Saving project to {project_path}...")
            project.save(project_path)
            review_path = project.export_for_review(
                project_path.with_name(f"{project_path.stem}_review.txt")
            )
            project.save(project_path)
            _phase(None, f"Review file written (nothing rendered): {review_path}")
            _out(
                "\nEdit the speakers and emotions, then import and render:\n"
                f"  audiobooker review-import {_quote_arg(review_path.name)} "
                f"-p {_quote_arg(project_path)}\n"
                f"  audiobooker render -p {_quote_arg(project_path)}"
            )
            book_result["status"] = "review"
            book_result["output"] = str(review_path)
            book_result["duration_s"] = _time.time() - book_start
            return book_result

        # Step 4: Save project.
        #
        # CLIUX-C-001: the ORDERING is the finding. Save was step 4 and render
        # step 5, so a run that replaced a hand-tuned project and then died at
        # ffmpeg left the user with no audiobook AND no project. A replacement
        # is therefore written BESIDE the original and only moved into place
        # once render_project has returned. If nothing is there to lose, write
        # straight to the destination.
        _phase(4, "Saving project...")
        if project_path.exists():
            staged_path = project_path.with_name(project_path.name + ".new")
            _discard_staged_project(staged_path)
            project.save(staged_path)
        else:
            project.save(project_path)

        # Step 5: Render.
        _phase(5, f"Rendering {len(project.chapters)} chapter(s) to {final_output}...")

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
        # FT-ENGINE-001: pass the resolved engine through when one was selected
        # (--engine on batch/make). None keeps the default voice-soundboard path.
        if engine is not None:
            render_kwargs["engine"] = engine
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

        # CLIUX-C-001: the render returned, so the replacement has earned its
        # place. os.replace is atomic, so there is no window in which neither
        # project exists.
        if staged_path is not None:
            _os.replace(str(staged_path), str(project_path))
            project.project_path = project_path
            staged_path = None

        # The render either produced the whole book or it did not. Recording
        # "success" unconditionally here is what let an incomplete render
        # (chapters dropped under allow_partial) reach the batch summary,
        # the --json payload and the exit code as a finished book.
        partial = _render_incompleteness(path)
        if partial is not None:
            book_result["status"] = "partial"
            book_result["error"] = _partial_render_message(partial)[:200]
        else:
            book_result["status"] = "success"
        book_result["output"] = str(path)
        book_result["duration_s"] = _time.time() - book_start

    except RenderError as e:
        # CLIUX-C-001: the render failed, so the staged replacement never
        # earned its place — drop it and leave the user's project exactly as
        # they left it.
        _discard_staged_project(staged_path)
        book_result["status"] = "failed"
        book_result["error"] = str(e)[:200]
        book_result["duration_s"] = _time.time() - book_start

    except Exception as e:
        _discard_staged_project(staged_path)
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
            _err(f"WARNING: ignoring non-integer series_index: {overrides['series_index']!r}")
    if overrides.get("year") is not None:
        try:
            meta.year = int(overrides["year"])
        except (TypeError, ValueError):
            _err(f"WARNING: ignoring non-integer year: {overrides['year']!r}")
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
            _err(f"WARNING: cover art not found, skipping: {cover_path}")

    cast_ref = overrides.get("cast")
    if cast_ref:
        cast_path = Path(cast_ref)
        if not cast_path.is_absolute():
            cast_path = base_dir / cast_path
        try:
            project.import_casting(cast_path)
        except (FileNotFoundError, ValueError) as e:
            _err(f"WARNING: could not import casting from manifest ({e})")


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

    # CLI-6: None when --format was not typed, so each book's config file wins
    # over argparse's default (_process_book resolves the built-in fallback).
    fmt = getattr(args, "output_format", None)
    jobs = getattr(args, "jobs", 1)
    lang = getattr(args, "lang", "en")
    # FT-ENGINE-001: resolve --engine once for the whole batch (explicit name
    # only; each book's project config could override but batch is a fleet op).
    batch_engine = _resolve_engine(args)
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
        _out(f"DRY RUN - {len(book_specs)} book(s) would be processed:\n")
        for i, (source, ov) in enumerate(book_specs, 1):
            label = ov.get("title") or source.name
            _out(f"  [{i}/{len(book_specs)}] {label} ({source})")
            # CLIUX-C-001: name the project file each book would write and
            # whether something is already there — the dry run existed but
            # never mentioned the file `batch` was about to overwrite.
            target = _resolve_project_path(source)
            if target.exists():
                _out(f"        project: {target} - EXISTS, would be REFUSED")
                _out(f"                 {_project_at_risk(target)}")
            else:
                _out(f"        project: {target} (new)")
        _out(f"\nFormat: {fmt or 'from config (default m4b)'}")
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
            engine=batch_engine,
            # CLIUX-C-001: `batch *.epub` overwrote EVERY project in the
            # directory. Refuse by default here too.
            overwrite_project=bool(getattr(args, "overwrite_project", False)),
            # FEAT-UX-003: phase lines are stdout chatter, and under --json
            # stdout is the payload stream.
            phase_log=not json_output,
            label="batch",
        )
        status = book_result["status"]
        if status == "success":
            _out(f"  OK: {book_result['output']} ({book_result['duration_s']:.1f}s)")
        elif status == "partial":
            _out(
                f"  PARTIAL: {book_result['output']} "
                f"({book_result['duration_s']:.1f}s) - {book_result['error']}"
            )
        elif status == "failed":
            _out(f"  FAILED: {book_result['error']}")
        elif status == "refused":
            # The refusal detail was already printed by _process_book.
            _out("  REFUSED: existing project left untouched")
        elif status == "skipped":
            _out(f"  Skipped: {book_result['error']}")
        else:
            _out(f"  ERROR: {book_result['error']}")
        results.append(book_result)

    # Summary
    total_elapsed = _time.time() - batch_start
    success = sum(1 for r in results if r["status"] == "success")
    # A book whose render dropped chapters is NOT a success — it gets its own
    # bucket so the count, the payload and the exit code all tell the truth.
    partial = sum(1 for r in results if r["status"] == "partial")
    # CLIUX-C-001: a refusal produced NO audiobook, so it can never leave the
    # exit code at 0 — but it is not a crash either, so it gets its own count.
    refused = sum(1 for r in results if r["status"] == "refused")
    failed = sum(1 for r in results if r["status"] in ("failed", "error")) + refused
    skipped = sum(1 for r in results if r["status"] == "skipped")

    # --json: emit the results array (machine-readable) instead of the table.
    if json_output:
        import json as json_mod
        print(json_mod.dumps(
            {
                "succeeded": success,
                "partial": partial,
                "failed": failed,
                "refused": refused,
                "skipped": skipped,
                "total_elapsed_s": round(total_elapsed, 2),
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ))
        if failed == 0 and partial == 0:
            return 0
        return 3 if (success or partial) else 1

    def _fmt_duration(s: float) -> str:
        if s >= 3600:
            return f"{s / 3600:.1f}h"
        elif s >= 60:
            return f"{s / 60:.1f}m"
        return f"{s:.1f}s"

    _out(f"\n{'='*72}")
    _out(
        f"  BATCH SUMMARY - {success} succeeded, {partial} partial, "
        f"{failed} failed ({refused} refused), {skipped} skipped"
    )
    _out(f"  Total elapsed: {_fmt_duration(total_elapsed)}")
    _out(f"{'='*72}")
    _out(f"  {'#':<4} {'Status':<10} {'Duration':<10} {'Title':<28} {'Output'}")
    _out(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*28} {'-'*20}")
    for idx, r in enumerate(results, 1):
        status = r["status"].upper()
        dur = _fmt_duration(r["duration_s"])
        name = r["name"][:27]
        if r["status"] in ("success", "partial"):
            out = r["output"]
        else:
            out = r.get("error", "")[:40]
        _out(f"  {idx:<4} {status:<10} {dur:<10} {name:<28} {out}")
    _out(f"{'='*72}")

    if failed == 0 and partial == 0:
        return 0
    elif success > 0 or partial > 0:
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
    # CLI-6: pass None through when --format was not typed so the config file
    # (not argparse's default) supplies it; _process_book resolves the default.
    fmt = getattr(args, "output_format", None)
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
    # FT-ENGINE-001: resolve --engine before the project exists (make creates
    # it); explicit name only, since there is no project config to fall back to.
    engine = _resolve_engine(args)
    return _process_book(
        source,
        fmt=fmt,
        jobs=jobs,
        lang=lang,
        render_overrides=render_overrides,
        output_path=Path(output_path) if output_path else None,
        emotion_preset=getattr(args, "emotion_preset", None),
        engine=engine,
        # CLI-4: both were advertised in `make --help` and silently dropped.
        chapter_delimiter=getattr(args, "chapter_delimiter", None),
        force_text=bool(getattr(args, "force_text", False)),
        # CLIUX-C-001: refuse by default, stage the replacement when allowed.
        overwrite_project=bool(getattr(args, "overwrite_project", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        # FEAT-UX-003: stop after compile + cast and write the review file.
        review=bool(getattr(args, "review", False)),
        label="make",
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
        _err(f"Error: Source file not found: {source}")
        return 1

    # FT-CLI-008: watch mode — re-run make whenever the source mtime changes.
    if getattr(args, "watch", False):
        return _watch_loop(source, lambda: _make_summary(_run_make_once(args)))

    return _make_summary(_run_make_once(args))


def _make_summary(book_result: dict) -> int:
    """Print a single-book make result and return the process exit code."""
    status = book_result["status"]
    if status == "dry_run":
        # CLIUX-C-001: _process_book already printed the whole plan.
        return 0
    if status == "review":
        # FEAT-UX-003: _process_book already printed the review file path
        # and the two commands that follow it.
        return 0
    if status == "refused":
        # CLIUX-C-001: _process_book already printed the refusal and both
        # paths forward; do not paper over it with "Make failed:".
        return 1
    if status == "success":
        _out(f"\nAudiobook created: {book_result['output']}")
        _out(f"  Source: {book_result['file']}")
        _out(f"  Elapsed: {book_result['duration_s']:.1f}s")
        return 0
    if status == "partial":
        # The file exists but is short some chapters — say so, and exit 3
        # (the documented partial code) rather than claiming success.
        _err(f"\nAudiobook assembled INCOMPLETE: {book_result['output']}")
        _err(f"  {book_result['error']}")
        _err(f"  Source: {book_result['file']}")
        _err(f"Hint: {_PARTIAL_RENDER_HINT}")
        return 3
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
                _out(f"\nChange detected in {source.name} - re-rendering...")
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
            _err(f"Error: Chapter {chapter_idx} not found (only {len(project.chapters)} chapters)")
            return 1

        chapter = project.chapters[chapter_idx]

        # Compile if needed
        if not chapter.is_compiled:
            _out("Compiling chapter...")
            project.compile()
            project.save()
            chapter = project.chapters[chapter_idx]

        if not chapter.utterances:
            _err(f"Error: Chapter {chapter_idx} has no utterances after compilation")
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

        # FT-ENGINE-001: render through the resolved engine when one is selected.
        tts_engine = _resolve_engine(args, project)
        render_kwargs = {"engine": tts_engine} if tts_engine is not None else {}
        path = render_chapter(
            preview_chapter,
            project.casting,
            output_path,
            **render_kwargs,
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
            # Residual 4: an error line printed with a bare print() bypasses
            # the _err chokepoint and lands in a piped stdout.
            _err(
                f"Error: Chapter {from_chapter} not found "
                f"(project has {len(project.chapters)} chapters)",
                args=args,
            )
            return 1

        _out(f"Rendering sample from chapter {from_chapter}...")
        _out(f"  Start: {start_seconds:.0f}s  Duration: {duration:.0f}s  Profile: {output_profile}")

        # FT-ENGINE-001: render through the resolved engine when one is selected.
        tts_engine = _resolve_engine(args, project)
        sample_kwargs = {"engine": tts_engine} if tts_engine is not None else {}
        path = render_sample(
            project,
            from_chapter=from_chapter,
            start_seconds=start_seconds,
            duration=duration,
            output_path=Path(output) if output else None,
            output_profile=output_profile,
            bitrate=bitrate,
            **sample_kwargs,
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
            _err(f"Error: Audio file not found: {file_path}", args=args)
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
                "\nResult: PASS - meets ACX's measurable loudness, peak, and "
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

        # CLIUX-H-009: nothing checked that anything had been RENDERED. An
        # unrendered chapter has duration_seconds == 0, so every marker
        # collapsed onto the inter-chapter pause: a compiled-but-unrendered
        # project produced a CUE sheet with track 2 at 00:02:00 and exit 0.
        # Refuse the same way cmd_podcast already does, and name the gaps when
        # only some chapters are missing.
        unrendered = [title for title, duration in chapters_data if not (duration or 0) > 0]
        if chapters_data and len(unrendered) == len(chapters_data):
            _err(
                "Error: no chapter has rendered audio - every duration is 0, so "
                "every marker would land on the same timestamp.",
                args=args,
            )
            _err(
                "Hint: render the book first (audiobooker render), then export "
                "the markers.",
                args=args,
            )
            return 1
        if unrendered:
            _err(
                f"\nWARNING: {len(unrendered)} chapter(s) have no rendered audio; "
                "their markers will have zero length and every marker after them "
                "will be early:",
                args=args,
            )
            for title in unrendered:
                _err(f"  - {title}", args=args)
            _err(
                "Hint: render the whole book (audiobooker render) before "
                "exporting markers for distribution.",
                args=args,
            )

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


def cmd_podcast(args) -> int:
    """
    FT-RENDER-M-008: Render one file per chapter and write a podcast RSS feed.

    Sequence:
      1. Render the project with split=True so each chapter is its own audio
         file (skipped with --no-render, which builds the feed from chapters
         already rendered).
      2. Build a per-chapter ``items`` list (title, filename, duration_seconds)
         from the rendered chapters.
      3. Call output.export_podcast_rss(project, items, base_url=...) and write
         the iTunes RSS 2.0 XML to podcast.xml (or -o).

    Flags: --base-url (prepended to each enclosure URL), -o (output XML path),
    --format (per-chapter audio format), -j/--jobs, --no-render, --engine.
    """
    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import RenderError
    from audiobooker.renderer.output import export_podcast_rss

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        base_url = getattr(args, "base_url", "") or ""
        no_render = getattr(args, "no_render", False)
        fmt = getattr(args, "output_format", None) or project.config.output_format

        if not no_render:
            # FT-ENGINE-001: resolve the TTS engine (explicit --engine >
            # project config > default). None keeps current behavior.
            tts_engine = _resolve_engine(args, project)

            # Ensure compiled before a split render.
            uncompiled = [c for c in project.chapters if not c.is_compiled and not c.skip]
            if uncompiled:
                _out("Compiling chapters...")
                project.compile()
                project.save()

            _out(f"Rendering {len(project.chapters)} chapter file(s) ({fmt})...")
            render_kwargs = dict(
                resume=True,
                jobs=getattr(args, "jobs", 1),
                force=True,
                output_format=fmt,
                split=True,
            )
            if tts_engine is not None:
                render_kwargs["engine"] = tts_engine
            project.render(**render_kwargs)
            project.save()

        # Build per-chapter feed items from rendered chapter audio.
        items = []
        for ch in project.chapters:
            if getattr(ch, "skip", False):
                continue
            audio = getattr(ch, "audio_path", None)
            filename = Path(audio).name if audio else ""
            items.append({
                "index": ch.index,
                "title": ch.title,
                "filename": filename,
                "duration_seconds": ch.duration_seconds,
            })

        if not any(item["filename"] for item in items):
            print(
                "Error: no rendered chapter audio found. Run the podcast command "
                "without --no-render, or render the chapters first."
            )
            return 1

        # output.export_podcast_rss is a pure string builder (renderer-owned).
        rss = export_podcast_rss(project, items, base_url=base_url)

        out_path = Path(getattr(args, "output", None) or "podcast.xml")
        out_path.write_text(rss, encoding="utf-8")

        episode_count = sum(1 for item in items if item["filename"])
        _out(f"\nPodcast feed written: {out_path}")
        _out(f"  Episodes: {episode_count}")
        if base_url:
            _out(f"  Base URL: {base_url}")
        return 0

    except RenderError as e:
        _print_render_failure(e)
        return 1

    except USER_ERROR_TYPES as e:
        _report_error(e, args)
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    # FEAT-IN-001: first thing, before anything can print. A book title the
    # console cannot encode must not be able to kill the command that just
    # succeeded. See _configure_output_encoding().
    _configure_output_encoding()

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
        "podcast": cmd_podcast,
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
