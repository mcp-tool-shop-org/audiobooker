"""
Command-Line Interface for Audiobooker.

Usage:
    audiobooker new book.epub              # Create project from EPUB
    audiobooker new book.txt               # Create project from text
    audiobooker cast narrator af_bella     # Assign voice to character
    audiobooker compile                    # Compile chapters to utterances
    audiobooker render                     # Render audiobook
    audiobooker info                       # Show project info
    audiobooker voices                     # List available voices
"""

import argparse
import sys
from pathlib import Path
from typing import Optional


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    from audiobooker import __version__

    parser = argparse.ArgumentParser(
        prog="audiobooker",
        description="AI Audiobook Generator - Convert books to narrated audiobooks",
    )
    parser.add_argument("--version", action="version", version=f"audiobooker {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- new ---
    new_parser = subparsers.add_parser("new", help="Create new project from source file")
    new_parser.add_argument("source", help="Source file (EPUB, TXT, MD)")
    new_parser.add_argument("-o", "--output", help="Output project file path")
    new_parser.add_argument("--lang", default="en", metavar="CODE", help="Language code (default: en)")

    # --- load ---
    load_parser = subparsers.add_parser("load", help="Load existing project")
    load_parser.add_argument("project", help="Project file (.audiobooker)")

    # --- cast ---
    cast_parser = subparsers.add_parser("cast", help="Assign voice to character")
    cast_parser.add_argument("character", help="Character name")
    cast_parser.add_argument("voice", help="Voice ID (e.g., af_bella, bm_george)")
    cast_parser.add_argument("-e", "--emotion", help="Default emotion")
    cast_parser.add_argument("-d", "--description", help="Character description")
    cast_parser.add_argument("-p", "--project", help="Project file (auto-detected if omitted)")

    # --- compile ---
    compile_parser = subparsers.add_parser("compile", help="Compile chapters to utterances")
    compile_parser.add_argument("-p", "--project", help="Project file")

    # --- render ---
    render_parser = subparsers.add_parser("render", help="Render audiobook")
    render_parser.add_argument("-p", "--project", help="Project file")
    render_parser.add_argument("-o", "--output", help="Output file path")
    render_parser.add_argument("-c", "--chapter", type=int, help="Render single chapter (0-indexed)")
    render_parser.add_argument("--no-resume", action="store_true", help="Force full re-render (ignore cache)")
    render_parser.add_argument("--from-chapter", type=int, metavar="N", help="Start rendering from chapter N (0-indexed)")
    render_parser.add_argument("--allow-partial", action="store_true", help="Assemble even if some chapters failed")
    render_parser.add_argument("--clean-cache", action="store_true", help="Delete render cache before starting")

    # --- info ---
    info_parser = subparsers.add_parser("info", help="Show project information")
    info_parser.add_argument("-p", "--project", help="Project file")
    info_parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed info")

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
    stdin_parser.add_argument("--lang", default="en", metavar="CODE", help="Language code (default: en)")
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
            f"Multiple project files found. Specify one with -p:\n"
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

        config = ProjectConfig(language_code=lang)

        if suffix == ".epub":
            project = AudiobookProject.from_epub(source, config=config)
        elif suffix in (".txt", ".md", ".markdown"):
            project = AudiobookProject.from_text(source, config=config)
        else:
            print(f"Error: Unsupported file format: {suffix}")
            print("Supported: .epub, .txt, .md")
            return 1

        # Save project
        output_path = args.output or source.with_suffix(".audiobooker")
        project.save(output_path)

        print(f"\nProject created: {output_path}")
        print(f"  Title: {project.title}")
        print(f"  Chapters: {len(project.chapters)}")
        print(f"  Words: ~{project.total_words:,}")
        print(f"  Estimated duration: ~{project.estimated_duration_minutes:.0f} min (at {project.config.estimated_wpm} wpm, varies by voice)")
        print("\nNext steps:")
        print(f"  1. Cast voices: audiobooker cast narrator af_heart")
        print(f"  2. Compile: audiobooker compile")
        print(f"  3. Render: audiobooker render")

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

        character = project.cast(
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

        print(f"Compiling {len(project.chapters)} chapters...")

        def progress(current, total, title):
            print(f"  [{current}/{total}] {title}")

        project.compile(progress_callback=progress)
        project.save()

        # Show uncast speakers
        uncast = project.get_uncast_speakers()
        if uncast:
            print(f"\nDetected speakers without voice assignments:")
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
                shutil.rmtree(cache_dir)
                print(f"Cache cleared: {cache_dir}")
            else:
                print("No cache to clean.")

        if args.chapter is not None:
            # Render single chapter
            print(f"Rendering chapter {args.chapter}...")
            output = args.output or f"chapter_{args.chapter:03d}.wav"
            path = project.render_chapter(args.chapter, output)
            print(f"Output: {path}")
        else:
            # Render full audiobook
            output = args.output or f"{project.title}.m4b"
            resume = not getattr(args, "no_resume", False)
            from_chapter = getattr(args, "from_chapter", None)
            allow_partial = getattr(args, "allow_partial", False)

            print(f"Rendering audiobook to: {output}")
            if not resume:
                print("  (cache disabled — full re-render)")

            def progress(current, total, status):
                print(f"  [{current}/{total}] {status}")

            path = project.render(
                output,
                progress_callback=progress,
                resume=resume,
                from_chapter=from_chapter,
                allow_partial=allow_partial,
            )
            project.save()

            print(f"\nAudiobook created: {path}")
            print(f"Duration: {project.total_duration_seconds / 60:.1f} minutes")

        return 0

    except RenderError as e:
        _print_render_failure(e)
        return 1

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
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

    print(f"\nRender summary: {summary.rendered} rendered, "
          f"{summary.skipped_cached} cached, {summary.failed} failed "
          f"(of {summary.total} total)")

    if summary.cache_dir:
        print(f"\nCached chapter audio: {summary.cache_dir}")
    if summary.manifest_path:
        print(f"Manifest: {summary.manifest_path}")

    print("\nTo resume: audiobooker render --resume")
    print("To force:  audiobooker render --no-resume")


def cmd_info(args) -> int:
    """Show project information."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        info = project.info()

        print(f"Title: {info['title']}")
        if info['author']:
            print(f"Author: {info['author']}")
        print(f"Source: {info['source']}")
        print(f"Chapters: {info['chapters']}")
        print(f"Words: ~{info['total_words']:,}")
        print(f"Estimated duration: ~{info['estimated_duration_minutes']:.0f} min (varies by voice)")
        print(f"Characters cast: {info['characters_cast']}")
        print(f"Compiled: {'Yes' if info['compiled'] else 'No'}")
        print(f"Rendered: {'Yes' if info['rendered'] else 'No'}")

        if info['uncast_speakers']:
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
            voice_gender = "female" if voice_id.startswith("af_") or voice_id.startswith("bf_") else "male"
            if voice_gender != args.gender.lower():
                continue

        # Filter by search term
        if args.search:
            search_lower = args.search.lower()
            if search_lower not in voice_id.lower() and search_lower not in str(info).lower():
                continue

        print(f"  {voice_id}")

    return 0


def cmd_chapters(args) -> int:
    """List chapters."""
    from audiobooker import AudiobookProject

    try:
        project_path = find_project_file(args.project)
        project = AudiobookProject.load(project_path)

        print(f"Chapters in {project.title}:\n")

        for chapter in project.chapters:
            status = ""
            if chapter.is_rendered:
                status = " [rendered]"
            elif chapter.is_compiled:
                status = " [compiled]"

            print(f"  {chapter.index + 1}. {chapter.title} ({chapter.word_count} words){status}")

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
            if speaker.lower() in cast_speakers:
                char = project.casting.characters[speaker.lower()]
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

        print(f"Exporting review file...")

        review_path = project.export_for_review(output)
        project.save()

        # Count stats
        total_utterances = sum(len(c.utterances) for c in project.chapters)
        speakers = project.get_detected_speakers()

        print(f"\nReview file created: {review_path}")
        print(f"  Chapters: {len(project.chapters)}")
        print(f"  Utterances: {total_utterances}")
        print(f"  Speakers: {', '.join(sorted(speakers))}")
        print(f"\nEdit the file to:")
        print(f"  - Change speaker names: @OldName -> @NewName")
        print(f"  - Add/change emotions: @Name -> @Name (emotion)")
        print(f"  - Delete unwanted lines by removing the block")
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

        print(f"\nImport complete:")
        print(f"  Chapters updated: {stats['chapters_updated']}")
        print(f"  Utterances imported: {stats['utterances_imported']}")
        print(f"  Speakers: {', '.join(sorted(stats['speakers_found']))}")
        print(f"\nProject saved. Ready to render: audiobooker render")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
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
        "compile": cmd_compile,
        "render": cmd_render,
        "info": cmd_info,
        "voices": cmd_voices,
        "chapters": cmd_chapters,
        "speakers": cmd_speakers,
        "from-stdin": cmd_from_stdin,
        "review-export": cmd_review_export,
        "review-import": cmd_review_import,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
