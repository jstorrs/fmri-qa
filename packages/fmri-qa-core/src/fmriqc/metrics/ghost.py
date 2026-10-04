"""Nyquist (N/2) ghost ratios and phase-encode-axis estimation.

The ghost is located by rolling the phantom half the FOV along the phase-encode
axis; every statistic here is a region-matched ghost-to-signal ratio built on
that idea. `estimate_ghost` builds the masks for both in-plane axes once and
measures the whole family from them, returning a `GhostResult` that carries the
masks it sampled — so a report draws the regions the numbers came from rather
than rebuilding them. `ghost_ratios` computes that same per-axis ratio for both
in-plane axes without picking a winner; `estimate_pe_axis` picks one -- the
axis where the ghost actually lands -- which `run_qa` uses as its last-resort
fallback when no sidecar/header PE axis is available (see `load.pe_axis`).
"""

from dataclasses import dataclass

import numpy as np
from skimage.morphology import isotropic_dilation, isotropic_erosion

from .._arrays import ArrayValue
from ..types import PE_AXES, BoolArray, FloatArray, PeAxis, readout_axis

# Fraction of the brightest ghost-region voxels averaged for the localized-ghost
# statistic (Greve / bxh fmriqa_ghostiness "top-10%"): catches a concentrated
# bright ghost that the region-mean ghost ratio dilutes.
GHOST_TOP_FRACTION = 0.10

# Erosion/dilation radius (voxels) that sets the ghost/signal band width. The
# single source of truth for every ghost statistic's default and for the report
# overlay, so the drawn masks always match the masks the numbers were sampled on.
GHOST_RADIUS = 3


def ghost_masks(
    phantom_mask: BoolArray,
    pe_axis: PeAxis,
    radius: int = GHOST_RADIUS,
    *,
    valid_mask: BoolArray,
) -> tuple[BoolArray, BoolArray]:
    """Region-matched (signal, ghost) masks for a candidate PE axis.

    The ghost is the phantom rolled half the FOV along `pe_axis`; the ghost mask
    keeps the part of it that lands clear of the phantom (eroded, with the dilated
    phantom and any invalid image edge removed). The signal mask is that same
    ghost mask rolled back half the FOV onto the phantom, so the ratio compares
    each ghost patch against the exact tissue that produced it. The phantom/PE-
    ghost overlap zone -- where signal and ghost are superimposed and cannot be
    separated -- is thereby excluded from both masks. `valid_mask` excludes zeroed
    image edges (see `edge_valid_mask`) and is required rather than defaulted: an
    image with a nonzero NIfTI `scl_inter` nulls its edge to the intercept, not to
    0.0, so a mask built from `edge_valid_mask`'s own default (`zero=0.0`) would
    silently detect no nulled edge on exactly the scans that default is wrong for.
    Pass `edge_valid_mask(mean_image, zero=...)` or `QAImages.valid_mask`.
    """
    shift = phantom_mask.shape[pe_axis] // 2
    ghost = np.roll(phantom_mask, shift, axis=pe_axis)

    ghost_mask = (
        isotropic_erosion(ghost, radius)
        & ~isotropic_dilation(phantom_mask, radius)
        & valid_mask
    )
    signal_mask = np.roll(ghost_mask, -shift, axis=pe_axis)
    return signal_mask, ghost_mask


def _mean_ratio(
    mean_image: FloatArray, signal_mask: BoolArray, ghost_mask: BoolArray
) -> float:
    """Region-mean ghost-to-signal ratio over one matched mask pair.

    The single definition of the fBIRN ghost ratio. NaN when either region came
    back empty -- no measurement at all, which is not the same as a low one.
    """
    if not ghost_mask.any() or not signal_mask.any():
        return float("nan")
    return float(mean_image[ghost_mask].mean() / mean_image[signal_mask].mean())


