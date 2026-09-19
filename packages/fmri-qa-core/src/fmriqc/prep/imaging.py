"""Low-level operations on raw phantom-image arrays.

The leaf layer the value objects and the metric modules both build on: trim,
slice selection, phantom segmentation, ROI indexing, the FBIRN summary-image
primitives, and a couple of numeric helpers. Everything here is a pure
`NDArray -> NDArray` (or scalar) transform with no dependency on the value
types, so it can be shared without import cycles.
"""

import math
import warnings
from typing import assert_never

import numpy as np
from scipy import ndimage
from skimage import filters, segmentation

from ..exceptions import InvalidChoiceError
from ..types import ROI_CENTER_MODES, BoolArray, FloatArray, IntArray, RoiCenter

# Open bounds on the plausible share of a frame a phantom mask covers. Outside
# them the segmentation has collapsed rather than found an unusual phantom: a
# QA phantom is prescribed to fill a good part of the FOV but never all of it,
# and never none. Deliberately wide — this catches collapse, not miscalibration.
# Defined here beside `segment_phantom`, whose output they describe; `geometry`
# imports them for the warning `detect_phantom` raises.
DEGENERATE_PHANTOM_MIN = 0.0
DEGENERATE_PHANTOM_MAX = 0.95

# Least in-mask/out-of-mask intensity ratio a mask must show to be a phantom
# rather than a partition of noise (see `phantom_area`). Measured on synthetic
# frames: air segments at ~1.5-1.9, a phantom only 7x above the air floor at
# ~10, a normal phantom at ~160. Deliberately nearer the noise end.
MIN_PHANTOM_CONTRAST = 4.0


def trim_count(*, tr: float, trim_sec: float) -> int:
    """Number of initial (non-steady-state) volumes dropped for `trim_sec`."""
    return max(round(trim_sec / tr), 0)


def trim_initial(data: FloatArray, *, tr: float, trim_sec: float) -> FloatArray:
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
    """How far the mask's interior stands above the background it was cut from.

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
    """Whether a segmentation with this frame share and contrast is a phantom.

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


def _segment_and_score(image: FloatArray) -> tuple[BoolArray, int]:
    """Segment `image` once, returning both the mask and its `phantom_area`.

    `phantom_area` and `select_slice`'s slice ranking both start from "segment
    this candidate, then judge it" — computing them separately would watershed
    the same image twice. This is the one place the pair is produced, so
    `select_slice` can hand its winning slice's *mask* on to `preprocess`
    (which threads it to `detect_phantom`) without anyone re-segmenting the MIP
    that was just ranked.
    """
    mask = segment_phantom(image)
    area = 0
    if phantom_plausible(
        fraction=float(mask.mean()), contrast=phantom_contrast(image, mask)
    ):
        area = int(mask.sum())
    return mask, area


def phantom_area(image: FloatArray) -> int:
    """Segmented phantom area (voxels), or 0 for an image holding no phantom.

    Area alone cannot rank slices — an air slice segments to ~45% of the frame
    and out-votes a real cross-section at ~20% — so a mask that is not
    `phantom_plausible` scores 0.
    """
    return _segment_and_score(image)[1]


