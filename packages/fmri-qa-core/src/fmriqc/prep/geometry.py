"""Phantom localization: the phantom/ROI value objects and how they're resolved.

Operates on the preprocessed `QAImages`, turning the raw-array primitives in
`imaging` into the value objects the metrics consume — the phantom mask and
detected center (`PhantomGeometry`), and the fixed-size, on-image summary `ROI`.
"""

import warnings
from dataclasses import dataclass

import numpy as np

from ..exceptions import InvalidChoiceError
from ..types import FBIRN_ROI_SIZE, ROI_CENTER_MODES, BoolArray, IntArray, RoiCenter
from .images import QAImages
from .imaging import (
    DEGENERATE_PHANTOM_MAX,
    DEGENERATE_PHANTOM_MIN,
    MIN_PHANTOM_CONTRAST,
    clamp_center,
    find_phantom_center,
    image_center,
    phantom_contrast,
    phantom_plausible,
    roi_indexes,
)


@dataclass(frozen=True, eq=False)
class PhantomGeometry:
    """Phantom location, computed by `detect_phantom` from `QAImages`."""

    phantom_mask: BoolArray  # (X, Y) bool
    roi_center: IntArray  # (row, col) in array-index order — detected phantom center
    contrast: float  # mean inside the mask over mean outside it (inf: zero air)

    @property
    def fraction(self) -> float:
        """Share of the frame the phantom mask covers, in [0, 1].

        A sanity figure for the segmentation itself: a real phantom occupies a
        middling fraction of the FOV, so a value at either extreme means the
        watershed collapsed rather than that the phantom is unusual (see
        `detect_phantom`). Carried into the artifact so a reader months later can
        tell a NaN metric from a bad mask.
        """
        return float(self.phantom_mask.mean())

    @property
    def plausible(self) -> bool:
        """Whether this mask is one a real phantom can produce.

        `phantom_plausible` over `fraction` and `contrast` — the same test slice
        selection ranks slices by, so a run cannot say "no slice holds a
        phantom" and then record the phantom it segmented anyway as good.
        `detect_phantom` warns on it, and `build` records it in the artifact so
        a reader — including one in another distribution, which cannot import
        this layer — gets the verdict rather than the bounds to re-apply.
        """
        return phantom_plausible(self.fraction, self.contrast)


@dataclass(frozen=True, eq=False)
class ROI:
    """A resolved square ROI: center (row, col, array order) and side length.

    Produced once by `resolve_roi` and threaded into the ROI-based statistics so
    the localization is computed a single time.
    """

    center: IntArray
    size: int

    @property
    def index(self) -> tuple[slice, slice]:
        """The (rows, cols) slice pair for indexing an image."""
        return roi_indexes(self.center, self.size)


def detect_phantom(images: QAImages) -> PhantomGeometry:
    """Locate the phantom from the preprocessed images: mask and detected center.

    Warns when the resulting mask is not a plausible phantom: degenerate —
    empty, or covering essentially the whole frame — or a partition of noise
    that stands no higher than the background it was cut from. Either way the
    watershed did not find a phantom, and every statistic measured through the
    mask is then unusable: a whole-frame mask in particular passes `roi_fits`
    vacuously and erodes the N/2 ghost region to nothing, and a noise partition
    covers a perfectly ordinary share of the frame, so nothing further would
    flag either. The geometry is still returned (the caller records the verdict
    in the artifact and the affected metrics resolve to NaN on their own)
    rather than raised on, so a batch reports the bad scan and keeps going.
    """
    phantom_mask = images.phantom_mask
    geom = PhantomGeometry(
        phantom_mask=phantom_mask,
        roi_center=find_phantom_center(phantom_mask),
        contrast=phantom_contrast(images.mip, phantom_mask),
    )
    if not geom.plausible:
        warnings.warn(
            f"{_implausibility(geom)}, so the mask-based metrics (SFNR, ghost, "
            f"outliers, smoothness) are unusable.",
            stacklevel=2,
        )
    return geom


def _implausibility(geom: PhantomGeometry) -> str:
    """Which plausibility test the segmentation failed, for the warning."""
    if not DEGENERATE_PHANTOM_MIN < geom.fraction < DEGENERATE_PHANTOM_MAX:
        return (
            f"phantom segmentation covers {100 * geom.fraction:.1f}% of the frame; "
            f"the mask did not separate phantom from background"
        )
    return (
        f"phantom segmentation stands only {geom.contrast:.1f}x above the "
        f"background it was separated from (a phantom stands at least "
        f"{MIN_PHANTOM_CONTRAST:g}x); the frame holds no recognizable phantom"
    )


def resolve_roi(
    images: QAImages,
    geom: PhantomGeometry,
    roi_size: int = FBIRN_ROI_SIZE,
    center: RoiCenter = "image",
) -> ROI:
    """Resolve the summary ROI once for a localization mode.

    "image": image-matrix center (Glover). "phantom": detected phantom center.
    The side is the fixed `roi_size` clamped to the image bounds, and the center
    is shifted if needed to keep the ROI on-image; whether it also fits inside the
    phantom is a separate check (see `roi_fits`).

    Raises:
        InvalidChoiceError: If `center` is not one of `ROI_CENTER_MODES`.
    """
    shape = images.center_slice.shape[:2]
    n = min(roi_size, *shape)
    if center == "image":
        c = image_center(shape)
    elif center == "phantom":
        c = geom.roi_center
    else:
        raise InvalidChoiceError("ROI center", center, ROI_CENTER_MODES)
    return ROI(center=clamp_center(c, n, shape), size=n)


def roi_fits(phantom_mask: BoolArray, roi: tuple[slice, slice]) -> bool:
    """True if `roi` is on-image and every voxel of it lies inside the phantom.

    An out-of-bounds ROI (negative/overflowing slice) counts as not fitting —
    `np.all` of the empty selection it would produce is vacuously True otherwise.
    """
    (r, c), (h, w) = roi, phantom_mask.shape[:2]
    if r.start < 0 or c.start < 0 or r.stop > h or c.stop > w:
        return False
    return bool(np.all(phantom_mask[roi]))
