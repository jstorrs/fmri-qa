"""ReportLab PDF driver: compose the format-agnostic panels/text onto pages.

The page layout (title, metadata, metric tiles, and the placement grid) is drawn
natively with ReportLab; every matplotlib figure from `panels` is embedded as
vector SVG (via svglib) so the axes, curves, and labels stay crisp. The phantom
images inside `imshow` are inherently raster and ride along inside the SVG.

`ls` this package to find a concern:

* `layout`       -- page arithmetic: fitting text, paginating rows
* `pages`        -- one function per page the driver can draw
* `packet`       -- assembling those pages into a PDF file
* `svglib_patch` -- the one svglib defect embedding a figure has to work around

This is the plug point for other output formats: a new driver reuses `panels`
and `summary` and only re-implements composition.
"""

from .packet import add_report_pages, write_report

__all__ = ["add_report_pages", "write_report"]
