"""The report document model: blocks and the depth-tier composition.

A report is a list of blocks a format driver walks. `compose` turns the scans
plus a depth *tier* into that block list; a `ScanSection` names the page *parts*
to render for one scan. The tiers are ordered by depth, and `dashboard` is a
strict prefix of `physics` -- physics renders the dashboard's parts and then
adds its own -- so the two tiers cannot drift out of agreement.

See `notes/report_redesign.md` for the design.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, get_args

import fmriqc as q

# The audience/depth tiers, ordered shallow -> deep.
Tier = Literal["dashboard", "physics"]
TIERS: tuple[Tier, ...] = get_args(Tier)

# A renderable page unit; each maps to one renderer in a format driver.
Part = Literal["overview", "stability"]

# Parts per tier. `physics` starts with `dashboard`'s parts, so the shallower
# tier is a strict prefix of the deeper one.
_TIER_PARTS: dict[Tier, tuple[Part, ...]] = {
    "dashboard": ("overview",),
    "physics": ("overview", "stability"),
}


@dataclass(frozen=True, slots=True)
class ScanSection:
    """One scan's block: its title, result, and the parts to render for it."""

    title: str
    result: q.QAResult
    parts: tuple[Part, ...]


def parts_for(tier: Tier) -> tuple[Part, ...]:
    """The ordered page parts a tier renders."""
    try:
        return _TIER_PARTS[tier]
    except KeyError:
        raise ValueError(f"unknown tier {tier!r}; choose from {TIERS}") from None


def compose(items: Iterable[tuple[str, q.QAResult]], tier: Tier) -> list[ScanSection]:
    """Build the block list: one `ScanSection` per scan at the given tier."""
    parts = parts_for(tier)
    return [ScanSection(title, result, parts) for title, result in items]
