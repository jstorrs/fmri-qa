"""Sphinx configuration for the fmri-qa-launcher documentation.

The pages describe the application shell in prose only: the command, the
desktop panel, and what a run writes. What a run computes and what its report
shows are the other packages' to document, and these pages link to them rather
than repeat them.

Links go only to core and report, the two packages the launcher depends on,
and are resolved with `intersphinx` against the objects.inv each one's build
has already written into the documentation site (build/site), never one
fetched over the network. That is why `make docs-launcher` builds both first.
Write such a link with the `{external+core:doc}` or `{external+report:doc}`
role, never a MyST `inv:` link: MyST does not adjust the latter's relative base
for a page's depth, so it breaks on a nested page while the build still passes.
"""

from pathlib import Path

project = "fmri-qa-launcher"
author = "Judd Storrs"
copyright = "2026, Judd Storrs"  # noqa: A001  (the name Sphinx reads)

extensions = ["myst_parser", "sphinx.ext.intersphinx"]

exclude_patterns = ["_build"]

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = "fmri-qa-launcher"

REPO = Path(__file__).resolve().parents[3]

# Keep in step with SITE in the Makefile. Each dependency's directory relative
# to these pages (all are siblings under build/site), and the inventory its
# build left there.
SITE = REPO / "build" / "site"
intersphinx_mapping = {
    "core": ("../core/", str(SITE / "core" / "objects.inv")),
    "report": ("../report/", str(SITE / "report" / "objects.inv")),
}

# These pages build into launcher/ beneath the documentation site's landing
# page (build/site; see the Makefile), and every page links back up to it. The
# link is a sidebar template shared with the other packages' projects from the
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
