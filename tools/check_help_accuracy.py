"""SHIP_GATE C4: is every flag the docs promise actually real?

The gate has been UNCHECKED since I found its evidence was dated 2026-02-27,
before roughly two-thirds of the current CLI existed. This measures it instead
of asserting it.

Two directions, and the first is the one that burns users:

  DOCUMENTED BUT MISSING  a reader copies the command and it fails
  REAL BUT UNDOCUMENTED   a capability nobody can find

Run with a repo root as argv[1] (defaults to the main checkout).
"""
import re
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else r"E:/AI/audiobooker")

DOC_FILES = [
    ROOT / "README.md",
    *sorted((ROOT / "site/src/content/docs/handbook").glob("*.md*")),
]

FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]{1,30})")
# Flags that appear in prose about OTHER tools, not audiobooker. The docs
# legitimately show `docker run`, `pip install` and friends, and their flags
# are not audiobooker's to implement.
#
# Keep this list HONEST: it is an exemption list on a gate, which is exactly
# the shape that quietly stops catching things. Add a flag here only when it
# demonstrably belongs to another program in the text where it appears —
# never to silence a genuine miss.
FOREIGN = {
    # docker
    "--rm", "--build-arg", "--env-file", "--user", "--mount", "--platform",
    # pip / pipx / npm
    "--version-file", "--no-cache", "--no-cache-dir", "--upgrade",
}


def real_flags():
    """Every flag argparse actually accepts, per subcommand."""
    out = subprocess.run([sys.executable, "-m", "audiobooker.cli", "--help"],
                         capture_output=True, text=True, cwd=ROOT).stdout
    m = re.search(r"\{([a-z0-9,\-]+)\}", out)
    subs = m.group(1).split(",") if m else []
    found = {f: {"(top level)"} for f in FLAG.findall(out)}
    for s in subs:
        h = subprocess.run(
            [sys.executable, "-m", "audiobooker.cli", s, "--help"],
            capture_output=True, text=True, cwd=ROOT).stdout
        for f in FLAG.findall(h):
            found.setdefault(f, set()).add(s)
    return found, subs


def documented():
    """Every flag the docs mention, and where."""
    found: dict[str, set[str]] = {}
    for p in DOC_FILES:
        if not p.exists():
            continue
        for ln, line in enumerate(p.read_text(encoding="utf-8",
                                              errors="replace").splitlines(), 1):
            for f in FLAG.findall(line):
                found.setdefault(f, set()).add(
                    f"{p.relative_to(ROOT).as_posix()}:{ln}")
    return found


real, subs = real_flags()
docs = documented()

missing = {f: w for f, w in docs.items() if f not in real and f not in FOREIGN}
undocumented = {f: w for f, w in real.items() if f not in docs}

print(f"subcommands: {len(subs)}   real flags: {len(real)}   "
      f"documented: {len(docs)}")
print()
print(f"=== DOCUMENTED BUT NOT REAL  ({len(missing)}) "
      f"-- a reader copies these and they fail")
for f in sorted(missing):
    where = sorted(missing[f])
    print(f"  {f:28} {', '.join(where[:3])}"
          + (f"  (+{len(where)-3} more)" if len(where) > 3 else ""))
print()
print(f"=== REAL BUT UNDOCUMENTED  ({len(undocumented)})")
for f in sorted(undocumented):
    cmds = sorted(undocumented[f])
    print(f"  {f:28} {', '.join(cmds[:6])}"
          + (f"  (+{len(cmds)-6})" if len(cmds) > 6 else ""))
print()
print("C4 VERDICT:", "PASS" if not missing else f"FAIL - {len(missing)} broken")

# Exit non-zero so this can gate rather than merely inform. Only the
# documented-but-missing direction fails: those are flags a reader copies and
# watches fail. An undocumented flag is a gap worth closing, not a lie.
sys.exit(1 if missing else 0)
