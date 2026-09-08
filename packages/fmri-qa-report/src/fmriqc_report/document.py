"""The report document model: blocks and the depth-tier composition.

A report is a list of blocks a format driver walks. `compose` turns the scans
plus a depth *tier* into that block list: an optional `Cover`, one `ScanSection`
per scan, and an optional `Appendix`. A `ScanSection` names the page *parts* to
render for one scan. The tiers are ordered by depth, and `dashboard` is a strict
prefix of `physics` -- physics renders the dashboard's parts and then adds its
own -- so the two tiers cannot drift out of agreement.

See `notes/report_redesign.md` for the design.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from fmriqc.analysis import QAArtifact

from .summary import _appendix_rows, package_version

# The audience/depth tiers, ordered shallow -> deep.
Tier = Literal["dashboard", "physics"]
TIERS: tuple[Tier, ...] = get_args(Tier)

# A renderable page unit; each maps to one renderer in a format driver.
Part = Literal["overview", "stability", "characterization", "methods"]

# Parts per tier. `physics` starts with `dashboard`'s parts, so the shallower
# tier is a strict prefix of the deeper one.
_TIER_PARTS: dict[Tier, tuple[Part, ...]] = {
    "dashboard": ("overview",),
    "physics": ("overview", "stability", "characterization", "methods"),
}


@dataclass(frozen=True, slots=True)
class Cover:
    """The packet's branded cover: the scan inventory and an optional subtitle.

    The title, logo, and footer come from the `Theme` at render time; the block
    carries only the content -- which scans the packet contains, in order, and
    which requested scans it does *not* (`omitted`: file name and reason), so a
    reader holding only the PDF can tell an omission from an absence.
    """

    scans: tuple[str, ...]
    subtitle: str = ""
    omitted: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ScanSection:
    """One scan's block: its title, artifact, and the parts to render for it."""

    title: str
    artifact: QAArtifact
    parts: tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class Appendix:
    """The packet's provenance appendix: per-scan rows plus the package version.

    Rows are `(scan title, provenance text)`, pre-extracted from the artifacts
    so the block stays format-agnostic.
    """

    rows: tuple[tuple[str, str], ...]
    version: str = ""


# A block a driver knows how to render into one or more pages.
Block = Cover | ScanSection | Appendix


def parts_for(tier: Tier) -> tuple[Part, ...]:
    """The ordered page parts a tier renders."""
    try:
        return _TIER_PARTS[tier]
    except KeyError:
        raise ValueError(f"unknown tier {tier!r}; choose from {TIERS}") from None


def compose(
    items: Iterable[tuple[str, QAArtifact]],
    tier: Tier,
    *,
    cover: bool = False,
    appendix: bool = False,
    omitted: Sequence[tuple[str, str]] = (),
) -> list[Block]:
    """Build the block list for a packet.

    One `ScanSection` per scan at `tier`, optionally wrapped in a `Cover` (the
    scan inventory) and an `Appendix` (per-scan provenance + the package version).
    `omitted` names the requested scans that are *not* in the packet, with the
    reason each was left out; the cover lists them and the appendix carries a
    row for each, so the omission travels with the document.
    """
    scans = list(items)
    parts = parts_for(tier)
    blocks: list[Block] = []
    if cover:
        blocks.append(
            Cover(scans=tuple(title for title, _ in scans), omitted=tuple(omitted))
        )
    blocks.extend(ScanSection(title, artifact, parts) for title, artifact in scans)
    if appendix:
        rows = list(_appendix_rows(scans))
        rows.extend(
            (name, f"omitted from this packet: {reason}") for name, reason in omitted
        )
        blocks.append(Appendix(rows=tuple(rows), version=package_version()))
    return blocks