def _top_ratio(
    mean_image: FloatArray,
    signal_mask: BoolArray,
    ghost_mask: BoolArray,
    top: float = GHOST_TOP_FRACTION,
) -> float:
    """Top-fraction ghost-to-signal ratio over one matched mask pair.

    The single definition of the localized ghost ratio: `_mean_ratio` with the
    numerator narrowed to the brightest `top` fraction of ghost voxels, so a
    concentrated bright ghost shows where the region mean dilutes it. At least
    one voxel is always averaged, so this can only exceed the region mean.
    """
    ghost = mean_image[ghost_mask]
    if ghost.size == 0 or not signal_mask.any():
        return float("nan")
    k = max(1, round(top * ghost.size))
    brightest = np.partition(ghost, -k)[-k:]  # the k largest ghost-voxel intensities
    return float(brightest.mean() / mean_image[signal_mask].mean())


@dataclass(frozen=True, eq=False, slots=True)
class GhostResult(ArrayValue):
    """The whole Nyquist-ghost family, measured on one pair of axes at once.

    Built by `estimate_ghost` from the masks it carries: `pe_signal`/`pe_ghost`
    are the region-matched pair along the resolved phase-encode axis, and
    `ro_signal`/`ro_ghost` the same pair along the readout axis (`readout_axis`),
    which is a background-relative baseline because no N/2 ghost lands there.
    Every ratio below was averaged over exactly these masks, so a report drawing
    them is drawing what was measured.

    `pe_ratio` is the fBIRN ghost-to-signal ratio, `pe_top_ratio` its localized
    (Greve / bxh `fmriqa_ghostiness`) companion over the brightest `top` fraction
    of ghost voxels, and `ro_ratio` the readout baseline. A NaN ratio means the
    region it needed came back empty -- the phantom spans the FOV along that
    axis, or the segmentation collapsed.
    """

    pe_axis: PeAxis
    radius: int
    pe_signal: BoolArray
    pe_ghost: BoolArray
    ro_signal: BoolArray
    ro_ghost: BoolArray
    pe_ratio: float
    ro_ratio: float
    pe_top_ratio: float

    @property
    def acr_ratio(self) -> float:
        """ACR/AAPM-equivalent ghosting ratio: `|pe_ratio - ro_ratio|`.

        The classic ACR/AAPM "percent-signal-ghosting" subtracts a background
        estimate (the frequency axis, which carries no N/2 ghost) from the
        phase-encode ghost, normalized by the central signal:
        `|ghost_pe - ghost_freq| / signal`. This is that same contrast in fBIRN
        region-matched space -- each ghost patch normalized by the exact tissue
        that produced it, with the phantom/ghost overlap zone excluded from both.

        Because each direction carries its own matched denominator, the readout
        ratio is a genuine background-relative-to-signal baseline; subtracting it
        cancels the background exactly as ACR intends, without ACR's
        single-signal assumption (for a uniform phantom the two denominators
        coincide and this reduces to the classic form).
        """
        return abs(self.pe_ratio - self.ro_ratio)

    @property
    def ghost_pct(self) -> float:
        """The fBIRN percent ghost along the phase-encode axis."""
        return 100.0 * self.pe_ratio

    @property
    def ghost_top_pct(self) -> float:
        """Localized (top-fraction) percent ghost along the phase-encode axis."""
        return 100.0 * self.pe_top_ratio

    @property
    def ro_ghost_pct(self) -> float:
        """Percent ghost along the readout axis: the background-relative baseline."""
        return 100.0 * self.ro_ratio

    @property
    def acr_ghost_pct(self) -> float:
        """ACR/AAPM percent-signal-ghosting: `|ghost_pct - ro_ghost_pct|`."""
        return 100.0 * self.acr_ratio


def estimate_ghost(
    mean_image: FloatArray,
    phantom_mask: BoolArray,
    pe_axis: PeAxis,
    *,
    valid_mask: BoolArray,
    radius: int = GHOST_RADIUS,
    top: float = GHOST_TOP_FRACTION,
) -> GhostResult:
    """Measure every Nyquist-ghost statistic for a known phase-encode axis.

    Builds the region-matched masks once per in-plane axis and takes all three
    ratios from them, so no two of the family can disagree and the caller keeps
    the masks that were sampled. `pe_axis` is the resolved phase-encode axis (0
    or 1); the readout axis is the other one. `radius` sets the erosion/dilation
    band width and `top` the localized-ghost fraction -- both are
    acquisition-dependent and should be verified per protocol. `valid_mask`
    excludes zeroed image edges (see `edge_valid_mask`).
    """
    pe_signal, pe_ghost = ghost_masks(
        phantom_mask, pe_axis, radius, valid_mask=valid_mask
    )
    ro_axis = readout_axis(pe_axis)
    ro_signal, ro_ghost = ghost_masks(
        phantom_mask, ro_axis, radius, valid_mask=valid_mask
    )
    return GhostResult(
        pe_axis=pe_axis,
        radius=radius,
        pe_signal=pe_signal,
        pe_ghost=pe_ghost,
        ro_signal=ro_signal,
        ro_ghost=ro_ghost,
        pe_ratio=_mean_ratio(mean_image, pe_signal, pe_ghost),
        ro_ratio=_mean_ratio(mean_image, ro_signal, ro_ghost),
        pe_top_ratio=_top_ratio(mean_image, pe_signal, pe_ghost, top),
    )


