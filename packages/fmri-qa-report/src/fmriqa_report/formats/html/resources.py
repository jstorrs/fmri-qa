"""The packaged, freeze-safe report resources: run template and stylesheet.

Everything is read through :func:`importlib.resources.files` on this package,
never ``__file__`` arithmetic, so a zipped or frozen install resolves like an
unpacked one. These two names are the complete resource inventory. Adding a
third means teaching any future packaging step about it.
"""

from importlib.resources import files
from typing import Literal

__all__ = [
    "RUN_TEMPLATE",
    "STYLESHEET",
    "ResourceName",
    "read_resource",
    "read_stylesheet",
]

#: Package-relative name of a bundled resource.
type ResourceName = Literal["assets/report.css", "templates/run.html"]


#: Name of the report stylesheet.
STYLESHEET: ResourceName = "assets/report.css"
#: Name of the run page template.
RUN_TEMPLATE: ResourceName = "templates/run.html"


def read_resource(name: ResourceName) -> str:
    """Return one packaged UTF-8 resource by its package-relative name."""
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


def read_stylesheet() -> str:
    """Return the packaged stylesheet, refusing a closing ``<style>`` tag.

    A run page inlines this text verbatim inside a ``<style>`` element, so a
    sequence that closes the element early would let arbitrary markup escape it.
    Every reader goes through this function, so the guard applies once.
    """
    css = read_resource(STYLESHEET)
    if "</style" in css.lower():
        raise ValueError("packaged stylesheet must not contain a closing style tag")
    return css