def select_slice(
    data: FloatArray, center: RoiCenter = "image"
) -> tuple[int, BoolArray | None]:
    """The index of the QA slice in an (X, Y, Z, T) volume, and its phantom mask.

    "image": the geometric middle slice (Glover/fBIRN convention); the mask is
    None because no segmentation is needed to find it, so none is done.
    "phantom": the slice with the largest phantom cross-section, measured by
    `phantom_area` — which scores a slice holding no phantom as 0, so a
    prescription that runs off the end of the phantom cannot win on the strength
    of a segmentation of its own air. If no slice holds a recognizable phantom,
    the middle slice is used and a warning says so. Either way the mask
    returned is the one `_segment_and_score` already built to rank that slice —
    the same watershed `detect_phantom` would otherwise repeat on the identical
    MIP once `preprocess` hands it the winner (see `QAImages.phantom_mask`).

    Raises:
        InvalidChoiceError: If `center` is not one of `ROI_CENTER_MODES`.
    """
    # Guarded up front so an untyped caller still gets the named error, then
    # matched exhaustively: `assert_never` is unreachable for a `RoiCenter`, so
    # adding a mode to that Literal makes this a type error rather than a
    # silent fall-through at runtime.
    if center not in ROI_CENTER_MODES:
        raise InvalidChoiceError("center", center, ROI_CENTER_MODES)
    match center:
        case "image":
            return int(data.shape[2] // 2), None
        case "phantom":
            return _largest_phantom_slice(data)
        case _:
            assert_never(center)


def _largest_phantom_slice(data: FloatArray) -> tuple[int, BoolArray]:
    """The slice with the largest phantom cross-section, and the mask that ranked it.

    Falls back to the middle slice, with a warning, when no slice holds a
    recognizable phantom -- `phantom_area` scores those 0, so there is no
    winner to pick and `center="image"`'s answer is the honest one.
    """
    mip = data.max(axis=-1)
    scored = [_segment_and_score(s) for s in np.moveaxis(mip, -1, 0)]
    areas = [area for _, area in scored]
    if any(areas):
        z = int(np.argmax(areas))
        return z, scored[z][0]
    z = int(data.shape[2] // 2)
    warnings.warn(
        "no slice holds a recognizable phantom (every segmentation was "
        "degenerate or indistinguishable from background); using the "
        f"middle slice {z} as center='image' would.",
        stacklevel=4,  # through `select_slice` to its caller (`preprocess`)
    )
    return z, scored[z][0]


def extract_center_slice(data: FloatArray, center: RoiCenter = "image") -> FloatArray:
    """The QA slice of a volume, as (X, Y, T): `data` at `select_slice`.

    Raises:
        InvalidChoiceError: If `center` is not one of `ROI_CENTER_MODES`.
    """
    z, _ = select_slice(data, center)
    return data[:, :, z, :]


def find_phantom_center(phantom_mask: BoolArray) -> IntArray:
    dist = ndimage.distance_transform_edt(phantom_mask)
    roi_center = np.unravel_index(np.argmax(dist), dist.shape)
    return np.array(roi_center)


def roi_indexes(roi_center: IntArray, n: int) -> tuple[slice, slice]:
    # roi_center is (row, col) in array-index order; return (rows, cols) so
    # callers index as mask[roi]. Do NOT swap these — the notebooks' swapped
    # version transposes the ROI and only agrees when roi_center[0] == roi_center[1].
    p1 = roi_center - (n - 1) // 2
    p2 = p1 + n
    return slice(p1[0], p2[0]), slice(p1[1], p2[1])


def image_center(shape: tuple[int, ...]) -> IntArray:
    """Geometric center (row, col) of an image, array-index order."""
    return np.array(shape[:2]) // 2


def clamp_center(center: IntArray, n: int, shape: tuple[int, ...]) -> IntArray:
    """Shift `center` so an n x n ROI (per `roi_indexes`) stays within `shape`."""
    lo = (n - 1) // 2
    hi = n - lo
    return np.array([int(np.clip(center[i], lo, shape[i] - hi)) for i in (0, 1)])


def edge_valid_mask(image: FloatArray, zero: float = 0.0) -> BoolArray:
    """(X, Y) bool mask of real data, clearing only entirely-nulled image edges.

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
    """|mean(even frames) - mean(odd frames)| — a temporal-stability image."""
    even = center_slice[..., 0::2].mean(axis=-1)
    odd = center_slice[..., 1::2].mean(axis=-1)
    return np.abs(even - odd)


def fluctuation_noise(residuals: FloatArray) -> FloatArray:
    """Temporal RMS of detrended residuals (std about zero) over the last axis."""
    return np.std(residuals, axis=-1, mean=0)


def geomean(x: FloatArray) -> float:
    """Geometric mean over the positive, finite entries; NaN if there are none."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    return float(np.exp(np.mean(np.log(x)))) if x.size else float("nan")
