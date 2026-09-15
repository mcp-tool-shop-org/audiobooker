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
import wave
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
    # Whether loudness mastering actually ran and produced the shipped file.
    # A best-effort loudnorm pass that failed used to log a warning and ship
    # the UN-normalized audio as a finished master, with nothing on this
    # object for the caller to check. Defaults to True so assemblers that do
    # no mastering (and every existing construction site) are unaffected.
    mastering_applied: bool = True
    mastering_error: str = ""


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
            # See ffmpeg_runner._TEXT_KWARGS: without an explicit encoding the
            # locale codepage decodes ffmpeg's UTF-8 output and dies on CJK.
            encoding="utf-8",
            errors="replace",
        )
        _ffmpeg_checked = result.returncode == 0
    except OSError:
        # Not on PATH, not executable, bad interpreter — all "no ffmpeg".
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
            # ffprobe echoes the (possibly CJK) path back on stderr; decode it
            # as UTF-8 rather than the locale codepage. See check_ffmpeg().
            encoding="utf-8",
            errors="replace",
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if result.returncode != 0:
            # F-RENDER-B-002: Log warning on ffprobe failure instead of silent 0.0
            logger.warning(
                f"ffprobe failed for {audio_path} (rc={result.returncode}): "
                f"{stderr.strip()[:200]}"
            )
            return 0.0
        return float(stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError) as e:
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


# Suffixes ffmpeg will infer a muxer from. Anything else (``.tmp``,
# ``.wav.tmp``) needs an explicit ``-f``.
_FFMPEG_KNOWN_AUDIO_SUFFIXES = frozenset({
    ".wav", ".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".opus", ".aac",
    ".wma", ".aiff", ".aif",
})


def _ffmpeg_output_format_args(output_path: Path) -> list[str]:
    """Return ``['-f', muxer]`` when the path suffix is not a known format.

    F-671abba9: ffmpeg infers the muxer from the output extension. A concat
    or silence target ending in ``.wav.tmp`` (or bare ``.tmp``) fails with
    "Unable to find a suitable output format" — the same class of bug the
    utterance stitch already closed with ``-f wav``.
    """
    suffix = output_path.suffix.lower()
    if suffix in _FFMPEG_KNOWN_AUDIO_SUFFIXES:
        return []
    # Concat of chapter WAVs is itself a WAV, regardless of temp suffix.
    return ["-f", "wav"]


def _write_silence_wav(path: Path, duration_ms: int, like: Path) -> Path:
    """Write ``duration_ms`` of silence matching ``like``'s WAV format.

    F-671abba9 / FEAT-PROD-011: concat ``-c copy`` refuses mixed streams, so
    inter-chapter silence must copy nchannels/sampwidth/framerate off a real
    neighbour rather than a profile integer (ACX 44100 vs typical TTS 24000).
    """
    with wave.open(str(like), "rb") as src:
        nchannels = src.getnchannels()
        sampwidth = src.getsampwidth()
        framerate = src.getframerate()

    nframes = int(round(framerate * duration_ms / 1000.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as dst:
        dst.setnchannels(nchannels)
        dst.setsampwidth(sampwidth)
        dst.setframerate(framerate)
        dst.writeframes(b"\x00" * (nframes * nchannels * sampwidth))
    return path


def _generate_silence_file(
    output_path: Path,
    pause_ms: int,
    sample_rate: int = 24000,
    runner: Optional["FFmpegRunner"] = None,
    *,
    like: Optional[Path] = None,
) -> Path:
    """
    FT-RENDER-014: Generate a single reusable silence WAV file.

    Args:
        output_path: Where to write the silence file.
        pause_ms: Duration of silence in milliseconds.
        sample_rate: Fallback rate when ``like`` is not a readable WAV.
        runner: Optional FFmpegRunner.
        like: A neighbour chapter WAV whose format the silence must match.
            Preferred over ``sample_rate`` so concat ``-c copy`` succeeds.

    Returns:
        Path to generated silence file.
    """
    if like is not None:
        try:
            return _write_silence_wav(output_path, pause_ms, like)
        except (OSError, wave.Error) as e:
            logger.warning(
                f"Could not match silence to {like} ({e}); falling back to lavfi"
            )

    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=mono:d={pause_ms / 1000}",
    ]
    cmd.extend(_ffmpeg_output_format_args(output_path))
    cmd.append(str(output_path))
    result = runner.run(cmd)
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
        sample_rate: Fallback sample rate if no neighbour WAV can be read
            (default: 24000 Hz). Silence is matched to the first chapter WAV
            when one exists.

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
        # FT-RENDER-014: Generate a single silence file, reused for all gaps.
        # Match the first chapter WAV's format so `-c copy` accepts the concat
        # (profile sample_rate is the OUTPUT rate, not the TTS WAV rate).
        if pause_ms > 0 and len(audio_files) > 1:
            tmp_silence = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            silence_path = Path(tmp_silence.name)
            tmp_silence.close()
            _generate_silence_file(
                silence_path, pause_ms, sample_rate, runner,
                like=audio_files[0],
            )
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
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
        ]
        concat_cmd.extend(_ffmpeg_output_format_args(output_path))
        concat_cmd.append(str(output_path))
        result = runner.run(concat_cmd)

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

