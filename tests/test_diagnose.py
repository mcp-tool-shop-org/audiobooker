"""Tests for the diagnose command."""

from __future__ import annotations

import json

from audiobooker.cli import main


def test_diagnose_text_output(capsys):
    """Diagnose command should produce readable text output."""
    code = main(["diagnose"])
    captured = capsys.readouterr()
    assert code == 0
    assert "python_version" in captured.out
    assert "audiobooker_version" in captured.out


def test_diagnose_json_output(capsys):
    """Diagnose --json should produce valid JSON."""
    code = main(["diagnose", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    data = json.loads(captured.out)
    assert "ok" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)


def test_diagnose_checks_ebooklib(capsys):
    """Diagnose should check ebooklib dependency."""
    main(["diagnose", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    check_names = [c["check"] for c in data["checks"]]
    assert "dep.ebooklib" in check_names
