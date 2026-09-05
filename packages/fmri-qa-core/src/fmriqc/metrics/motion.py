"""In-plane phantom motion: per-volume registration to the temporal mean.

3dvolreg-style estimation specialized for a rigid phantom — a 2-D affine with
the rotation dropped (translation + symmetric strain), because a stationary
phantom cannot rotate while gradient heating translates, scales, and shears the
image. The analyzed series is not resampled from this fit; it is a diagnostic.
"""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from ..prep.imaging import normalize_voxel_mm
from ..types import BoolArray, FloatArray

# Per-volume registration budget (in-plane phantom motion). Phantom drift is
# sub-voxel, so a few Gauss-Newton steps converge; TOL is on the largest
# per-step parameter update (voxels for translation, fraction for strain).
MOTION_MAX_ITER = 12
MOTION_TOL = 1e-4


@dataclass(frozen=True)
class MotionResult:
    """Per-volume in-plane deformation of the phantom (thermal-drift model).

    A phantom is rigid and stationary, so between volumes it cannot rotate; what
    gradient heating *does* produce is a slow translation plus a scaling/shear of
    the image as the gradient calibration drifts. This is 3dvolreg's per-volume
    registration with the rotation degrees of freedom removed: each frame is
    aligned to the temporal-mean image under a 2-D affine restricted to
    translation + symmetric strain (anisotropic scale + shear) -- 5 parameters,
    no rotation.

    `params` is (n_t, 5); each row is that frame's fit relative to the reference
    (an all-zero row = perfectly aligned):

      0 dr, 1 dc  -- translation along array axes 0/1 (voxels)
      2 sr, 3 sc  -- fractional scaling along axes 0/1 (image grows where > 0)
      4 shear     -- symmetric off-diagonal strain (dimensionless)
    """

    params: FloatArray  # (n_t, 5): dr, dc, sr, sc, shear
    voxel_mm: tuple[float, float] | None = None  # in-plane (axis0, axis1) mm/voxel

    @property
    def translation(self) -> FloatArray:
        """(n_t, 2) per-volume translation along the two in-plane axes (voxels)."""
        return self.params[:, 0:2]

    @property
    def scale_pct(self) -> FloatArray:
        """(n_t, 2) per-volume fractional scaling along each axis, as percent."""
        return 100.0 * self.params[:, 2:4]

    @property
    def shear_pct(self) -> FloatArray:
        """(n_t,) per-volume symmetric shear, as percent."""
        return 100.0 * self.params[:, 4]

    @property
    def displacement(self) -> FloatArray:
        """(n_t,) translation magnitude per volume, in mm if `voxel_mm` is known.

        Falls back to voxels when the in-plane voxel size is unavailable.
        """
        d = self.params[:, 0:2]
        if self.voxel_mm is not None:
            d = d * np.asarray(self.voxel_mm)
        return np.hypot(d[:, 0], d[:, 1])

    @property
    def max_translation(self) -> float:
        """Peak per-volume translation magnitude (voxels)."""
        return float(np.max(np.hypot(self.params[:, 0], self.params[:, 1])))

    @property
    def max_scale_pct(self) -> float:
        """Peak absolute scaling across both axes (percent)."""
        return float(np.max(np.abs(self.scale_pct)))

    @property
    def max_shear_pct(self) -> float:
        """Peak absolute shear (percent)."""
        return float(np.max(np.abs(self.shear_pct)))


def _register_norotate(
    moving: FloatArray,
    reference: FloatArray,
    rr: FloatArray,
    cc: FloatArray,
    center: FloatArray,
    mask: BoolArray,
    max_iter: int,
    tol: float,
) -> FloatArray:
    """Register one frame to `reference` under translation + symmetric strain.

    Forward-additive Lucas-Kanade for the 5-parameter warp
    `W(x) = center + U (x - center) + t`, with `U = [[1+sr, h], [h, 1+sc]]`
    symmetric (scale + shear, **no rotation**) and `t = (dr, dc)`. Each step
    warps `moving` by the current parameters, then solves the Gauss-Newton normal
    equations over `mask` for the additive update; the warp Jacobian is linear in
    the (centered) coordinates `rr`/`cc` and independent of the parameters, so the
    additive scheme is exact up to the image interpolation. Returns
    `[dr, dc, sr, sc, h]`, the frame's pose relative to the reference.
    """
    m = mask.ravel()
    ref = reference.ravel()[m]
    rrm, ccm = rr.ravel()[m], cc.ravel()[m]
    p = np.zeros(5)
    for _ in range(max_iter):
        u = np.array([[1.0 + p[2], p[4]], [p[4], 1.0 + p[3]]])
        offset = center - u @ center + p[:2]
        # affine_transform samples moving at u @ o + offset for output pixel o,
        # i.e. it pulls the frame back onto the reference grid under W.
        warped = ndimage.affine_transform(
            moving, u, offset=offset, order=1, mode="nearest"
        )
        gr, gc = np.gradient(warped)  # d/axis0, d/axis1 of the warped frame
        gr, gc = gr.ravel()[m], gc.ravel()[m]
        # steepest-descent images = grad(W) . dW/dp for p = [dr, dc, sr, sc, h]
        sd = np.stack([gr, gc, gr * rrm, gc * ccm, gr * ccm + gc * rrm], axis=1)
        err = warped.ravel()[m] - ref
        try:
            dp = np.linalg.solve(sd.T @ sd, sd.T @ err)
        except np.linalg.LinAlgError:
            break
        p = p - dp
        if np.max(np.abs(dp)) < tol:
            break
    return p


def estimate_motion(
    center_slice: FloatArray,
    mask: BoolArray,
    voxel_mm: tuple[float, float] | None = None,
    max_iter: int = MOTION_MAX_ITER,
    tol: float = MOTION_TOL,
) -> MotionResult:
    """Per-volume in-plane registration of the phantom to its temporal mean.

    3dvolreg-style motion estimation specialized for a rigid phantom: the model
    is a 2-D affine with the rotation dropped -- translation + symmetric strain
    (anisotropic scale + shear) -- because a stationary phantom cannot rotate,
    while gradient heating translates, scales, and shears the image. Each frame
    of `center_slice` (X, Y, T) is aligned to the temporal-mean image by
    forward-additive Lucas-Kanade over `mask` (the phantom), pivoting the strain
    at the phantom centroid so translation and deformation stay separable.
    Returns the per-frame `[dr, dc, sr, sc, shear]`; `voxel_mm` (in-plane, from
    the header) is carried through so displacements can be reported in mm.
    """
    reference = center_slice.mean(axis=-1)
    r_idx, c_idx = np.nonzero(mask)
    center = (
        np.array([r_idx.mean(), c_idx.mean()])
        if r_idx.size
        else np.array(reference.shape[:2], dtype=float) / 2.0
    )
    rows, cols = np.indices(reference.shape[:2]).astype(float)
    rr, cc = rows - center[0], cols - center[1]

    nt = center_slice.shape[-1]
    params = np.zeros((nt, 5))
    for t in range(nt):
        params[t] = _register_norotate(
            center_slice[..., t], reference, rr, cc, center, mask, max_iter, tol
        )
    return MotionResult(params=params, voxel_mm=normalize_voxel_mm(voxel_mm))