def _measure_loudnorm_input(
    input_args: list[str],
    loudnorm_filter: str,
    *,
    runner: "FFmpegRunner",
) -> Optional[dict]:
    """First half of the standard two-pass loudnorm flow, over any input.

    ``input_args`` is the ffmpeg input spec (e.g. ``["-i", "chapter.wav"]`` or
    ``["-f", "concat", "-safe", "0", "-i", "list.txt"]``). Returns the JSON
    report, or None when it cannot be measured (the caller then falls back to
    single-pass dynamic normalization).
    """
    probe = runner.run([
        "ffmpeg", "-hide_banner", "-y",
        *input_args,
        "-af", f"{loudnorm_filter}:print_format=json",
        "-f", "null", "-",
    ])
    if probe.returncode != 0:
        logger.info(
            f"ASSEMBLY_NORMALIZE_MEASURE: analysis pass returned "
            f"rc={probe.returncode}; falling back to single-pass loudnorm"
        )
        return None
    return _parse_loudnorm_json(probe.stderr or "")


def _measure_loudnorm(
    concat_list_path: Path,
    loudnorm_filter: str,
    *,
    runner: "FFmpegRunner",
) -> Optional[dict]:
    """Two-pass loudnorm measurement over a concat list (see above)."""
    return _measure_loudnorm_input(
        ["-f", "concat", "-safe", "0", "-i", str(concat_list_path)],
        loudnorm_filter,
        runner=runner,
    )


def _plan_loudnorm_args(
    input_args: list[str],
    profile: dict[str, str],
    profile_name: str,
    *,
    runner: "FFmpegRunner",
) -> list[str]:
    """Build the ``-af`` args for a two-pass loudnorm over ``input_args``.

    RH-B-001: this used to exist only inside ``assemble_m4b``. ``normalize``
    was therefore honoured for exactly one output format, and every other
    assembler shipped un-normalized audio — including ``--acx`` "retail
    masters" in mp3 / opus / flac / --split, which force normalization on.
    Factored out so every assembler runs the same mastering path.
    """
    base = profile["loudnorm"]
    measured = _measure_loudnorm_input(input_args, base, runner=runner)
    measured_filter = _loudnorm_second_pass_filter(base, measured) if measured else None
    if measured_filter:
        logger.info(
            f"ASSEMBLY_NORMALIZE: two-pass loudnorm "
            f"(profile={profile_name}, measured I={measured.get('input_i')})"
        )
        return ["-af", measured_filter]
    logger.info(
        f"ASSEMBLY_NORMALIZE: measurement pass produced no usable report; "
        f"falling back to single-pass dynamic loudnorm "
        f"(profile={profile_name}, {base})"
    )
    return ["-af", base]


