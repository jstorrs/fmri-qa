"""Sphinx configuration for the fmri-qa documentation.

One project builds the whole site: the landing page and a user guide covering
every package. The analysis pages describe what each analysis computes and what
it adds to the netCDF artifact. So equations must render as equations, and
figures must be real output, not illustrations. MyST renders the math (`$$`
blocks go to MathJax). matplotlib's `plot_directive` draws the figures by
running each figure's code against the installed package, over the synthetic
phantom in `phantom.py`. `make docs` builds with `-W`, so a figure whose code
stops matching the package fails the build.

The API reference is generated from the installed packages' docstrings by
autodoc. numpydoc turns their numpydoc sections into rendered fields.

Nothing here resolves against another project's inventory. Every page links
only within this one, so the build works offline. The cost is in the API
reference: numpy, standard-library and xarray types in a signature or a
docstring render as unlinked text. For the same reason `nitpicky` stays off,
and `-W` cannot catch an unresolved `py:` reference there.
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

# `dollarmath` is for inline and `$$` display math. `amsmath` is for aligned
# environments in multi-line derivations. `colon_fence` lets a directive be
# written as a ::: block instead of a backtick fence.
myst_enable_extensions = ["dollarmath", "amsmath", "colon_fence"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = "fmri-qa"

# Show the figure, not the code that drew it. PNG at 150 dpi works on screen
# and in print.
plot_include_source = False
plot_html_show_source_link = False
plot_html_show_formats = False
plot_formats = [("png", 150)]

# Where a `plot` block's code runs. matplotlib chdirs here and puts it on
# `sys.path`, so every figure can `import phantom` and share one analysis of
# the phantom.
plot_working_directory = str(Path(__file__).parent)

# A single-backtick name in a docstring (`roi`, `Theme`) links when it resolves
# and does not warn when it cannot. Resolution runs in the defining module, so
# a name imported from elsewhere links only when written fully qualified
# (`~fmriqc.AnalysisSettings`). A name that does not import renders as
# emphasis. The house style uses single backticks for both cross-references and
# parameter names, so the default role must tolerate the latter.
default_role = "autolink"

# Document only members with a docstring or a `#:` comment. `show-inheritance`
# stays off: the records are flat, so "Bases: object" adds nothing.
autodoc_default_options = {"members": True}

# Group each module's names by kind (classes, functions, data), sorted
# alphabetically within each group. Not alphabetical across kinds or in source
# order.
autodoc_member_order = "groupwise"

# Keep types in the signature line instead of repeating them as extra fields
# under the description (numpydoc supplies those). This is Sphinx's default,
# set here to make it visible.
autodoc_typehints = "signature"

# Otherwise numpydoc appends a table of every attribute and method to each
# class, duplicating the members autodoc lists below it.
numpydoc_show_class_members = False
