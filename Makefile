.PHONY: verify lint test audit cov fmt

verify: lint test audit

lint:
	python -m ruff check audiobooker/ tests/

# TEST-A-004: no --ignore here any more. tests/test_e2e_smoke.py holds four
# dependency-free tests (parse -> cast -> compile -> save/load against the
# golden book) and two that need real voice-soundboard / real ffmpeg. The
# file-level --ignore excluded all six because of the two, so the four ran
# nowhere: not here, not in CI, and not in the `test-full` target either,
# because nothing invoked `test-full`. The heavy pair now lives in its own
# class and self-skips when the binaries are absent; the other four run.
#
# `test-full` is deleted rather than kept: with the --ignore gone it was a
# byte-identical alias for `test`, and a second name for the same command is
# how the original one came to be forgotten. Nothing referenced it (checked:
# no workflow, no doc, no other target).
test:
	python -m pytest tests/ -v --tb=short --junitxml=test-results.xml

# COORD-B-003: scoped to THIS PROJECT (`.`), not to the ambient interpreter.
#
# `pip-audit --strict --desc --skip-editable` audited whatever happened to be
# installed in the developer's Python. On this rig that is 61 known
# vulnerabilities across cryptography, pillow, pypdf, setuptools and an
# unrelated local package — none of which audiobooker depends on. Its declared
# set is ebooklib plus optional extras, and pypdf is not even the PDF library
# this project uses (that is pymupdf).
#
# It was also self-defeating: --skip-editable skips the editable install of
# audiobooker-ai itself, and --strict then treats that skip as a
# dependency-collection failure, so the command exited 1 having audited
# nothing ("ERROR pip_audit._cli: audiobooker-ai: distribution marked as
# editable") and took `make verify` down with it. Without --strict it reported
# the 61 ambient findings and then crashed formatting them. Either way a
# developer learns the audit step is noise — and then skims the CI gate that
# is not.
#
# `pip-audit --desc on .` resolves the project's own dependency closure in an
# isolated build, which is the same question ci.yml's dep-audit job asks when
# it runs `pip-audit --desc` in a fresh venv holding only `pip install .`.
# Measured on this rig: exit 0, "No known vulnerabilities found", ~17s.
# (`--desc on` rather than bare `--desc`: --desc takes an optional value, so
# `--desc .` is parsed as the description flag swallowing the project path.)
#
# No vulnerability was being missed before. The finding is the asymmetry
# between the two legs, not a security hole.
audit:
	@command -v pip-audit >/dev/null 2>&1 || { echo "pip-audit not installed — skipping"; exit 0; }
	pip-audit --desc on .

cov:
	python -m pytest tests/ -v --tb=short \
		--cov=audiobooker --cov-report=html --cov-report=term-missing

fmt:
	ruff check --fix audiobooker/ tests/
	ruff format audiobooker/ tests/
