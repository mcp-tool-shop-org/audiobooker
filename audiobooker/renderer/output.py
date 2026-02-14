"""
Output Assembly for Audiobooker.

Assembles chapter audio files into final M4B/M4A audiobook
with chapter markers and metadata using FFmpeg.
"""

import logging
import subprocess
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("audiobooker.output")


@dataclass
class AssemblyResult:
    """Result of M4B assembly with status details."""
    output_path: Path
    chapters_embedded: bool
    chapter_error: str = ""


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_audio_duration(audio_path: Path) -> float:
    """
    Get duration of audio file in seconds using ffprobe.

    Args:
        audio_path: Path to audio file

    Returns:
        Duration in seconds
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def generate_chapter_metadata(
    chapters: list[tuple[Path, str, float]],
    chapter_pause_ms: int = 2000,
) -> str:
    """
    Generate FFmpeg metadata file content for chapters.

    Args:
        chapters: List of (audio_path, title, duration_seconds)
        chapter_pause_ms: Pause between chapters in milliseconds

    Returns:
        FFmpeg metadata file content
    """
    lines = [
        ";FFMETADATA1",
    ]

    current_time_ms = 0
    pause_ms = chapter_pause_ms

    for i, (audio_path, title, duration) in enumerate(chapters):
        # Get actual duration if not provided
        if duration <= 0:
            duration = get_audio_duration(audio_path)

        duration_ms = int(duration * 1000)

        # Chapter marker
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={current_time_ms}")
        lines.append(f"END={current_time_ms + duration_ms}")
        lines.append(f"title={title}")
        lines.append("")

        # Move to next chapter (with pause)
        current_time_ms += duration_ms + pause_ms

    return "\n".join(lines)


def concatenate_audio_files(
    audio_files: list[Path],
    output_path: Path,
    pause_ms: int = 2000,
) -> Path:
    """
    Concatenate multiple audio files with pauses between.

    Args:
        audio_files: List of audio file paths
        output_path: Output file path
        pause_ms: Pause between files in milliseconds

    Returns:
        Path to concatenated file
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for audio assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )

    # Create concat file list
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as f:
        concat_file = Path(f.name)

        for i, audio_path in enumerate(audio_files):
            # Add audio file
            f.write(f"file '{audio_path.absolute()}'\n")

            # Add silence between chapters (except after last)
            if i < len(audio_files) - 1 and pause_ms > 0:
                # Generate silence file
                silence_path = Path(tempfile.mktemp(suffix=".wav"))
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi",
                        "-i", f"anullsrc=r=24000:cl=mono:d={pause_ms/1000}",
                        str(silence_path),
                    ],
                    capture_output=True,
                )
                f.write(f"file '{silence_path.absolute()}'\n")

    try:
        # Concatenate
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")

        return output_path

    finally:
        concat_file.unlink(missing_ok=True)


def assemble_m4b(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
) -> AssemblyResult:
    """
    Assemble chapter audio files into M4B audiobook.

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Output M4B path
        title: Book title
        author: Book author
        chapter_pause_ms: Pause between chapters

    Returns:
        AssemblyResult with output_path and chapters_embedded flag.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for M4B assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )

    output_path = Path(output_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="audiobooker_m4b_"))

    try:
        # Step 1: Concatenate all audio files
        audio_paths = [p for p, _, _ in chapter_files]
        concat_path = temp_dir / "concat.wav"
        concatenate_audio_files(audio_paths, concat_path, chapter_pause_ms)

        # Step 2: Generate chapter metadata
        metadata_content = generate_chapter_metadata(chapter_files, chapter_pause_ms)

        # Add title and author to metadata
        metadata_lines = metadata_content.split("\n")
        metadata_lines.insert(1, f"title={title}")
        if author:
            metadata_lines.insert(2, f"artist={author}")
        metadata_content = "\n".join(metadata_lines)

        metadata_path = temp_dir / "metadata.txt"
        metadata_path.write_text(metadata_content, encoding="utf-8")

        # Step 3: Convert to M4B with chapters
        # First convert to AAC
        aac_path = temp_dir / "audio.m4a"

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(concat_path),
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "24000",
                str(aac_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg AAC conversion failed: {result.stderr}")

        # Add chapter metadata
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(aac_path),
                "-i", str(metadata_path),
                "-map", "0:a",
                "-map_metadata", "1",
                "-c", "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            # Log the actual FFmpeg error so it's never invisible
            stderr_tail = "\n".join(result.stderr.strip().splitlines()[-20:])
            logger.warning(
                "Chapter embedding failed, producing M4A without chapters.\n"
                f"FFmpeg stderr (last 20 lines):\n{stderr_tail}"
            )
            shutil.copy(aac_path, output_path)
            return AssemblyResult(
                output_path=output_path,
                chapters_embedded=False,
                chapter_error=stderr_tail,
            )

        return AssemblyResult(
            output_path=output_path,
            chapters_embedded=True,
        )

    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def assemble_mp3_chapters(
    chapter_files: list[tuple[Path, str, float]],
    output_dir: Path,
    title: str = "Audiobook",
) -> list[Path]:
    """
    Convert chapter audio files to MP3s (one per chapter).

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_dir: Output directory
        title: Book title (for filenames)

    Returns:
        List of MP3 file paths
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg is required for MP3 conversion.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mp3_paths = []

    for i, (audio_path, chapter_title, _) in enumerate(chapter_files):
        # Sanitize filename
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in chapter_title)
        mp3_path = output_dir / f"{i+1:02d}_{safe_title}.mp3"

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-metadata", f"title={chapter_title}",
                "-metadata", f"album={title}",
                "-metadata", f"track={i+1}",
                str(mp3_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg MP3 conversion failed: {result.stderr}")

        mp3_paths.append(mp3_path)

    return mp3_paths
