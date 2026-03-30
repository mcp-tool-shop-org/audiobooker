.PHONY: verify lint test test-full audit cov fmt

verify: lint test audit

lint:
	python -m ruff check audiobooker/ tests/

test:
	python -m pytest tests/ -v --tb=short --junitxml=test-results.xml --ignore=tests/test_e2e_smoke.py -k "not requires_voice_soundboard and not requires_ffmpeg"

test-full:
	python -m pytest tests/ -v --tb=short --junitxml=test-results.xml

audit:
	@command -v pip-audit >/dev/null 2>&1 || { echo "pip-audit not installed — skipping"; exit 0; }
	pip-audit --strict --desc

cov:
	python -m pytest tests/ -v --tb=short --ignore=tests/test_e2e_smoke.py \
		-k "not requires_voice_soundboard and not requires_ffmpeg" \
		--cov=audiobooker --cov-report=html --cov-report=term-missing

fmt:
	ruff check --fix audiobooker/ tests/
	ruff format audiobooker/ tests/
