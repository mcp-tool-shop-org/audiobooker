"""
FT-TEST-003 + FT-TEST-007: Output assembly module tests.

Tests for FFmpeg metadata escaping, sanitization, chapter metadata
generation, and concat path escaping.
"""



from audiobooker.renderer.output import (
    _escape_ffmpeg_metadata,
    _sanitize_metadata_value,
    generate_chapter_metadata,
    _escape_concat_path,
)


# ---------------------------------------------------------------------------
# FT-TEST-003: _escape_ffmpeg_metadata
# ---------------------------------------------------------------------------

class TestEscapeFFmpegMetadata:
    """Tests for _escape_ffmpeg_metadata special-char handling."""

    def test_semicolons_escaped(self):
        """Semicolons are escaped with backslash."""
        assert _escape_ffmpeg_metadata("foo;bar") == "foo\\;bar"

    def test_backslashes_escaped(self):
        """Backslashes are escaped (and escape order is correct)."""
        assert _escape_ffmpeg_metadata("a\\b") == "a\\\\b"

    def test_hash_signs_escaped(self):
        """Hash signs are escaped."""
        assert _escape_ffmpeg_metadata("ch#1") == "ch\\#1"

    def test_newlines_escaped(self):
        """Newlines are escaped with backslash."""
        result = _escape_ffmpeg_metadata("line1\nline2")
        assert result == "line1\\\nline2"

    def test_backslash_then_semicolon(self):
        """Backslash before semicolon: both are escaped without double-escaping."""
        result = _escape_ffmpeg_metadata("a\\;b")
        # Backslash -> \\, then semicolon -> \;
        assert result == "a\\\\\\;b"

    def test_unicode_preserved(self):
        """Unicode characters (CJK, emoji) pass through untouched."""
        assert _escape_ffmpeg_metadata("Title: \u4e16\u754c") == "Title: \u4e16\u754c"

    def test_control_chars_stripped(self):
        """Non-printable control characters are stripped."""
        result = _escape_ffmpeg_metadata("hello\x00world\x7f")
        assert "\x00" not in result
        assert "\x7f" not in result
        assert "helloworld" in result

    def test_plain_text_unchanged(self):
        """Plain ASCII text passes through unchanged."""
        assert _escape_ffmpeg_metadata("Chapter 1") == "Chapter 1"


# ---------------------------------------------------------------------------
# FT-TEST-003: _sanitize_metadata_value
# ---------------------------------------------------------------------------

class TestSanitizeMetadataValue:
    """Tests for _sanitize_metadata_value."""

    def test_newlines_replaced_with_spaces(self):
        """Newlines and carriage returns are replaced with spaces."""
        result = _sanitize_metadata_value("line1\nline2\rline3")
        assert "\n" not in result
        assert "\r" not in result
        assert "line1" in result
        assert "line2" in result

    def test_control_chars_stripped(self):
        """Control characters are stripped."""
        result = _sanitize_metadata_value("hello\x00\x01\x1fworld")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "helloworld" in result

    def test_unicode_preserved(self):
        """Unicode is preserved."""
        assert _sanitize_metadata_value("\u00e9l\u00e8ve") == "\u00e9l\u00e8ve"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        assert _sanitize_metadata_value("  padded  ") == "padded"

    def test_plain_text_unchanged(self):
        """Normal text passes through."""
        assert _sanitize_metadata_value("My Audiobook") == "My Audiobook"


# ---------------------------------------------------------------------------
# FT-TEST-003: generate_chapter_metadata
# ---------------------------------------------------------------------------

class TestGenerateChapterMetadata:
    """Tests for generate_chapter_metadata."""

    def test_single_chapter(self, tmp_path):
        """Single chapter produces correct FFMETADATA1 block."""
        dummy = tmp_path / "ch0.wav"
        dummy.write_bytes(b"\x00")
        chapters = [(dummy, "Intro", 10.0)]
        result = generate_chapter_metadata(chapters, chapter_pause_ms=2000)

        assert result.startswith(";FFMETADATA1")
        assert "[CHAPTER]" in result
        assert "TIMEBASE=1/1000" in result
        assert "START=0" in result
        assert "END=10000" in result
        assert "title=Intro" in result

    def test_multiple_chapters_timing(self, tmp_path):
        """Multiple chapters have correct cumulative START/END with pauses."""
        dummy = tmp_path / "ch.wav"
        dummy.write_bytes(b"\x00")
        chapters = [
            (dummy, "Ch 1", 5.0),
            (dummy, "Ch 2", 3.0),
        ]
        result = generate_chapter_metadata(chapters, chapter_pause_ms=1000)

        # First chapter: START=0, END=5000
        assert "START=0" in result
        assert "END=5000" in result
        # Second chapter: START = 5000 + 1000 = 6000, END = 6000 + 3000 = 9000
        assert "START=6000" in result
        assert "END=9000" in result

    def test_special_chars_in_title(self, tmp_path):
        """Chapter titles with special chars are escaped."""
        dummy = tmp_path / "ch.wav"
        dummy.write_bytes(b"\x00")
        chapters = [(dummy, "Ch;1 #intro", 2.0)]
        result = generate_chapter_metadata(chapters)
        # Semicolons and hashes should be escaped
        assert "\\;" in result
        assert "\\#" in result


# ---------------------------------------------------------------------------
# FT-TEST-003 + FT-TEST-007: _escape_concat_path
# ---------------------------------------------------------------------------

class TestEscapeConcatPath:
    """Tests for _escape_concat_path with various path characters."""

    def test_single_quotes_escaped(self):
        """Single quotes are escaped for FFmpeg concat format."""
        result = _escape_concat_path("/path/it's/file.wav")
        assert "'" in result
        # FFmpeg concat escaping: ' -> '\''
        assert "'\\''s" in result

    def test_double_quotes_unchanged(self):
        """Double quotes pass through (only single quotes need escaping)."""
        result = _escape_concat_path('/path/to/"file".wav')
        assert '"file"' in result

    def test_spaces_unchanged(self):
        """Spaces pass through (the concat file uses 'file ...' quoting)."""
        result = _escape_concat_path("/path/my file.wav")
        assert "my file" in result

    def test_windows_backslashes_unchanged(self):
        """Backslashes (Windows paths) pass through _escape_concat_path.

        Note: concatenate_audio_files uses .as_posix() before calling this,
        so backslashes only appear in raw test inputs, not real usage.
        """
        result = _escape_concat_path("C:\\Users\\me\\file.wav")
        assert "C:\\Users\\me\\file.wav" == result

    def test_unicode_path(self):
        """Unicode in paths passes through unchanged."""
        result = _escape_concat_path("/path/\u00e9t\u00e9/audio.wav")
        assert "\u00e9t\u00e9" in result

    def test_multiple_single_quotes(self):
        """Multiple single quotes are all escaped."""
        result = _escape_concat_path("it's a cat's life.wav")
        # Each ' should become '\''
        assert result.count("'\\''") == 2

    def test_plain_path_unchanged(self):
        """Normal path without special chars passes through."""
        path = "/home/user/audio/chapter_01.wav"
        assert _escape_concat_path(path) == path
