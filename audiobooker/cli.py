"""
Command-Line Interface for Audiobooker.

Usage:
    audiobooker new book.epub              # Create project from EPUB
    audiobooker new book.pdf               # Create project from PDF
    audiobooker new book.txt               # Create project from text
    audiobooker cast narrator af_bella     # Assign voice to character
    audiobooker cast-export cast.json      # Export casting table
    audiobooker cast-import cast.json      # Import casting table
    audiobooker compile                    # Compile chapters to utterances
    audiobooker compile --dry-run          # Preview speaker/line summary
    audiobooker render                     # Render audiobook
    audiobooker render --dry-run           # Preview render without executing
    audiobooker render --cover cover.jpg   # Render with cover art
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
    audiobooker status                     # Show render/cache status
    audiobooker cache info                 # Show cache statistics
    audiobooker cache clean                # Delete all cached audio
    audiobooker cache clean-failed         # Reset failed cache entries
    audiobooker info                       # Show project info
    audiobooker voices                     # List available voices
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audiobooker.renderer.engine import RenderError
from pathlib import Path
from typing import Optional


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

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- new ---
    new_parser = subparsers.add_parser(
        "new", help="Create new project from source file"
    )
    new_parser.add_argument("source", help="Source file (EPUB, TXT, MD, PDF)")
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

    # --- load ---
    load_parser = subparsers.add_parser("load", help="Load existing project")
    load_parser.add_argument("project", help="Project file (.audiobooker)")

    # --- cast ---
    cast_parser = subparsers.add_parser("cast", help="Assign voice to character")
    cast_parser.add_argument("character", help="Character name")
    cast_parser.add_argument("voice", help="Voice ID (e.g., af_bella, bm_george)")
    cast_parser.add_argument("-e", "--emotion", help="Default emotion")
    cast_parser.add_argument("-d", "--description", help="Character description")
    cast_parser.add_argument(
        "-p", "--project", help="Project file (auto-detected if omitted)"
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

    # --- info ---
    info_parser = subparsers.add_parser("info", help="Show project information")
    info_parser.add_argument("-p", "--project", help="Project file")
    info_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed info"
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
        help="Batch process multiple source files (EPUB/TXT/PDF)",
    )
    batch_parser.add_argument(
        "files",
        nargs="+",
        help="Source files or glob patterns (e.g. '*.epub')",
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

    # --- cast-export ---
    cast_export_parser = subparsers.add_parser(
        "cast-export", help="Export casting table to JSON file"
    )
    cast_export_parser.add_argument("path", help="Output JSON file path")
    cast_export_parser.add_argument("-p", "--project", help="Project file")

    # --- cast-import ---
    cast_import_parser = subparsers.add_parser(
        "cast-import", help="Import casting table from JSON file"
    )
    cast_import_parser.add_argument("path", help="Input JSON file path")
    cast_import_parser.add_argument("-p", "--project", help="Project file")

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

    return parser


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


def cmd_new(args) -> int:
    """Create new project from source file."""
    from audiobooker import AudiobookProject

    source = Path(args.source)
    if not source.exists():
        print(f"Error: Source file not found: {source}")
        return 1

    suffix = source.suffix.lower()

    print(f"Creating project from: {source}")

    try:
        from audiobooker.language.profile import get_profile, available_profiles
        from audiobooker.models import ProjectConfig

        lang = getattr(args, "lang", "en")
        try:
            get_profile(lang)
        except ValueError:
            print(f"Error: Unsupported language: {lang!r}")
            print(f"Available: {', '.join(available_profiles())}")
            return 1

        booknlp_mode = getattr(args, "booknlp", "auto")
        config = ProjectConfig(language_code=lang, booknlp_mode=booknlp_mode)

        if suffix == ".epub":
            project = AudiobookProject.from_epub(source, config=config)
        elif suffix == ".pdf":
            project = AudiobookProject.from_pdf(source, config=config)
        elif suffix in (".txt", ".md", ".markdown"):
            project = AudiobookProject.from_text(source, config=config)
        else:
            print(f"Error: Unsupported file format: {suffix}")
            print("Supported: .epub, .txt, .md, .pdf")
            return 1

        # Save project
        output_path = args.output or source.with_suffix(".audiobooker")
        project.save(output_path)

        print(f"\nProject created: {output_path}")
        print(f"  Title: {project.title}")
        print(f"  Chapters: {len(project.chapters)}")
        print(f"  Words: ~{project.total_words:,}")
        print(
            f"  Estimated duration: ~{project.estimated_duration_minutes:.0f} min (at {project.config.estimated_wpm} wpm, varies by voice)"
        )
        print("\nNext steps:")
        print("  1. Cast voices: audiobooker cast narrator af_heart")
        print("  2. Compile: audiobooker compile")
        print("  3. Render: audiobooker render")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_cast(args) -> int:
    """Assign voice to character."""
    from audiobooker import AudiobookProject

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

        print(f"Cast {args.character} as {args.voice}")
        if args.emotion:
            print(f"  Default emotion: {args.emotion}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_compile(args) -> int:
    """Compile chapters to utterances."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # --dry-run: compile in dry-run mode, print speaker summary table
        if getattr(args, "dry_run", False):
            dry_result = project.compile(dry_run=True)
            if dry_result is None:
                print("No chapters to compile.")
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

            print(f"\nDRY RUN — Compile preview for {project.title}")
            print(f"{'='*70}")
            print(f"  {'Speaker':<20} {'Lines':<8} {'Sample'}")
            print(f"  {'-'*20} {'-'*8} {'-'*40}")
            for speaker in sorted(speaker_stats.keys()):
                info = speaker_stats[speaker]
                sample = info["sample"]
                if len(sample) > 40:
                    sample = sample[:37] + "..."
                print(f"  {speaker:<20} {info['lines']:<8} {sample}")
            total = sum(s["lines"] for s in speaker_stats.values())
            print(f"  {'-'*20} {'-'*8}")
            print(f"  {'TOTAL':<20} {total:<8}")
            print(f"{'='*70}")
            return 0

        print(f"Compiling {len(project.chapters)} chapters...")

        def progress(current, total, title):
            print(f"  [{current}/{total}] {title}")

        project.compile(progress_callback=progress)
        project.save()

        # Show uncast speakers
        uncast = project.get_uncast_speakers()
        if uncast:
            print("\nDetected speakers without voice assignments:")
            for speaker in sorted(uncast):
                print(f"  - {speaker}")
            print("\nAssign voices with: audiobooker cast <speaker> <voice>")

        total_utterances = sum(len(c.utterances) for c in project.chapters)
        print(f"\nCompiled {total_utterances} utterances")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_render(args) -> int:
    """Render audiobook."""
    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import RenderError

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

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
                print(f"Cache cleared: {cache_dir}")
            else:
                print("No cache to clean.")

        # FT-RENDER-011: Auto-apply voice suggestions if --cast-suggest
        if getattr(args, "cast_suggest", False):
            from audiobooker.casting.voice_suggester import VoiceSuggester

            uncast = project.get_uncast_speakers()
            if uncast:
                print(f"Auto-casting {len(uncast)} uncast speakers...")
                already_cast = project.casting.get_voice_mapping()
                suggester = VoiceSuggester(max_suggestions=1)
                results = suggester.suggest_all(sorted(uncast), already_cast=already_cast)
                for result in results:
                    if result.top:
                        project.cast(result.speaker, result.top.voice_id)
                        print(f"  Cast {result.speaker} as {result.top.voice_id}")
                project.save()

        # FT-RENDER-017: Chapter selection filtering
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
            print(f"Chapter selection: {len(project.chapters)} of {original_count} chapters")

        if args.chapter is not None:
            # Render single chapter
            print(f"Rendering chapter {args.chapter}...")
            output = args.output or f"chapter_{args.chapter:03d}.wav"
            path = project.render_chapter(args.chapter, output)
            print(f"Output: {path}")
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

            # FT-RENDER-004: Dry-run mode
            if getattr(args, "dry_run", False):
                from audiobooker.renderer.engine import dry_run_render
                dry_run_render(project, resume=resume, from_chapter=from_chapter)
                return 0

            # FT-RENDER-018: Render time estimation
            total_words = sum(ch.word_count for ch in project.chapters)
            wpm = project.config.estimated_wpm or 150
            est_minutes = total_words / wpm
            if est_minutes >= 60:
                est_str = f"~{est_minutes / 60:.1f} hours"
            else:
                est_str = f"~{est_minutes:.0f} minutes"
            print(f"Estimated render time: {est_str} ({total_words:,} words)")

            print(f"Rendering audiobook to: {output}")
            if not resume:
                print("  (cache disabled — full re-render)")
            if jobs > 1:
                print(f"  (parallel rendering: {jobs} workers)")

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
                if cover:
                    # FT-RENDER-006: Call render_project directly to pass cover_art
                    from audiobooker.renderer.engine import render_project
                    # Ensure compiled
                    uncompiled = [c for c in project.chapters if not c.is_compiled and not c.skip]
                    if uncompiled:
                        project.compile()
                    path = render_project(
                        project,
                        Path(output),
                        progress_callback=progress,
                        resume=resume,
                        from_chapter=from_chapter,
                        allow_partial=allow_partial,
                        jobs=jobs,
                        force=force,
                        output_format=getattr(args, "output_format", None),
                        cover_art=cover,
                        normalize=normalize,
                    )
                else:
                    # Pass normalize via render_project directly when no cover
                    if normalize:
                        from audiobooker.renderer.engine import render_project
                        uncompiled = [c for c in project.chapters if not c.is_compiled and not c.skip]
                        if uncompiled:
                            project.compile()
                        path = render_project(
                            project,
                            Path(output),
                            progress_callback=progress,
                            resume=resume,
                            from_chapter=from_chapter,
                            allow_partial=allow_partial,
                            jobs=jobs,
                            force=force,
                            output_format=getattr(args, "output_format", None),
                            normalize=normalize,
                        )
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
                        )
            finally:
                if progress_bar is not None:
                    progress_bar.stop()

            project.save()

            print(f"\nAudiobook created: {path}")
            print(f"Duration: {project.total_duration_seconds / 60:.1f} minutes")

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
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        if getattr(args, "notify", False):
            _send_notification(
                title="Audiobooker",
                message=f"Render error: {e}",
            )
        return 1


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

    print("\nTo resume: audiobooker render")
    print("To force:  audiobooker render --no-resume")


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
        # Try BurntToast
        try:
            subprocess.run(
                [
                    "powershell", "-Command",
                    f'New-BurntToastNotification -Text "{title}", "{message}"',
                ],
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
        try:
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
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

        print(f"Title: {info['title']}")
        if info["author"]:
            print(f"Author: {info['author']}")
        print(f"Source: {info['source']}")
        print(f"Chapters: {info['chapters']}")
        print(f"Words: ~{info['total_words']:,}")
        print(
            f"Estimated duration: ~{info['estimated_duration_minutes']:.0f} min (varies by voice)"
        )
        print(f"Characters cast: {info['characters_cast']}")
        print(f"Compiled: {'Yes' if info['compiled'] else 'No'}")
        print(f"Rendered: {'Yes' if info['rendered'] else 'No'}")

        if info["uncast_speakers"]:
            print(f"\nUncast speakers: {', '.join(info['uncast_speakers'])}")

        if args.verbose and project.casting.characters:
            print("\nCasting:")
            for name, char in project.casting.characters.items():
                print(f"  {char.name}: {char.voice} ({char.line_count} lines)")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_voices(args) -> int:
    """List available voices."""
    try:
        from voice_soundboard.config import VOICES
    except ImportError:
        print("Error: voice-soundboard not installed")
        print("Install with: pip install -e F:/AI/voice-soundboard")
        return 1

    print("Available voices:\n")

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

        print(f"  {voice_id}")

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
            print(f"Merged chapters {args.start}-{args.end} into: {merged.title}")
            print(f"  New chapter count: {len(project.chapters)}")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

    elif chapters_command == "split":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            first, second = project.split_chapter(args.index, args.paragraph)
            project.save()
            print(f"Split chapter {args.index} at paragraph {args.paragraph}:")
            print(f"  [{first.index}] {first.title} ({first.word_count} words)")
            print(f"  [{second.index}] {second.title} ({second.word_count} words)")
            print(f"  New chapter count: {len(project.chapters)}")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

    elif chapters_command == "exclude":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            project.exclude_chapter(args.index)
            project.save()
            ch = project.chapters[args.index]
            print(f"Excluded chapter {args.index}: {ch.title}")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

    elif chapters_command == "include":
        try:
            project_path = find_project_file(args.project)
            project = AudiobookProject.load(project_path)
            project.include_chapter(args.index)
            project.save()
            ch = project.chapters[args.index]
            print(f"Included chapter {args.index}: {ch.title}")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

    # Default: list chapters
    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        print(f"Chapters in {project.title}:\n")

        for chapter in project.chapters:
            status = ""
            if chapter.skip:
                status = " [excluded]"
            elif chapter.is_rendered:
                status = " [rendered]"
            elif chapter.is_compiled:
                status = " [compiled]"

            print(
                f"  {chapter.index + 1}. {chapter.title} ({chapter.word_count} words){status}"
            )

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_speakers(args) -> int:
    """List detected speakers."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            print("Compiling to detect speakers...")
            project.compile()
            project.save()

        speakers = project.get_detected_speakers()
        cast_speakers = set(project.casting.characters.keys())

        print(f"Speakers in {project.title}:\n")

        for speaker in sorted(speakers):
            normalized = project.casting.normalize_key(speaker)
            if normalized in cast_speakers:
                char = project.casting.characters[normalized]
                print(f"  {speaker}: {char.voice} ({char.line_count} lines)")
            else:
                print(f"  {speaker}: [uncast]")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_review_export(args) -> int:
    """Export compiled script for human review."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        output = args.output
        if output:
            output = Path(output)

        print("Exporting review file...")

        review_path = project.export_for_review(output)
        project.save()

        # Count stats
        total_utterances = sum(len(c.utterances) for c in project.chapters)
        speakers = project.get_detected_speakers()

        print(f"\nReview file created: {review_path}")
        print(f"  Chapters: {len(project.chapters)}")
        print(f"  Utterances: {total_utterances}")
        print(f"  Speakers: {', '.join(sorted(speakers))}")
        print("\nEdit the file to:")
        print("  - Change speaker names: @OldName -> @NewName")
        print("  - Add/change emotions: @Name -> @Name (emotion)")
        print("  - Delete unwanted lines by removing the block")
        print(f"\nThen import: audiobooker review-import {review_path.name}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
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

        print(f"Importing review file: {review_path}")

        stats = project.import_reviewed(review_path)
        project.save()

        print("\nImport complete:")
        print(f"  Chapters updated: {stats['chapters_updated']}")
        print(f"  Utterances imported: {stats['utterances_imported']}")
        print(f"  Speakers: {', '.join(sorted(stats['speakers_found']))}")
        print("\nProject saved. Ready to render: audiobooker render")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
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
            print("Compiling to detect speakers...")
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

        print(f"Voice suggestions for {project.title}:\n")
        for result in results:
            cast_key = project.casting.normalize_key(result.speaker)
            is_cast = cast_key in project.casting.characters
            status = (
                f" (cast: {project.casting.characters[cast_key].voice})"
                if is_cast
                else " [uncast]"
            )
            print(f"  {result.speaker}{status}")
            for i, s in enumerate(result.suggestions):
                marker = ">>>" if i == 0 else "   "
                print(f"    {marker} {s.voice_id} (score: {s.score:.2f}) - {s.reason}")
            print()

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_cast_apply(args) -> int:
    """Auto-apply voice suggestions."""
    from audiobooker import AudiobookProject
    from audiobooker.casting.voice_suggester import VoiceSuggester

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if not getattr(args, "auto", False):
            print("Use --auto to apply top suggestions for all uncast speakers.")
            return 0

        # Compile if needed
        if not any(c.is_compiled for c in project.chapters):
            print("Compiling to detect speakers...")
            project.compile()

        uncast = project.get_uncast_speakers()
        if not uncast:
            print("All speakers are already cast.")
            return 0

        already_cast = project.casting.get_voice_mapping()
        suggester = VoiceSuggester(max_suggestions=1)
        results = suggester.suggest_all(sorted(uncast), already_cast=already_cast)

        applied = 0
        for result in results:
            if result.top:
                project.cast(result.speaker, result.top.voice_id)
                print(
                    f"  Cast {result.speaker} as {result.top.voice_id} ({result.top.reason})"
                )
                applied += 1

        project.save()
        print(f"\nApplied {applied} voice assignments.")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_cast_export(args) -> int:
    """Export casting table to JSON file."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        path = Path(args.path)
        project.export_casting(path)
        project.save()

        count = len(project.casting.characters)
        print(f"Exported {count} character(s) to {path}")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_cast_import(args) -> int:
    """Import casting table from JSON file."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        path = Path(args.path)
        project.import_casting(path)
        project.save()

        count = len(project.casting.characters)
        print(f"Imported casting table from {path}")
        print(f"  Total characters: {count}")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_emotions(args) -> int:
    """Emotion management commands."""
    from audiobooker import AudiobookProject

    emotions_command = getattr(args, "emotions_command", None)
    if emotions_command is None:
        print("Usage: audiobooker emotions {list|override}")
        return 1

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if emotions_command == "list":
            emotions = project.list_emotions()
            if not emotions:
                print("No compiled chapters with emotion data. Run compile first.")
                return 0

            print(f"Emotion summary for {project.title}:\n")
            for ch_idx in sorted(emotions.keys()):
                chapter = project.chapters[ch_idx]
                counts = emotions[ch_idx]
                total = sum(counts.values())
                emotion_parts = ", ".join(
                    f"{e}: {c}" for e, c in sorted(counts.items(), key=lambda x: -x[1])
                )
                print(f"  [{ch_idx}] {chapter.title} ({total} lines): {emotion_parts}")
            return 0

        elif emotions_command == "override":
            project.override_emotion(args.chapter, args.line, args.emotion)
            project.save()
            ch = project.chapters[args.chapter]
            utt = ch.utterances[args.line]
            print(
                f"Set emotion to '{args.emotion}' on chapter {args.chapter}, "
                f"line {args.line} (speaker: {utt.speaker})"
            )
            return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 1


def cmd_pronunciation(args) -> int:
    """Pronunciation override management."""
    from audiobooker import AudiobookProject

    pronunciation_command = getattr(args, "pronunciation_command", None)
    if pronunciation_command is None:
        print("Usage: audiobooker pronunciation {add|remove|list}")
        return 1

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        if pronunciation_command == "add":
            project.config.pronunciation_overrides[args.word] = args.replacement
            project.save()
            print(f"Added pronunciation override: '{args.word}' -> '{args.replacement}'")
            return 0

        elif pronunciation_command == "remove":
            if args.word in project.config.pronunciation_overrides:
                del project.config.pronunciation_overrides[args.word]
                project.save()
                print(f"Removed pronunciation override for '{args.word}'")
            else:
                print(f"No override found for '{args.word}'")
                # List existing ones for reference
                if project.config.pronunciation_overrides:
                    print("\nExisting overrides:")
                    for w, r in sorted(project.config.pronunciation_overrides.items()):
                        print(f"  '{w}' -> '{r}'")
            return 0

        elif pronunciation_command == "list":
            overrides = project.config.pronunciation_overrides
            if not overrides:
                print("No pronunciation overrides configured.")
                return 0
            print(f"Pronunciation overrides ({len(overrides)}):\n")
            for word, replacement in sorted(overrides.items()):
                print(f"  '{word}' -> '{replacement}'")
            return 0

    except Exception as e:
        print(f"Error: {e}")
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
        project = AudiobookProject.from_string(
            text,
            title=args.title,
            author=args.author,
            lang=args.lang,
        )

        output_path = args.output or f"{args.title}.audiobooker"
        project.save(output_path)

        print(f"Project created: {output_path}")
        print(f"  Title: {project.title}")
        print(f"  Chapters: {len(project.chapters)}")
        print(f"  Words: ~{project.total_words:,}")
        print(f"  Language: {args.lang}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
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

        print(f"Project: {project.title}")
        if project.author:
            print(f"Author:  {project.author}")
        print(f"Format:  {project.config.output_format}")
        print(f"Chapters: {len(project.chapters)}")
        total_words = sum(ch.word_count for ch in project.chapters)
        print(f"Words:   ~{total_words:,}")

        # Cache info
        cache_root = get_cache_root(project_path.parent)
        if not cache_root.exists():
            print("\nCache: not created yet (no renders)")
            return 0

        manifest_path = get_manifest_path(cache_root)
        manifest = load_manifest(manifest_path)

        ok_count = 0
        failed_count = 0
        last_render = ""
        if manifest:
            ok_count = len(manifest.ok_chapters())
            failed_count = len(manifest.failed_chapters())
            last_render = manifest.last_updated or "(unknown)"

        # Disk usage of cache dir
        total_size = 0
        for f in cache_root.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size

        if total_size >= 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024):.1f} MB"
        elif total_size >= 1024:
            size_str = f"{total_size / 1024:.1f} KB"
        else:
            size_str = f"{total_size} bytes"

        print(f"\nRender Cache: {cache_root}")
        print(f"  Rendered (cached): {ok_count}")
        print(f"  Failed:            {failed_count}")
        print(f"  Pending:           {len(project.chapters) - ok_count - failed_count}")
        print(f"  Disk usage:        {size_str}")
        if last_render:
            print(f"  Last render:       {last_render}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
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
                print("No cache directory found.")
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

            print(f"Cache directory: {cache_root}")
            print(f"  Files: {file_count}")
            print(f"  Total size: {size_str}")
            if manifest:
                print(f"  OK chapters: {len(manifest.ok_chapters())}")
                print(f"  Failed chapters: {len(manifest.failed_chapters())}")
                print(f"  Last updated: {manifest.last_updated}")
            return 0

        elif cache_command == "clean":
            if not cache_root.exists():
                print("No cache to clean.")
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
            print(f"Cache deleted: {cache_root}")
            return 0

        elif cache_command == "clean-failed":
            if not cache_root.exists():
                print("No cache directory found.")
                return 0

            manifest_path = get_manifest_path(cache_root)
            manifest = load_manifest(manifest_path)
            if manifest is None:
                print("No manifest found.")
                return 0

            failed = manifest.failed_chapters()
            if not failed:
                print("No failed entries to clean.")
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
            print(f"Cleaned {cleaned} failed entries. They will be re-rendered on next run.")
            return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


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

    # Optional: voice-soundboard
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
    except (ImportError, Exception):
        checks.append(
            {
                "check": "voice_engine",
                "status": "info",
                "value": "voice-soundboard not installed",
                "hint": "pip install voice-soundboard (required for rendering)",
            }
        )

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


def cmd_batch(args) -> int:
    """
    FT-RENDER-012: Batch process multiple source files.

    For each source file: create project -> auto-cast -> compile -> render.
    Logs per-book progress, elapsed time, and summary table at the end.
    """
    import glob as glob_mod
    import time as _time
    from audiobooker import AudiobookProject
    from audiobooker.renderer.engine import RenderError

    # Expand glob patterns
    source_files: list[Path] = []
    for pattern in args.files:
        expanded = glob_mod.glob(pattern, recursive=True)
        if expanded:
            source_files.extend(Path(f) for f in expanded)
        else:
            # Treat as literal path
            source_files.append(Path(pattern))

    if not source_files:
        print("No source files found.")
        return 1

    # Deduplicate and filter to supported extensions
    supported = {".epub", ".txt", ".md", ".markdown", ".pdf"}
    source_files = list(dict.fromkeys(source_files))  # deduplicate preserving order
    source_files = [f for f in source_files if f.suffix.lower() in supported and f.exists()]

    if not source_files:
        print("No supported source files found (EPUB/TXT/MD/PDF).")
        return 1

    # --dry-run: show what would be processed without rendering
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        print(f"DRY RUN — {len(source_files)} file(s) would be processed:\n")
        for i, source in enumerate(source_files, 1):
            print(f"  [{i}/{len(source_files)}] {source.name} ({source.suffix})")
        print(f"\nFormat: {getattr(args, 'output_format', None) or 'm4b'}")
        print(f"Language: {getattr(args, 'lang', 'en')}")
        print(f"Workers: {getattr(args, 'jobs', 1)}")
        return 0

    print(f"Batch processing {len(source_files)} file(s)...\n")

    results: list[dict] = []
    fmt = getattr(args, "output_format", None) or "m4b"
    jobs = getattr(args, "jobs", 1)
    lang = getattr(args, "lang", "en")
    batch_start = _time.time()

    for i, source in enumerate(source_files, 1):
        book_start = _time.time()
        print(f"[{i}/{len(source_files)}] {source.name}")
        book_result = {
            "file": str(source),
            "name": source.stem,
            "status": "unknown",
            "output": "",
            "error": "",
            "duration_s": 0.0,
        }

        try:
            # Step 1: Create project
            from audiobooker.models import ProjectConfig
            config = ProjectConfig(language_code=lang)

            suffix = source.suffix.lower()
            if suffix == ".epub":
                project = AudiobookProject.from_epub(source, config=config)
            elif suffix == ".pdf":
                project = AudiobookProject.from_pdf(source, config=config)
            elif suffix in (".txt", ".md", ".markdown"):
                project = AudiobookProject.from_text(source, config=config)
            else:
                book_result["status"] = "skipped"
                book_result["error"] = f"Unsupported format: {suffix}"
                book_result["duration_s"] = _time.time() - book_start
                results.append(book_result)
                print(f"  Skipped: unsupported format {suffix}")
                continue

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
                    suggest_results = suggester.suggest_all(sorted(uncast), already_cast=already_cast)
                    for sr in suggest_results:
                        if sr.top:
                            project.cast(sr.speaker, sr.top.voice_id)
                except Exception as cast_err:
                    print(f"  Warning: Auto-cast failed ({cast_err}), using fallback voices")

            # Step 4: Save project
            project_path = source.with_suffix(".audiobooker")
            project.save(project_path)

            # Step 5: Render
            from audiobooker.project import _sanitize_filename
            output_path = source.parent / f"{_sanitize_filename(project.title)}.{fmt}"

            from audiobooker.renderer.engine import render_project
            path = render_project(
                project,
                output_path,
                jobs=jobs,
                force=True,  # skip casting validation in batch
                output_format=fmt,
            )

            book_result["status"] = "success"
            book_result["output"] = str(path)
            book_result["duration_s"] = _time.time() - book_start
            elapsed = book_result["duration_s"]
            print(f"  OK: {path} ({elapsed:.1f}s)")

        except RenderError as e:
            book_result["status"] = "failed"
            book_result["error"] = str(e)[:200]
            book_result["duration_s"] = _time.time() - book_start
            print(f"  FAILED: {e}")

        except Exception as e:
            book_result["status"] = "error"
            book_result["error"] = str(e)[:200]
            book_result["duration_s"] = _time.time() - book_start
            print(f"  ERROR: {e}")

        results.append(book_result)

    # Summary table
    total_elapsed = _time.time() - batch_start
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] in ("failed", "error"))
    skipped = sum(1 for r in results if r["status"] == "skipped")

    def _fmt_duration(s: float) -> str:
        if s >= 3600:
            return f"{s / 3600:.1f}h"
        elif s >= 60:
            return f"{s / 60:.1f}m"
        return f"{s:.1f}s"

    print(f"\n{'='*72}")
    print(f"  BATCH SUMMARY — {success} succeeded, {failed} failed, {skipped} skipped")
    print(f"  Total elapsed: {_fmt_duration(total_elapsed)}")
    print(f"{'='*72}")
    print(f"  {'#':<4} {'Status':<10} {'Duration':<10} {'Title':<28} {'Output'}")
    print(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*28} {'-'*20}")
    for idx, r in enumerate(results, 1):
        status = r["status"].upper()
        dur = _fmt_duration(r["duration_s"])
        name = r["name"][:27]
        out = r["output"] if r["status"] == "success" else r.get("error", "")[:40]
        print(f"  {idx:<4} {status:<10} {dur:<10} {name:<28} {out}")
    print(f"{'='*72}")

    return 0 if failed == 0 else 1


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
            print("Compiling chapter...")
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

        print(f"Previewing chapter {chapter_idx}: {chapter.title}")
        print(f"  Utterances: {len(preview_chapter.utterances)} of {len(chapter.utterances)}")
        print(f"  Target duration: ~{target_seconds}s")

        path = render_chapter(
            preview_chapter,
            project.casting,
            output_path,
        )

        print(f"\nPreview saved: {path}")
        return 0

    except RenderError as e:
        print(f"Render failed: {e}")
        return 1

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    commands = {
        "new": cmd_new,
        "cast": cmd_cast,
        "cast-suggest": cmd_cast_suggest,
        "cast-apply": cmd_cast_apply,
        "cast-export": cmd_cast_export,
        "cast-import": cmd_cast_import,
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
        "diagnose": cmd_diagnose,
        "batch": cmd_batch,
        "preview": cmd_preview,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
