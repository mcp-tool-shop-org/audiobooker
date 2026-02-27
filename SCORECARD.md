# Scorecard

> Score a repo before remediation. Fill this out first, then use SHIP_GATE.md to fix.

**Repo:** audiobooker
**Date:** 2026-02-27
**Type tags:** [pypi] [cli] [container]

## Pre-Remediation Assessment

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | 5/10 | No SECURITY.md, no threat model in README |
| B. Error Handling | 8/10 | RenderError, RenderFailureReport, structured CLI output |
| C. Operator Docs | 8/10 | Good README with CLI reference, CHANGELOG present |
| D. Shipping Hygiene | 6/10 | CI exists but no coverage, no verify script, pre-1.0 version |
| E. Identity (soft) | 10/10 | Logo, translations, landing page, metadata all present |
| **Overall** | **37/50** | |

## Key Gaps

1. No SECURITY.md — no vulnerability reporting process
2. No coverage in CI, no verify script, no dep-audit
3. Version still at 0.5.2 — needs promotion to 1.0.0
4. No Security & Data Scope in README

## Remediation Priority

| Priority | Item | Estimated effort |
|----------|------|-----------------|
| 1 | Create SECURITY.md + threat model in README | 5 min |
| 2 | Add coverage + Codecov + dep-audit to CI, create Makefile | 10 min |
| 3 | Bump version to 1.0.0 + update CHANGELOG | 3 min |

## Post-Remediation

| Category | Before | After |
|----------|--------|-------|
| A. Security | 5/10 | 10/10 |
| B. Error Handling | 8/10 | 10/10 |
| C. Operator Docs | 8/10 | 10/10 |
| D. Shipping Hygiene | 6/10 | 10/10 |
| E. Identity (soft) | 10/10 | 10/10 |
| **Overall** | **37/50** | **50/50** |