def _log_mastering_failure(profile_name: str, message: str) -> None:
    """Report a loudnorm pass that failed — ERROR for acx, WARNING otherwise.

    An 'acx' render is a retail master: shipping it un-normalized is a defect,
    not a nicety, so it is never reported below ERROR.
    """
    log = logger.error if profile_name == "acx" else logger.warning
    log(
        f"ASSEMBLY_NORMALIZE_FAIL: {message} — continuing WITHOUT "
        f"normalization; the output will NOT be loudness-normalized"
        + (
            " and cannot meet the ACX retail spec."
            if profile_name == "acx"
            else "."
        )
    )


def _loudnorm_second_pass_filter(
    base_filter: str,
    measured: dict,
) -> Optional[str]:
    """Build the measured (second-pass) loudnorm filter string.

    Returns None when the report is missing a required field, so the caller can
    fall back rather than emit a half-populated filter.
    """
    required = ("input_i", "input_tp", "input_lra", "input_thresh")
    values: dict[str, float] = {}
    for key in required:
        try:
            values[key] = float(measured[key])
        except (KeyError, TypeError, ValueError):
            return None

    parts = [
        base_filter,
        f"measured_I={values['input_i']}",
        f"measured_TP={values['input_tp']}",
        f"measured_LRA={values['input_lra']}",
        f"measured_thresh={values['input_thresh']}",
        "linear=true",
    ]
    try:
        parts.append(f"offset={float(measured['target_offset'])}")
    except (KeyError, TypeError, ValueError):
        pass
    return ":".join(parts)


def _cue_quoted(value: str) -> str:
    """Body of a CUE-sheet quoted string.

    CUE has no escape sequence for a double quote inside a quoted string, so a
    title containing one (EPUB TOC entries routinely do — ``The "Quiet" Room``)
    terminates the string early and produces a malformed sheet that players
    reject or silently truncate. The interoperable convention, and what
    CD-ripping tools emit, is to fold the inner quotes to typographic quotes.
    """
    sanitized = _sanitize_metadata_value(str(value))
    return sanitized.replace('"', "”")


