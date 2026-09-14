"""Tests for the diagnose command."""

from __future__ import annotations

import json

from audiobooker.cli import main


def test_diagnose_text_output(capsys):
    """Diagnose command should produce readable text output."""
    code = main(["diagnose"])
    captured = capsys.readouterr()
    # CLIUX-H-004: the exit code tracks render-readiness, which depends on the
    # host (CI installs neither ffmpeg nor voice-soundboard). Assert the
    # INVARIANT instead of a host-specific number: the code agrees with the
    # verdict the user is shown. This test is about the text output.
    ready = "Ready to render." in captured.out
    assert (code == 0) is ready, captured.out
    assert "NOT ready to render" in captured.out or ready
    assert "python_version" in captured.out
    assert "audiobooker_version" in captured.out


def test_diagnose_json_output(capsys):
    """Diagnose --json should produce valid JSON."""
    code = main(["diagnose", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "ok" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)
    # CLIUX-H-004: readiness is its own axis and drives the exit code.
    assert "ready" in data
    assert (code == 0) is bool(data["ready"])


def test_diagnose_checks_ebooklib(capsys):
    """Diagnose should check ebooklib dependency."""
    main(["diagnose", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    check_names = [c["check"] for c in data["checks"]]
    assert "dep.ebooklib" in check_names
