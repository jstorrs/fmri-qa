"""The synthetic phantom, shared by every package, the docs and the spikes.

This is the deterministic test and doc phantom, shipped so they all measure
against one definition. It is a uniform disk rendered from its exact k-space
(see `kspace`, after Guerquin-Kern et al. [1]_), with seeded complex k-space
noise, so its magnitude image has the edges, Gibbs ringing and Rayleigh air
background a scanner gives. An N/2 ghost and a linear signal drift can be added
the way an acquisition produces them. `synthetic_series` is the raw array.
`phantom_scan` is the `QAScan` that loading the file
`fmriqa_io.testing.write_phantom` writes gives back, built without touching a
file. A parity test in `fmri-qa-io` pins the two together.

Pure: no file IO. Re-exported by `fmriqa.testing`.

References
----------
.. [1] M. Guerquin-Kern, L. Lejeune, K. P. Pruessmann, M. Unser, "Realistic
   Analytical Phantoms for Parallel Magnetic Resonance Imaging," IEEE Trans.
   Med. Imaging 31(3):626-636, 2012. doi:10.1109/TMI.2011.2174158
"""

import math

import numpy as np

from ..load.metadata import ScanMeta
from ..load.scan import QAScan
from ..types import FloatArray
from .kspace import Component, Disk, Grid, kspace_noise, object_spectrum, reconstruct

#: Image noise std per real and imaginary part, in signal units, before any
#: smoothing. Unsmoothed, the magnitude background is then Rayleigh, of mean
#: ``NOISE_SIGMA·√(π/2)`` (about 6.3), as a
#: real air background is. A constant one would make the intensity quantiles
#: that seed `segment_phantom` degenerate.
NOISE_SIGMA = 5.0
#: Signal inside the disk, in signal units.
PHANTOM_SIGNAL = 1000.0

# The phantom's acquisition, as `write_phantom` records it in the header and the
# sidecar and `phantom_scan` repeats in memory.
TR_SEC = 2.0
VOXEL_MM = 3.0
PE_AXIS = 1


