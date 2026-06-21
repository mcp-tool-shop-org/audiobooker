"""
Output Assembly for Audiobooker.

Assembles chapter audio files into final M4B/M4A audiobook
with chapter markers and metadata using FFmpeg.
"""

import logging
import re
import subprocess
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from audiobooker.renderer.protocols import FFmpegRunner

logger = logging.getLogger("audiobooker.output")

# Module-level cache for check_ffmpeg() to avoid redundant subprocess spawns
_ffmpeg_checked: Optional[bool] = None


@dataclass
class AssemblyResult:
    """Result of M4B assembly with status details."""
    output_path: Path
    chapters_embedded: bool
    chapter_error: str = ""


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available. Result is cached after first call."""
    global _ffmpeg_checked
    if _ffmpeg_checked is not None:
        return _ffmpeg_checked
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        _ffmpeg_checked = result.returncode == 0
    except FileNotFoundError:
        _ffmpeg_checked = False
    return _ffmpeg_checked


def reset_ffmpeg_cache() -> None:
    """Reset the module-level FFmpeg availability cache (useful for testing)."""
    global _ffmpeg_checked
    _ffmpeg_checked = None


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
        if result.returncode != 0:
            # F-RENDER-B-002: Log warning on ffprobe failure instead of silent 0.0
            logger.warning(
                f"ffprobe failed for {audio_path} (rc={result.returncode}): "
                f"{result.stderr.strip()[:200]}"
            )
            return 0.0
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError) as e:
        # F-RENDER-B-002: Log warning on ffprobe failure
        logger.warning(f"ffprobe error for {audio_path}: {e}")
        return 0.0


def _escape_ffmpeg_metadata(value: str) -> str:
    """
    Escape a string for FFmpeg metadata format.

    Per FFmpeg metadata spec, semicolons, hash signs, backslashes,
    and newlines must be escaped with a backslash.
    Non-printable characters are stripped.
    """
    # Strip control characters only (preserve all printable Unicode)
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value)
    # Escape backslashes first to avoid double-escaping
    value = value.replace('\\', '\\\\')
    value = value.replace(';', '\\;')
    value = value.replace('#', '\\#')
    value = value.replace('\n', '\\\n')
    return value


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
        lines.append(f"title={_escape_ffmpeg_metadata(title)}")
        lines.append("")

        # Move to next chapter (with pause)
        current_time_ms += duration_ms + pause_ms

    return "\n".join(lines)


def _escape_concat_path(path: str) -> str:
    """Escape single quotes in file paths for FFmpeg concat file format."""
    return path.replace("'", "'\\''")


def _generate_silence_file(
    output_path: Path,
    pause_ms: int,
    sample_rate: int = 24000,
    runner: Optional["FFmpegRunner"] = None,
) -> Path:
    """
    FT-RENDER-014: Generate a single reusable silence WAV file.

    Args:
        output_path: Where to write the silence file.
        pause_ms: Duration of silence in milliseconds.
        sample_rate: Audio sample rate (default: 24000 Hz).
        runner: Optional FFmpegRunner.

    Returns:
        Path to generated silence file.
    """
    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    result = runner.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=mono:d={pause_ms / 1000}",
        str(output_path),
    ])
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg silence generation failed (rc={result.returncode}): "
            f"{result.stderr.strip()[:300]}"
        )
    return output_path


def concatenate_audio_files(
    audio_files: list[Path],
    output_path: Path,
    pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
    sample_rate: int = 24000,
) -> Path:
    """
    Concatenate multiple audio files with pauses between.

    FT-RENDER-014: Uses a single silence WAV file referenced between every
    chapter instead of spawning N-1 FFmpeg processes.

    Args:
        audio_files: List of audio file paths
        output_path: Output file path
        pause_ms: Pause between files in milliseconds
        runner: Optional FFmpegRunner for subprocess calls (defaults to RealFFmpegRunner).
        sample_rate: Sample rate for silence generation (default: 24000 Hz).

    Returns:
        Path to concatenated file
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for audio assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    silence_path: Optional[Path] = None
    concat_file: Optional[Path] = None

    # F-RENDER-B-009: Wrap silence+concat gen in dedicated try/finally
    try:
        # FT-RENDER-014: Generate a single silence file, reused for all gaps
        if pause_ms > 0 and len(audio_files) > 1:
            tmp_silence = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            silence_path = Path(tmp_silence.name)
            tmp_silence.close()
            _generate_silence_file(silence_path, pause_ms, sample_rate, runner)
            escaped_silence = _escape_concat_path(silence_path.absolute().as_posix())

        # Create concat file list
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as f:
            concat_file = Path(f.name)

            for i, audio_path in enumerate(audio_files):
                # F-RENDER-B-013: Use forward slashes for Windows compat in concat file
                escaped = _escape_concat_path(audio_path.absolute().as_posix())
                f.write(f"file '{escaped}'\n")

                # Add silence between chapters (except after last)
                if i < len(audio_files) - 1 and pause_ms > 0 and silence_path is not None:
                    f.write(f"file '{escaped_silence}'\n")

        # Concatenate
        result = runner.run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ])

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")

        return output_path

    finally:
        # F-RENDER-B-009: Clean up all temp files even on early exception
        if concat_file is not None:
            concat_file.unlink(missing_ok=True)
        if silence_path is not None:
            silence_path.unlink(missing_ok=True)


