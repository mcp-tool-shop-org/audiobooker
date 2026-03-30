#!/usr/bin/env python3
"""
Audiobooker demo: parse -> compile -> review cycle.

Demonstrates the core pipeline without TTS rendering.
Uses sample_book.txt from the examples directory.

Usage:
    python examples/demo.py
"""

from pathlib import Path

from audiobooker import AudiobookProject


def main() -> None:
    # Locate sample book relative to this script
    sample = Path(__file__).parent / "sample_book.txt"
    if not sample.exists():
        print(f"Sample book not found at {sample}")
        return

    print("=== Audiobooker Demo ===\n")

    # 1. Create project from text file
    print("1. Parsing source file...")
    project = AudiobookProject.from_text(sample)
    print(f"   Title:    {project.title}")
    print(f"   Author:   {project.author}")
    print(f"   Chapters: {len(project.chapters)}")
    print(f"   Words:    {project.total_words}")
    print()

    # 2. Cast voices (no TTS needed for demo)
    print("2. Casting voices...")
    project.cast("narrator", "bm_george", emotion="calm")
    project.cast("Sarah", "af_bella", emotion="warm")
    project.cast("gardener", "bm_lewis", emotion="gruff")
    for name in project.list_characters():
        print(f"   {name}")
    print()

    # 3. Compile chapters to utterances
    print("3. Compiling chapters...")
    project.compile()
    for chapter in project.chapters:
        speakers = {u.speaker for u in chapter.utterances}
        print(f"   {chapter.title}: {len(chapter.utterances)} utterances, speakers: {speakers}")
    print()

    # 4. Export for review
    print("4. Exporting for review...")
    review_path = project.export_for_review()
    print(f"   Review file: {review_path}")
    print()

    # 5. Preview first chapter review format
    print("5. Preview (Chapter 1 review format):")
    print("-" * 40)
    preview = project.preview_review_format(0)
    # Show first 20 lines
    for line in preview.splitlines()[:20]:
        print(f"   {line}")
    print("   ...")
    print("-" * 40)
    print()

    # 6. Project info summary
    print("6. Project info:")
    info = project.info()
    for key, value in info.items():
        print(f"   {key}: {value}")
    print()

    # 7. Save project
    save_path = project.save("demo_project.audiobooker")
    print(f"7. Project saved to {save_path}")
    print()

    # Cleanup
    save_path.unlink(missing_ok=True)
    review_path.unlink(missing_ok=True)
    print("Demo complete. Temporary files cleaned up.")


if __name__ == "__main__":
    main()