def ghost_ratio(
    mean_image: FloatArray,
    phantom_mask: BoolArray,
    pe_axis: PeAxis,
    radius: int = GHOST_RADIUS,
    *,
    valid_mask: BoolArray,
) -> float:
    """The fBIRN Nyquist ghost-to-signal ratio for one candidate axis.

    A single axis' worth of `estimate_ghost` — what `ghost_ratios` needs to
    score a candidate, before any axis is settled. A run that has settled its
    axis calls `estimate_ghost` and reads `pe_ratio`, so the whole family comes
    off one set of masks. `valid_mask` excludes zeroed image edges (see
    `edge_valid_mask`) and is required rather than defaulted: an image with a
    nonzero NIfTI `scl_inter` nulls its edge to the intercept, not to 0.0, so a
    mask built from `edge_valid_mask`'s own default (`zero=0.0`) would silently
    detect no nulled edge on exactly the scans that default is wrong for. Pass
    `edge_valid_mask(mean_image, zero=...)` or `QAImages.valid_mask`.
    """
    signal_mask, ghost_mask = ghost_masks(
        phantom_mask, pe_axis, radius, valid_mask=valid_mask
    )
    return _mean_ratio(mean_image, signal_mask, ghost_mask)


def ghost_ratios(
    mean_image: FloatArray,
    phantom_mask: BoolArray,
    radius: int = GHOST_RADIUS,
    *,
    valid_mask: BoolArray,
) -> dict[PeAxis, float]:
    """`ghost_ratio` for both in-plane axes, keyed by axis index.

    Rolling the phantom along the *true* PE axis lines the ghost region up with
    real ghost signal (high mean); along the wrong axis it lands on background
    (low mean) — what `estimate_pe_axis` compares to pick a winner. An axis
    whose ghost region came back empty — the phantom spans the FOV along it, or
    the segmentation collapsed — scores NaN: not a low
    ratio but no ratio at all, a distinction `estimate_pe_axis` relies on.
    """
    return {
        axis: ghost_ratio(
            mean_image, phantom_mask, pe_axis=axis, radius=radius, valid_mask=valid_mask
        )
        for axis in PE_AXES
    }


def estimate_pe_axis(
    mean_image: FloatArray,
    phantom_mask: BoolArray,
    radius: int = GHOST_RADIUS,
    *,
    valid_mask: BoolArray,
) -> PeAxis | None:
    """Guess the phase-encode axis from where the Nyquist ghost actually lands.

    The axis with the larger `ghost_ratios` ratio wins, but only among axes the
    ratio could actually be measured on: comparing against a NaN ratio is what
    a plain float comparison silently gets wrong, always answering False and
    leaving whichever axis was looked at first as the winner. When neither axis
    is measurable, or both finite ratios are exactly equal, the answer is None.
    A single measurable axis wins even when its ratio is zero.

    NOTE: shares the tuning caveats of `ghost_ratio` — a win by a hair is still
    a guess, so verify against the acquisition's known PE direction before
    trusting it.
    """
    ratios = ghost_ratios(mean_image, phantom_mask, radius, valid_mask=valid_mask)
    # Annotated: inferring the element type from the comprehension widens the
    # axes back to `int`, and the `ratios` lookup below only accepts a `PeAxis`.
    measurable: list[PeAxis] = [
        axis for axis, ratio in ratios.items() if np.isfinite(ratio)
    ]
    if not measurable or ratios[0] == ratios[1]:
        return None
    return max(measurable, key=ratios.__getitem__)
