# Scorecard

**Repo:** audiobooker
**Type tags:** [pypi] [npm] [cli] [container]

## Current — measured 2026-09-14 (v3.0.0, post dogfood swarm)

`npx @mcptoolshop/shipcheck audit` — **26 checked · 0 unchecked · 11 skipped ·
100% · all hard gates pass.**

| Category | Score | Evidence |
|----------|-------|----------|
| A. Security | 10/10 | SECURITY.md with a real supported-versions table (it named 1.0.x while 2.1.1 shipped, until this pass); threat model in README; `pip-audit` gates CI in a clean venv |
| B. Error Handling | 10/10 | Structured `code`/`message`/`hint`/`retryable` on every raise; exit codes `0/1/2/3`; a failed compile now raises instead of returning `None` and exits 1, not 2 |
| C. Operator Docs | 10/10 | 34/34 subcommands in the README table; `--help` accuracy **measured**, not dated — `tools/check_help_accuracy.py`, 0 documented-but-nonexistent flags |
| D. Shipping Hygiene | 10/10 | `make verify`; version derived rather than retyped in 4 places, and the drift test caught the stale editable install during this very bump; CI 5 jobs / **7 billable minutes** per push — 256s of wall time, but GitHub rounds each job up to the minute, which the previous "5" did not (measured on run 34922950012: 30s + 59s + 75s + 20s + 72s); published tarballs carry CHANGELOG |
| E. Identity (soft) | 10/10 | Logo (the artwork as drawn, cropped and not otherwise processed — the `<picture>` dark variant was a repainted derivative and is gone), 7 translations, landing page, 7-page handbook, repo metadata |
| **Overall** | **50/50** | |

### What that number does and does not mean

50/50 is a **gate** score: every hard gate has a truthful, current claim
behind it. It is not a defect count. This repo took **200+ findings** across
five health waves and a feature pass, and several were CRITICAL — a book whose
every chapter failed to compile reported success and exited 0; `make`
destroyed hand-tuned casting without asking; two languages gave every line the
previous speaker's voice; the render cache printed "Cached" over audio that
did not match the request. The gates did not catch any of those, because gates
check that the claims are true, not that the code is right.

The tests are what moved: **1468 → 1947**.

Two of this release's defects were found by *writing the documentation for the
feature*, not by auditing it — `utterance_cache` removed every pause in the
book, and `report` printed the narration-diluted rate this release exists to
have replaced. Both had passing tests. That is an argument for writing the
docs before shipping rather than after, and it is why the doc pass is inside
the gate rather than after it.

### Three gates were passing on claims that were false

Worth recording, because a green scorecard is exactly where this hides:

- `[npm] SKIP: not an npm package` — audiobooker ships `@mcptoolshop/audiobooker`.
  The false skip hid a real failure: the published 2.1.1 tarball had no CHANGELOG.
- `[complex] SKIP: not complex enough for a handbook` — 34 subcommands and a
  7-page Starlight handbook. The skip itself stands, but for a different
  reason (C7 wants an *ops* handbook and this is a one-shot CLI); the stated
  reason was wrong on its face.
- `[cli] --help accurate` — evidence read "verified in CI, 2026-02-27", still
  sitting there after two-thirds of the CLI had been added. Measured now:
  one documented flag (`cast --speed`) did not exist.

A gate whose evidence is a date decays silently. The C4 check is a script now.

---

## Historical — v0.5.2 → v1.0.0 remediation (2026-02-27)

> Kept as a record of that pass. Superseded by the table above.

| Category | Before | After |
|----------|--------|-------|
| A. Security | 5/10 | 10/10 |
| B. Error Handling | 8/10 | 10/10 |
| C. Operator Docs | 8/10 | 10/10 |
| D. Shipping Hygiene | 6/10 | 10/10 |
| E. Identity (soft) | 10/10 | 10/10 |
| **Overall** | **37/50** | **50/50** |

Gaps closed in that pass: no SECURITY.md or vulnerability reporting process;
no coverage, verify script or dep-audit in CI; version still at 0.5.2; no
Security & Data Scope section in the README.
