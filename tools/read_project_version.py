"""Print [project].version from a pyproject.toml.

Used by action.yml (the composite must install THIS checkout's version, not
PyPI latest) and by release.yml / docker.yml tag-vs-manifest checks.
"""
from __future__ import annotations

import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "pyproject.toml")
text = path.read_text(encoding="utf-8")
match = re.search(
    r"(?m)^\[project\]\s*\n(?:(?!\[).*\n)*?^version\s*=\s*\"([^\"]+)\"",
    text,
)
if not match:
    sys.stderr.write(f"no [project] version in {path}\n")
    sys.exit(1)
print(match.group(1))
