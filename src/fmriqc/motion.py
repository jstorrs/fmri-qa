"""In-plane phantom motion: per-volume registration to the temporal mean.

3dvolreg-style estimation specialized for a rigid phantom — a 2-D affine with
the rotation dropped (translation + symmetric strain), because a stationary
phantom cannot rotate while gradient heating translates, scales, and shears the
image. The analyzed series is not resampled from this fit; it is a diagnostic.
"""

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from .constants import MOTION_MAX_ITER, MOTION_TOL
from .types import MotionResult


def _register_norotate(
    moving: NDArray,
    reference: NDArray,
    rr: NDArray,
    cc: NDArray,
    center: NDArray,
    mask: NDArray,
    max_iter: int,
    tol: float,
) -> NDArray:
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
    center_slice: NDArray,
    mask: NDArray,
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
    vm = (float(voxel_mm[0]), float(voxel_mm[1])) if voxel_mm is not None else None
    return MotionResult(params=params, voxel_mm=vm)
