# Standard development loop for fmri-qa. See style/tooling.md.
#
# Everything runs through `uv run` against the locked environment; sync with
# all extras once so optional deps resolve (see style/tooling.md).

.PHONY: all format lint typecheck pyright test check sync

all: lint typecheck test

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

# CI-style gate: fail on any formatting drift or lint hit, then typecheck + test.
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pytest