def _safe_chapter_filename(
    title: str,
    index: int,
    max_len: int = 60,
) -> str:
    """Filesystem-safe, length-bounded stem for a per-chapter output file.

    Chapter titles come from the EPUB TOC and are unbounded — a document whose
    "chapter title" is its first paragraph produced a path that blew past the
    OS limit (260 chars on Windows without long-path support) and failed the
    whole render at the last step. Trailing dots and spaces are illegal at the
    end of a Windows filename, and a title made entirely of punctuation
    collapses to an empty stem, so both fall back to ``chapter_NN``.
    """
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in str(title))
    cleaned = cleaned[:max_len]
    # Collapse the runs of underscores that punctuation-heavy titles produce,
    # then drop the trailing characters Windows will not accept.
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip(" ._-")
    if not cleaned:
        cleaned = f"chapter_{index + 1:02d}"
    return f"{index + 1:02d}_{cleaned}"


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
              like=audio_paths[0],
          )

      with open(concat_list_path, "w", encoding="utf-8") as f:
          for idx, audio_path in enumerate(audio_paths):
              escaped = _escape_concat_path(audio_path.absolute().as_posix())
              f.write(f"file '{escaped}'\n")
              if idx < len(audio_paths) - 1 and silence_path is not None:
                  escaped_silence = _escape_concat_path(silence_path.absolute().as_posix())
                  f.write(f"file '{escaped_silence}'\n")

      # Single-pass: concat → (optional loudnorm) → AAC encode → output.
      aac_path = temp_dir / "audio.m4a"
      encode_start = _time.time()

      # FT-RENDER-019 / FT-ACX-001: mastering belongs in THIS pass.
      # It used to run afterwards as an AAC→AAC re-encode, i.e. a second lossy
      # generation applied to already-quantized audio — the worst place to do
      # gain work. Filtering here operates on the lossless chapter WAVs and
      # encodes once. The standard loudnorm flow is also two-pass (measure,
      # then encode with the measured values); the single-pass dynamic mode it
      # used before is explicitly the lower-quality path.
      mastering_applied = True
      mastering_error = ""
      loudnorm_args: list[str] = []
      if normalize:
          base_loudnorm = profile["loudnorm"]
          measured = _measure_loudnorm(concat_list_path, base_loudnorm, runner=runner)
          measured_filter = (
              _loudnorm_second_pass_filter(base_loudnorm, measured) if measured else None
          )
          if measured_filter:
              logger.info(
                  f"ASSEMBLY_NORMALIZE: two-pass loudnorm "
                  f"(profile={loudnorm_profile}, measured I={measured.get('input_i')})"
              )
              loudnorm_args = ["-af", measured_filter]
          else:
              logger.info(
                  f"ASSEMBLY_NORMALIZE: measurement pass produced no usable "
                  f"report; falling back to single-pass dynamic loudnorm "
                  f"(profile={loudnorm_profile}, {base_loudnorm})"
              )
              loudnorm_args = ["-af", base_loudnorm]

      def _concat_encode(extra_filter_args: list[str]):
          return runner.run([
              "ffmpeg", "-y",
              "-f", "concat",
              "-safe", "0",
              "-i", str(concat_list_path),
              *extra_filter_args,
              "-c:a", "aac",
              "-b:a", aac_bitrate,
              "-ar", sample_rate,
              str(aac_path),
          ])

      result = _concat_encode(loudnorm_args)

      if result.returncode != 0 and loudnorm_args:
          # Mastering is what broke the pass. Keep the book — but record that
          # the shipped file is NOT normalized instead of logging a warning
          # nobody reads and returning a result that looks finished.
          mastering_applied = False
          mastering_error = (
              f"loudnorm pass failed (rc={result.returncode}, "
              f"profile={loudnorm_profile}): {(result.stderr or '')[:300]}"
          )
          log = logger.error if loudnorm_profile == "acx" else logger.warning
          log(
              f"ASSEMBLY_NORMALIZE_FAIL: {mastering_error} — retrying without "
              f"normalization; the output will NOT be loudness-normalized"
              + (
                  " and cannot meet the ACX retail spec."
                  if loudnorm_profile == "acx"
                  else "."
              )
          )
          loudnorm_args = []
          result = _concat_encode([])

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

          def _wav_encode(extra_filter_args: list[str]):
              return runner.run([
                  "ffmpeg", "-y",
                  "-i", str(concat_path),
                  *extra_filter_args,
                  "-c:a", "aac",
                  "-b:a", aac_bitrate,
                  "-ar", sample_rate,
                  str(aac_path),
              ])

          # Still a single encode from lossless audio — carry the mastering
          # filter here too rather than re-encoding the AAC afterwards.
          result = _wav_encode(loudnorm_args)
          if result.returncode != 0 and loudnorm_args:
              mastering_applied = False
              mastering_error = (
                  f"loudnorm pass failed (rc={result.returncode}, "
                  f"profile={loudnorm_profile}): {(result.stderr or '')[:300]}"
              )
              log = logger.error if loudnorm_profile == "acx" else logger.warning
              log(
                  f"ASSEMBLY_NORMALIZE_FAIL: {mastering_error} — encoding "
                  f"without normalization."
              )
              loudnorm_args = []
              result = _wav_encode([])

          if result.returncode != 0:
              raise RuntimeError(f"FFmpeg AAC conversion failed: {result.stderr}")

          encode_elapsed = _time.time() - encode_start
          logger.info(f"ASSEMBLY_ENCODE: AAC encoding completed in {encode_elapsed:.1f}s")

      if normalize and mastering_applied:
          logger.info("ASSEMBLY_NORMALIZE: Normalization complete")

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
              mastering_applied=mastering_applied,
              mastering_error=mastering_error,
          )

      return AssemblyResult(
          output_path=output_path,
          chapters_embedded=True,
          mastering_applied=mastering_applied,
          mastering_error=mastering_error,
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
    normalize: bool = False,
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
        normalize: If True, run loudness mastering on every chapter
            (RH-B-001).
        loudnorm_profile: Mastering profile ('podcast' or 'acx').
        cover_art: Optional cover image path (embedded into each MP3).

    Returns:
        AssemblyResult pointing to the output directory.
    """
    output_dir = output_path.parent / output_path.stem
    report: dict = {}
    mp3_paths = assemble_mp3_chapters(
        chapter_files, output_dir, title=title, author=author, runner=runner,
        bitrate=bitrate, metadata=metadata, normalize=normalize,
        loudnorm_profile=loudnorm_profile, cover_art=cover_art,
        mastering_report=report,
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
        mastering_applied=bool(report.get("mastering_applied", True)),
        mastering_error=str(report.get("mastering_error", "")),
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
    normalize: bool = False,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
    mastering_report: Optional[dict] = None,
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
        normalize: If True, run two-pass loudnorm mastering per chapter with
            ``loudnorm_profile`` (RH-B-001 — this used to be m4b-only, so
            ``--normalize --format mp3`` produced un-normalized audio).
        loudnorm_profile: Mastering profile ('podcast' = -16 LUFS / 24kHz,
            'acx' = -20 LUFS / TP -3 / 44.1kHz). Drives the sample rate.
        cover_art: Optional cover image path (embedded into each MP3).
        mastering_report: Optional dict this function populates with
            ``{"mastering_applied": bool, "mastering_error": str}`` so the
            caller (which only gets a list of paths back) can still tell
            whether the loudness pass actually ran.

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
    mastering_applied = True
    mastering_error = ""

    for i, (audio_path, chapter_title, _) in enumerate(chapter_files):
        # Sanitize + bound the filename (unbounded EPUB TOC titles blew the
        # OS path limit and failed the render at the last step).
        mp3_path = output_dir / f"{_safe_chapter_filename(chapter_title, i)}.mp3"

        safe_chapter_title = _sanitize_metadata_value(chapter_title)
        safe_album = _sanitize_metadata_value(title)

        # RH-B-001: mastering runs per chapter, from the lossless WAV, in the
        # same pass that encodes — never as a second lossy generation.
        loudnorm_args: list[str] = []
        if normalize:
            loudnorm_args = _plan_loudnorm_args(
                ["-i", str(audio_path)], profile, loudnorm_profile, runner=runner,
            )

        def _encode(extra_filter_args: list[str]):
            cmd = [
                "ffmpeg", "-y",
                "-i", str(audio_path),
            ]
            if cover_ok:
                cmd.extend(["-i", str(cover_art)])
            cmd.extend([
                *extra_filter_args,
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
            return runner.run(cmd)

        result = _encode(loudnorm_args)

        if result.returncode != 0 and loudnorm_args:
            # Mastering is what broke the pass. Keep the book, but RECORD that
            # the shipped audio is not normalized.
            mastering_applied = False
            mastering_error = (
                f"loudnorm pass failed on chapter {i + 1} "
                f"(rc={result.returncode}, profile={loudnorm_profile}): "
                f"{(result.stderr or '')[:300]}"
            )
            _log_mastering_failure(loudnorm_profile, mastering_error)
            result = _encode([])

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg MP3 conversion failed: {result.stderr}")

        mp3_paths.append(mp3_path)

    if mastering_report is not None:
        mastering_report["mastering_applied"] = mastering_applied
        mastering_report["mastering_error"] = mastering_error

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
    embed_chapters: bool = True,
    normalize: bool = False,
    loudnorm_profile_dict: Optional[dict[str, str]] = None,
    loudnorm_profile_name: str = "podcast",
) -> AssemblyResult:
    """
    Shared concat → single-file encode helper for opus/flac/wav.

    Builds the silence-padded concat list, optionally masters it with a
    two-pass loudnorm (RH-B-001 — ``normalize`` used to be honoured only by
    ``assemble_m4b``), encodes with ``codec_args``, then muxes chapter
    markers + tags. Returns an AssemblyResult; on a chapter-mux failure,
    falls back to the codec-only file (no chapters).
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
                like=audio_paths[0],
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

        # RH-B-001: master in THIS pass, from the lossless chapter WAVs.
        mastering_applied = True
        mastering_error = ""
        loudnorm_args: list[str] = []
        if normalize and loudnorm_profile_dict is not None:
            loudnorm_args = _plan_loudnorm_args(
                ["-f", "concat", "-safe", "0", "-i", str(concat_list_path)],
                loudnorm_profile_dict,
                loudnorm_profile_name,
                runner=runner,
            )

        # Encode the concatenated audio to the target codec.
        encoded_path = temp_dir / f"encoded{output_path.suffix}"

        def _encode(extra_filter_args: list[str]):
            return runner.run([
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list_path),
                *extra_filter_args,
                *codec_args,
                "-ar", sample_rate,
                str(encoded_path),
            ])

        result = _encode(loudnorm_args)
        if result.returncode != 0 and loudnorm_args:
            mastering_applied = False
            mastering_error = (
                f"loudnorm pass failed (rc={result.returncode}, "
                f"profile={loudnorm_profile_name}): {(result.stderr or '')[:300]}"
            )
            _log_mastering_failure(loudnorm_profile_name, mastering_error)
            loudnorm_args = []
            result = _encode([])
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg {output_path.suffix} encode failed: {result.stderr}"
            )

        # A container that cannot carry chapters must not be asked to.
        # WAV has no chapter atom, so the mux below would shell out to ffmpeg
        # and fail on EVERY render, then fall back to this same file while
        # logging a warning and an ffmpeg stderr dump. Reporting
        # chapters_embedded=False with no chapter_error says the true thing:
        # nothing went wrong, the format simply has nowhere to put them.
        if not embed_chapters:
            shutil.copy(encoded_path, output_path)
            elapsed = _time.time() - start
            logger.info(
                f"ASSEMBLY_TOTAL ({output_path.suffix}): completed in "
                f"{elapsed:.1f}s (no chapter markers - the format has no "
                f"chapter atom)"
            )
            return AssemblyResult(
                output_path=output_path,
                chapters_embedded=False,
                mastering_applied=mastering_applied,
                mastering_error=mastering_error,
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
                mastering_applied=mastering_applied,
                mastering_error=mastering_error,
            )

        logger.info(f"ASSEMBLY_TOTAL ({output_path.suffix}): completed in {elapsed:.1f}s")
        return AssemblyResult(
            output_path=output_path,
            chapters_embedded=True,
            mastering_applied=mastering_applied,
            mastering_error=mastering_error,
        )


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
    normalize: bool = False,
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
        normalize: If True, run two-pass loudnorm mastering with
            ``loudnorm_profile`` (RH-B-001).
        loudnorm_profile: Mastering profile ('podcast' or 'acx') — drives
            the output sample rate and the loudness target.

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
        normalize=normalize,
        loudnorm_profile_dict=profile,
        loudnorm_profile_name=loudnorm_profile,
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
    normalize: bool = False,
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
        normalize: If True, run two-pass loudnorm mastering with
            ``loudnorm_profile`` (RH-B-001).
        loudnorm_profile: Mastering profile ('podcast' or 'acx') — drives
            the output sample rate and the loudness target.
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
        normalize=normalize,
        loudnorm_profile_dict=profile,
        loudnorm_profile_name=loudnorm_profile,
    )


