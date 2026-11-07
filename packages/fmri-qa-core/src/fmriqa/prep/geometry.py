"""Phantom localization: the phantom/ROI value objects and how they're resolved.

Operates on the preprocessed `QAImages`, turning the raw-array primitives in
`imaging` into the value objects the metrics consume: the phantom mask and
detected center (`PhantomGeometry`), and the fixed-size, on-image summary `ROI`.
"""

from dataclasses import dataclass
from typing import Any, assert_never

import numpy as np
from scipy import ndimage

from .._arrays import ArrayValue
from ..exceptions import InvalidChoiceError
from ..types import (
    FBIRN_ROI_SIZE,
    ROI_CENTER_MODES,
    BoolArray,
    FloatArray,
    IntArray,
    RoiCenter,
)
from ..warn import warn
from .images import QAImages
from .imaging import (
    DEGENERATE_PHANTOM_MAX,
    DEGENERATE_PHANTOM_MIN,
    MIN_PHANTOM_CONTRAST,
    phantom_contrast,
    phantom_plausible,
)

__all__ = [
    "ROI",
    "PhantomGeometry",
    "detect_phantom",
    "resolve_roi",
    "roi_fits",
]


@dataclass(frozen=True, eq=False, slots=True)
class PhantomGeometry(ArrayValue):
    """Phantom location, computed by `detect_phantom` from `QAImages`."""

    phantom_mask: BoolArray  # (X, Y) bool
    roi_center: IntArray  # (row, col) in array-index order — detected phantom center
    contrast: float  # mean inside the mask over mean outside it (inf: zero air)

    @property
    def fraction(self) -> float:
        """Share of the frame the phantom mask covers, in [0, 1].

        A sanity figure for the segmentation. A real phantom occupies a middling
        fraction of the FOV, so an extreme value means the watershed collapsed
        (see `detect_phantom`). Carried into the analysis file so a reader months
        later can tell a NaN metric from a bad mask.
        """
        return float(self.phantom_mask.mean())

    @property
    def plausible(self) -> bool:
        """Whether this mask is one a real phantom can produce.

        `phantom_plausible` over `fraction` and `contrast`, the same test slice
        selection uses, so a run can't report "no slice holds a phantom" and then
        record its segmented phantom as good. `detect_phantom` warns on it, and
        `build` records it in the analysis file so a reader in another distribution
        gets the verdict and not the bounds to re-apply.
        """
        return phantom_plausible(fraction=self.fraction, contrast=self.contrast)


@dataclass(frozen=True, eq=False, slots=True)
class ROI(ArrayValue):
    """A resolved square ROI: center (row, col, array order) and side length.

    Produced once by `resolve_roi` and passed to the ROI-based statistics so the
    localization is computed a single time.
    """

    center: IntArray
    size: int

    @property
    def index(self) -> tuple[slice, slice]:
        """The (rows, cols) slice pair for indexing an image."""
        return _roi_indexes(self.center, self.size)

    def mean(self, image: FloatArray) -> Any:
        """Average `image` over the ROI's rows and columns.

        A scalar for an (X, Y) image; a per-frame series for an (X, Y, T) one.
        """
        return image[self.index].mean(axis=(0, 1))


def detect_phantom(images: QAImages) -> PhantomGeometry:
    """Locate the phantom in the preprocessed images: mask and center.

    Warns when the mask is not a plausible phantom: degenerate (empty, or
    covering essentially the whole frame) or a partition of noise no brighter
    than the background it was cut from. Either way every statistic measured
    through the mask is unusable. A whole-frame mask passes `roi_fits` vacuously
    and erodes the N/2 ghost region to nothing, and a noise partition covers an
    ordinary share of the frame, so nothing else would flag either. The geometry
    is still returned, not raised on, so a batch reports the bad scan and keeps
    going. The caller records the verdict in the analysis file and the affected
    metrics resolve to NaN.
    """
    phantom_mask = images.phantom_mask
    geom = PhantomGeometry(
        phantom_mask=phantom_mask,
        roi_center=_find_phantom_center(phantom_mask),
        contrast=phantom_contrast(images.mip, phantom_mask),
    )
    if not geom.plausible:
        warn(
            f"{_implausibility(geom)}, so the mask-based metrics (SFNR, ghost, "
            f"outliers, smoothness) are unusable.",
        )
    return geom


def _implausibility(geom: PhantomGeometry) -> str:
    """Name the plausibility test the segmentation failed, for the warning."""
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
    is shifted if needed to keep the ROI on-image. Whether it also fits inside
    the phantom is a separate check (see `roi_fits`).

    Raises
    ------
    InvalidChoiceError
        If `center` is not one of `ROI_CENTER_MODES`.
    """
    # Guarded up front so an untyped caller still gets the named error, then
    # matched exhaustively. `assert_never` is unreachable for a `RoiCenter`, so
    # adding a mode to that Literal is a type error, not a silent fall-through
    # at runtime.
    if center not in ROI_CENTER_MODES:
        raise InvalidChoiceError("ROI center", center, ROI_CENTER_MODES)
    shape = images.center_slice.shape[:2]
    n = min(roi_size, *shape)
    match center:
        case "image":
            c = _image_center(shape)
        case "phantom":
            c = geom.roi_center
        case _:
            assert_never(center)
    return ROI(center=_clamp_center(c, n, shape), size=n)


def roi_fits(phantom_mask: BoolArray, roi: ROI) -> bool:
    """Return True if `roi` is on-image and every voxel of it lies in the phantom.

    An out-of-bounds ROI (negative/overflowing slice) counts as not fitting.
    `np.all` of the empty selection it would produce is vacuously True.
    """
    index = roi.index
    (r, c), (h, w) = index, phantom_mask.shape[:2]
    if r.start < 0 or c.start < 0 or r.stop > h or c.stop > w:
        return False
    return bool(np.all(phantom_mask[index]))


def _find_phantom_center(phantom_mask: BoolArray) -> IntArray:
    """Find the center (row, col) of the phantom's largest inscribed circle."""
    dist = ndimage.distance_transform_edt(phantom_mask)
    roi_center = np.unravel_index(np.argmax(dist), dist.shape)
    return np.array(roi_center)


def _roi_indexes(roi_center: IntArray, n: int) -> tuple[slice, slice]:
    """Index the `n` x `n` ROI around `roi_center` as (rows, cols) slices."""
    # roi_center is (row, col) in array-index order; return (rows, cols) so
    # callers index as mask[roi]. Do NOT swap these. The notebooks' swapped
    # version transposes the ROI and only agrees when roi_center[0] == roi_center[1].
    p1 = roi_center - (n - 1) // 2
    p2 = p1 + n
    return slice(p1[0], p2[0]), slice(p1[1], p2[1])


def _image_center(shape: tuple[int, ...]) -> IntArray:
    """Return the geometric center (row, col) of an image, in array order."""
    return np.array(shape[:2]) // 2


def _clamp_center(center: IntArray, n: int, shape: tuple[int, ...]) -> IntArray:
    """Shift `center` so an n x n ROI (per `_roi_indexes`) stays within `shape`."""
    lo = (n - 1) // 2
    hi = n - lo
    return np.array([int(np.clip(center[i], lo, shape[i] - hi)) for i in (0, 1)])
