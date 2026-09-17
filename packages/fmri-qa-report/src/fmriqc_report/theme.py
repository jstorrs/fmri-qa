"""The report `Theme`: the single source of every visual decision.

A `Theme` carries the page geometry, typography, and colours a report is drawn
with. One instance is threaded through both output paths -- the ReportLab page
furniture (this driver) and, once wired, the matplotlib panels -- so an embedded
figure stays visually consistent with the page around it. The default `Theme()`
reproduces the historical appearance exactly, so adopting it changes no output;
a group rebrands by instantiating or subclassing it.

See `notes/report_redesign.md` for the design.
"""

from dataclasses import dataclass, field
from pathlib import Path

from cycler import cycler
from reportlab.lib.pagesizes import letter

# matplotlib's default categorical cycle; the theme accent replaces its first
# entry so a themed primary series recolours while the semantic tab10 colours
# (used explicitly by the multi-series plots) stay put.
_MPL_TAB10 = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


@dataclass(frozen=True, slots=True)
class Theme:
    """Page geometry, fonts, and colours for a rendered report.

    Colours are ReportLab gray levels (0.0 black .. 1.0 white) for the furniture
    the driver draws natively, and hex strings for the marks the matplotlib
    panels draw. `pass_warn_fail` is reserved for the deferred acceptance
    thresholds and is unused until they land.
    """

    # Page geometry (points).
    page_size: tuple[float, float] = field(default_factory=lambda: letter)
    margin: float = 40.0

    # Typography: names of fonts registered with ReportLab.
    font_title: str = "Helvetica-Bold"
    font_body: str = "Helvetica"
    font_numeric: str = "Helvetica-Bold"  # the big metric-tile values

    # Furniture colours as ReportLab gray levels.
    text_primary_gray: float = 0.0
    text_muted_gray: float = 0.40
    tile_value_gray: float = 0.10
    tile_label_gray: float = 0.45
    tile_fill_gray: float = 0.96
    tile_stroke_gray: float = 0.80

    # Panel colours, applied to the matplotlib figures via `rc_params`.
    panel_cmap: str = "gray"
    panel_accent: str = "#1f77b4"  # matplotlib "tab:blue"; the primary-series colour
    panel_font_family: str | None = None  # None keeps the matplotlib default family
    pass_warn_fail: tuple[str, str, str] = ("#2e7d32", "#f9a825", "#c62828")  # reserved

    # Brand furniture.
    logo: Path | None = None
    footer: str = ""
    cover_title: str = "fMRI QA Report"

    @property
    def page_width(self) -> float:
        """Width of the sheet (points)."""
        return self.page_size[0]

    @property
    def page_height(self) -> float:
        """Height of the sheet (points)."""
        return self.page_size[1]

    @property
    def content_width(self) -> float:
        """Drawable width between the left and right margins (points)."""
        return self.page_width - 2 * self.margin

    def rc_params(self) -> dict[str, object]:
        """matplotlib rcParams that style the panels to match the page.

        A driver activates these with `matplotlib.rc_context` around the figure
        building so the phantom colormap, the primary-series colour, and the
        font follow the theme. The default theme returns matplotlib's own
        defaults (gray images, the tab10 cycle), so panels are unchanged.
        """
        rc: dict[str, object] = {
            "image.cmap": self.panel_cmap,
            "axes.prop_cycle": cycler(color=[self.panel_accent, *_MPL_TAB10[1:]]),
        }
        if self.panel_font_family is not None:
            rc["font.family"] = self.panel_font_family
        return rc


DEFAULT_THEME = Theme()
