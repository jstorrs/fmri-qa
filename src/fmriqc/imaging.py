"""Low-level operations on raw phantom-image arrays.

The leaf layer the value objects and the metric modules both build on: trim,
slice selection, phantom segmentation, ROI indexing, the FBIRN summary-image
primitives, and a couple of numeric helpers. Everything here is a pure
`NDArray -> NDArray` (or scalar) transform with no dependency on the value
types, so it can be shared without import cycles.
"""

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage
from skimage import filters, segmentation

from .constants import ROI_CENTER_MODES


def trim_count(tr: float, trim_sec: float) -> int:
    """Number of initial (non-steady-state) volumes dropped for `trim_sec`."""
    return max(round(trim_sec / tr), 0)


def trim_initial(data: NDArray, tr: float, trim_sec: float) -> NDArray:
    return data[..., trim_count(tr, trim_sec) :]


def segment_phantom(image: NDArray) -> NDArray:
    # mode="wrap": MRI images are periodic (FFT reconstruction), so the edge
    # filter must wrap rather than pad.
    edges = filters.sobel(image, mode="wrap")
    labels = np.zeros_like(image, dtype=np.uint8)
    labels[image < np.quantile(image, 0.1)] = 1
    labels[image > np.quantile(image, 0.9)] = 2
    return segmentation.watershed(edges, labels) == 2


def extract_center_slice(data: NDArray, center: str = "image") -> NDArray:
    """Select the QA slice from a volume.

    "image": the geometric middle slice (Glover/fBIRN convention).
    "phantom": the slice with the largest phantom cross-section (detected).
    """
    if center == "image":
        z = data.shape[2] // 2
    elif center == "phantom":
        mip = data.max(axis=-1)
        z = int(np.argmax([segment_phantom(s).sum() for s in np.moveaxis(mip, -1, 0)]))
    else:
        raise ValueError(f"unknown center {center!r}; choose from {ROI_CENTER_MODES}")
    return data[:, :, z, :]


def find_phantom_center(phantom_mask: NDArray) -> NDArray:
    dist = ndimage.distance_transform_edt(phantom_mask)
    roi_center = np.unravel_index(np.argmax(dist), dist.shape)
    return np.array(roi_center)


def roi_indexes(roi_center: NDArray, n: int) -> tuple[slice, slice]:
    # roi_center is (row, col) in array-index order; return (rows, cols) so
    # callers index as mask[roi]. Do NOT swap these — the notebooks' swapped
    # version transposes the ROI and only agrees when roi_center[0] == roi_center[1].
    p1 = roi_center - (n - 1) // 2
    p2 = p1 + n
    return slice(p1[0], p2[0]), slice(p1[1], p2[1])


def image_center(shape: tuple[int, ...]) -> NDArray:
    """Geometric center (row, col) of an image, array-index order."""
    return np.array(shape[:2]) // 2


def _clamp_center(center: NDArray, n: int, shape: tuple[int, ...]) -> NDArray:
    """Shift `center` so an n x n ROI (per `roi_indexes`) stays within `shape`."""
    lo = (n - 1) // 2
    hi = n - lo
    return np.array([int(np.clip(center[i], lo, shape[i] - hi)) for i in (0, 1)])


def edge_valid_mask(image: NDArray) -> NDArray:
    """(X, Y) bool mask of real data, clearing only entirely-zeroed image edges.

    Some vendors (e.g. Siemens) null one outer image row/column to encode the
    phase-encode direction. A fully-zero border carries no signal and must not
    enter ROI averages or ghost statistics, but blanket-trimming one voxel on
    every side needlessly discards valid data on the other three. Each of the
    four edges is tested independently and only the zeroed ones are cleared.

    Pass the time-MIP for the most permissive test: a voxel that is nonzero in
    any frame counts as valid, so only a genuinely dead line is trimmed.
    """
    valid = np.ones(image.shape[:2], dtype=bool)
    if not image[0, :].any():
        valid[0, :] = False
    if not image[-1, :].any():
        valid[-1, :] = False
    if not image[:, 0].any():
        valid[:, 0] = False
    if not image[:, -1].any():
        valid[:, -1] = False
    return valid


def odd_even_difference(center_slice: NDArray) -> NDArray:
    """|mean(even frames) - mean(odd frames)| — a temporal-stability image."""
    even = center_slice[..., 0::2].mean(axis=-1)
    odd = center_slice[..., 1::2].mean(axis=-1)
    return np.abs(even - odd)


def fluctuation_noise(residuals: NDArray) -> NDArray:
    """Temporal RMS of detrended residuals (std about zero) over the last axis."""
    return np.std(residuals, axis=-1, mean=0)


def _geomean(x: NDArray) -> float:
    """Geometric mean over the positive, finite entries; NaN if there are none."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    return float(np.exp(np.mean(np.log(x)))) if x.size else float("nan")
