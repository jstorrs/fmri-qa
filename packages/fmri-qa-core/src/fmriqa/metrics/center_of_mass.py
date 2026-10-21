"""Per-volume intensity centroid of the phantom, computed on the periodic FOV.

bxh `fmriqa_volmeasures`' center-of-mass trace: a circular first moment over
the whole grid. It needs no phantom mask, because a uniform background and the
180-degree Nyquist ghost cancel on the periodic FOV. Missing data (a
vendor-nulled edge) is filled in first. A cheap complement to `motion`.
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

    This relative tolerance rejects cancellation roundoff regardless of image
    brightness or the number of temporal samples.
    """
    resolved = (total > 0) & (np.hypot(sine, cosine) > 1e-12 * total)
    angle = np.full_like(sine, np.nan, dtype=np.float64)
    angle[resolved] = np.arctan2(sine[resolved], cosine[resolved])
    return angle


@dataclass(frozen=True, eq=False, slots=True)
class CenterOfMassResult(ArrayValue):
    """Per-volume intensity-weighted center of mass of the phantom.

    `com` is (n_t, 2): each frame's intensity centroid along in-plane axes 0/1,
    in voxels within `[0, N)`. The circular mean gives the true centroid for a
    phantom against a wrapped edge (MRI images are periodic under FFT
    reconstruction) and cancels a uniform background and the 180-degree Nyquist
    ghost, so no phantom mask is needed. Only missing data (a Siemens zeroed
    edge) is filled in first (see `estimate_center_of_mass`). A stable phantom
    holds a fixed centroid, and a ramp or jump flags drift, a spike, or
    instability that ROI-only summaries miss. It is a cheap first-moment
    complement to `MotionResult`.

    An axis whose circular resultant is numerically zero has a NaN coordinate,
    and the other axis can still resolve. Missing coordinates do not contribute
    to the temporal reference, which is itself NaN on any axis with a
    numerically zero resultant (including balanced antipodal centroids).

    `shape` is the in-plane array size `(N0, N1)`. These are the wrap periods,
    so displacements respect the periodic boundary. `voxel` lets lengths be
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

        Wrapped into `(-N/2, N/2]` per axis, so a centroid crossing the periodic
        boundary gives a small displacement, not a full-FOV jump.
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

        The peak of `displacement`, in the same unit. Uses `nanmax`, not `max`,
        because an unresolved centroid says nothing about frames that did
        resolve. A displacement needs both coordinates and both reference axes,
        so the peak is NaN when none is complete, including when the temporal
        reference is ambiguous.
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

    bxh `fmriqa_volmeasures`' center-of-mass trace, for the QA center slice. For
    each frame, each coordinate maps to an angle `2*pi*x/N`, the
    intensity-weighted mean unit vector is formed over the **whole periodic
    grid**, and its angle maps back to `[0, N)`. Three properties follow on the
    periodic FOV (MRI images wrap under FFT reconstruction), so no phantom
    segmentation is needed. A segmentation would harm the result by carving the
    grid into a sub-region and destroying the full-period symmetry the first two
    properties rely on:

    * A phantom straddling a wrapped image edge yields the true centroid instead
      of aliasing to mid-FOV.
    * A **uniform background** contributes zero net vector, because a full period
      of unit vectors sums to zero (`sum_x exp(i 2pi x/N) = 0`). A flat noise
      floor does not pull the centroid however many background voxels there
      are. A linear COM cannot do this: uniform background drags it toward the
      image center, which forces a mask.
    * The **Nyquist ghost** sits at half-FOV, 180 degrees. Along the
      phase-encode axis each ghost voxel is anti-parallel to its source, so it
      cancels and does not bias the angle. Along the readout axis it is
      co-located and reinforces the correct position. Either way the ghost
      cannot shift the centroid.

    **Missing data** does break the background cancellation, for example an
    outer row or column that a vendor (Siemens) nulls to encode the PE
    direction. A nulled line is a hole in the otherwise-uniform background ring,
    and against a complete floor (which sums to zero) it injects a residual
    vector along the axis. The hole is filled in, not masked out. The background
    pedestal (the lowest valid magnitude) is subtracted so the floor sits at ~0,
    and the invalid voxels are then set to 0, so the gap matches the background.
    `valid_mask` (True = real data) is required, not defaulted. An image with a
    nonzero NIfTI `scl_inter` nulls its edge to the intercept, not to 0.0, so a
    mask built from `edge_valid_mask`'s default (`zero=0.0`) would silently
    detect no nulled edge on exactly the scans where that default is wrong. Pass
    `edge_valid_mask(center_slice.max(axis=-1), zero=...)` or `QAImages.valid_mask`.
    Pedestal subtraction also removes the background DC term outright, so the
    phantom (the dominant above-floor signal) sets the resultant more cleanly
    than symmetry cancellation alone.

    Weights are the per-frame magnitudes above the fixed pedestal, so the trace
    tracks where the signal sits over time. This complements `estimate_motion`
    with a cheap first-moment centroid.

    Each axis requires a resultant norm greater than `1e-12` times the total
    positive weight. This scale-relative tolerance rejects cancellation
    roundoff: a uniform positive frame has no defined centroid even if its total
    weight is nonzero. Unresolved coordinates are NaN and are excluded
    independently from each axis of the temporal reference, which uses the same
    tolerance on its unit-vector sums.

    `center_slice` is (X, Y, T). `voxel` (in-plane, from the header) is carried
    so displacements can be reported in mm.
    """
    shape = (int(center_slice.shape[0]), int(center_slice.shape[1]))
    nt = center_slice.shape[-1]

    # Fill in missing data before the circular mean. Subtract the lowest valid
    # magnitude to put the background floor at ~0, then zero the invalid voxels
    # so a nulled edge matches the background instead of leaving a hole in the
    # periodic ring. The pedestal is one scalar for all frames, so it does not
    # disturb frame-to-frame tracking.
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
