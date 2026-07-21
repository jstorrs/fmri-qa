"""Phantom localization: detect the phantom and resolve the summary ROI.

Operates on the preprocessed `QAImages`, turning the raw-array primitives in
`imaging` into the value objects the metrics consume — the phantom mask and
detected center (`PhantomGeometry`), and the fixed-size, on-image summary `ROI`.
"""

import numpy as np
from numpy.typing import NDArray

from .constants import FBIRN_ROI_SIZE, ROI_CENTER_MODES, RoiCenter
from .exceptions import InvalidChoiceError
from .imaging import _clamp_center, find_phantom_center, image_center, segment_phantom
from .types import ROI, PhantomGeometry, QAImages


def detect_phantom(images: QAImages) -> PhantomGeometry:
    """Locate the phantom from the preprocessed images: mask and detected center."""
    phantom_mask = segment_phantom(images.mip)
    return PhantomGeometry(
        phantom_mask=phantom_mask,
        roi_center=find_phantom_center(phantom_mask),
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
    return ROI(center=_clamp_center(c, n, shape), size=n)


def roi_fits(phantom_mask: NDArray, roi: tuple[slice, slice]) -> bool:
    """True if `roi` is on-image and every voxel of it lies inside the phantom.

    An out-of-bounds ROI (negative/overflowing slice) counts as not fitting —
    `np.all` of the empty selection it would produce is vacuously True otherwise.
    """
    (r, c), (h, w) = roi, phantom_mask.shape[:2]
    if r.start < 0 or c.start < 0 or r.stop > h or c.stop > w:
        return False
    return bool(np.all(phantom_mask[roi]))
