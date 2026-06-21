"""
Output Assembly for Audiobooker.

Assembles chapter audio files into final M4B/M4A audiobook
with chapter markers and metadata using FFmpeg.
"""

import json
import logging
import re
import subprocess
import tempfile
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union
from xml.sax.saxutils import escape as _xml_escape

from audiobooker.renderer.protocols import FFmpegRunner

if TYPE_CHECKING:
    from audiobooker.models import BookMetadata
    from audiobooker.project import AudiobookProject

logger = logging.getLogger("audiobooker.output")

# Module-level cache for check_ffmpeg() to avoid redundant subprocess spawns
_ffmpeg_checked: Optional[bool] = None


# ---------------------------------------------------------------------------
# FT-ACX-001 / FT-RENDER-M-001: Loudness mastering profiles
# ---------------------------------------------------------------------------
#
# 'podcast' preserves the historical behavior (EBU R128, -16 LUFS) used by the
# normalize=True path. 'acx' targets the ACX retail spec:
#   - Integrated loudness I = -20 LUFS  (ACX RMS window lands in [-23, -18] dB)
#   - True peak TP <= -3 dBTP
#   - Loudness range LRA = 11
#   - 44.1 kHz sample rate, 192k bitrate
#
# Each profile entry carries the loudnorm filter string plus the sample
# rate / default bitrate the profile expects. Callers that pass an explicit
# bitrate still win — the profile bitrate is only the default.
LOUDNORM_PROFILES: dict[str, dict[str, str]] = {
    "podcast": {
        "loudnorm": "loudnorm=I=-16:LRA=11:TP=-1.5",
        "sample_rate": "24000",
        "bitrate": "128k",
    },
    "acx": {
        "loudnorm": "loudnorm=I=-20:LRA=11:TP=-3",
        "sample_rate": "44100",
        "bitrate": "192k",
    },
}

# ACX retail master-check limits (FT-ACX-001).
ACX_RMS_MIN_DB = -23.0
ACX_RMS_MAX_DB = -18.0
ACX_PEAK_MAX_DBTP = -3.0
ACX_NOISE_FLOOR_MAX_DB = -60.0


def _resolve_loudnorm_profile(name: Optional[str]) -> dict[str, str]:
    """Return the loudnorm profile dict, defaulting to 'podcast'."""
    if not name:
        return LOUDNORM_PROFILES["podcast"]
    profile = LOUDNORM_PROFILES.get(name)
    if profile is None:
        logger.warning(
            "Unknown loudnorm profile %r — falling back to 'podcast'. "
            "Valid profiles: %s",
            name, ", ".join(sorted(LOUDNORM_PROFILES)),
        )
        return LOUDNORM_PROFILES["podcast"]
    return profile


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


# ---------------------------------------------------------------------------
# FT-RENDER-M-001: Full metadata tagging
# ---------------------------------------------------------------------------

def _metadata_ffmetadata_lines(metadata: Optional["BookMetadata"]) -> list[str]:
    """
    Build FFMETADATA key=value lines from a BookMetadata for the m4b path.

    Returns lines suitable for insertion into a metadata.txt header (the
    title/author lines are written separately by the caller). Covers
    narrator (album_artist), genre, year (date), publisher, and the series
    (mapped to album + grouping/TXXX-style ``show`` so players that read
    audiobook series surface it).
    """
    if metadata is None:
        return []

    lines: list[str] = []

    def _add(key: str, value: object) -> None:
        if value is None or value == "":
            return
        safe = _escape_ffmpeg_metadata(_sanitize_metadata_value(str(value)))
        lines.append(f"{key}={safe}")

    # Narrator → album_artist (the performer credit audiobook players read).
    _add("album_artist", metadata.narrator_name)
    _add("composer", metadata.narrator_name)  # iTunes shows narrator as composer
    _add("genre", metadata.genre)
    _add("date", metadata.year)
    _add("publisher", metadata.publisher)

    # Series → album (so the book groups under the series in most players),
    # plus an explicit SERIES / SERIES-PART pair for tools that read them.
    if metadata.series:
        _add("album", metadata.series)
        _add("SERIES", metadata.series)
        _add("show", metadata.series)
    if metadata.series_index is not None:
        _add("SERIES-PART", metadata.series_index)
        _add("episode_id", metadata.series_index)

    return lines


