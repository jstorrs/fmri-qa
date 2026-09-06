# Standard development loop for fmri-qa. See style/tooling.md.
#
# The repo is a uv workspace of two distributions (fmri-qa-core and
# fmri-qa-report); every target runs against the whole workspace, so a change
# to the analysis artifact is checked on both sides at once. Sync the whole
# workspace once before anything else (see style/tooling.md); the heavy
# notebook stack is a separate group, `make sync-notebooks`.

.PHONY: all format lint typecheck pyright test license check sync sync-notebooks build

all: lint typecheck pyright test

sync:
	uv sync --all-packages --all-extras

# The exploratory notebook stack (JupyterLab, nilearn, dcm2bids, ...) is a
# separate dependency group because it is heavy and nothing in the gate needs
# it, so `make sync` deliberately leaves it out. Take it when you want to open
# a notebook.
sync-notebooks:
	uv sync --all-packages --all-extras --group notebooks

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

# Each distribution ships its own copy of the root LICENSE, because a
# license-files path reaching out of the package root does not survive the
# build. The root file is the source of truth; this proves the copies have not
# drifted from it.
license:
	cmp LICENSE packages/fmri-qa-core/LICENSE
	cmp LICENSE packages/fmri-qa-report/LICENSE

build:
	uv build --all-packages

# CI-style gate: prove each package still ships the right LICENSE, then fail on
# any formatting drift or lint hit, then both type checkers + test with a
# coverage floor (guards the core from silent regression).
check: license
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pyright
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=90
