"""Sphinx configuration for the fmri-qa documentation.

One project builds the whole site: the landing page, and a user guide covering
every package. The analysis pages describe what each analysis computes and what
it contributes to the netCDF artifact, so two things have to be true of the
build: an equation has to render as an equation, and a figure has to be
*output*, not an illustration. MyST gives the first (Markdown the repository
already writes, with `$$` math handed to MathJax); matplotlib's `plot_directive`
gives the second, by running each figure's code against the installed package
at build time over the synthetic phantom in `phantom.py`. `make docs` builds
with `-W`, so a figure whose code stops matching the package fails the build
rather than going stale.

Deliberately nothing here resolves against another project's inventory: every
page links only within this one, and a build that reaches the network to
succeed is one that fails offline.
"""

from pathlib import Path

project = "fmri-qa"
author = "Judd Storrs"
copyright = "2026, Judd Storrs"  # noqa: A001  (the name Sphinx reads)

extensions = [
    "myst_parser",
    "sphinx.ext.mathjax",
    "matplotlib.sphinxext.plot_directive",
]

exclude_patterns = ["_build"]

# `dollarmath` for the inline and `$$` display math the method sections are
# written in, `amsmath` for the aligned environments a multi-line derivation
# needs, and `colon_fence` so a directive can be written as a ::: block where
# that reads better than a backtick fence.
myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = "fmri-qa"

# Figures are results, not examples: the reader wants the curve, and the code
# that drew it bears on the page's subject only incidentally. PNG at 150 dpi
# is what a browser and a printed page both want from a plot this size.
plot_include_source = False
plot_html_show_source_link = False
plot_html_show_formats = False
plot_formats = [("png", 150)]

# Where a `plot` block's code runs. matplotlib chdirs here and puts it on
# `sys.path`, which is what lets every figure `import phantom` and share one
# analysis of the phantom rather than each rebuilding it.
plot_working_directory = str(Path(__file__).parent)
