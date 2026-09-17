"""Assemble the pages into a PDF file.

Walks the block list `document.compose` produced, hands each block to the page
renderers in `pages`, counts the pages up front so the running footer can say
"3 / 7", and writes the whole thing atomically. `write_report` is the driver's
public entry point; `add_report_pages` is the per-scan primitive beneath it.
"""

import os
import tempfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import matplotlib
from reportlab.pdfgen import canvas

from fmriqc.analysis import QAArtifact

from ...document import Appendix, Block, Cover, ScanSection, Tier, compose, parts_for
from ...theme import DEFAULT_THEME, Theme
from .layout import appendix_chunks, cover_chunks
from .pages import PART_RENDERERS, appendix_page, cover_page, draw_footer


def _draw_parts(
    c: canvas.Canvas,
    section: ScanSection,
    theme: Theme,
    after_part: Callable[[int], None] = lambda _: None,
) -> int:
    """Draw and finalize one scan's parts; return how many pages that took.

    The parts are built under the theme's `rc_context`, so the phantom colormap
    and the primary-series colour follow the theme along with the furniture.
    `after_part` runs on each page before `showPage`, numbered from 1, which is
    where a packet draws its footer and a bare `add_report_pages` draws nothing.
    """
    with matplotlib.rc_context(theme.rc_params()):
        for index, part in enumerate(section.parts, start=1):
            PART_RENDERERS[part](c, section.artifact, section.title, theme)
            after_part(index)
            c.showPage()
    return len(section.parts)


def add_report_pages(
    c: canvas.Canvas,
    artifact: QAArtifact,
    title: str = "",
    tier: Tier = "dashboard",
    theme: Theme = DEFAULT_THEME,
) -> int:
    """Draw a scan's report page(s) onto an open ReportLab `Canvas`.

    `tier="dashboard"` renders the single condensed overview page; `tier="physics"`
    renders that overview and then a full-size stability page. Each page is
    finalized with `showPage()`. Returns the number of pages drawn. This is the
    per-scan primitive with no packet furniture; `write_report` adds the cover,
    appendix, and page footers.
    """
    return _draw_parts(c, ScanSection(title, artifact, parts_for(tier)), theme)


def _block_pages(block: Block, theme: Theme) -> int:
    """How many pages a block draws: its parts for a scan, else one."""
    if isinstance(block, ScanSection):
        return len(block.parts)
    if isinstance(block, Cover):
        return len(cover_chunks(block, theme))
    return len(appendix_chunks(block, theme))


def _render_block(
    c: canvas.Canvas,
    block: Block,
    theme: Theme,
    page_no: int,
    total: int,
    note: str = "",
) -> int:
    """Draw one block; return the running page number after it.

    The cover carries no footer (it reads as a title page, and lists any
    omission itself); every other page gets the running footer with `note`.
    """
    if isinstance(block, Cover):
        for index, rows in enumerate(cover_chunks(block, theme)):
            cover_page(c, block, rows, theme, continuation=index > 0)
            c.showPage()
            page_no += 1
        return page_no
    if isinstance(block, Appendix):
        for index, entries in enumerate(appendix_chunks(block, theme)):
            page_no += 1
            appendix_page(c, block, entries, theme, continuation=index > 0)
            draw_footer(c, theme, page_no, total, note)
            c.showPage()
        return page_no
    first = page_no
    _draw_parts(
        c, block, theme, lambda n: draw_footer(c, theme, first + n, total, note)
    )
    return first + len(block.parts)


def write_report(
    items: Iterable[tuple[str, QAArtifact]] | QAArtifact,
    pdf_path: str | Path,
    tier: Tier = "dashboard",
    theme: Theme = DEFAULT_THEME,
    *,
    cover: bool = False,
    appendix: bool = False,
    omitted: Sequence[tuple[str, str]] = (),
) -> int:
    """Write a combined PDF packet: optional cover, the scans, optional appendix.

    `items` is an iterable of `(title, QAArtifact)`, or a single `QAArtifact`.
    `cover` prepends a branded cover with the scan inventory; `appendix` appends
    a provenance page. Multi-page packets carry a running footer with the theme's
    brand text and page numbers. `omitted` names requested scans that are not in
    the packet (file name, reason): they are listed on the cover and in the
    appendix, the PDF's subject metadata counts them, and every scan page's
    footer says the packet is incomplete -- a page handed on alone must not
    read as the whole. Returns the total number of pages written.
    """
    if isinstance(items, QAArtifact):
        items = [("", items)]
    blocks = compose(items, tier, cover=cover, appendix=appendix, omitted=omitted)
    total = sum(_block_pages(b, theme) for b in blocks)
    n_scans = sum(isinstance(b, ScanSection) for b in blocks)
    note = ""
    subject = f"fMRI QA packet: {n_scans} scan(s)"
    if omitted:
        n_requested = n_scans + len(omitted)
        note = f"INCOMPLETE PACKET: {len(omitted)} of {n_requested} scans omitted"
        subject = (
            f"fMRI QA packet: {n_scans} of {n_requested} scans; {len(omitted)} omitted"
        )
    target = Path(pdf_path)
    # Match `save_artifact`: create the destination directory rather than fail
    # on the temporary file, whose name is an implementation detail of the
    # atomic write and has no business appearing in a user-facing error.
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        c = canvas.Canvas(str(temporary), pagesize=theme.page_size)
        c.setTitle(theme.cover_title)
        c.setSubject(subject)
        page_no = 0
        for block in blocks:
            page_no = _render_block(c, block, theme, page_no, total, note)
        c.save()
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return total