def _metadata_mp3_args(metadata: Optional["BookMetadata"]) -> list[str]:
    """
    Build ``-metadata key=value`` CLI args from a BookMetadata for the mp3 path.

    Mirrors _metadata_ffmetadata_lines but emits the ``-metadata`` flag pairs
    the per-chapter mp3 encoder expects (genre / date / album_artist / etc.).
    """
    if metadata is None:
        return []

    args: list[str] = []

    def _add(key: str, value: object) -> None:
        if value is None or value == "":
            return
        safe = _sanitize_metadata_value(str(value))
        args.extend(["-metadata", f"{key}={safe}"])

    _add("album_artist", metadata.narrator_name)
    _add("composer", metadata.narrator_name)
    _add("genre", metadata.genre)
    _add("date", metadata.year)
    _add("publisher", metadata.publisher)
    if metadata.series:
        _add("SERIES", metadata.series)
        _add("show", metadata.series)
    if metadata.series_index is not None:
        _add("SERIES-PART", metadata.series_index)
        _add("episode_id", metadata.series_index)

    return args


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
    metadata: Optional["BookMetadata"] = None,
    loudnorm_profile: str = "podcast",
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
        normalize: If True, run loudnorm mastering with ``loudnorm_profile``.
        metadata: Optional BookMetadata for full tagging (FT-RENDER-M-001):
            narrator → album_artist, genre, year → date, series → album +
            SERIES/SERIES-PART atoms.
        loudnorm_profile: 'podcast' (-16 LUFS, 24kHz) or 'acx' (-20 LUFS, TP
            -3, 44.1kHz). For 'acx', the sample rate is forced to 44.1kHz.

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

    # FT-ACX-001: profile drives sample rate (ACX requires 44.1kHz).
    profile = _resolve_loudnorm_profile(loudnorm_profile)
    sample_rate = profile["sample_rate"]

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
      header_lines = [f"title={safe_title}"]
      if author:
          safe_author = _escape_ffmpeg_metadata(_sanitize_metadata_value(author))
          header_lines.append(f"artist={safe_author}")
      # FT-RENDER-M-001: full tagging (narrator/genre/year/series/...)
      header_lines.extend(_metadata_ffmetadata_lines(metadata))
      # Insert header lines right after the ;FFMETADATA1 magic line.
      metadata_lines[1:1] = header_lines
      metadata_content = "\n".join(metadata_lines)

      metadata_path = temp_dir / "metadata.txt"
      metadata_path.write_text(metadata_content, encoding="utf-8")

      # FT-RENDER-008: Try single-pass FFmpeg assembly first
      # Build a concat list with silence gaps
      concat_list_path = temp_dir / "concat_list.txt"
      silence_path: Optional[Path] = None

      if chapter_pause_ms > 0 and len(audio_paths) > 1:
          silence_path = temp_dir / "silence.wav"
          _generate_silence_file(
              silence_path, chapter_pause_ms,
              sample_rate=int(sample_rate), runner=runner,
          )

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
          "-ar", sample_rate,
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
              "-ar", sample_rate,
              str(aac_path),
          ])

          if result.returncode != 0:
              raise RuntimeError(f"FFmpeg AAC conversion failed: {result.stderr}")

          encode_elapsed = _time.time() - encode_start
          logger.info(f"ASSEMBLY_ENCODE: AAC encoding completed in {encode_elapsed:.1f}s")

      # FT-RENDER-019 / FT-ACX-001: Audio normalization via the selected
      # loudnorm profile ('podcast' = EBU R128 -16 LUFS, 'acx' = -20 LUFS TP -3).
      if normalize:
          norm_path = temp_dir / "audio_normalized.m4a"
          loudnorm_filter = profile["loudnorm"]
          logger.info(
              f"ASSEMBLY_NORMALIZE: Running loudnorm filter "
              f"(profile={loudnorm_profile}, {loudnorm_filter})"
          )
          norm_result = runner.run([
              "ffmpeg", "-y",
              "-i", str(aac_path),
              "-af", loudnorm_filter,
              "-c:a", "aac",
              "-b:a", aac_bitrate,
              "-ar", sample_rate,
              str(norm_path),
          ])
          if norm_result.returncode == 0 and norm_path.exists():
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
    bitrate: str = "128k",
    metadata: Optional["BookMetadata"] = None,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
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
        bitrate: MP3 encoding bitrate (default: "128k").
        metadata: Optional BookMetadata for full tagging (FT-RENDER-M-001).
        loudnorm_profile: Mastering profile ('podcast' or 'acx').
        cover_art: Optional cover image path (embedded into each MP3).

    Returns:
        AssemblyResult pointing to the output directory.
    """
    output_dir = output_path.parent / output_path.stem
    mp3_paths = assemble_mp3_chapters(
        chapter_files, output_dir, title=title, author=author, runner=runner,
        bitrate=bitrate, metadata=metadata, loudnorm_profile=loudnorm_profile,
        cover_art=cover_art,
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
    bitrate: str = "128k",
    metadata: Optional["BookMetadata"] = None,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
) -> list[Path]:
    """
    Convert chapter audio files to MP3s (one per chapter).

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_dir: Output directory
        title: Book title (for filenames)
        runner: Optional FFmpegRunner for subprocess calls (defaults to RealFFmpegRunner).
        bitrate: MP3 encoding bitrate (default: "128k").
        metadata: Optional BookMetadata for full tagging (FT-RENDER-M-001):
            genre / date / album_artist / series tags applied to every chapter.
        loudnorm_profile: Mastering profile ('podcast' = -16 LUFS / 24kHz,
            'acx' = -20 LUFS / TP -3 / 44.1kHz). Drives the sample rate.
        cover_art: Optional cover image path (embedded into each MP3).

    Returns:
        List of MP3 file paths
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg is required for MP3 conversion.")

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    profile = _resolve_loudnorm_profile(loudnorm_profile)
    sample_rate = profile["sample_rate"]

    cover_ok = bool(cover_art and Path(cover_art).exists())
    if cover_art and not cover_ok:
        logger.warning(
            f"Cover art not embedded — file not found: {cover_art}. "
            f"MP3 output will have no cover image."
        )

    # FT-RENDER-M-001: shared metadata args reused across every chapter.
    extra_metadata = _metadata_mp3_args(metadata)

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
        ]
        if cover_ok:
            cmd.extend(["-i", str(cover_art)])
        cmd.extend([
            "-c:a", "libmp3lame",
            "-b:a", bitrate,
            "-ar", sample_rate,
            "-metadata", f"title={safe_chapter_title}",
            "-metadata", f"album={safe_album}",
            "-metadata", f"track={i+1}",
        ])
        if author:
            safe_author = _sanitize_metadata_value(author)
            cmd.extend(["-metadata", f"artist={safe_author}"])
        cmd.extend(extra_metadata)
        if cover_ok:
            # Map both streams, mark the image as the attached cover.
            cmd.extend([
                "-map", "0:a",
                "-map", "1:v",
                "-c:v", "copy",
                "-disposition:v", "attached_pic",
            ])
        cmd.append(str(mp3_path))

        result = runner.run(cmd)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg MP3 conversion failed: {result.stderr}")

        mp3_paths.append(mp3_path)

    return mp3_paths


