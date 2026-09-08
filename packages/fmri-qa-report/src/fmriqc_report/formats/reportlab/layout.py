"""Page arithmetic for the PDF driver: fitting text and paginating rows.

Pure measurement, with no canvas in sight — how wide a string renders in a font,
how many lines a paragraph breaks into, and how many rows of a cover inventory
or a provenance appendix fit on a page before it has to continue on the next.
`pages` draws what these functions decide.
"""

from typing import Literal

from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics

from ...document import Appendix, Cover
from ...theme import Theme

# Row pitch (points) of the two paginated lists.
COVER_ROW_H = 14.0
APPENDIX_ROW_H = 33.0


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


def cover_chunks(cover: Cover, theme: Theme) -> list[tuple[CoverRow, ...]]:
    """Paginate a cover inventory for the active page geometry."""
    y = theme.page_size[1] * 0.70
    if theme.logo is not None and theme.logo.is_file():
        y -= 18
    # The drops `cover_page` makes before the first row: past the title, the
    # subtitle, and the "Scans (n)" heading.
    y -= 26
    y -= 40
    y -= 16
    floor = theme.margin + 10
    first = int((y - floor) // COVER_ROW_H) + 1
    continuation_y = theme.page_size[1] - 34 - 22 - 16 - 16
    following = int((continuation_y - floor) // COVER_ROW_H) + 1
    return _page_chunks(cover_rows(cover), first, following)


def appendix_chunks(
    appendix: Appendix, theme: Theme
) -> list[tuple[tuple[str, str], ...]]:
    """Paginate provenance rows above the running-footer area."""
    y = theme.page_size[1] - 34 - 20
    if appendix.version:
        y -= 20
    floor = theme.margin + 15
    first = int((y - floor) // APPENDIX_ROW_H) + 1
    continuation_y = theme.page_size[1] - 34 - 20
    following = int((continuation_y - floor) // APPENDIX_ROW_H) + 1
    return _page_chunks(appendix.rows, first, following)