def _sanitize_metadata_value(value: str) -> str:
    """Strip newlines and non-printable characters from FFmpeg -metadata values."""
    # Remove newlines
    value = value.replace('\n', ' ').replace('\r', ' ')
    # Strip control characters only (preserve all printable Unicode)
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value)
    return value.strip()


def assemble_m4b(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
    aac_bitrate: str = "128k",
    cover_art: Optional[str] = None,
    normalize: bool = False,
) -> AssemblyResult:
    """
    Assemble chapter audio files into M4B audiobook.

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Output M4B path
        title: Book title
        author: Book author
        chapter_pause_ms: Pause between chapters
        runner: Optional FFmpegRunner for subprocess calls (defaults to RealFFmpegRunner).
        aac_bitrate: AAC encoding bitrate (default: "128k").
        cover_art: Optional path to cover image (JPG/PNG) to embed.

    Returns:
        AssemblyResult with output_path and chapters_embedded flag.
    """
    import time as _time

    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for M4B assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    output_path = Path(output_path)

    # F-RENDER-B-004: Use TemporaryDirectory context manager for automatic cleanup
    with tempfile.TemporaryDirectory(prefix="audiobooker_m4b_") as _temp_str:
      temp_dir = Path(_temp_str)

      # F-RENDER-B-019: Timing instrumentation for assembly
      assembly_start = _time.time()

      # Step 1: Build concat list with silence gaps (FT-RENDER-014: single silence file)
      audio_paths = [p for p, _, _ in chapter_files]

      # Step 2: Generate chapter metadata
      metadata_content = generate_chapter_metadata(chapter_files, chapter_pause_ms)

      # Add title and author to metadata (sanitize values)
      safe_title = _escape_ffmpeg_metadata(_sanitize_metadata_value(title))
      metadata_lines = metadata_content.split("\n")
      metadata_lines.insert(1, f"title={safe_title}")
      if author:
          safe_author = _escape_ffmpeg_metadata(_sanitize_metadata_value(author))
          metadata_lines.insert(2, f"artist={safe_author}")
      metadata_content = "\n".join(metadata_lines)

      metadata_path = temp_dir / "metadata.txt"
      metadata_path.write_text(metadata_content, encoding="utf-8")

      # FT-RENDER-008: Try single-pass FFmpeg assembly first
      # Build a concat list with silence gaps
      concat_list_path = temp_dir / "concat_list.txt"
      silence_path: Optional[Path] = None

      if chapter_pause_ms > 0 and len(audio_paths) > 1:
          silence_path = temp_dir / "silence.wav"
          _generate_silence_file(silence_path, chapter_pause_ms, runner=runner)

      with open(concat_list_path, "w", encoding="utf-8") as f:
          for idx, audio_path in enumerate(audio_paths):
              escaped = _escape_concat_path(audio_path.absolute().as_posix())
              f.write(f"file '{escaped}'\n")
              if idx < len(audio_paths) - 1 and silence_path is not None:
                  escaped_silence = _escape_concat_path(silence_path.absolute().as_posix())
                  f.write(f"file '{escaped_silence}'\n")

      # Single-pass: concat → AAC encode → output in one FFmpeg command
      aac_path = temp_dir / "audio.m4a"
      encode_start = _time.time()

      result = runner.run([
          "ffmpeg", "-y",
          "-f", "concat",
          "-safe", "0",
          "-i", str(concat_list_path),
          "-c:a", "aac",
          "-b:a", aac_bitrate,
          "-ar", "24000",
          str(aac_path),
      ])

      if result.returncode == 0:
          encode_elapsed = _time.time() - encode_start
          logger.info(
              f"ASSEMBLY_SINGLE_PASS: concat+encode completed in {encode_elapsed:.1f}s "
              f"(eliminated intermediate WAV)"
          )
      else:
          # FT-RENDER-008: Fallback to two-pass approach
          logger.warning(
              f"ASSEMBLY_SINGLE_PASS_FAIL: rc={result.returncode}, "
              f"falling back to two-pass approach"
          )
          concat_path = temp_dir / "concat.wav"
          concatenate_audio_files(audio_paths, concat_path, chapter_pause_ms, runner=runner)

          concat_elapsed = _time.time() - assembly_start
          logger.info(f"ASSEMBLY_CONCAT: {len(audio_paths)} chapters concatenated in {concat_elapsed:.1f}s")

          result = runner.run([
              "ffmpeg", "-y",
              "-i", str(concat_path),
              "-c:a", "aac",
              "-b:a", aac_bitrate,
              "-ar", "24000",
              str(aac_path),
          ])

          if result.returncode != 0:
              raise RuntimeError(f"FFmpeg AAC conversion failed: {result.stderr}")

          encode_elapsed = _time.time() - encode_start
          logger.info(f"ASSEMBLY_ENCODE: AAC encoding completed in {encode_elapsed:.1f}s")

      # FT-RENDER-019: Audio normalization (EBU R128, target -16 LUFS)
      if normalize:
          norm_path = temp_dir / "audio_normalized.m4a"
          logger.info("ASSEMBLY_NORMALIZE: Running loudnorm filter (EBU R128, -16 LUFS)")
          norm_result = runner.run([
              "ffmpeg", "-y",
              "-i", str(aac_path),
              "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
              "-c:a", "aac",
              "-b:a", aac_bitrate,
              "-ar", "24000",
              str(norm_path),
          ])
          if norm_result.returncode == 0:
              # Replace original with normalized version
              aac_path.unlink(missing_ok=True)
              norm_path.rename(aac_path)
              logger.info("ASSEMBLY_NORMALIZE: Normalization complete")
          else:
              logger.warning(
                  f"ASSEMBLY_NORMALIZE_FAIL: rc={norm_result.returncode}, "
                  f"continuing without normalization. stderr: {norm_result.stderr[:300]}"
              )

      # Add chapter metadata (and cover art if provided — FT-RENDER-006)
      metadata_cmd = [
          "ffmpeg", "-y",
          "-i", str(aac_path),
          "-i", str(metadata_path),
      ]
      if cover_art and Path(cover_art).exists():
          metadata_cmd.extend(["-i", str(cover_art)])
          metadata_cmd.extend([
              "-map", "0:a",
              "-map", "2:v",
              "-map_metadata", "1",
              "-c:a", "copy",
              "-c:v", "copy",
              "-disposition:v", "attached_pic",
          ])
      else:
          # OUTPUT-A-006: surface the silent no-op when a cover was requested but
          # the path is missing — otherwise the user just gets no cover with no
          # explanation.
          if cover_art:
              logger.warning(
                  f"Cover art not embedded — file not found: {cover_art}. "
                  f"Output will have no cover image."
              )
          metadata_cmd.extend([
              "-map", "0:a",
              "-map_metadata", "1",
              "-c", "copy",
          ])
      metadata_cmd.append(str(output_path))
      result = runner.run(metadata_cmd)

      total_elapsed = _time.time() - assembly_start
      logger.info(f"ASSEMBLY_TOTAL: completed in {total_elapsed:.1f}s")

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