def synthetic_series(
    n: int = 32,
    z: int = 3,
    t: int = 40,
    seed: int = 0,
    smoothing: float = 0.0,
    *,
    ghost: float = 0.0,
    drift: float = 0.0,
    noise: float = NOISE_SIGMA,
) -> FloatArray:
    r"""Render a uniform disk phantom from exact k-space, with seeded noise.

    The disk is centred on voxel ``n // 2`` along both in-plane axes, with
    radius ``n / 4`` voxels and signal `PHANTOM_SIGNAL`, under a uniform coil.
    Every slice and frame samples the same analytic spectrum [1]_, adds fresh
    complex white noise and takes the magnitude, so the background is Rayleigh
    and, unsmoothed, the disk carries temporal noise of std about `noise`.

    Parameters
    ----------
    n : int
        In-plane matrix, in voxels of `VOXEL_MM`.
    z : int
        Slices.
    t : int
        Frames.
    seed : int
        Seeds the noise; a seed always gives the same series.
    smoothing : float
        In-plane Gaussian blur std, in voxels. Applied as k-space apodization
        ``exp(-2π²s²|k|²)``, s in mm, to signal and noise alike, so the noise
        gains a correlation length and a smaller std. Finite and
        non-negative; zero leaves the series unblurred.
    ghost : float
        Noise-free N/2 ghost-to-signal magnitude ratio along `PE_AXIS`.
        Finite and non-negative; `n` must be even when positive.
    drift : float
        Signal change from the first frame to the last, as a fraction of the
        series mean signal. Linear in frame index. Within (-2, 2).
    noise : float
        Image noise std per real and imaginary part, in signal units, before
        `smoothing` (which lowers it). Finite and non-negative; zero gives the
        noise-free series.

    Returns
    -------
    (n, n, z, t) ndarray of float64
        Magnitude images, in signal units.

    Raises
    ------
    ValueError
        If `smoothing`, `noise` or `ghost` is negative or not finite, `ghost`
        is positive and `n` odd, or `drift` is not finite or outside (-2, 2).

    Notes
    -----
    Ghost: an even/odd phase error between alternate phase-encode lines, as in
    EPI. Lines of odd frequency index ``m`` along `PE_AXIS` are multiplied by
    ``e^{iφ}``. That is the weight ``(1 + e^{iφ})/2 + (1 - e^{iφ})/2·(-1)^m``,
    and ``(-1)^m`` shifts the image by N/2, so

    .. math::

        g = \tfrac{1 + e^{i\varphi}}{2} f
            + \tfrac{1 - e^{i\varphi}}{2} f(\cdot - N/2).

    The ghost-to-signal magnitude ratio is ``|tan(φ/2)|``, so
    ``φ = 2·arctan(ghost)`` makes it `ghost`. The disk itself dims by
    ``cos(φ/2)``: the ghost's energy comes out of it.

    Drift: frame ``i`` of ``t`` scales the object's k-space (not the noise) by
    ``1 + drift·(i/(t - 1) - 1/2)``. The gain averages to one, so the mean
    signal is unchanged and a linear detrend sees a peak-to-peak trend of
    ``drift`` times it: `fmriqa.drift_percent` reads ``100·drift`` on an
    untrimmed, noise-free series whose detrend fits at least a line.

    References
    ----------
    .. [1] M. Guerquin-Kern, L. Lejeune, K. P. Pruessmann, M. Unser,
       "Realistic Analytical Phantoms for Parallel Magnetic Resonance
       Imaging," IEEE Trans. Med. Imaging 31(3):626-636, 2012.
       doi:10.1109/TMI.2011.2174158
    """
    if not (math.isfinite(smoothing) and smoothing >= 0.0):
        raise ValueError(f"smoothing must be finite and non-negative, got {smoothing}")
    if not (math.isfinite(noise) and noise >= 0.0):
        raise ValueError(f"noise must be finite and non-negative, got {noise}")
    if not (math.isfinite(ghost) and ghost >= 0.0):
        raise ValueError(f"ghost must be finite and non-negative, got {ghost}")
    if ghost > 0.0 and n % 2:
        # (-1)^m shifts by exactly N/2 only when N/2 is a whole number of voxels.
        raise ValueError(f"ghost > 0 needs an even n, got n={n}")
    if not (math.isfinite(drift) and abs(drift) < 2.0):
        # At |drift| >= 2 the gain reaches zero or flips sign.
        raise ValueError(f"drift must be finite and within (-2, 2), got {drift}")

    grid = Grid((n, n), (VOXEL_MM, VOXEL_MM))
    ky, kx = grid.k()
    disk = Component(Disk((0.0, 0.0), n / 4 * VOXEL_MM), PHANTOM_SIGNAL)
    # One noise-free spectrum serves every slice and frame.
    signal = object_spectrum([disk], ky, kx)

    sigma_mm = smoothing * VOXEL_MM
    apodization = np.exp(-2 * np.pi**2 * sigma_mm**2 * np.add.outer(ky**2, kx**2))
    odd_line = (np.arange(n) - n // 2) % 2 == 1
    phase = np.where(odd_line, np.exp(2j * math.atan(ghost)), 1.0)
    # Both act pointwise on k-space; e^{i0} and exp(0) are exactly one, so a
    # clean, unblurred series takes no rounding from them.
    weight = apodization * phase[None, :]
    gain = 1.0 + drift * (np.arange(t) - (t - 1) / 2) / max(t - 1, 1)

    rng = np.random.default_rng(seed)
    series = np.empty((n, n, z, t), dtype=np.float64)
    # Frame by frame: `reconstruct` transforms 2-D k-space only, and one frame
    # at a time bounds memory at the largest sizes the spikes use.
    for iz in range(z):
        for it in range(t):
            kspace = gain[it] * signal + kspace_noise(grid, noise, rng)
            series[:, :, iz, it] = np.abs(reconstruct(kspace * weight, grid))
    return series


def phantom_scan(
    *, n: int = 32, z: int = 3, t: int = 40, seed: int = 0, flip: float = 77.0
) -> QAScan:
    """Build the scan `fmriqa_io.load_scan(write_phantom(...))` gives back.

    The samples go through `uint16` and back, as they do on disk, so they are
    truncated to whole numbers. `meta` holds what the header and sidecar give:
    geometry, TR, flip angle and the phase-encode direction.
    """
    data = synthetic_series(n=n, z=z, t=t, seed=seed).astype(np.uint16)
    meta = ScanMeta(
        voxel_mm=(VOXEL_MM, VOXEL_MM, VOXEL_MM),
        matrix=(n, n),
        tr=TR_SEC,
        flip_angle=flip,
        pe_dir="col",
    )
    return QAScan(
        data=data.astype(np.float64),
        tr=TR_SEC,
        affine=np.eye(4),
        pe_axis=PE_AXIS,
        meta=meta,
        slope=1.0,
        inter=0.0,
        stored_integer=True,
    )
