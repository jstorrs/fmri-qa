"""The report `Theme`, the visual decisions the matplotlib panels follow.

A `Theme` carries the colormap, accent colour, and font family a run page's
figures use, exposed as matplotlib rcParams through `rc_params()`. The default
`Theme()` draws gray images with matplotlib's tab10 colour cycle and default
font; a group rebrands by instantiating it.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cycler import cycler

if TYPE_CHECKING:
    from matplotlib.typing import RcKeyType

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
    """Colours and fonts for a rendered report's matplotlib panels."""

    # Panel colours, applied to the matplotlib figures via `rc_params`.
    panel_cmap: str = "gray"
    panel_accent: str = "#1f77b4"  # matplotlib "tab:blue"; the primary-series colour
    panel_font_family: str | None = None  # None keeps the matplotlib default family

    def rc_params(self) -> "dict[RcKeyType, object]":
        """Build the matplotlib rcParams that style the panels to match the page.

        A driver activates these with `matplotlib.rc_context` around the figure
        building so the phantom colormap, the primary-series colour, and the
        font follow the theme. The default theme draws gray images with
        matplotlib's tab10 colour cycle and default font.
        """
        rc: dict[RcKeyType, object] = {
            "image.cmap": self.panel_cmap,
            "axes.prop_cycle": cycler(color=[self.panel_accent, *_MPL_TAB10[1:]]),
        }
        if self.panel_font_family is not None:
            rc["font.family"] = self.panel_font_family
        return rc


DEFAULT_THEME = Theme()
