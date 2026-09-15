"""Tests for version consistency.

CH-B-005 reduced four hand-maintained copies of the version to two, by
deriving `audiobooker.__version__` from the installed distribution's metadata.
That is the right fix, and it made the test here tautological: it asserted

    __version__ == version("audiobooker-ai")

against a `__version__` that is now *defined* as `version("audiobooker-ai")`.
An expression compared to itself. It could not fail.

Worth naming how that happened, because it was nobody's mistake: the change
lived in one agent's file grant and the test in another's, so neither could
see the pair. A fix in one domain silently voided a check in another — the
same cross-domain blind spot that exclusive file ownership does not cover.

The real invariant is that the two REMAINING copies — pyproject.toml for
Python packaging, npm/package.json for npm — agree with each other and with
what actually got installed. That is what these assert now.
"""

import json
import pathlib
import re
import sys

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the floor is 3.10
    tomllib = None

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    if tomllib is None:
        pytest.skip("tomllib needs 3.11+; the declared-version check needs it")
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_installed_version_matches_pyproject():
    """What is installed must match what the source declares.

    This is the assertion the old tautology was standing in for. It fails
    when someone bumps pyproject.toml without reinstalling, which is a true
    positive, not noise: `__version__` derives from the INSTALLED
    distribution's metadata, so until you reinstall, `audiobooker --version`
    genuinely reports the old number.
    """
    from audiobooker import __version__

    declared = _pyproject_version()
    assert __version__ == declared, (
        f"installed metadata says {__version__!r} but pyproject.toml declares "
        f"{declared!r} — reinstall with `pip install -e .` to resync"
    )


def test_npm_package_version_matches_pyproject():
    """The two packaging ecosystems ship the same release.

    npm/package.json is the second of the two remaining hand-maintained
    copies (npm/bin/audiobooker.js now derives from it). release.yml checks
    it against the git tag, but only at release time — this catches a drift
    the moment it is committed.
    """
    pkg = ROOT / "npm" / "package.json"
    if not pkg.exists():  # pragma: no cover
        pytest.skip("no npm launcher in this checkout")
    npm_version = json.loads(pkg.read_text(encoding="utf-8"))["version"]
    assert npm_version == _pyproject_version()


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