# ---------------------------------------------------------------------------
# FT-RENDER-M-006: Opus + FLAC single-file assemblers
# ---------------------------------------------------------------------------

def _concat_to_single(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    chapter_pause_ms: int,
    codec_args: list[str],
    *,
    runner: "FFmpegRunner",
    sample_rate: str,
    metadata: Optional["BookMetadata"],
    title: str,
    author: str,
    cover_art: Optional[str] = None,
    embed_cover: bool = False,
) -> AssemblyResult:
    """
    Shared concat → single-file encode helper for opus/flac.

    Builds the silence-padded concat list, encodes with ``codec_args``,
    then muxes chapter markers + tags. Returns an AssemblyResult; on a
    chapter-mux failure, falls back to the codec-only file (no chapters).
    """
    import time as _time

    with tempfile.TemporaryDirectory(prefix="audiobooker_assemble_") as _temp_str:
        temp_dir = Path(_temp_str)
        start = _time.time()

        audio_paths = [p for p, _, _ in chapter_files]

        # Build the silence-padded concat list (single reusable silence file).
        concat_list_path = temp_dir / "concat_list.txt"
        silence_path: Optional[Path] = None
        if chapter_pause_ms > 0 and len(audio_paths) > 1:
            silence_path = temp_dir / "silence.wav"
            _generate_silence_file(
                silence_path, chapter_pause_ms,
                sample_rate=int(sample_rate), runner=runner,
            )

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for idx, audio_path in enumerate(audio_paths):
                escaped = _escape_concat_path(audio_path.absolute().as_posix())
                f.write(f"file '{escaped}'\n")
                if idx < len(audio_paths) - 1 and silence_path is not None:
                    escaped_silence = _escape_concat_path(silence_path.absolute().as_posix())
                    f.write(f"file '{escaped_silence}'\n")

        # Chapter + book metadata file.
        metadata_content = generate_chapter_metadata(chapter_files, chapter_pause_ms)
        safe_title = _escape_ffmpeg_metadata(_sanitize_metadata_value(title))
        header_lines = [f"title={safe_title}"]
        if author:
            safe_author = _escape_ffmpeg_metadata(_sanitize_metadata_value(author))
            header_lines.append(f"artist={safe_author}")
        header_lines.extend(_metadata_ffmetadata_lines(metadata))
        metadata_lines = metadata_content.split("\n")
        metadata_lines[1:1] = header_lines
        metadata_path = temp_dir / "metadata.txt"
        metadata_path.write_text("\n".join(metadata_lines), encoding="utf-8")

        # Encode the concatenated audio to the target codec.
        encoded_path = temp_dir / f"encoded{output_path.suffix}"
        encode_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            *codec_args,
            "-ar", sample_rate,
            str(encoded_path),
        ]
        result = runner.run(encode_cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg {output_path.suffix} encode failed: {result.stderr}"
            )

        # Mux chapter markers + tags (copy the already-encoded stream).
        cover_ok = bool(embed_cover and cover_art and Path(cover_art).exists())
        if embed_cover and cover_art and not cover_ok:
            logger.warning(
                f"Cover art not embedded — file not found: {cover_art}."
            )

        mux_cmd = [
            "ffmpeg", "-y",
            "-i", str(encoded_path),
            "-i", str(metadata_path),
        ]
        if cover_ok:
            mux_cmd.extend(["-i", str(cover_art)])
            mux_cmd.extend([
                "-map", "0:a",
                "-map", "2:v",
                "-map_metadata", "1",
                "-c:a", "copy",
                "-c:v", "copy",
                "-disposition:v", "attached_pic",
            ])
        else:
            mux_cmd.extend([
                "-map", "0:a",
                "-map_metadata", "1",
                "-c", "copy",
            ])
        mux_cmd.append(str(output_path))

        result = runner.run(mux_cmd)
        elapsed = _time.time() - start

        if result.returncode != 0:
            stderr_tail = "\n".join(result.stderr.strip().splitlines()[-20:])
            logger.warning(
                "Chapter embedding failed, producing %s without chapters.\n"
                "FFmpeg stderr (last 20 lines):\n%s",
                output_path.suffix, stderr_tail,
            )
            if encoded_path.exists():
                shutil.copy(encoded_path, output_path)
            return AssemblyResult(
                output_path=output_path,
                chapters_embedded=False,
                chapter_error=stderr_tail,
            )

        logger.info(f"ASSEMBLY_TOTAL ({output_path.suffix}): completed in {elapsed:.1f}s")
        return AssemblyResult(output_path=output_path, chapters_embedded=True)


