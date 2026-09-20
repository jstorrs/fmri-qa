"""The packaged, freeze-safe report resources: the run template and the stylesheet.

Everything is read through :func:`importlib.resources.files` on this package —
never ``__file__`` arithmetic — so a zipped or frozen install resolves the same
way an unpacked one does.  These two names are the complete resource
inventory; adding a third means teaching any future packaging step about it.
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

type ResourceName = Literal["assets/report.css", "templates/run.html"]


STYLESHEET: ResourceName = "assets/report.css"
RUN_TEMPLATE: ResourceName = "templates/run.html"


def read_resource(name: ResourceName) -> str:
    """Return one packaged UTF-8 resource by its package-relative name."""
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


def read_stylesheet() -> str:
    """Return the packaged stylesheet, guarded against escaping its ``<style>`` tag.

    A run page inlines this text verbatim inside a ``<style>`` element, so a
    byte sequence that closes that element early would let arbitrary markup
    escape it. Every reader of the stylesheet goes through this one function,
    so the guard applies once at the resource boundary rather than once per
    caller.
    """
    css = read_resource(STYLESHEET)
    if "</style" in css.lower():
        raise ValueError("packaged stylesheet must not contain a closing style tag")
    return css
