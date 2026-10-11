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

The API reference is generated from the installed packages' docstrings by
autodoc, with numpydoc turning their numpydoc sections into rendered fields.

Deliberately nothing here resolves against another project's inventory: every
page links only within this one, and a build that reaches the network to
succeed is one that fails offline. The price is in the API reference: numpy,
standard-library and xarray types in a signature or a docstring render as
unlinked text. That is also why `nitpicky` stays off, and why `-W` cannot catch
an unresolved `py:` reference there.
"""

from pathlib import Path

project = "fmri-qa"
author = "Judd Storrs"
copyright = "2026, Judd Storrs"  # noqa: A001  (the name Sphinx reads)

extensions = [
    "myst_parser",
    "sphinx.ext.mathjax",
    "matplotlib.sphinxext.plot_directive",
    "sphinx.ext.autodoc",
    # Only for its `autolink` role (the default role below), not for stub pages.
    # numpydoc loads it anyway; listing it records the dependency.
    "sphinx.ext.autosummary",
    "numpydoc",
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

# A single-backtick name in a docstring (`roi`, `Theme`) links when it resolves
# and does not warn when it cannot. Resolution runs in the defining module, so
# a name imported from elsewhere links only when written fully qualified
# (`~fmriqc.AnalysisSettings`); one that does not import renders as emphasis. The
# house style uses single backticks for both cross-references and parameter
# names, so the default role has to tolerate the latter.
default_role = "autolink"

# Document members, but only the ones with a docstring or a `#:` comment: an
# undocumented name in the reference is noise. `show-inheritance` stays off:
# the records are flat, and a "Bases: object" line says nothing.
autodoc_default_options = {"members": True}

# Each module's names in the order of kind (classes, functions, data), the way a
# reader looks things up, not alphabetically across kinds or in source order.
autodoc_member_order = "groupwise"

# Types stay in the signature line, where they are written, rather than being
# repeated as extra fields under the description (numpydoc supplies those). This
# is Sphinx's default, set here so the choice is visible.
autodoc_typehints = "signature"

# numpydoc would otherwise append a table of every attribute and method to each
# class, duplicating the members autodoc already lists below it.
numpydoc_show_class_members = False
