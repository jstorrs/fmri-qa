"""Offline HTML report pages and complete static-site publication."""

from .figures import FIGURE_ASSETS, FigureAsset, write_figures
from .site import SiteResult, SiteStatus, write_site

__all__ = [
    "FIGURE_ASSETS",
    "FigureAsset",
    "SiteResult",
    "SiteStatus",
    "write_figures",
    "write_site",
]
