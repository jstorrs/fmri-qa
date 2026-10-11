# Standard development loop for fmri-qa. See style/tooling.md.
#
# The repo is a uv workspace of three distributions (fmri-qa-core,
# fmri-qa-report and fmri-qa-launcher); every target runs against the whole
# workspace, so a change to the analysis artifact is checked on every side at
# once. Sync the whole workspace once before anything else (see
# style/tooling.md); the heavy notebook stack is a separate group,
# `make sync-notebooks`.

.PHONY: all format format-check lint typecheck pyright test test-cov license check sync sync-notebooks \
	sync-docs docs docs-clean build bundle

all: lint typecheck pyright test

sync:
	uv sync --all-packages

# The exploratory notebook stack (JupyterLab, nilearn, dcm2bids, ...) is a
# separate dependency group because it is heavy and nothing in the gate needs
# it, so `make sync` deliberately leaves it out. Take it when you want to open
# a notebook.
sync-notebooks:
	uv sync --all-packages --group notebooks

# The Sphinx stack for the documentation, likewise its own group.
sync-docs:
	uv sync --all-packages --group docs

# The documentation is one Sphinx project, docs/, built into build/site: the
# landing page at the root, and the user guide and API reference for every
# package beneath it.
#
# Warnings are errors (-W): a reference that does not resolve, or a figure whose
# code fails against the real pipeline, is a page that has drifted from the
# package, and drift is what these pages exist to prevent. --keep-going reports
# every such failure in one run rather than the first. Needs `make sync-docs`.
#
# The doctrees go under build/sphinx (-d) rather than in the default .doctrees
# inside the output, which keeps them, and the plot_directive scratch matplotlib
# writes next to the doctree directory, out of the published tree.
#
# The last step checks every relative link in the finished site, which -W
# cannot: -W sees the references written in the sources, not the links the
# theme, its templates and the extensions write into the HTML around them.
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
# license-files path reaching out of the package root does not survive the
# build. The root file is the source of truth; this proves the copies have not
# drifted from it.
license:
	cmp LICENSE packages/fmri-qa-core/LICENSE
	cmp LICENSE packages/fmri-qa-report/LICENSE
	cmp LICENSE packages/fmri-qa-launcher/LICENSE

build:
	uv build --all-packages

# The single-file executable: `fmri-qa-run` with the interpreter, the whole
# scientific stack and dcm2niix inside, for a machine with no Python. The spec
# says what goes in and why. `--isolated --no-default-groups` builds from a
# throwaway environment resolved from uv.lock rather than from .venv: PyInstaller
# bundles whatever the import graph reaches, so it should only be able to reach
# what the packages declare. Output goes under dist/bundle and build/bundle to
# stay clear of the wheels `make build` leaves in dist/. The closing `--version`
# is the cheapest proof the result starts and found its own metadata; it is
# slow (seconds) because a one-file executable unpacks itself on every launch.
# PyInstaller does not cross-compile: this builds for the platform it runs on.
# scripts/bundle.ps1 is the same two commands for Windows, where there is no
# make; change them together.
bundle:
	uv run --isolated --locked --all-packages --no-default-groups --group bundle \
		pyinstaller --noconfirm --distpath dist/bundle --workpath build/bundle \
		packages/fmri-qa-launcher/bundle/fmri-qa-run.spec
	dist/bundle/fmri-qa-run --version

# CI-style gate: prove each package still ships the right LICENSE, then fail on
# any formatting drift or lint hit, then both type checkers + test with a
# coverage floor (guards the core from silent regression), and finally build the
# whole documentation site. The docs are in the gate because their figures are
# rendered by running the pipeline: a clean build is a check that the pages
# still describe the package. It costs about 25 s.
check: license format-check lint typecheck pyright test-cov
	$(MAKE) docs