def assemble_opus(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
    bitrate: str = "48k",
    metadata: Optional["BookMetadata"] = None,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
) -> AssemblyResult:
    """
    FT-RENDER-M-006: Assemble chapters into a single Opus (Ogg) audiobook.

    Opus is a highly efficient speech codec — ~48 kbps is transparent for
    spoken word. Chapters are concatenated with silence gaps and chapter
    markers are written into the Ogg container via the FFMETADATA chapter
    block (players that read Ogg chapter comments pick them up; otherwise
    the markers degrade gracefully to a single track).

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Output .opus / .ogg path.
        title: Book title.
        author: Book author.
        chapter_pause_ms: Pause between chapters.
        runner: Optional FFmpegRunner.
        bitrate: Opus bitrate (default "48k", tuned for speech).
        metadata: Optional BookMetadata for full tagging.
        loudnorm_profile: Mastering profile ('podcast' or 'acx') — drives
            the output sample rate.

    Returns:
        AssemblyResult.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for Opus assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )
    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    profile = _resolve_loudnorm_profile(loudnorm_profile)
    output_path = Path(output_path)

    return _concat_to_single(
        chapter_files, output_path, chapter_pause_ms,
        codec_args=["-c:a", "libopus", "-b:a", bitrate],
        runner=runner,
        sample_rate=profile["sample_rate"],
        metadata=metadata,
        title=title,
        author=author,
        cover_art=cover_art,
        embed_cover=False,  # Opus cover art is unreliable across players
    )


def assemble_flac(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
    metadata: Optional["BookMetadata"] = None,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
    # bitrate is accepted for assembler-selection symmetry but ignored —
    # FLAC is lossless and has no target bitrate.
    bitrate: Optional[str] = None,
) -> AssemblyResult:
    """
    FT-RENDER-M-006: Assemble chapters into a single lossless FLAC audiobook.

    FLAC is lossless — there is no bitrate to set; the ``bitrate`` kwarg is
    accepted only so the assembler-selection code can pass it uniformly. The
    cover image is embedded as an attached picture when provided.

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Output .flac path.
        title: Book title.
        author: Book author.
        chapter_pause_ms: Pause between chapters.
        runner: Optional FFmpegRunner.
        metadata: Optional BookMetadata for full tagging.
        loudnorm_profile: Mastering profile ('podcast' or 'acx') — drives
            the output sample rate.
        cover_art: Optional cover image path (embedded as attached picture).

    Returns:
        AssemblyResult.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for FLAC assembly. "
            "Install from: https://ffmpeg.org/download.html"
        )
    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    profile = _resolve_loudnorm_profile(loudnorm_profile)
    output_path = Path(output_path)

    return _concat_to_single(
        chapter_files, output_path, chapter_pause_ms,
        codec_args=["-c:a", "flac"],
        runner=runner,
        sample_rate=profile["sample_rate"],
        metadata=metadata,
        title=title,
        author=author,
        cover_art=cover_art,
        embed_cover=True,
    )


