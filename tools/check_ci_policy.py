"""Planted-RED assertions for the ci-tooling amend gates.

Restore any of the defects this wave closed and this script exits 1.
Wired into the existing typecheck job (no new CI job, not a second pytest).
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPA_V1142 = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
REQUIRED_CI_JOBS = ("ci", "dep-audit", "typecheck")
# YAML block scalars: | / > plus chomp (|- |+ >- >+) and indent (|2, |-2).
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?(?:\d+)?$")
failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def _is_block_indicator(rest: str) -> bool:
    """True when `run:` starts a YAML block (including |-, |+, >-, >+)."""
    token = rest.split("#", 1)[0].strip()
    if token == "":
        return True
    return bool(_BLOCK_SCALAR.match(token))


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
            if _is_block_indicator(rest):
                in_run = True
                run_indent = indent
            else:
                in_run = False
                bodies.append((i, rest))
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
        if "${{" in line:
            fail(
                f"action.yml:{lineno}: interpolates ${{{{ in a run script "
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


def check_workflow_run_interpolation() -> None:
    """Any `${{` inside a workflow `run:` body is expression injection.

    action.yml inputs were the wave-2 instance; siblings include
    github.event.* in workflow scripts and the same pattern inside |-.
    """
    workflows = ROOT / ".github" / "workflows"
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in _run_block_bodies(text):
            if "${{" in line:
                fail(
                    f"{rel}:{lineno}: interpolates ${{{{ in a run script "
                    "(assign via env: and reference $VAR)"
                )


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
    current_job: str | None = None
    for i, line in enumerate(text.splitlines(), 1):
        job = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if job:
            current_job = job.group(1)
            continue
        if (
            current_job in REQUIRED_CI_JOBS
            and "continue-on-error:" in line
            and "true" in line
        ):
            fail(
                f"ci.yml:{i}: required job {current_job} has continue-on-error: true "
                "(required check cannot go RED)"
            )
    if re.search(r"(?m)^\s*fail-fast:\s*true\s*$", text):
        fail(
            "ci.yml: matrix fail-fast: true cancels sibling cells "
            "(a 3.10-only break never logs)"
        )
    if "check_pyright_gate.py" not in text:
        fail("ci.yml: typecheck does not invoke tools/check_pyright_gate.py")


def check_pyright_gate() -> None:
    gate_path = ROOT / "tools" / "check_pyright_gate.py"
    text = gate_path.read_text(encoding="utf-8")
    cap = re.search(r"(?m)^MAX_ERRORS\s*=\s*(\d+)\s*(?:#.*)?$", text)
    if not cap:
        fail("check_pyright_gate.py: MAX_ERRORS assignment missing")
    elif int(cap.group(1)) > 105:
        fail(
            f"check_pyright_gate.py: MAX_ERRORS={cap.group(1)} exceeds residual "
            "cap 105 (raising it makes the required check vacuous)"
        )
    if "generalDiagnostics" not in text:
        fail(
            "check_pyright_gate.py: does not dump generalDiagnostics "
            "(count-only occupancy hides which errors)"
        )
    if "pyright_baseline" not in text:
        fail("check_pyright_gate.py: no identity baseline (count-only ratchet)")
    if not (ROOT / "tools" / "pyright_baseline.txt").is_file():
        fail("tools/pyright_baseline.txt missing")


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
    if not re.search(r"needs:\s*\[preflight,\s*publish\]", text):
        fail(
            "release.yml: publish-npm is not gated on publish "
            "(an OIDC/PyPI reject can still ship npm)"
        )
    if not re.search(r"(?m)^\s*cancel-in-progress:\s*false\s*$", text):
        fail(
            "release.yml: cancel-in-progress is not false "
            "(a second tag can abort an in-flight OIDC upload)"
        )
    if "upload-artifact" not in text:
        fail("release.yml: preflight does not upload dist/ for publish to consume")
    if "download-artifact" not in text:
        fail("release.yml: publish does not download the preflight dist/")
    build_hits = [
        ln for ln, line in _run_block_bodies(text) if "python -m build" in line
    ]
    if len(build_hits) != 1:
        fail(
            "release.yml: expected exactly one preflight `python -m build`; "
            f"found {len(build_hits)} (publish must not rebuild dist/)"
        )
    if re.search(r"(?m)^\s*workflow_dispatch:\s*$", text):
        if "github.event_name == 'workflow_dispatch'" not in text:
            fail(
                "release.yml: workflow_dispatch has no dispatch-only notice job "
                "(silent green no-op)"
            )
        if "publishes only from a GitHub Release" not in text:
            fail(
                "release.yml: dispatch notice does not fail closed "
                "(operator would see Success while nothing published)"
            )


def main() -> int:
    check_action_yml()
    check_workflow_run_interpolation()
    check_docker_yml()
    check_ci_yml()
    check_pyright_gate()
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
