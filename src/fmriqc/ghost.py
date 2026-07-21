"""Nyquist (N/2) ghost ratios and phase-encode-axis estimation.

The ghost is located by rolling the phantom half the FOV along the phase-encode
axis; every statistic here is a region-matched ghost-to-signal ratio built on
that idea. When no sidecar/header PE axis is available, the same machinery picks
the axis where the ghost actually lands.
"""

from typing import Literal, overload

import numpy as np
from numpy.typing import NDArray
from skimage import morphology

from .constants import GHOST_TOP_FRACTION
from .imaging import edge_valid_mask, segment_phantom


def _ghost_masks(
    phantom_mask: NDArray, pe_axis: int, radius: int, valid_mask: NDArray
) -> tuple[NDArray, NDArray]:
    """Region-matched (signal, ghost) masks for a candidate PE axis.

    The ghost is the phantom rolled half the FOV along `pe_axis`; the ghost mask
    keeps the part of it that lands clear of the phantom (eroded, with the dilated
    phantom and any invalid image edge removed). The signal mask is that same
    ghost mask rolled back half the FOV onto the phantom, so the ratio compares
    each ghost patch against the exact tissue that produced it. The phantom/PE-
    ghost overlap zone -- where signal and ghost are superimposed and cannot be
    separated -- is thereby excluded from both masks. `valid_mask` (see
    `edge_valid_mask`) drops the ghost pixels that wrap onto a zeroed edge.
    """
    shift = phantom_mask.shape[pe_axis] // 2
    ghost = np.roll(phantom_mask, shift, axis=pe_axis)

    ghost_mask = (
        morphology.isotropic_erosion(ghost, radius)
        & ~morphology.isotropic_dilation(phantom_mask, radius)
        & valid_mask
    )
    signal_mask = np.roll(ghost_mask, -shift, axis=pe_axis)
    return signal_mask, ghost_mask


def ghost_ratio(
    mean_image: NDArray,
    phantom_mask: NDArray,
    pe_axis: int = 0,
    radius: int = 3,
    valid_mask: NDArray | None = None,
) -> float:
    """fBIRN Nyquist ghost-to-signal ratio (mean ghost / mean signal).

    The fBIRN "percent ghost" is 100x this value. The ghost is located by rolling
    the phantom half the FOV along the phase-encode axis; `pe_axis` and the
    erosion/dilation `radius` are acquisition-dependent and should be verified per
    protocol. `valid_mask` excludes zeroed image edges (see `edge_valid_mask`);
    it defaults to detecting them from `mean_image`.
    """
    if valid_mask is None:
        valid_mask = edge_valid_mask(mean_image)
    signal_mask, ghost_mask = _ghost_masks(phantom_mask, pe_axis, radius, valid_mask)
    return float(mean_image[ghost_mask].mean() / mean_image[signal_mask].mean())


def ghost_top_ratio(
    mean_image: NDArray,
    phantom_mask: NDArray,
    pe_axis: int = 0,
    radius: int = 3,
    valid_mask: NDArray | None = None,
    top: float = GHOST_TOP_FRACTION,
) -> float:
    """Localized (top-fraction) Nyquist ghost ratio (Greve / bxh fmriqa_ghostiness).

    Identical to `ghost_ratio` but the numerator is the mean of the brightest
    `top` fraction of ghost-region voxels rather than the whole-region mean, so a
    concentrated bright ghost (a localized reconstruction artifact) shows up where
    the region mean would dilute it. The signal denominator is the same
    region-matched source patch as `ghost_ratio`, so this ratio shares that scale
    and is always >= the mean ghost ratio; 100x it is the "top-10% percent ghost".
    At least one voxel is always averaged; NaN if the ghost region is empty.
    """
    if valid_mask is None:
        valid_mask = edge_valid_mask(mean_image)
    signal_mask, ghost_mask = _ghost_masks(phantom_mask, pe_axis, radius, valid_mask)
    g = mean_image[ghost_mask]
    if g.size == 0:
        return float("nan")
    k = max(1, round(top * g.size))
    bright = np.partition(g, -k)[-k:]  # the k largest ghost-voxel intensities
    return float(bright.mean() / mean_image[signal_mask].mean())


