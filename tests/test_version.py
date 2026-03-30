"""Tests for version consistency."""

import re

import pytest


def test_version_matches_metadata():
    """Package __version__ matches importlib.metadata."""
    from importlib.metadata import version

    from audiobooker import __version__

    assert __version__ == version("audiobooker-ai")


def test_version_is_semver():
    """Version follows semver format."""
    from audiobooker import __version__

    assert re.match(r"^\d+\.\d+\.\d+", __version__)


def test_cli_version_flag(capsys):
    """audiobooker --version prints the correct version."""
    from audiobooker import __version__
    from audiobooker.cli import main

    with pytest.raises(SystemExit):
        main(["--version"])
    captured = capsys.readouterr()
    assert __version__ in captured.out
