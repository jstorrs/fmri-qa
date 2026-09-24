"""Sphinx configuration for the fmri-qa-report documentation.

The pages describe how a report is rendered and what it shows, in prose only:
no figure here is rendered, because what a report draws is the analysis
package's to document, and these pages link to it rather than repeat it.

Links go only to core, the one package the report depends on, and are resolved
with `intersphinx` against the objects.inv core's build has already written into
the documentation site (build/site), never one fetched over the network. That is
why `make docs-report` builds core first. Write such a link with the
`{external+core:doc}` role, never a MyST `inv:` link: MyST does not adjust the
latter's relative base for a page's depth, so it breaks on a nested page while
the build still passes.
"""

from pathlib import Path

project = "fmri-qa-report"
author = "Judd Storrs"
copyright = "2026, Judd Storrs"  # noqa: A001  (the name Sphinx reads)

extensions = ["myst_parser", "sphinx.ext.intersphinx"]

exclude_patterns = ["_build"]

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = "fmri-qa-report"

REPO = Path(__file__).resolve().parents[3]

# Keep in step with SITE in the Makefile. Core's directory relative to these
# pages (both are siblings under build/site), and the inventory its build left
# there.
intersphinx_mapping = {
    "core": ("../core/", str(REPO / "build" / "site" / "core" / "objects.inv")),
}

# These pages build into report/ beneath the documentation site's landing page
# (build/site; see the Makefile), and every page links back up to it. The link
# is a sidebar template shared with the other packages' projects from the
# repository's docs/_templates; the sidebar is furo's default with that one
# entry put first.
templates_path = [str(REPO / "docs" / "_templates")]
html_sidebars = {
    "**": [
        "sidebar/site-home.html",
        "sidebar/brand.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/ethical-ads.html",
        "sidebar/scroll-end.html",
        "sidebar/variant-selector.html",
    ]
}
