"""Page arithmetic for the PDF driver: fitting text and paginating rows.

Pure measurement, with no canvas in sight — how wide a string renders in a font,
how many lines a paragraph breaks into, and how many rows of a cover inventory
or a provenance appendix fit on a page before it has to continue on the next.
`pages` draws what these functions decide: the cursor functions below give the
baseline of every line a cover or appendix page draws, so the count that decides
how many rows fit and the positions they are drawn at are one arithmetic, and a
row that fits cannot land off the bottom of the sheet. The one thing measured
from outside the page is the cover's logo, whose drop depends on whether the
themed file is on disk; deciding that here keeps it from being decided twice.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics

from ...document import Appendix, Cover
from ...theme import Theme

# Row pitch (points) of the cover inventory: one line per scan.
COVER_ROW_H = 14.0

# An appendix row is a name line with a detail line beneath it, so its pitch is
# the two drops together and the row cannot outgrow its own spacing.
APPENDIX_NAME_DROP = 13.0
APPENDIX_DETAIL_DROP = 20.0
APPENDIX_ROW_H = APPENDIX_NAME_DROP + APPENDIX_DETAIL_DROP


def fit_text(text: str, font: str, size: float, width: float) -> str:
    """Truncate one-line report text to ``width``, preserving an ellipsis."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    ellipsis = "..."
    available = width - pdfmetrics.stringWidth(ellipsis, font, size)
    if available <= 0:
        return ""
    end = len(text)
    while end > 0 and pdfmetrics.stringWidth(text[:end], font, size) > available:
        end -= 1
    return text[:end].rstrip() + ellipsis


def wrap_text(text: str, font: str, size: float, width: float) -> list[str]:
    """Break report prose into lines no wider than `width` (points).

    For the catalog's definitions and methods, which say what a number is and
    must not be cut short the way a one-line label (`fit_text`) can be.
    """
    return simpleSplit(text, font, size, width) or [""]


def _page_chunks[T](
    rows: tuple[T, ...], first_capacity: int, next_capacity: int
) -> list[tuple[T, ...]]:
    """Split rows across a differently sized first page and continuation pages."""
    first_capacity = max(first_capacity, 1)
    next_capacity = max(next_capacity, 1)
    chunks = [rows[:first_capacity]]
    offset = first_capacity
    while offset < len(rows):
        chunks.append(rows[offset : offset + next_capacity])
        offset += next_capacity
    return chunks


# One line of the cover inventory: what kind of line it is, and its text.
CoverRow = tuple[Literal["scan", "heading", "omitted"], str]


def cover_rows(cover: Cover) -> tuple[CoverRow, ...]:
    """The cover's lines in order: the scans, then any omitted scans under a heading."""
    rows: list[CoverRow] = [("scan", name) for name in cover.scans]
    if cover.omitted:
        rows.append(("heading", f"Omitted ({len(cover.omitted)})"))
        rows.extend(("omitted", f"{name} — {reason}") for name, reason in cover.omitted)
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class CoverCursors:
    """The baselines a cover page draws on, top to bottom, and its lowest row.

    `logo` is the image file to draw and the baseline to draw it on, or `None`
    on a page that carries no logo — the file and its place travel together, so
    a page cannot reserve the space without having something to put in it. The
    drop the logo costs is likewise made only when there is one. `floor` is the
    last baseline a row may occupy.
    """

    logo: tuple[Path, float] | None
    title_y: float
    subtitle_y: float
    heading_y: float
    first_row_y: float
    floor: float


def cover_cursors(theme: Theme, *, continuation: bool) -> CoverCursors:
    """Where a cover page's logo, headings, and first inventory row sit.

    The subtitle's drop is made whether or not a subtitle is drawn, so a cover
    with one and a cover without paginate alike; the logo's drop is made only
    where there is a logo to draw, which means a first page whose themed logo
    file is on disk.
    """
    top = theme.page_height - 34.0 if continuation else theme.page_height * 0.70
    logo = (
        (theme.logo, top)
        if not continuation and theme.logo is not None and theme.logo.is_file()
        else None
    )
    title_y = top - 18.0 if logo is not None else top
    subtitle_y = title_y - (22.0 if continuation else 26.0)
    heading_y = subtitle_y - (16.0 if continuation else 40.0)
    return CoverCursors(
        logo=logo,
        title_y=title_y,
        subtitle_y=subtitle_y,
        heading_y=heading_y,
        first_row_y=heading_y - 16.0,
        floor=theme.margin + 10.0,
    )


@dataclass(frozen=True, slots=True)
class AppendixCursors:
    """The baselines an appendix page draws on, and its lowest row.

    `version_y` is `None` on a page that draws no version line; the drop it
    costs is then not made either. `floor` is the last baseline a row may take.
    """

    title_y: float
    version_y: float | None
    first_row_y: float
    floor: float


def appendix_cursors(
    theme: Theme, *, continuation: bool, has_version: bool
) -> AppendixCursors:
    """Where an appendix page's title, version line, and first row sit.

    Only a first page names the package version; a continuation carries the
    rows straight on under its own title.
    """
    title_y = theme.page_height - 34.0
    below_title = title_y - 20.0
    shows_version = has_version and not continuation
    return AppendixCursors(
        title_y=title_y,
        version_y=below_title if shows_version else None,
        first_row_y=below_title - 20.0 if shows_version else below_title,
        floor=theme.margin + 15.0,
    )


def _capacity(first_row_y: float, floor: float, row_h: float) -> int:
    """How many rows of pitch `row_h` fit between the first baseline and the floor."""
    return int((first_row_y - floor) // row_h) + 1


def cover_chunks(cover: Cover, theme: Theme) -> list[tuple[CoverRow, ...]]:
    """Paginate a cover inventory for the active page geometry."""
    first = cover_cursors(theme, continuation=False)
    following = cover_cursors(theme, continuation=True)
    return _page_chunks(
        cover_rows(cover),
        _capacity(first.first_row_y, first.floor, COVER_ROW_H),
        _capacity(following.first_row_y, following.floor, COVER_ROW_H),
    )


def appendix_chunks(
    appendix: Appendix, theme: Theme
) -> list[tuple[tuple[str, str], ...]]:
    """Paginate provenance rows above the running-footer area."""
    has_version = bool(appendix.version)
    first = appendix_cursors(theme, continuation=False, has_version=has_version)
    following = appendix_cursors(theme, continuation=True, has_version=has_version)
    return _page_chunks(
        appendix.rows,
        _capacity(first.first_row_y, first.floor, APPENDIX_ROW_H),
        _capacity(following.first_row_y, following.floor, APPENDIX_ROW_H),
    )