# ---------------------------------------------------------------------------
# FT-RENDER-M-007: Chapter-per-file AAC (.m4a) split + index playlist
# ---------------------------------------------------------------------------

def assemble_m4a_split(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
    aac_bitrate: str = "128k",
    bitrate: Optional[str] = None,
    metadata: Optional["BookMetadata"] = None,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
) -> AssemblyResult:
    """
    FT-RENDER-M-007: Emit one .m4a per chapter plus an index playlist.

    Mirrors the assemble_mp3 per-chapter pattern but for AAC: each chapter
    becomes ``NN_Title.m4a`` with track/album/artist tags, written into a
    directory named after ``output_path`` (extension stripped). A ``.m3u``
    index playlist lists the files in order.

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Base output path (a directory is created from its stem).
        title: Book title (album tag).
        author: Book author (artist tag).
        chapter_pause_ms: Unused (each chapter is a separate file).
        runner: Optional FFmpegRunner.
        aac_bitrate: AAC bitrate (default "128k"). ``bitrate`` is accepted as
            an alias so the assembler-selection code can pass it uniformly.
        metadata: Optional BookMetadata for full tagging.
        loudnorm_profile: Mastering profile ('podcast' or 'acx').
        cover_art: Optional cover image (embedded into each .m4a).

    Returns:
        AssemblyResult pointing to the output directory.
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg is required for AAC chapter split.")
    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    effective_bitrate = bitrate or aac_bitrate
    profile = _resolve_loudnorm_profile(loudnorm_profile)
    sample_rate = profile["sample_rate"]

    cover_ok = bool(cover_art and Path(cover_art).exists())
    if cover_art and not cover_ok:
        logger.warning(
            f"Cover art not embedded — file not found: {cover_art}."
        )
    extra_metadata = _metadata_mp3_args(metadata)

    output_dir = output_path.parent / output_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_album = _sanitize_metadata_value(title)
    m4a_paths: list[Path] = []

    for i, (audio_path, chapter_title, _) in enumerate(chapter_files):
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in chapter_title)
        m4a_path = output_dir / f"{i+1:02d}_{safe_name}.m4a"
        safe_chapter_title = _sanitize_metadata_value(chapter_title)

        cmd = ["ffmpeg", "-y", "-i", str(audio_path)]
        if cover_ok:
            cmd.extend(["-i", str(cover_art)])
        cmd.extend([
            "-c:a", "aac",
            "-b:a", effective_bitrate,
            "-ar", sample_rate,
            "-metadata", f"title={safe_chapter_title}",
            "-metadata", f"album={safe_album}",
            "-metadata", f"track={i+1}",
        ])
        if author:
            cmd.extend(["-metadata", f"artist={_sanitize_metadata_value(author)}"])
        cmd.extend(extra_metadata)
        if cover_ok:
            cmd.extend([
                "-map", "0:a",
                "-map", "1:v",
                "-c:v", "copy",
                "-disposition:v", "attached_pic",
            ])
        cmd.append(str(m4a_path))

        result = runner.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg AAC chapter encode failed: {result.stderr}")
        m4a_paths.append(m4a_path)

    # Index playlist (mirrors the mp3 _playlist.m3u pattern).
    playlist = output_dir / "_playlist.m3u"
    playlist.write_text(
        "\n".join(p.name for p in m4a_paths),
        encoding="utf-8",
    )

    return AssemblyResult(output_path=output_dir, chapters_embedded=True)


# ---------------------------------------------------------------------------
# FT-ACX-001: Master check (loudness / peak / noise-floor measurement)
# ---------------------------------------------------------------------------

def _parse_loudnorm_json(stderr: str) -> Optional[dict]:
    """Extract the trailing JSON object printed by loudnorm print_format=json."""
    # loudnorm prints its JSON report as the last {...} block on stderr.
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(stderr[start:end + 1])
    except json.JSONDecodeError:
        return None


def _parse_astats_floor_db(stderr: str) -> Optional[float]:
    """Extract the overall noise-floor (min level, dB) from astats output."""
    # astats prints e.g. "Noise floor dB: -72.345678" in the Overall section.
    matches = re.findall(r"Noise floor dB:\s*(-?\d+(?:\.\d+)?)", stderr)
    if matches:
        try:
            # Use the last (Overall) reading.
            return float(matches[-1])
        except ValueError:
            return None
    return None


def master_check(
    file_path: Union[str, Path],
    profile: str = "acx",
    *,
    runner: Optional["FFmpegRunner"] = None,
) -> dict:
    """
    FT-ACX-001: Measure an audio file against retail mastering limits.

    Runs ffmpeg loudnorm (print_format=json) for integrated loudness +
    true-peak, and astats for the noise floor, then evaluates them against
    the ACX retail spec:

        - RMS / integrated loudness in [-23, -18] dB
        - true peak <= -3 dBTP
        - noise floor <= -60 dB

    Args:
        file_path: Path to the audio file to check.
        profile: Limit profile (only 'acx' is enforced today; other values
            still measure but mark themselves informational).
        runner: Optional FFmpegRunner (for testing).

    Returns:
        Dict with keys:
            profile, measured_rms_db, measured_peak_db,
            measured_noise_floor_db, passes (bool), failures (list[str]).
        On a missing/broken ffmpeg or unreadable file, ``passes`` is False
        and ``failures`` carries a clear, structured reason (never raises).
    """
    file_path = Path(file_path)

    result: dict = {
        "profile": profile,
        "measured_rms_db": None,
        "measured_peak_db": None,
        "measured_noise_floor_db": None,
        "passes": False,
        "failures": [],
    }

    if not check_ffmpeg():
        result["failures"].append(
            "ffmpeg not found on PATH — cannot measure loudness. "
            "Install from https://ffmpeg.org/download.html"
        )
        return result

    if not file_path.exists():
        result["failures"].append(f"File not found: {file_path}")
        return result

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    # --- Measurement pass 1: loudnorm (integrated loudness + true peak) ---
    loud = runner.run([
        "ffmpeg", "-hide_banner",
        "-i", str(file_path),
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ])
    report = _parse_loudnorm_json(loud.stderr)
    if report is None:
        result["failures"].append(
            "Could not parse loudness measurement from ffmpeg output "
            "(file may be empty, corrupt, or not audio)."
        )
        return result

    def _to_float(value: object) -> Optional[float]:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    measured_i = _to_float(report.get("input_i"))
    measured_tp = _to_float(report.get("input_tp"))
    result["measured_rms_db"] = measured_i
    result["measured_peak_db"] = measured_tp

    # --- Measurement pass 2: astats (noise floor) ---
    stats = runner.run([
        "ffmpeg", "-hide_banner",
        "-i", str(file_path),
        "-af", "astats=metadata=1",
        "-f", "null", "-",
    ])
    floor = _parse_astats_floor_db(stats.stderr)
    result["measured_noise_floor_db"] = floor

    # --- Evaluate against limits ---
    failures: list[str] = []
    is_acx = profile == "acx"

    if measured_i is None:
        failures.append("Integrated loudness could not be measured.")
    elif is_acx and not (ACX_RMS_MIN_DB <= measured_i <= ACX_RMS_MAX_DB):
        failures.append(
            f"RMS/loudness {measured_i:.1f} dB is outside the ACX range "
            f"[{ACX_RMS_MIN_DB:.0f}, {ACX_RMS_MAX_DB:.0f}] dB."
        )

    if measured_tp is None:
        failures.append("True peak could not be measured.")
    elif is_acx and measured_tp > ACX_PEAK_MAX_DBTP:
        failures.append(
            f"Peak {measured_tp:.1f} dBTP exceeds the ACX ceiling "
            f"of {ACX_PEAK_MAX_DBTP:.0f} dBTP."
        )

    if floor is None:
        failures.append(
            "Noise floor could not be measured (astats produced no reading)."
        )
    elif is_acx and floor > ACX_NOISE_FLOOR_MAX_DB:
        failures.append(
            f"Noise floor {floor:.1f} dB is louder than the ACX limit "
            f"of {ACX_NOISE_FLOOR_MAX_DB:.0f} dB."
        )

    result["failures"] = failures
    result["passes"] = not failures
    return result


# ---------------------------------------------------------------------------
# FT-CLI-007: Chapter metadata export (ffmetadata / CUE / JSON)
# ---------------------------------------------------------------------------

def export_chapter_metadata(
    chapters_or_durations: list,
    fmt: str = "ffmetadata",
    *,
    chapter_pause_ms: int = 2000,
    title: str = "Audiobook",
) -> str:
    """
    FT-CLI-007: Render chapter timing into a sidecar metadata format.

    Accepts the same chapter tuples ``generate_chapter_metadata`` consumes —
    a list of ``(audio_path, title, duration_seconds)`` — OR a list of
    ``(title, duration_seconds)`` pairs when no audio paths are handy.
    Computes cumulative start/end timings (including the inter-chapter pause)
    and serializes them as:

        - 'ffmetadata' — an FFMETADATA1 chapter block (ffmpeg ``-i`` ready)
        - 'cue'        — a CUE sheet (TRACK / TITLE / INDEX 01)
        - 'json'       — a JSON array of {index,title,start,end,duration}

    Args:
        chapters_or_durations: Chapter tuples (see above).
        fmt: One of 'ffmetadata', 'cue', 'json'.
        chapter_pause_ms: Inter-chapter pause used for cumulative timing.
        title: Album/title used in the CUE header.

    Returns:
        The file contents as a string.

    Raises:
        ValueError: If ``fmt`` is not a supported format.
    """
    fmt = fmt.lower()
    if fmt not in ("ffmetadata", "cue", "json"):
        raise ValueError(
            f"Unknown chapter metadata format {fmt!r}. "
            "Must be one of: ffmetadata, cue, json."
        )

    # Normalize entries into (title, duration) computing start/end timings.
    normalized: list[dict] = []
    current_ms = 0
    for i, entry in enumerate(chapters_or_durations):
        if len(entry) == 3:
            _path, ch_title, duration = entry
        elif len(entry) == 2:
            ch_title, duration = entry
        else:
            raise ValueError(
                f"Chapter entry {i} must be a (title, duration) or "
                f"(path, title, duration) tuple, got {entry!r}."
            )
        duration = float(duration or 0.0)
        duration_ms = int(duration * 1000)
        start_ms = current_ms
        end_ms = current_ms + duration_ms
        normalized.append({
            "index": i,
            "title": str(ch_title),
            "start": start_ms / 1000.0,
            "end": end_ms / 1000.0,
            "duration": duration,
            "_start_ms": start_ms,
            "_end_ms": end_ms,
        })
        current_ms = end_ms + chapter_pause_ms

    if fmt == "json":
        return json.dumps(
            [
                {k: v for k, v in entry.items() if not k.startswith("_")}
                for entry in normalized
            ],
            indent=2,
            ensure_ascii=False,
        )

    if fmt == "ffmetadata":
        lines = [";FFMETADATA1"]
        for entry in normalized:
            lines.append("[CHAPTER]")
            lines.append("TIMEBASE=1/1000")
            lines.append(f"START={entry['_start_ms']}")
            lines.append(f"END={entry['_end_ms']}")
            lines.append(f"title={_escape_ffmpeg_metadata(entry['title'])}")
            lines.append("")
        return "\n".join(lines)

    # fmt == "cue"
    def _cue_timestamp(seconds: float) -> str:
        # CUE uses MM:SS:FF where FF is frames (75 per second).
        total_frames = int(round(seconds * 75))
        minutes = total_frames // (75 * 60)
        rem = total_frames % (75 * 60)
        secs = rem // 75
        frames = rem % 75
        return f"{minutes:02d}:{secs:02d}:{frames:02d}"

    cue_lines = [
        f'TITLE "{_sanitize_metadata_value(title)}"',
        'FILE "audiobook.wav" WAVE',
    ]
    for entry in normalized:
        cue_lines.append(f"  TRACK {entry['index'] + 1:02d} AUDIO")
        cue_lines.append(f'    TITLE "{_sanitize_metadata_value(entry["title"])}"')
        cue_lines.append(f"    INDEX 01 {_cue_timestamp(entry['start'])}")
    return "\n".join(cue_lines) + "\n"


# ---------------------------------------------------------------------------
# FT-RENDER-M-008: Podcast RSS feed (iTunes RSS 2.0)
# ---------------------------------------------------------------------------

def _itunes_duration(seconds: float) -> str:
    """Format a duration in seconds as HH:MM:SS for <itunes:duration>."""
    total = int(round(max(0.0, float(seconds or 0.0))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _rss_pubdate(value: object) -> str:
    """Coerce a pubDate input into an RFC 822 date string.

    Accepts a datetime, an already-formatted RFC 822 string, or None (which
    falls back to 'now' in UTC). Naive datetimes are assumed UTC.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return format_datetime(datetime.now(timezone.utc))


