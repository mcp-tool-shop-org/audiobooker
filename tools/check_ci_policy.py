"""Planted-RED assertions for the ci-tooling amend gates.

Restore any of the five defects this wave closed and this script exits 1.
Wired into the existing typecheck job (no new CI job, not a second pytest).
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPA_V1142 = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def _run_block_bodies(text: str) -> list[tuple[int, str]]:
    """Collect (lineno, line) pairs that sit inside a YAML `run:` script."""
    bodies: list[tuple[int, str]] = []
    in_run = False
    run_indent = 0
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.startswith("run:"):
            rest = stripped[4:].strip()
            in_run = rest in ("|", ">", "")
            run_indent = indent
            if rest and rest not in ("|", ">"):
                bodies.append((i, rest))
                in_run = False
            continue
        if in_run:
            if stripped == "" or indent > run_indent:
                bodies.append((i, line))
            else:
                in_run = False
    return bodies


def check_action_yml() -> None:
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    for lineno, line in _run_block_bodies(text):
        if "${{ inputs." in line:
            fail(
                f"action.yml:{lineno}: interpolates inputs into a run script "
                "(assign them via env: and reference $VAR)"
            )
        if "echo " in line and "GITHUB_OUTPUT" in line and "audiobook=" in line:
            fail(
                f"action.yml:{lineno}: writes GITHUB_OUTPUT via echo; "
                "use printf %s and a delimiter"
            )
        if re.search(r"pip install .*audiobooker-ai", line) and "ACTION_PATH" not in line:
            fail(
                f"action.yml:{lineno}: pip-installs audiobooker-ai from PyPI; "
                "install from github.action_path and pin == pyproject version"
            )
    if "ACTION_PATH" not in text:
        fail("action.yml: missing ACTION_PATH env (install must use the checkout)")


def check_docker_yml() -> None:
    text = (ROOT / ".github/workflows/docker.yml").read_text(encoding="utf-8")
    if re.search(r"(?m)^\s*push:\s*true\s*$", text):
        fail("docker.yml: push: true is unconditional; gate on event_name == release")
    if "enable={{is_default_branch}}" in text:
        fail(
            "docker.yml: :latest is enabled on is_default_branch "
            "(workflow_dispatch from main overwrites latest)"
        )


def check_ci_yml() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    # Only the typecheck job's Pyright step is in scope. A continue-on-error
    # anywhere in that job makes the required context vacuous.
    in_typecheck = False
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^  typecheck:\s*$", line):
            in_typecheck = True
            continue
        if in_typecheck:
            if line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
                if not line.startswith("  typecheck:"):
                    in_typecheck = False
                    continue
            if "continue-on-error:" in line and "true" in line:
                fail(
                    f"ci.yml:{i}: typecheck has continue-on-error: true "
                    "(required check cannot go RED)"
                )
    if "check_pyright_gate.py" not in text:
        fail("ci.yml: typecheck does not invoke tools/check_pyright_gate.py")


def check_release_yml() -> None:
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    if PYPA_V1142 not in text:
        fail(
            f"release.yml: pypa/gh-action-pypi-publish is not pinned to "
            f"{PYPA_V1142} (v1.14.2, Metadata-Version 2.5)"
        )
    if re.search(r"pip install --upgrade pip build(?!\S)", text):
        fail("release.yml: unpinned `pip install --upgrade pip build`")
    if "needs: preflight" not in text:
        fail(
            "release.yml: publish jobs are not gated on preflight "
            "(PyPI twine reject can still ship npm)"
        )


def main() -> int:
    check_action_yml()
    check_docker_yml()
    check_ci_yml()
    check_release_yml()
    if failures:
        sys.stderr.write("ci-policy failures:\n")
        for msg in failures:
            sys.stderr.write(f"  - {msg}\n")
        return 1
    print("ci-policy OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