def assemble_wav(
    chapter_files: list[tuple[Path, str, float]],
    output_path: Path,
    title: str = "Audiobook",
    author: str = "",
    chapter_pause_ms: int = 2000,
    *,
    runner: Optional["FFmpegRunner"] = None,
    metadata: Optional["BookMetadata"] = None,
    normalize: bool = False,
    loudnorm_profile: str = "podcast",
    cover_art: Optional[str] = None,
    # Accepted for assembler-selection symmetry and ignored: PCM is
    # uncompressed and has no target bitrate.
    bitrate: Optional[str] = None,
) -> AssemblyResult:
    """
    F-7a3c91e2: assemble chapters into one uncompressed WAV.

    ``--format wav`` has been offered by every CLI allowlist since the first
    release and had no assembler. The dispatch's ``else`` branch sent it to
    ``assemble_m4b``, so it wrote AAC-in-MP4 bytes to a path ending ``.wav``
    -- a file most players reject and every DAW misreads.

    WAV carries no chapter markers and no cover art; both are skipped rather
    than attempted, and the AssemblyResult says so honestly instead of
    reporting a failure. Use m4b if you want chapters.

    Args:
        chapter_files: List of (audio_path, chapter_title, duration_seconds)
        output_path: Output .wav path.
        title: Book title (kept for signature symmetry; WAV has no tag atom).
        author: Book author (likewise).
        chapter_pause_ms: Pause between chapters.
        runner: Optional FFmpegRunner.
        metadata: Optional BookMetadata (unused -- WAV carries no tags).
        normalize: If True, run two-pass loudnorm mastering (RH-B-001).
        loudnorm_profile: Mastering profile ('podcast' or 'acx').
        cover_art: Ignored -- WAV cannot embed an attached picture.

    Returns:
        AssemblyResult with ``chapters_embedded=False`` and no chapter_error.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "FFmpeg is required for WAV assembly (the chapter files are "
            "concatenated and re-encoded to PCM). "
            "Install from: https://ffmpeg.org/download.html"
        )
    if runner is None:
        from audiobooker.renderer.ffmpeg_runner import RealFFmpegRunner
        runner = RealFFmpegRunner()

    if cover_art:
        logger.info(
            "Cover art is not embedded in WAV output - the format has no "
            "attached-picture stream. Use --format m4b or flac for cover art."
        )

    profile = _resolve_loudnorm_profile(loudnorm_profile)
    output_path = Path(output_path)

    return _concat_to_single(
        chapter_files, output_path, chapter_pause_ms,
        codec_args=["-c:a", "pcm_s16le"],
        runner=runner,
        sample_rate=profile["sample_rate"],
        metadata=metadata,
        title=title,
        author=author,
        cover_art=None,
        embed_cover=False,
        embed_chapters=False,
        normalize=normalize,
        loudnorm_profile_dict=profile,
        loudnorm_profile_name=loudnorm_profile,
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
    normalize: bool = False,
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
        normalize: If True, run two-pass loudnorm mastering on every chapter
            (RH-B-001 — ``--normalize --split`` used to produce completely
            un-normalized audio with no log line at any level).
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
    mastering_applied = True
    mastering_error = ""

    for i, (audio_path, chapter_title, _) in enumerate(chapter_files):
        m4a_path = output_dir / f"{_safe_chapter_filename(chapter_title, i)}.m4a"
        safe_chapter_title = _sanitize_metadata_value(chapter_title)

        # RH-B-001: --split used to drop `normalize` entirely, so an ACX
        # "retail master" split into per-chapter .m4a files shipped with no
        # loudness normalization at all.
        loudnorm_args: list[str] = []
        if normalize:
            loudnorm_args = _plan_loudnorm_args(
                ["-i", str(audio_path)], profile, loudnorm_profile, runner=runner,
            )

        def _encode(extra_filter_args: list[str]):
            cmd = ["ffmpeg", "-y", "-i", str(audio_path)]
            if cover_ok:
                cmd.extend(["-i", str(cover_art)])
            cmd.extend([
                *extra_filter_args,
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
            return runner.run(cmd)

        result = _encode(loudnorm_args)
        if result.returncode != 0 and loudnorm_args:
            mastering_applied = False
            mastering_error = (
                f"loudnorm pass failed on chapter {i + 1} "
                f"(rc={result.returncode}, profile={loudnorm_profile}): "
                f"{(result.stderr or '')[:300]}"
            )
            _log_mastering_failure(loudnorm_profile, mastering_error)
            result = _encode([])
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg AAC chapter encode failed: {result.stderr}")
        m4a_paths.append(m4a_path)

    # Index playlist (mirrors the mp3 _playlist.m3u pattern).
    playlist = output_dir / "_playlist.m3u"
    playlist.write_text(
        "\n".join(p.name for p in m4a_paths),
        encoding="utf-8",
    )

    return AssemblyResult(
        output_path=output_dir,
        chapters_embedded=True,
        mastering_applied=mastering_applied,
        mastering_error=mastering_error,
    )


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


def _parse_volumedetect_mean_db(stderr: str) -> Optional[float]:
    """Extract ``mean_volume`` (unweighted RMS, dBFS) from volumedetect output.

    This is the quantity ACX's spec actually gates on. ACX states its
    requirement as an RMS window ("between -23dB and -18dB RMS") and uses no
    loudness-standard vocabulary; ffmpeg's ``loudnorm`` reports ``input_i`` as
    EBU R128 *integrated loudness* in LUFS — K-weighted and gated, a different
    measurement that disagrees with RMS by several dB on speech. Audacity's
    ACX Check plugin and the open-source acx-rms tooling both measure plain
    RMS for this reason.
    """
    matches = re.findall(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", stderr)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            return None
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

    Runs three ffmpeg measurement passes and evaluates them against the ACX
    retail spec:

        - RMS in [-23, -18] dB   (volumedetect ``mean_volume``)
        - true peak <= -3 dBTP   (loudnorm ``input_tp``)
        - noise floor <= -60 dB  (astats)

    ACX publishes its loudness requirement as an **RMS** window and its noise
    floor as an **RMS** figure; it uses no loudness-standard vocabulary. This
    check previously compared loudnorm's ``input_i`` — EBU R128 integrated
    loudness in LUFS, K-weighted and gated — against that RMS window and
    printed PASS on a quantity ACX does not gate on. ``input_i`` is still
    measured and reported, under its correct name ``measured_lufs``.

    True peak is kept for the peak comparison: TP is stricter than ACX's plain
    "peak", so using it errs safe.

    Args:
        file_path: Path to the audio file to check.
        profile: Limit profile (only 'acx' is enforced today; other values
            still measure but mark themselves informational).
        runner: Optional FFmpegRunner (for testing).

    Returns:
        Dict with keys:
            profile, measured_rms_db, measured_lufs, rms_source,
            measured_peak_db, measured_noise_floor_db, passes (bool),
            failures (list[str]), warnings (list[str]).
        On a missing/broken ffmpeg or unreadable file, ``passes`` is False
        and ``failures`` carries a clear, structured reason (never raises).
    """
    file_path = Path(file_path)

    result: dict = {
        "profile": profile,
        "measured_rms_db": None,
        "measured_lufs": None,
        "rms_source": None,
        "measured_peak_db": None,
        "measured_noise_floor_db": None,
        "passes": False,
        "failures": [],
        "warnings": [],
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
    result["measured_lufs"] = measured_i
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

    # --- Measurement pass 3: volumedetect (unweighted RMS — what ACX gates on) ---
    vol = runner.run([
        "ffmpeg", "-hide_banner",
        "-i", str(file_path),
        "-af", "volumedetect",
        "-f", "null", "-",
    ])
    measured_rms = _parse_volumedetect_mean_db(vol.stderr)
    warnings: list[str] = []
    if measured_rms is not None:
        result["measured_rms_db"] = measured_rms
        result["rms_source"] = "volumedetect"
    else:
        # Degrade rather than refuse to report, but never let a LUFS number
        # masquerade as an RMS number without saying so.
        result["measured_rms_db"] = measured_i
        result["rms_source"] = "loudnorm-integrated-lufs-fallback"
        warnings.append(
            "volumedetect produced no mean_volume reading; the reported RMS is "
            "loudnorm's EBU R128 integrated loudness (LUFS), which is NOT the "
            "quantity ACX specifies. Treat the loudness verdict as advisory."
        )
    measured_rms_value = result["measured_rms_db"]

    # --- Evaluate against limits ---
    failures: list[str] = []
    is_acx = profile == "acx"

    if measured_rms_value is None:
        failures.append("Loudness could not be measured.")
    elif is_acx and not (ACX_RMS_MIN_DB <= measured_rms_value <= ACX_RMS_MAX_DB):
        failures.append(
            f"RMS {measured_rms_value:.1f} dB is outside the ACX range "
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
    result["warnings"] = warnings
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
        f'TITLE "{_cue_quoted(title)}"',
        'FILE "audiobook.wav" WAVE',
    ]
    for entry in normalized:
        cue_lines.append(f"  TRACK {entry['index'] + 1:02d} AUDIO")
        cue_lines.append(f'    TITLE "{_cue_quoted(entry["title"])}"')
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
