"""
FT-TEST-002: Atomic save safety tests for AudiobookProject.save().

Verifies that the atomic-write pattern (write .tmp then os.replace)
leaves the original file intact when json.dump fails mid-write.
"""

import json
from unittest.mock import patch

import pytest

from audiobooker.project import AudiobookProject


class TestAtomicSaveSafety:
    """Tests for the atomic write pattern in AudiobookProject.save()."""

    def test_happy_path_save_and_reload(self, tmp_path):
        """save() writes valid JSON that can be reloaded."""
        project = AudiobookProject(title="My Book", author="Author")
        save_path = tmp_path / "project.audiobooker"
        result = project.save(save_path)

        assert result == save_path
        assert save_path.exists()

        # Verify round-trip
        loaded = AudiobookProject.load(save_path)
        assert loaded.title == "My Book"
        assert loaded.author == "Author"

    def test_original_file_unchanged_on_write_error(self, tmp_path):
        """When json.dump raises, original file content is preserved."""
        save_path = tmp_path / "project.audiobooker"

        # Create an initial valid project file
        original_project = AudiobookProject(title="Original", author="First")
        original_project.save(save_path)
        original_content = save_path.read_text(encoding="utf-8")

        # Now attempt a save that fails during json.dump
        updated_project = AudiobookProject(title="Updated", author="Second")
        updated_project.project_path = save_path

        with patch("audiobooker.project.json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                updated_project.save(save_path)

        # Original file should be unchanged
        assert save_path.read_text(encoding="utf-8") == original_content

    def test_tmp_file_cleaned_up_on_error(self, tmp_path):
        """When save fails, the .tmp file is removed."""
        save_path = tmp_path / "project.audiobooker"
        tmp_file = save_path.with_suffix(".audiobooker.tmp")

        project = AudiobookProject(title="Crash Test")

        with patch("audiobooker.project.json.dump", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                project.save(save_path)

        assert not tmp_file.exists(), ".tmp file should be cleaned up after failure"

    def test_exception_propagates(self, tmp_path):
        """The original exception from json.dump propagates to the caller."""
        save_path = tmp_path / "project.audiobooker"
        project = AudiobookProject(title="Error Test")

        with patch("audiobooker.project.json.dump", side_effect=RuntimeError("custom error")):
            with pytest.raises(RuntimeError, match="custom error"):
                project.save(save_path)

    def test_save_creates_file_when_none_exists(self, tmp_path):
        """save() creates the file when no prior file exists."""
        save_path = tmp_path / "brand_new.audiobooker"
        assert not save_path.exists()

        project = AudiobookProject(title="Brand New")
        project.save(save_path)

        assert save_path.exists()
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert data["title"] == "Brand New"
