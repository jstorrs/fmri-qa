# Standard development loop for fmri-qa. See style/tooling.md.
#
# The repo is a uv workspace of two distributions (fmri-qa-core and
# fmri-qa-report); every target runs against the whole workspace, so a change
# to the analysis artifact is checked on both sides at once. Sync the whole
# workspace once before anything else (see style/tooling.md); the heavy
# notebook stack is a separate group, `make sync-notebooks`.

.PHONY: all format lint typecheck pyright test license check sync sync-notebooks \
	sync-docs docs build

all: lint typecheck pyright test

sync:
	uv sync --all-packages --all-extras

# The exploratory notebook stack (JupyterLab, nilearn, dcm2bids, ...) is a
# separate dependency group because it is heavy and nothing in the gate needs
# it, so `make sync` deliberately leaves it out. Take it when you want to open
# a notebook.
sync-notebooks:
	uv sync --all-packages --all-extras --group notebooks

# The Sphinx stack for the analysis documentation, likewise its own group.
sync-docs:
	uv sync --all-packages --all-extras --group docs

# Build the analysis documentation. Warnings are errors (-W): a reference that
# does not resolve, or a figure whose code fails against the real pipeline, is a
# page that has drifted from the package, and drift is what these pages exist to
# prevent. --keep-going reports every such failure in one run rather than the
# first. Needs `make sync-docs`.
docs:
	uv run --group docs sphinx-build -W --keep-going -b html \
		packages/fmri-qa-core/docs packages/fmri-qa-core/docs/_build/html

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
# coverage floor (guards the core from silent regression), and finally build the
# analysis documentation. The docs are in the gate because their figures are
# rendered by running the pipeline: a clean build is a check that the pages
# still describe the package, and it costs about 25 s.
check: license
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pyright
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=90
	$(MAKE) docs
