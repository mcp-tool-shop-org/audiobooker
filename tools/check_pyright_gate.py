"""Fail closed on pyright regressions without blocking on known residuals.

The typecheck job is a branch-protection required context. continue-on-error
made that context vacuous: 82 residuals still greened the check. This script
is the actual gate. It runs pyright and exits 1 if errorCount exceeds
MAX_ERRORS. Lower the cap when residuals are paid down. Never raise it
without a tracked finding. Do not restore continue-on-error.

Usage: python tools/check_pyright_gate.py [path]
"""
from __future__ import annotations

import json
import subprocess
import sys

# Measured 2026-09-15 on this worktree (pyright 1.1.414, typeCheckingMode=basic):
# 82 errors / 3 warnings / 45 files. Ratchet down; never up.
MAX_ERRORS = 82
TARGET = sys.argv[1] if len(sys.argv) > 1 else "audiobooker"


def main() -> int:
    proc = subprocess.run(
        ["pyright", TARGET, "--outputjson"],
        capture_output=True,
        text=True,
    )
    raw = proc.stdout.strip()
    try:
        start = raw.index("{")
        data = json.loads(raw[start:])
    except (ValueError, json.JSONDecodeError):
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        sys.stderr.write("pyright did not emit parseable JSON\n")
        return proc.returncode or 1

    count = int(data.get("summary", {}).get("errorCount", 0))
    print(f"pyright errors: {count} (cap {MAX_ERRORS})")
    if count > MAX_ERRORS:
        sys.stderr.write(
            f"pyright error count {count} exceeds cap {MAX_ERRORS}. "
            "New type errors on a required check.\n"
        )
        return 1
    if count < MAX_ERRORS:
        print(
            f"note: {MAX_ERRORS - count} below cap — lower MAX_ERRORS in "
            "tools/check_pyright_gate.py to ratchet the gate."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
