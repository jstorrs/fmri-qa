# Standard development loop for fmri-qa. See style/tooling.md.
#
# The repo is a uv workspace of six distributions (fmri-qa-core, fmri-qa-io,
# fmri-qa-cli, fmri-qa-report, fmri-qa-launcher and the private fmri-qa-web).
# Every target runs against the whole workspace, so a change to the analysis artifact is checked on every side.
# Sync the workspace once first (see style/tooling.md). The heavy notebook
# stack is a separate group, `make sync-notebooks`.

.PHONY: all format format-check lint typecheck pyright test test-cov license check sync sync-notebooks \
	sync-docs docs docs-clean build bundle

all: lint typecheck pyright test

sync:
	uv sync --all-packages

# The exploratory notebook stack (JupyterLab, nilearn, dcm2bids, ...) is a
# separate dependency group. It is heavy and nothing in the gate needs it, so
# `make sync` leaves it out. Take it when you want to open a notebook.
sync-notebooks:
	uv sync --all-packages --group notebooks

# The Sphinx stack for the documentation is also its own group.
sync-docs:
	uv sync --all-packages --group docs

# The documentation is one Sphinx project, docs/, built into build/site: the
# landing page at the root, with the user guide and API reference for every
# package beneath it.
#
# Warnings are errors (-W). An unresolved reference, or a figure whose code
# fails against the real pipeline, means the page has drifted from the package.
# --keep-going reports every failure in one run. Needs `make sync-docs`.
#
# The doctrees go under build/sphinx (-d), not the default .doctrees inside the
# output. This keeps them, and the plot_directive scratch matplotlib writes
# next to the doctree directory, out of the published tree.
#
# The last step checks every relative link in the finished site. -W cannot do
# this: it sees the references in the sources, not the links the theme,
# templates and extensions write into the HTML.
SITE := build/site
SPHINX := uv run --group docs sphinx-build -W --keep-going -b html

docs:
	$(SPHINX) -d build/sphinx/doctrees docs $(SITE)
	uv run python scripts/check_site_links.py $(SITE)

docs-clean:
	rm -rf $(SITE) build/sphinx

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run mypy

pyright:
	uv run pyright

test:
	uv run pytest

test-cov:
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=90

# Each distribution ships its own copy of the root LICENSE, because a
# license-files path outside the package root does not survive the build. The
# root file is the source of truth. This checks the copies match it.
license:
	cmp LICENSE packages/fmri-qa-core/LICENSE
	cmp LICENSE packages/fmri-qa-io/LICENSE
	cmp LICENSE packages/fmri-qa-cli/LICENSE
	cmp LICENSE packages/fmri-qa-report/LICENSE
	cmp LICENSE packages/fmri-qa-launcher/LICENSE
	cmp LICENSE packages/fmri-qa-web/LICENSE

build:
	uv build --all-packages

# The single-file executable: `fmri-qa-run` with the interpreter, the whole
# scientific stack and dcm2niix inside, for a machine with no Python. The spec
# says what goes in and why. `--isolated --no-default-groups` builds from a
# throwaway environment resolved from uv.lock, not from .venv. PyInstaller
# bundles whatever the import graph reaches, so it should reach only what the
# packages declare. Output goes under dist/bundle and build/bundle, clear of the
# wheels `make build` leaves in dist/. The closing `--version` is the cheapest
# proof that the result starts and found its own metadata. It takes seconds
# because a one-file executable unpacks itself on every launch. PyInstaller does
# not cross-compile: this builds for the platform it runs on.
# scripts/bundle.ps1 is the same two commands for Windows, where there is no
# make. Change them together.
bundle:
	uv run --isolated --locked --all-packages --no-default-groups --group bundle \
		pyinstaller --noconfirm --distpath dist/bundle --workpath build/bundle \
		packages/fmri-qa-launcher/bundle/fmri-qa-run.spec
	dist/bundle/fmri-qa-run --version

# CI-style gate: check each package ships the right LICENSE, then fail on any
# formatting drift or lint hit, then run both type checkers and the tests with a
# coverage floor (guards the core against silent regression), and finally build
# the whole documentation site. The docs are in the gate because their figures
# come from running the pipeline, so a clean build shows the pages still
# describe the package. It takes about 25 s.
check: license format-check lint typecheck pyright test-cov
	$(MAKE) docs
