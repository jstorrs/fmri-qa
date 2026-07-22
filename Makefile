# Standard development loop for fmri-qa. See style/tooling.md.
#
# Everything runs through `uv run` against the locked environment; sync with
# all extras once so optional deps resolve (see style/tooling.md).

.PHONY: all format lint typecheck pyright test check sync build

all: lint typecheck pyright test

sync:
	uv sync --all-extras

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
	uv build

# CI-style gate: fail on any formatting drift or lint hit, then both type
# checkers + test with a coverage floor (guards the core from silent regression).
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pyright
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=90
