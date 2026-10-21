"""Nyquist (N/2) ghost ratios and phase-encode-axis estimation.

The ghost is located by rolling the phantom half the FOV along the phase-encode
axis, and every statistic here is a region-matched ghost-to-signal ratio built on
that. `estimate_ghost` builds the masks for both in-plane axes once and measures
the whole family from them. Its `GhostResult` carries the masks, so a report
draws the regions the numbers came from. `ghost_ratios` computes the per-axis
ratio for both axes without picking a winner. `estimate_pe_axis` picks the axis
where the ghost lands, as `run_qa`'s last-resort fallback when no sidecar or
header PE axis exists (see `load.pe_axis`).
"""

from dataclasses import dataclass

import numpy as np
from skimage.morphology import isotropic_dilation, isotropic_erosion

from .._arrays import ArrayValue
from ..types import PE_AXES, BoolArray, FloatArray, PeAxis, readout_axis

__all__ = [
    "GHOST_RADIUS",
    "GHOST_TOP_FRACTION",
    "GhostResult",
    "estimate_ghost",
    "estimate_pe_axis",
    "ghost_masks",
    "ghost_ratios",
]

# Greve / bxh fmriqa_ghostiness "top-10%". Catches a concentrated bright ghost
# that the region-mean ratio dilutes.
#: Fraction of the brightest ghost-region voxels averaged for the localized-ghost
#: statistic.
GHOST_TOP_FRACTION = 0.10

# The single source for every ghost statistic's default and for the report
# overlay, so the drawn masks match the masks the numbers were sampled on.
#: Erosion/dilation radius, in voxels, that sets the width of the ghost and signal
#: bands.
GHOST_RADIUS = 3


def ghost_masks(
    phantom_mask: BoolArray,
    pe_axis: PeAxis,
    radius: int = GHOST_RADIUS,
    *,
    valid_mask: BoolArray,
) -> tuple[BoolArray, BoolArray]:
    """Build region-matched (signal, ghost) masks for a candidate PE axis.

    The ghost is the phantom rolled half the FOV along `pe_axis`. The ghost mask
    keeps the part that lands clear of the phantom (eroded, with the dilated
    phantom and any invalid image edge removed). The signal mask is that ghost
    mask rolled back half the FOV onto the phantom, so the ratio compares each
    ghost patch against the tissue that produced it. This excludes the
    phantom/ghost overlap zone, where signal and ghost are superimposed and
    cannot be separated, from both masks. `valid_mask` excludes zeroed image
    edges (see `edge_valid_mask`) and is required, not defaulted. An image with
    a nonzero NIfTI `scl_inter` nulls its edge to the intercept, not to 0.0, so
    a mask built from `edge_valid_mask`'s default (`zero=0.0`) would silently
    detect no nulled edge on exactly the scans where that default is wrong. Pass
    `edge_valid_mask(mean_image, zero=...)` or `QAImages.valid_mask`.
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
    """Compute the region-mean ghost-to-signal ratio for one mask pair.

    The single definition of the FBIRN ghost ratio. NaN when either region is
    empty, which means no measurement, not a low one.
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
    """Compute the top-fraction ghost-to-signal ratio for one mask pair.

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

    Built by `estimate_ghost` from the masks it carries. `pe_signal`/`pe_ghost`
    are the region-matched pair along the resolved phase-encode axis, and
    `ro_signal`/`ro_ghost` are the same pair along the readout axis
    (`readout_axis`), a background-relative baseline because no N/2 ghost lands
    there. Every ratio below was averaged over exactly these masks, so a report
    drawing them draws what was measured.

    `pe_ratio` is the FBIRN ghost-to-signal ratio. `pe_top_ratio` is its
    localized companion (Greve / bxh `fmriqa_ghostiness`) over the brightest
    `top` fraction of ghost voxels. `ro_ratio` is the readout baseline. A NaN
    ratio means the region it needed was empty: the phantom spans the FOV along
    that axis, or the segmentation collapsed.
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
        `|ghost_pe - ghost_freq| / signal`. This is the same contrast in FBIRN
        region-matched space, with each ghost patch normalized by the tissue that
        produced it and the phantom/ghost overlap zone excluded from both.

        Each direction has its own matched denominator, so the readout ratio is
        a genuine background-relative-to-signal baseline. Subtracting it cancels
        the background as ACR intends, without ACR's single-signal assumption.
        For a uniform phantom the two denominators coincide and this reduces to
        the classic form.
        """
        return abs(self.pe_ratio - self.ro_ratio)

    @property
    def ghost_pct(self) -> float:
        """The FBIRN percent ghost along the phase-encode axis."""
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

    It builds the region-matched masks once per in-plane axis and takes all
    three ratios from them, so no two of the family can disagree and the caller
    keeps the masks that were sampled. `pe_axis` is the resolved phase-encode
    axis (0 or 1), and the readout axis is the other one. `radius` sets the
    erosion/dilation band width and `top` the localized-ghost fraction. Both are
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


def _ghost_ratio(
    mean_image: FloatArray,
    phantom_mask: BoolArray,
    pe_axis: PeAxis,
    radius: int = GHOST_RADIUS,
    *,
    valid_mask: BoolArray,
) -> float:
    """Measure the FBIRN Nyquist ghost-to-signal ratio for one candidate axis.

    One axis' worth of `estimate_ghost`, for `ghost_ratios` to score a candidate
    before any axis is settled. A run that has settled its axis calls
    `estimate_ghost` and reads `pe_ratio`, so the whole family comes off one set
    of masks. `valid_mask` excludes zeroed image edges (see `edge_valid_mask`)
    and is required, not defaulted. An image with a nonzero NIfTI `scl_inter`
    nulls its edge to the intercept, not to 0.0, so a mask built from
    `edge_valid_mask`'s default (`zero=0.0`) would silently detect no nulled edge
    on exactly the scans where that default is wrong. Pass
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
    """Measure the region-mean ghost ratio on both in-plane axes, keyed by axis.

    Rolling the phantom along the true PE axis lines the ghost region up with
    real ghost signal (high mean). Along the wrong axis it lands on background
    (low mean). `estimate_pe_axis` compares the two to pick a winner. An axis
    whose ghost region is empty (the phantom spans the FOV along it, or the
    segmentation collapsed) scores NaN, which means no ratio, not a low one.
    `estimate_pe_axis` relies on that distinction.
    """
    return {
        axis: _ghost_ratio(
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
    ratio could be measured on. A plain float comparison against NaN always
    answers False, which would leave whichever axis was looked at first as the
    winner. When neither axis is measurable, or both finite ratios are equal, the
    answer is None. A single measurable axis wins even when its ratio is zero.

    NOTE: shares the tuning caveats of `ghost_ratios`. A win by a hair is still
    a guess, so verify against the acquisition's known PE direction before
    trusting it.
    """
    ratios = ghost_ratios(mean_image, phantom_mask, radius, valid_mask=valid_mask)
    # Annotated because inferring the element type from the comprehension widens
    # the axes to `int`, and the `ratios` lookup below only accepts a `PeAxis`.
    measurable: list[PeAxis] = [
        axis for axis, ratio in ratios.items() if np.isfinite(ratio)
    ]
    if not measurable or ratios[0] == ratios[1]:
        return None
    return max(measurable, key=ratios.__getitem__)