def _item_get(item: object, key: str, default: object = None) -> object:
    """Read ``key`` from an RSS item that may be a dict or an attribute object."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def export_podcast_rss(
    project: "AudiobookProject",
    items: list,
    *,
    base_url: str = "",
) -> str:
    """
    FT-RENDER-M-008: Build an iTunes-compatible RSS 2.0 podcast feed.

    Pure string builder — does no I/O. The channel is populated from the
    project's title/author and its ``BookMetadata`` (genre → itunes:category,
    narrator → itunes:author/owner, publisher, year). One ``<item>`` is emitted
    per chapter with an ``<itunes:duration>``, an ``<enclosure>`` whose ``url``
    is ``base_url + filename``, the enclosure ``length`` (bytes), and a
    ``pubDate``.

    Args:
        project: AudiobookProject supplying title/author/metadata.
        items: One entry per chapter. Each entry may be a dict or an object
            exposing these fields:
                - ``title`` (str, required-ish; defaults to "Chapter N")
                - ``filename`` (str) — appended to ``base_url`` for the enclosure
                - ``duration_seconds`` (float) — for ``<itunes:duration>``
                - ``length`` (int) — enclosure byte length (default 0)
                - ``pubdate`` (datetime | RFC-822 str | None)
                - ``description`` (str, optional)
                - ``guid`` (str, optional; defaults to the enclosure URL)
                - ``mime_type`` (str, optional; inferred from the filename ext)
        base_url: Prefix joined to each item's ``filename`` to form the
            enclosure URL (e.g. "https://example.com/feed/"). Empty by default.

    Returns:
        The complete RSS 2.0 XML document as a string.
    """
    metadata = getattr(project, "metadata", None)
    title = getattr(project, "title", "") or "Audiobook"
    author = getattr(project, "author", "") or ""
    narrator = getattr(metadata, "narrator_name", "") if metadata else ""
    genre = getattr(metadata, "genre", "") if metadata else ""
    publisher = getattr(metadata, "publisher", "") if metadata else ""
    # itunes:author is the credited voice — prefer the narrator, fall back to
    # the book author so the feed always carries an author.
    itunes_author = narrator or author

    def esc(value: object) -> str:
        return _xml_escape("" if value is None else str(value))

    def join_url(prefix: str, name: str) -> str:
        if not prefix:
            return name
        if prefix.endswith("/") or not name:
            return f"{prefix}{name}"
        return f"{prefix}/{name}"

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" '
        'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "  <channel>",
        f"    <title>{esc(title)}</title>",
        f"    <link>{esc(base_url)}</link>",
        f"    <language>{esc(getattr(getattr(project, 'config', None), 'language_code', '') or 'en')}</language>",
    ]

    book_description = author and f"{title} by {author}" or title
    lines.append(f"    <description>{esc(book_description)}</description>")

    if itunes_author:
        lines.append(f"    <itunes:author>{esc(itunes_author)}</itunes:author>")
        lines.append("    <itunes:owner>")
        lines.append(f"      <itunes:name>{esc(itunes_author)}</itunes:name>")
        lines.append("    </itunes:owner>")
    if publisher:
        lines.append(f"    <copyright>{esc(publisher)}</copyright>")
    if genre:
        lines.append(f'    <itunes:category text="{esc(genre)}"/>')
    lines.append("    <itunes:explicit>false</itunes:explicit>")

    for i, item in enumerate(items):
        ch_title = _item_get(item, "title") or f"Chapter {i + 1}"
        filename = _item_get(item, "filename", "") or ""
        duration_s = _item_get(item, "duration_seconds", 0.0) or 0.0
        length = int(_item_get(item, "length", 0) or 0)
        description = _item_get(item, "description", "")
        url = join_url(base_url, str(filename))
        guid = _item_get(item, "guid") or url
        mime_type = _item_get(item, "mime_type") or _guess_audio_mime(str(filename))
        pubdate = _rss_pubdate(_item_get(item, "pubdate"))

        lines.append("    <item>")
        lines.append(f"      <title>{esc(ch_title)}</title>")
        if description:
            lines.append(f"      <description>{esc(description)}</description>")
        lines.append(
            f'      <enclosure url="{esc(url)}" '
            f'length="{length}" type="{esc(mime_type)}"/>'
        )
        lines.append(f'      <guid isPermaLink="false">{esc(guid)}</guid>')
        lines.append(f"      <pubDate>{esc(pubdate)}</pubDate>")
        lines.append(
            f"      <itunes:duration>{esc(_itunes_duration(duration_s))}</itunes:duration>"
        )
        lines.append("    </item>")

    lines.append("  </channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


# MIME types for podcast enclosures, keyed on the audio file extension.
_AUDIO_MIME_TYPES = {
    ".m4b": "audio/x-m4b",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".opus": "audio/opus",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
}


def _guess_audio_mime(filename: str) -> str:
    """Best-effort audio MIME type from a filename extension (default mp3)."""
    ext = Path(filename).suffix.lower()
    return _AUDIO_MIME_TYPES.get(ext, "audio/mpeg")
