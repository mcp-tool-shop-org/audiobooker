# Ship Gate

> No repo is "done" until every applicable line is checked.
> Copy this into your repo root. Check items off per-release.

**Tags:** `[all]` every repo · `[npm]` `[pypi]` `[vsix]` `[desktop]` `[container]` published artifacts · `[mcp]` MCP servers · `[cli]` CLI tools

---

## A. Security Baseline

- [x] `[all]` SECURITY.md exists (report email, supported versions, response timeline) (2026-02-27)
- [x] `[all]` README includes threat model paragraph (data touched, data NOT touched, permissions required) (2026-02-27)
- [x] `[all]` No secrets, tokens, or credentials in source or diagnostics output (2026-02-27)
- [x] `[all]` No telemetry by default — state it explicitly even if obvious (2026-02-27)

### Default safety posture

- [x] `[cli|mcp|desktop]` Dangerous actions (kill, delete, restart) require explicit `--allow-*` flag (2026-02-27) — --clean-cache is explicit opt-in for destructive cache operations
- [x] `[cli|mcp|desktop]` File operations constrained to known directories (2026-02-27) — writes only to user-specified output dirs
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server

## B. Error Handling

- [x] `[all]` Errors follow the Structured Error Shape: `code`, `message`, `hint`, `cause?`, `retryable?` (2026-09-14) — `AudiobookerError` base with `.structured()`; `ConfigValidationError`, `RenderError`, `PresetError` and `VoiceNotFoundError` all inherit it, each keeping `ValueError`/`RuntimeError` in its MRO so existing call sites catch unchanged. The prior evidence (2026-04-23) was partly FALSE: `AudiobookerError` was dead code with zero imports repo-wide, `RenderError`/`VoiceNotFoundError` hand-rolled the shape outside the family, and `PresetError` carried no `code` at all.
- [x] `[cli]` Exit codes: 0 ok · 1 user error · 2 runtime error · 3 partial success (2026-09-14) — `batch`/`make` return 3 on partial success, and `render --allow-partial` returns 3 when chapters were dropped. Previously only `batch` did; a partial render reported plain success.
- [x] `[cli]` No raw stack traces without `--debug` (2026-04-23) — all tracebacks gated behind --debug flag
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[desktop]` SKIP: not a desktop application
- [ ] `[vscode]` SKIP: not a VS Code extension

## C. Operator Docs

- [x] `[all]` README is current: what it does, install, usage, supported platforms + runtime versions (2026-02-27)
- [x] `[all]` CHANGELOG.md (Keep a Changelog format) (2026-02-27)
- [x] `[all]` LICENSE file present and repo states support status (2026-02-27)
- [ ] `[cli]` `--help` output accurate for all commands and flags — **UNCHECKED 2026-09-14.** The prior evidence ("verified in CI", 2026-02-27) predates roughly two-thirds of the current CLI surface (`make`, `audition`, `cast-preset`, `cast-fill`, `podcast`, `master-check`, `sample`, `emotions`, `pronunciation` all postdate it), and at least one help string is provably wrong today: `render --watch` (cli.py:526) reads "Watch the source file and re-render" but watches the PROJECT file — only `make --watch` (:1188) watches the source. Re-verify across all 34 subcommands before re-checking; do not restore the check on the old evidence.
- [x] `[cli|mcp|desktop]` Logging levels defined: silent / normal / verbose / debug — secrets redacted at all levels (2026-04-23) — --silent/--debug global flags, _SecretRedactFilter on all handlers
- [ ] `[mcp]` SKIP: not an MCP server
- [ ] `[complex]` SKIP: no daily-ops surface. C7 asks for an OPS handbook — daily operations, warn/critical response, recovery procedures — which presupposes a long-running service. audiobooker is a one-shot CLI: there is nothing to operate between invocations, no alerting, and recovery is `audiobooker render` resuming from the cache. **Reason corrected 2026-09-14**; the old wording ("not complex enough for HANDBOOK") was wrong on its face, since the tool ships 34 subcommands and a 7-page Starlight handbook. That handbook is a USER handbook (getting-started / usage / reference / troubleshooting / architecture) and does not satisfy C7 either — it is a different artifact, not evidence for this line.

## D. Shipping Hygiene

- [x] `[all]` `verify` script exists (test + build + smoke in one command) (2026-02-27) — Makefile verify target
- [x] `[all]` Version in manifest matches git tag (2026-09-14) — pyproject 2.1.1 == tag v2.1.1, verified. The prior note said "v2.0.0 tag pending" and it never landed: `git tag -l` shows v0.2.0, v0.5.1, v0.5.2, v2.0.1, v2.1.0, v2.1.1 — **no v1.0.0 and no v2.0.0**, though CHANGELOG documents both as shipped releases (0.3.0/0.4.0/0.5.0 are likewise untagged). The gate as stated passes on the current version; the CHANGELOG/tag divergence is real and tracked separately rather than papered over here.
- [x] `[all]` Dependency scanning runs in CI (ecosystem-appropriate) (2026-02-27) — dep-audit job
- [x] `[all]` Automated dependency update mechanism exists (2026-04-23) — .github/dependabot.yml (pip + github-actions)
- [x] `[npm]` `npm pack --dry-run` includes README.md, CHANGELOG.md, LICENSE (2026-09-14) — verified live. This line previously read "SKIP: not an npm package", which was false — `@mcptoolshop/audiobooker` ships to npm — and the false skip hid a real failure: the published 2.1.1 tarball carried README + LICENSE and **no CHANGELOG**. release.yml now stages it from the repo root before publish.
- [x] `[npm]` `engines.node` set · `[pypi]` `python_requires` set (2026-02-27) — >=3.10
- [x] `[npm]` Lockfile committed · `[pypi]` Clean wheel + sdist build (2026-02-27) — setuptools build
- [ ] `[vsix]` SKIP: not a VS Code extension
- [ ] `[desktop]` SKIP: not a desktop application

## E. Identity (soft gate — does not block ship)

- [x] `[all]` Logo in README header (2026-02-27)
- [x] `[all]` Translations (polyglot-mcp, 8 languages) (2026-02-27)
- [x] `[org]` Landing page (@mcptoolshop/site-theme) (2026-02-27)
- [x] `[all]` GitHub repo metadata: description, homepage, topics (2026-02-27)

---

## Gate Rules

**Hard gate (A–D):** Must pass before any version is tagged or published.
If a section doesn't apply, mark `SKIP:` with justification — don't leave it unchecked.

**Soft gate (E):** Should be done. Product ships without it, but isn't "whole."

**Checking off:**
```
- [x] `[all]` SECURITY.md exists (2026-02-27)
```

**Skipping:**
```
- [ ] `[pypi]` SKIP: not a Python project
```
