"""The report `Theme`: the visual settings the matplotlib panels follow.

A `Theme` carries the colormap, accent color and font family a run page's
figures use, exposed as matplotlib rcParams through `rc_params()`. The default
draws gray images with matplotlib's tab10 color cycle and default font. A group
rebrands by instantiating its own.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cycler import cycler

if TYPE_CHECKING:
    from matplotlib.typing import RcKeyType

# matplotlib's default categorical cycle. The theme accent replaces its first
# entry, so a themed primary series recolors. The semantic tab10 colors stay
# put: `plot_motion`, `plot_com` and `plot_psf` use them explicitly by name, not
# through the cycle.
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
    """Colors and fonts for a rendered report's matplotlib panels."""

    # Panel colors, applied to the matplotlib figures via `rc_params`.
    panel_cmap: str = "gray"
    panel_accent: str = "#1f77b4"  # matplotlib "tab:blue"; the primary-series color
    panel_font_family: str | None = None  # None keeps the matplotlib default family

    def rc_params(self) -> "dict[RcKeyType, object]":
        """Build the matplotlib rcParams that style the panels to match the page.

        A driver activates these with `matplotlib.rc_context` around figure
        building, so the phantom colormap, primary-series color and font follow
        the theme.
        """
        rc: dict[RcKeyType, object] = {
            "image.cmap": self.panel_cmap,
            "axes.prop_cycle": cycler(color=[self.panel_accent, *_MPL_TAB10[1:]]),
        }
        if self.panel_font_family is not None:
            rc["font.family"] = self.panel_font_family
        return rc


#: The theme a report uses when none is given: gray colormap, tab:blue accent,
#: default font.
DEFAULT_THEME = Theme()
