"""Sphinx configuration for the fmri-qa documentation site's landing page.

The documentation is one site under build/site: each package's own Sphinx
project builds into a directory beneath it (core/), and this project builds
last, into the site root, as the one page that points into all of them. Its
links into a package are resolved with `intersphinx` against the objects.inv
that package's build has already written into the site, never one fetched over
the network, so the build works offline and fails if a sibling has not been
built. `make docs` builds them in order.
"""

from pathlib import Path

project = "fmri-qa"
author = "Judd Storrs"
copyright = "2026, Judd Storrs"  # noqa: A001  (the name Sphinx reads)

extensions = ["myst_parser", "sphinx.ext.intersphinx"]

exclude_patterns = ["_build", "_templates"]

html_theme = "furo"
html_title = "fmri-qa"

# Keep in step with SITE in the Makefile.
SITE = Path(__file__).resolve().parent.parent / "build" / "site"

# Each entry is a sibling's directory relative to this page, and the inventory
# its build left there. A page only ever links toward its dependencies, and
# this one depends on every package.
intersphinx_mapping = {
    "core": ("core/", str(SITE / "core" / "objects.inv")),
}
