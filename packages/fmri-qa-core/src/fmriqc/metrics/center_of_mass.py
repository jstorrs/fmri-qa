"""Per-volume intensity centroid of the phantom, computed on the periodic FOV.

bxh `fmriqa_volmeasures`' center-of-mass trace: a *circular* first moment over
the whole grid, which needs no phantom mask because a uniform background and the
180-degree Nyquist ghost self-cancel on the periodic FOV. Only genuinely missing
data (a vendor-nulled edge) is healed first. A cheap complement to `motion`.
"""

from dataclasses import dataclass

import numpy as np

from .._arrays import ArrayValue
from ..prep.scale import UNKNOWN_VOXEL_SIZE, VoxelSize
from ..types import BoolArray, FloatArray

__all__ = [
    "CenterOfMassResult",
    "estimate_center_of_mass",
]


def _resolved_angle(
    sine: FloatArray, cosine: FloatArray, total: FloatArray
) -> FloatArray:
    """Compute angles whose resultant exceeds 1e-12 of the total weight.

    This relative numerical tolerance rejects cancellation roundoff without
    depending on image brightness or the number of temporal samples.
    """
    resolved = (total > 0) & (np.hypot(sine, cosine) > 1e-12 * total)
    angle = np.full_like(sine, np.nan, dtype=np.float64)
    angle[resolved] = np.arctan2(sine[resolved], cosine[resolved])
    return angle


@dataclass(frozen=True, eq=False, slots=True)
class CenterOfMassResult(ArrayValue):
    """Per-volume intensity-weighted center of mass of the phantom.

    `com` is (n_t, 2): each frame's intensity centroid along in-plane axes 0/1, in
    voxels within `[0, N)`, computed with a *circular* mean so a phantom sitting
    against a wrapped image edge yields the true centroid instead of aliasing to
    mid-FOV (MRI images are periodic under FFT reconstruction). The circular mean
    also makes a uniform background and the 180-degree Nyquist ghost self-cancel,
    so the centroid needs no phantom mask -- only missing data (a Siemens zeroed
    edge) is healed first (see `estimate_center_of_mass`). A rigid, stable phantom
    holds a fixed centroid; a slow ramp or a sudden jump in the trace flags drift,
    a spike, or gross instability the ROI-only GSQAP summaries miss. A cheap
    first-moment complement to `MotionResult` (registration-based deformation).

    An axis whose circular resultant is numerically zero has a NaN coordinate;
    the other axis can still resolve. Missing coordinates do not contribute to
    the temporal reference, which is itself NaN on any axis with a numerically
    zero resultant (including balanced antipodal centroids).

    `shape` is the in-plane array size `(N0, N1)` — the wrap periods, so
    displacements respect the periodic boundary; `voxel` lets lengths be
    reported in mm.
    """

    com: FloatArray  # (n_t, 2) per-frame circular COM (voxels, [0, N) or NaN)
    shape: tuple[int, int]  # in-plane (N0, N1): the axis wrap periods
    voxel: VoxelSize = UNKNOWN_VOXEL_SIZE  # mm/voxel, and the unit it implies

    @property
    def reference(self) -> FloatArray:
        """(2,) circular mean of resolved COM coordinates; ambiguous axes are NaN."""
        n = np.asarray(self.shape, dtype=float)
        theta = self.com * (2.0 * np.pi / n)
        mean_theta = _resolved_angle(
            np.nansum(np.sin(theta), axis=0),
            np.nansum(np.cos(theta), axis=0),
            np.asarray(np.isfinite(theta).sum(axis=0), dtype=np.float64),
        )
        return np.asarray(
            (mean_theta % (2.0 * np.pi)) * n / (2.0 * np.pi), dtype=np.float64
        )

    @property
    def deviation(self) -> FloatArray:
        """(n_t, 2) signed per-frame displacement from the reference (voxels).

        Wrapped into `(-N/2, N/2]` per axis, so a centroid that crosses the
        periodic boundary yields a small displacement, not a full-FOV jump.
        """
        n = np.asarray(self.shape, dtype=float)
        d = self.com - self.reference
        return np.asarray((d + n / 2.0) % n - n / 2.0, dtype=np.float64)

    @property
    def displacement(self) -> FloatArray:
        """(n_t,) centroid displacement per volume, in `voxel.unit`."""
        return self.voxel.magnitude(self.deviation)

    @property
    def max_displacement(self) -> float:
        """Peak per-volume centroid displacement, in `voxel.unit`.

        The peak of `displacement`, so it shares that property's unit. Uses
        `nanmax`, not `max`: an unresolved centroid says nothing about frames
        that did resolve. A displacement needs both coordinates and both
        reference axes, so the peak is NaN when no complete displacement is
        available, including when the temporal reference is ambiguous.
        """
        d = self.displacement
        return float(np.nanmax(d)) if np.isfinite(d).any() else float("nan")


def estimate_center_of_mass(
    center_slice: FloatArray,
    *,
    valid_mask: BoolArray,
    voxel: VoxelSize = UNKNOWN_VOXEL_SIZE,
) -> CenterOfMassResult:
    """Estimate the per-volume intensity-weighted center of mass (circular).

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
    data) is required rather than defaulted: an image with a nonzero NIfTI
    `scl_inter` nulls its edge to the intercept, not to 0.0, so a mask built from
    `edge_valid_mask`'s own default (`zero=0.0`) would silently detect no nulled
    edge on exactly the scans that default is wrong for. Pass
    `edge_valid_mask(center_slice.max(axis=-1), zero=...)` or `QAImages.valid_mask`.
    Pedestal subtraction also removes the background DC term outright, so the
    phantom (the dominant above-floor signal) sets the resultant more cleanly
    than symmetry cancellation alone.

    Weights are the per-frame magnitudes above the (fixed) pedestal, so the trace
    tracks where the signal actually sits over time. Complements `estimate_motion`
    (registration-based deformation) with a cheap first-moment centroid.

    Each axis requires a resultant norm greater than `1e-12` times the total
    positive weight. This scale-relative numerical tolerance rejects roundoff
    from cancellation: a uniform positive frame, for example, has no defined
    centroid even if its total weight is nonzero. Unresolved coordinates are
    NaN and excluded independently from each axis of the temporal reference,
    which uses the same tolerance on its unit-vector sums.

    `center_slice` is (X, Y, T); `voxel` (in-plane, from the header) is carried
    so displacements can be reported in mm.
    """
    shape = (int(center_slice.shape[0]), int(center_slice.shape[1]))
    nt = center_slice.shape[-1]

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
    com = np.full((nt, 2), np.nan)
    for axis in (0, 1):
        theta = idx[axis] * (2.0 * np.pi / shape[axis])
        ang = _resolved_angle(np.sin(theta) @ W, np.cos(theta) @ W, total)
        com[:, axis] = (ang % (2.0 * np.pi)) * shape[axis] / (2.0 * np.pi)

    return CenterOfMassResult(com=com, shape=shape, voxel=voxel)