def acr_ghosting_ratio(
    mean_image: NDArray,
    phantom_mask: NDArray,
    pe_axis: int = 0,
    radius: int = 3,
    valid_mask: NDArray | None = None,
) -> float:
    """ACR/AAPM-equivalent ghosting ratio from region-matched percent ghosts.

    The classic ACR/AAPM "percent-signal-ghosting" subtracts a background estimate
    (the frequency axis, which carries no N/2 ghost) from the phase-encode ghost,
    normalized by the central signal: |ghost_pe - ghost_freq| / signal. This builds
    the same contrast in fBIRN region-matched space: `ghost_ratio` is evaluated
    independently along the PE and frequency axes -- each ghost patch normalized by
    the exact tissue that produced it (`_ghost_masks`), with the phantom/ghost
    overlap zone excluded from both -- and the ACR-equivalent is the absolute
    difference of the two ratios.

    Because each direction carries its own matched denominator, the frequency-axis
    ratio is a genuine background-relative-to-signal baseline; subtracting it cancels
    the background exactly as ACR intends, without ACR's single-signal assumption
    (for a uniform phantom the two denominators coincide and this reduces to the
    classic form). 100x this value is the percent-signal-ghosting. `valid_mask`
    excludes zeroed image edges (see `edge_valid_mask`); it defaults to detecting
    them from `mean_image`.
    """
    if valid_mask is None:
        valid_mask = edge_valid_mask(mean_image)
    freq_axis = 1 - pe_axis
    pe = ghost_ratio(mean_image, phantom_mask, pe_axis, radius, valid_mask)
    ro = ghost_ratio(mean_image, phantom_mask, freq_axis, radius, valid_mask)
    return abs(pe - ro)


def _pe_axis_from_header(header) -> int | None:
    """PE axis from the NIfTI `dim_info` phase field, or None if unset/invalid.

    `dim_info` carries no polarity, which we don't need for ghost placement.
    """
    phase = header.get_dim_info()[1]
    return int(phase) if phase in (0, 1, 2) else None


def phase_encode_axis(data: NDArray, radius: int = 3) -> int:
    """Estimate the PE axis from a MIP over time and all slices.

    Collapsing time and slices concentrates the ghost, giving a stronger signal
    than any single slice — the fallback when no sidecar is available.
    """
    mip = data.max(axis=(-2, -1))  # (X, Y): max over Z and T
    return estimate_pe_axis(mip, segment_phantom(mip), radius=radius)


@overload
def estimate_pe_axis(
    mean_image: NDArray,
    phantom_mask: NDArray,
    radius: int = ...,
    return_ratios: Literal[False] = ...,
    *,
    valid_mask: NDArray | None = ...,
) -> int: ...
@overload
def estimate_pe_axis(
    mean_image: NDArray,
    phantom_mask: NDArray,
    radius: int = ...,
    *,
    return_ratios: Literal[True],
    valid_mask: NDArray | None = ...,
) -> tuple[int, dict[int, float]]: ...
def estimate_pe_axis(
    mean_image: NDArray,
    phantom_mask: NDArray,
    radius: int = 3,
    return_ratios: bool = False,
    valid_mask: NDArray | None = None,
) -> int | tuple[int, dict[int, float]]:
    """Guess the phase-encode axis from where the Nyquist ghost actually lands.

    Rolling the phantom along the *true* PE axis lines the ghost region up with
    real ghost signal (high mean); along the wrong axis it lands on background
    (low mean). The axis with the larger ghost-to-signal ratio wins.

    Returns the axis index (0 or 1), or `(axis, {axis: ratio})` if
    `return_ratios` is set. NOTE: shares the tuning caveats of `ghost_ratio` —
    verify against the acquisition's known PE direction before trusting it.
    """
    ratios = {
        axis: ghost_ratio(
            mean_image, phantom_mask, pe_axis=axis, radius=radius, valid_mask=valid_mask
        )
        for axis in (0, 1)
    }
    best = max(ratios, key=ratios.__getitem__)
    return (best, ratios) if return_ratios else best
