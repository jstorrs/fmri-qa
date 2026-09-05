# Standard development loop for fmri-qa. See style/tooling.md.
#
# The repo is a uv workspace of two distributions (fmri-qa-core and
# fmri-qa-report); every target runs against the whole workspace, so a change
# to the analysis artifact is checked on both sides at once. Sync all packages
# and extras once so optional deps resolve (see style/tooling.md).

.PHONY: all format lint typecheck pyright test check sync build

all: lint typecheck pyright test

sync:
	uv sync --all-packages --all-extras

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run mypy

pyright:
	uv run pyright

test:
	uv run pytest

build:
	uv build --all-packages

# CI-style gate: fail on any formatting drift or lint hit, then both type
# checkers + test with a coverage floor (guards the core from silent regression).
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pyright
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=90
