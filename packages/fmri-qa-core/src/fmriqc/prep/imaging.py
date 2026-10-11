"""Low-level operations on raw phantom-image arrays.

The leaf layer the value objects and the metric modules both build on: trim,
slice selection, phantom segmentation, the valid-data mask, and the FBIRN
summary-image primitives. Everything here is a pure `NDArray -> NDArray` (or
scalar) transform with no dependency on the value types, so it can be shared
without import cycles.
"""

import math
from typing import assert_never

import numpy as np
from skimage import filters, segmentation

from ..exceptions import InvalidChoiceError
from ..types import ROI_CENTER_MODES, BoolArray, FloatArray, RoiCenter
from ..warn import warn

__all__ = [
    "DEGENERATE_PHANTOM_MAX",
    "DEGENERATE_PHANTOM_MIN",
    "MIN_PHANTOM_CONTRAST",
    "edge_valid_mask",
    "fluctuation_noise",
    "odd_even_difference",
    "phantom_contrast",
    "phantom_plausible",
    "segment_phantom",
    "select_slice",
    "trim_count",
    "trim_initial",
]

# Open bounds on the plausible share of a frame a phantom mask covers. Outside
# them the segmentation has collapsed rather than found an unusual phantom: a
# QA phantom is prescribed to fill a good part of the FOV but never all of it,
# and never none. Deliberately wide — this catches collapse, not miscalibration.
# Defined here beside `segment_phantom`, whose output they describe; `geometry`
# imports them for the warning `detect_phantom` raises.
#: Lower open bound on the fraction of a frame a plausible phantom mask covers.
DEGENERATE_PHANTOM_MIN = 0.0
#: Upper open bound on the fraction of a frame a plausible phantom mask covers.
DEGENERATE_PHANTOM_MAX = 0.95

# Least in-mask/out-of-mask intensity ratio a mask must show to be a phantom
# rather than a partition of noise (see `_phantom_area`). Measured on synthetic
# frames: air segments at ~1.5-1.9, a phantom only 7x above the air floor at
# ~10, a normal phantom at ~160. Deliberately nearer the noise end.
#: Least in-mask to out-of-mask intensity ratio for a mask to count as a phantom.
MIN_PHANTOM_CONTRAST = 4.0


def trim_count(*, tr: float, trim_sec: float) -> int:
    """Count the initial (non-steady-state) volumes dropped for `trim_sec`."""
    return max(round(trim_sec / tr), 0)


def trim_initial(data: FloatArray, *, tr: float, trim_sec: float) -> FloatArray:
    """Drop the initial volumes that `trim_sec` seconds covers at `tr`."""
    return data[..., trim_count(tr=tr, trim_sec=trim_sec) :]


def segment_phantom(image: FloatArray) -> BoolArray:
    """Watershed the phantom out of the background, seeded by intensity quantiles.

    The seeds are inclusive (`<=` / `>=`) rather than strict. A strict `<` seeds
    *nothing* whenever a tenth or more of the image sits exactly on the minimum —
    an exactly-zero background, which vendors do produce (background-suppressed
    or mask-multiplied reconstructions). Watershed with no background seed floods
    the whole frame as phantom, and every downstream statistic then silently
    reads background: the ROI-fit guard passes vacuously, SFNR divides by a
    noiseless floor, and the N/2 ghost region erodes to nothing. The same holds
    symmetrically at the bright end. If the quantiles coincide, the minimum and
    maximum seed the two classes instead, keeping them disjoint. A constant
    image has no distinct classes and returns an empty mask. `detect_phantom`
    still checks the result for degenerate masks.
    """
    low, high = np.quantile(image, [0.1, 0.9])
    if low == high:
        low, high = image.min(), image.max()
        if low == high:
            return np.zeros_like(image, dtype=bool)

    # mode="wrap": MRI images are periodic (FFT reconstruction), so the edge
    # filter must wrap rather than pad.
    edges = filters.sobel(image, mode="wrap")
    labels = np.zeros_like(image, dtype=np.uint8)
    labels[image <= low] = 1
    labels[image >= high] = 2
    return np.asarray(segmentation.watershed(edges, labels) == 2)


def phantom_contrast(image: FloatArray, mask: BoolArray) -> float:
    """Measure how far the mask's interior stands above its background.

    The ratio of the mean intensity inside `mask` to the mean outside it. An
    exactly-zero background (a background-suppressed reconstruction) makes the
    ratio infinite: any signal at all is then contrast enough. A mask that
    partitions nothing — empty, or the whole frame — has no background to stand
    above and scores 0.
    """
    if not mask.any() or mask.all():
        return 0.0
    inside = float(image[mask].mean())
    background = float(image[~mask].mean())
    if background <= 0:
        return math.inf if inside > 0 else 0.0
    return inside / background


