.PHONY: verify lint test audit

verify: lint test

lint:
	python -m ruff check audiobooker/

test:
	python -m pytest tests/ -v --tb=short --ignore=tests/test_e2e_smoke.py -k "not requires_voice_soundboard and not requires_ffmpeg"

audit:
	pip-audit --strict --desc || true
