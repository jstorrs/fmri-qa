"""Per-volume intensity centroid of the phantom, computed on the periodic FOV.

bxh `fmriqa_volmeasures`' center-of-mass trace: a *circular* first moment over
the whole grid, which needs no phantom mask because a uniform background and the
180-degree Nyquist ghost self-cancel on the periodic FOV. Only genuinely missing
data (a vendor-nulled edge) is healed first. A cheap complement to `motion`.
"""

import numpy as np

from .constants import BoolArray, FloatArray
from .imaging import edge_valid_mask
from .types import CenterOfMassResult


def estimate_center_of_mass(
    center_slice: FloatArray,
    valid_mask: BoolArray | None = None,
    voxel_mm: tuple[float, float] | None = None,
) -> CenterOfMassResult:
    """Per-volume intensity-weighted center of mass of the phantom (circular).

    bxh `fmriqa_volmeasures`' center-of-mass trace, specialized to the QA center
    slice: for each frame, the intensity centroid along each in-plane axis via a
    *circular* mean -- every coordinate is mapped to an angle `2*pi*x/N`, the
    intensity-weighted mean unit vector is formed over the **whole periodic grid**,
    and its angle mapped back to `[0, N)`. Three properties follow from the
    circular mean on the periodic FOV (MRI images wrap under FFT reconstruction),
    and together they mean the centroid needs no phantom segmentation -- which
    would in fact *harm* it, by carving the grid into a sub-region and destroying
    the full-period symmetry the first two properties rely on:

    * A phantom straddling a wrapped image edge yields the true centroid instead
      of aliasing to mid-FOV.
    * A **uniform background** contributes *zero* net vector -- a full period of
      unit vectors sums to zero (`sum_x exp(i 2pi x/N) = 0`) -- so a flat noise
      floor does not pull the centroid no matter how many background voxels there
      are. (This is what a linear COM cannot do: there, uniform background drags
      the centroid toward image center, forcing a mask.)
    * The **Nyquist ghost** sits at exactly half-FOV = 180 degrees, so along the
      phase-encode axis each ghost voxel is anti-parallel to its source (it
      cancels, biasing the angle not at all) and along the readout axis it is
      co-located (it reinforces the correct position). Either way the ghost cannot
      shift the centroid.

    The one thing that *does* break the background cancellation is **missing
    data** -- e.g. an outer row/column a vendor (Siemens) nulls to encode the PE
    direction. A nulled line is a hole punched in the otherwise-uniform background
    ring, and relative to a complete floor (which sums to zero) that hole injects
    a residual vector along the axis. It is healed rather than masked out: the
    background pedestal (the lowest *valid* magnitude) is subtracted so the floor
    sits at ~0, and the invalid voxels are then set to 0 -- so the gap matches the
    now-zero background instead of a hole in the ring. `valid_mask` (True = real
    data) defaults to `edge_valid_mask` of the time-MIP, which detects exactly the
    zeroed-edge case; pass one to override. Pedestal subtraction also removes the
    background DC term outright, so the phantom (the dominant above-floor signal)
    sets the resultant more cleanly than symmetry cancellation alone.

    Weights are the per-frame magnitudes above the (fixed) pedestal, so the trace
    tracks where the signal actually sits over time. Complements `estimate_motion`
    (registration-based deformation) with a cheap first-moment centroid.

    `center_slice` is (X, Y, T); `voxel_mm` (in-plane, from the header) is carried
    so displacements can be reported in mm.
    """
    shape = (int(center_slice.shape[0]), int(center_slice.shape[1]))
    nt = center_slice.shape[-1]
    if valid_mask is None:
        valid_mask = edge_valid_mask(center_slice.max(axis=-1))

    # Heal missing data before the circular mean: shift the background floor to ~0
    # by subtracting the lowest valid magnitude, then zero the invalid voxels so a
    # nulled edge matches the now-zero background rather than punching a hole in
    # the periodic ring. The pedestal is a single scalar (constant across frames),
    # so it does not perturb the frame-to-frame centroid tracking.
    valid_vals = center_slice[valid_mask]
    pedestal = float(valid_vals.min()) if valid_vals.size else 0.0
    weights = np.clip(center_slice - pedestal, 0.0, None)
    weights[~valid_mask] = 0.0
    W = weights.reshape(-1, nt)  # (npix, n_t)

    idx = np.indices(shape).reshape(2, -1)  # (2, npix): full periodic grid
    total = W.sum(axis=0)  # (n_t,)
    good = total > 0  # blank frames -> NaN centroid
    com = np.full((nt, 2), np.nan)
    for axis in (0, 1):
        theta = idx[axis] * (2.0 * np.pi / shape[axis])
        ang = np.arctan2(np.sin(theta) @ W, np.cos(theta) @ W)
        com[good, axis] = (ang[good] % (2.0 * np.pi)) * shape[axis] / (2.0 * np.pi)

    vm = (float(voxel_mm[0]), float(voxel_mm[1])) if voxel_mm is not None else None
    return CenterOfMassResult(com=com, shape=shape, voxel_mm=vm)
