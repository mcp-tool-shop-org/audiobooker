"""Tests for the diagnose command."""

from __future__ import annotations

import json

from audiobooker.cli import main


def test_diagnose_text_output():
    """Diagnose command should produce readable text output."""
    # main() returns exit code, prints to stdout
    import io
    import sys

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        code = main(["diagnose"])
    finally:
        sys.stdout = old_stdout
    output = captured.getvalue()
    assert code == 0
    assert "python_version" in output
    assert "audiobooker_version" in output


def test_diagnose_json_output():
    """Diagnose --json should produce valid JSON."""
    import io
    import sys

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        code = main(["diagnose", "--json"])
    finally:
        sys.stdout = old_stdout
    output = captured.getvalue()
    assert code == 0
    data = json.loads(output)
    assert "ok" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)


def test_diagnose_checks_ebooklib():
    """Diagnose should check ebooklib dependency."""
    import io
    import sys

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        main(["diagnose", "--json"])
    finally:
        sys.stdout = old_stdout
    data = json.loads(captured.getvalue())
    check_names = [c["check"] for c in data["checks"]]
    assert "dep.ebooklib" in check_names