def assemble_mp3(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
) -> AssemblyResult:
    """
    FT-RENDER-003: Assemble chapter audio as individual MP3 files.

    This wrapper satisfies the AssemblerProtocol so it can be used as
    a drop-in replacement for assemble_m4b when output_format='mp3'.

    MP3 doesn't support chapter markers in a single file, so we produce
    one MP3 per chapter in a directory named after output_path (without extension).

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Base output path (directory will be created alongside)
        title: Book title
        author: Book author
        chapter_pause_ms: Ignored for MP3 (each chapter is a separate file)
        runner: Optional FFmpegRunner.

    Returns:
        AssemblyResult pointing to the output directory.
    """
    output_dir = output_path.parent / output_path.stem
    mp3_paths = assemble_mp3_chapters(
        chapter_files, output_dir, title=title, author=author, runner=runner,
    )
    # Create a manifest file listing all MP3s
    manifest = output_dir / "_playlist.m3u"
    manifest.write_text(
        "\n".join(str(p.name) for p in mp3_paths),
        encoding="utf-8",
    )
    return AssemblyResult(
        output_path=output_dir,
        chapters_embedded=True,  # each chapter is its own file
    )


def assemble_mp3_chapters(
    chapter_files: list[tuple[Path, str, float]],
    output_dir: Path,
    title: str = "Audiobook",
    author: str = "",
    *,
    runner: Optional["FFmpegRunner"] = None,
) -> list[Path]:
    """
    Convert chapter audio files to MP3s (one per chapter).

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_dir: Output directory
        title: Book title (for filenames)
        runner: Optional FFmpegRunner for subprocess calls (defaults to RealFFmpegRunner).

    Returns:
        List of MP3 file paths
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg is required for MP3 conversion.")

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mp3_paths = []

    for i, (audio_path, chapter_title, _) in enumerate(chapter_files):
        # Sanitize filename
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in chapter_title)
        mp3_path = output_dir / f"{i+1:02d}_{safe_title}.mp3"

        safe_chapter_title = _sanitize_metadata_value(chapter_title)
        safe_album = _sanitize_metadata_value(title)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-metadata", f"title={safe_chapter_title}",
            "-metadata", f"album={safe_album}",
            "-metadata", f"track={i+1}",
        ]
        if author:
            safe_author = _sanitize_metadata_value(author)
            cmd.extend(["-metadata", f"artist={safe_author}"])
        cmd.append(str(mp3_path))

        result = runner.run(cmd)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg MP3 conversion failed: {result.stderr}")

        mp3_paths.append(mp3_path)

    return mp3_paths