def phantom_plausible(*, fraction: float, contrast: float) -> bool:
    """Return True if a segmentation with this share and contrast is a phantom.

    `segment_phantom` always returns *some* mask: given a frame of pure air it
    seeds one quantile of the noise against the other and labels about half of
    it. So a mask must be shown to *be* a phantom, by two cheap tests: it covers
    a plausible share of the frame (a collapse covers none or all of it), and
    what it selected stands `MIN_PHANTOM_CONTRAST` above the background it was
    separated from, which a partition of noise never does. This is the single
    definition of "this segmentation held" — slice selection ranks slices by it
    and the phantom verdict the artifact records is it.
    """
    return (
        DEGENERATE_PHANTOM_MIN < fraction < DEGENERATE_PHANTOM_MAX
        and contrast >= MIN_PHANTOM_CONTRAST
    )


def _phantom_area(image: FloatArray) -> int:
    """Return the segmented phantom area (voxels), or 0 if there is no phantom.

    Area alone cannot rank slices — an air slice segments to ~45% of the frame
    and out-votes a real cross-section at ~20% — so a mask that is not
    `phantom_plausible` scores 0.
    """
    mask = segment_phantom(image)
    if phantom_plausible(
        fraction=float(mask.mean()), contrast=phantom_contrast(image, mask)
    ):
        return int(mask.sum())
    return 0


def select_slice(data: FloatArray, center: RoiCenter = "image") -> int:
    """Select the index of the QA slice in an (X, Y, Z, T) volume.

    "image": the geometric middle slice (Glover/FBIRN convention).
    "phantom": the slice with the largest phantom cross-section, measured by
    `_phantom_area` — which scores a slice holding no phantom as 0, so a
    prescription that runs off the end of the phantom cannot win on the strength
    of a segmentation of its own air. If no slice holds a recognizable phantom,
    the middle slice is used and a warning says so.

    Raises
    ------
    InvalidChoiceError
        If `center` is not one of `ROI_CENTER_MODES`.
    """
    # Guarded up front so an untyped caller still gets the named error, then
    # matched exhaustively: `assert_never` is unreachable for a `RoiCenter`, so
    # adding a mode to that Literal makes this a type error rather than a
    # silent fall-through at runtime.
    if center not in ROI_CENTER_MODES:
        raise InvalidChoiceError("center", center, ROI_CENTER_MODES)
    match center:
        case "image":
            return int(data.shape[2] // 2)
        case "phantom":
            return _largest_phantom_slice(data)
        case _:
            assert_never(center)


def _largest_phantom_slice(data: FloatArray) -> int:
    """Find the slice with the largest phantom cross-section.

    Falls back to the middle slice, with a warning, when no slice holds a
    recognizable phantom -- `_phantom_area` scores those 0, so there is no
    winner to pick and `center="image"`'s answer is the honest one.
    """
    mip = data.max(axis=-1)
    areas = [_phantom_area(s) for s in np.moveaxis(mip, -1, 0)]
    if any(areas):
        return int(np.argmax(areas))
    z = int(data.shape[2] // 2)
    warn(
        "no slice holds a recognizable phantom (every segmentation was "
        "degenerate or indistinguishable from background); using the "
        f"middle slice {z} as center='image' would.",
    )
    return z


def edge_valid_mask(image: FloatArray, zero: float = 0.0) -> BoolArray:
    """Build an (X, Y) mask of real data, clearing only entirely-nulled edges.

    Some vendors (e.g. Siemens) null one outer image row/column to encode the
    phase-encode direction. A nulled border carries no signal and must not enter
    ROI averages or ghost statistics, but blanket-trimming one voxel on every
    side needlessly discards valid data on the other three. Each of the four
    edges is tested independently and only the nulled ones are cleared.

    `zero` is the image value a *stored* zero maps to. It is not always 0.0:
    `get_fdata` returns `stored * slope + inter`, so under a nonzero
    `scl_inter` a nulled edge reads as exactly `inter` — exactly, because
    `0 * slope` is 0.0 and the intercept survives the addition unchanged. Pass
    the scan's intercept (see `QAImages.zero_value`) or the edge is not
    recognized at all and its constant line enters every statistic.

    Pass the time-MIP for the most permissive test: a voxel that departs from
    `zero` in any frame counts as valid, so only a genuinely dead line is
    trimmed.
    """
    nulled = image == zero
    valid = np.ones(image.shape[:2], dtype=bool)
    if nulled[0, :].all():
        valid[0, :] = False
    if nulled[-1, :].all():
        valid[-1, :] = False
    if nulled[:, 0].all():
        valid[:, 0] = False
    if nulled[:, -1].all():
        valid[:, -1] = False
    return valid


def odd_even_difference(center_slice: FloatArray) -> FloatArray:
    """Compute ``|mean(even frames) - mean(odd frames)|``, a stability image."""
    even = center_slice[..., 0::2].mean(axis=-1)
    odd = center_slice[..., 1::2].mean(axis=-1)
    return np.abs(even - odd)


def fluctuation_noise(residuals: FloatArray) -> FloatArray:
    """Compute the temporal RMS of detrended residuals over the last axis."""
    return np.std(residuals, axis=-1, mean=0)
