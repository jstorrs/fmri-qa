"""High/low flip-angle noise separation (thermal vs. instability).

Greve's high/low flip-angle QA: two phantom runs that differ only in flip angle
let thermal (additive) noise be separated from instability (multiplicative)
noise, because their variances scale differently with signal level. `run_hilo`
pools statistics over the shared eroded phantom core; `separate_noise` is the
flip-angle algebra, kept pure so it can be exercised directly.
"""

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .exceptions import IncompatibleScansError
from .load.scan import QAScan
from .prep.detrend import detrend_fn
from .prep.imaging import fluctuation_noise, segment_phantom, trim_initial
from .types import BoolArray, DetrendMethod, FloatArray
from .validation import validate_hilo_run

# Voxel layers peeled off the phantom to form the hi/lo core mask (AFNI
# 3dAutomask -erode 5) -- excludes edge / partial-volume / ghost-contaminated voxels.
HILO_ERODE = 5
_GEOMETRY_RTOL = 1e-5
_GEOMETRY_ATOL = 1e-4


@dataclass(frozen=True)
class HiLoResult:
    """Thermal vs. instability noise separation from a high/low flip-angle pair.

    Greve's high/low flip-angle QA (`bxh-fmriqa-hilo.md`): two phantom runs that
    differ *only* in flip angle let the two noise sources be separated, because
    thermal (additive) noise variance is independent of signal level while
    instability (multiplicative: drift, gradient heating, physiological-like
    fluctuation) noise variance scales with signal squared. With the squared
    signal ratio `M = (mean_high / mean_low)**2`,

        var_high = thermal_var + M * instability_var0
        var_low  = thermal_var +     instability_var0

    which solve to `thermal_var = (M*var_low - var_high)/(M - 1)` and
    `instability_var = var_high - thermal_var`. If measurement noise drives
    `instability_var` negative, it falls back to `thermal_var = var_low`,
    `instability_var = var_high - var_low` (`fell_back` records this).

    All statistics are pooled over the shared eroded phantom core: `mean_*` is the
    core-mean of the per-voxel temporal mean; `var_*` is the *square* of the
    core-mean per-voxel temporal SD of the detrended residual (the note's
    `ROIstats` on the `stddev` image, then squared). `flip_high`/`flip_low` are
    the sidecar flip angles, carried for the report and the ordering check.
    """

    mean_high: float
    mean_low: float
    var_high: float
    var_low: float
    thermal_var: float
    instability_var: float
    n_voxels: int
    fell_back: bool
    flip_high: float | None = None
    flip_low: float | None = None

    @property
    def m(self) -> float:
        """Squared signal ratio `(mean_high / mean_low)**2`."""
        return (self.mean_high / self.mean_low) ** 2

    @property
    def thermal_fsnr(self) -> float:
        """Functional SNR of the thermal component: `mean_high / sqrt(thermal_var)`.

        NaN if the separated thermal variance is non-positive (an unphysical
        result that means the model did not fit -- e.g. near-equal flip signals).
        """
        return (
            float(self.mean_high / np.sqrt(self.thermal_var))
            if self.thermal_var > 0
            else float("nan")
        )

    @property
    def instability_fsnr(self) -> float:
        """Functional SNR of the instability component.

        `mean_high / sqrt(instability_var)`; infinite when no instability is
        detected (`instability_var == 0`), NaN if it is negative.
        """
        if self.instability_var > 0:
            return float(self.mean_high / np.sqrt(self.instability_var))
        return float("inf") if self.instability_var == 0 else float("nan")

    @property
    def instability_fraction(self) -> float:
        """Share of the high-flip variance attributed to instability noise."""
        return (
            self.instability_var / self.var_high if self.var_high > 0 else float("nan")
        )


def separate_noise(
    mean_high: float,
    mean_low: float,
    var_high: float,
    var_low: float,
    n_voxels: int = 0,
    flip_high: float | None = None,
    flip_low: float | None = None,
) -> HiLoResult:
    """Thermal/instability variance split from pooled hi/lo statistics (pure algebra).

    The flip-angle noise-separation math of `HiLoResult`; `run_hilo` computes the
    pooled `mean_*`/`var_*` from a scan pair and calls this. Kept separate so the
    algebra can be exercised directly.
    """
    m = (mean_high / mean_low) ** 2 if mean_low != 0.0 else float("inf")
    if not np.isfinite(m) or m == 1.0:
        # Signal unchanged across the two flip angles (m == 1, e.g. the same scan
        # passed twice) or zero low-flip signal: the split divides by (m - 1) and
        # is undefined. Report NaN variances rather than dividing by zero -- the
        # FSNR properties already fold a non-positive variance to NaN.
        return HiLoResult(
            mean_high=mean_high,
            mean_low=mean_low,
            var_high=var_high,
            var_low=var_low,
            thermal_var=float("nan"),
            instability_var=float("nan"),
            n_voxels=n_voxels,
            fell_back=False,
            flip_high=flip_high,
            flip_low=flip_low,
        )
    thermal_var = (m * var_low - var_high) / (m - 1.0)
    instability_var = var_high - thermal_var
    fell_back = instability_var < 0.0
    if fell_back:  # measurement noise pushed instability negative -- Greve fallback
        thermal_var = var_low
        instability_var = var_high - var_low
    return HiLoResult(
        mean_high=mean_high,
        mean_low=mean_low,
        var_high=var_high,
        var_low=var_low,
        thermal_var=thermal_var,
        instability_var=instability_var,
        n_voxels=n_voxels,
        fell_back=fell_back,
        flip_high=flip_high,
        flip_low=flip_low,
    )


def phantom_core_mask(volume: FloatArray, erode: int = HILO_ERODE) -> BoolArray:
    """Eroded phantom-core mask of a 3-D image (AFNI `3dAutomask -q -erode` analogue).

    Segments the phantom from the temporal-mean `volume` with the same watershed
    used in-plane (`segment_phantom`, applied to the whole volume — its Sobel /
    quantile / watershed steps are all dimension-agnostic), keeps the largest
    connected component with its interior holes filled, then peels `erode` voxel
    layers so the core excludes edge and partial-volume voxels — matching the
    note's `3dAutomask -q -erode 5`.
    """
    mask = ndimage.binary_fill_holes(segment_phantom(volume))
    labels, n = ndimage.label(mask)
    if n > 1:  # keep the largest connected component only
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        mask = labels == int(np.argmax(sizes))
    if erode > 0:
        mask = ndimage.binary_erosion(mask, iterations=erode)
    return np.asarray(mask, dtype=bool)


def _hilo_stats(
    scan: QAScan, trim_sec: float, detrend: DetrendMethod, erode: int
) -> tuple[FloatArray, FloatArray, BoolArray]:
    """(temporal-mean map, temporal-SD-of-residual map, eroded core mask) for a scan.

    The whole 3-D volume is used (not a single slice): thermal/instability
    separation is a global scanner property. The series is trimmed like the rest
    of the pipeline, the mean map is taken on the trimmed signal, and the SD map
    on the per-voxel detrended residual (poly degree scaled to this scan's own run
    length, as elsewhere). The core mask comes from the mean map.
    """
    data = trim_initial(scan.data, scan.tr, trim_sec)  # (X, Y, Z, T)
    mean_map = data.mean(axis=-1)
    detrend_op, _ = detrend_fn(data, scan.tr, detrend)
    sd_map = fluctuation_noise(detrend_op(data))
    return mean_map, sd_map, phantom_core_mask(mean_map, erode)


def _require_compatible_scans(high: QAScan, low: QAScan) -> None:
    """Require matching geometry and acquisition parameters before pooling."""
    if high.data.shape != low.data.shape:
        raise IncompatibleScansError(
            "data geometry",
            high.data.shape,
            low.data.shape,
            "the scans must differ only in flip angle",
        )
    if not np.isclose(high.tr, low.tr, rtol=_GEOMETRY_RTOL, atol=_GEOMETRY_ATOL):
        raise IncompatibleScansError("TR", high.tr, low.tr)

    if (high.affine is None) != (low.affine is None):
        raise IncompatibleScansError("affine", high.affine, low.affine)
    if (
        high.affine is not None
        and low.affine is not None
        and not np.allclose(
            high.affine,
            low.affine,
            rtol=_GEOMETRY_RTOL,
            atol=_GEOMETRY_ATOL,
        )
    ):
        raise IncompatibleScansError("affine", high.affine, low.affine)

    if high.meta is None or low.meta is None:
        return
    if not np.allclose(
        high.meta.voxel_mm,
        low.meta.voxel_mm,
        rtol=_GEOMETRY_RTOL,
        atol=_GEOMETRY_ATOL,
    ):
        raise IncompatibleScansError(
            "voxel size", high.meta.voxel_mm, low.meta.voxel_mm
        )
    if (
        high.meta.te is not None
        and low.meta.te is not None
        and not np.isclose(
            high.meta.te,
            low.meta.te,
            rtol=_GEOMETRY_RTOL,
            atol=_GEOMETRY_ATOL,
        )
    ):
        raise IncompatibleScansError("TE", high.meta.te, low.meta.te)


def run_hilo(
    high: QAScan,
    low: QAScan,
    trim_sec: float = 5.0,
    detrend: DetrendMethod = "poly",
    erode: int = HILO_ERODE,
) -> HiLoResult:
    """Separate thermal from instability noise using a high/low flip-angle scan pair.

    Following `bxh-fmriqa-hilo.md`: `high` and `low` must be the same acquisition
    except for flip angle (the high-flip run first). Each scan is reduced to a
    temporal-mean map and a temporal-SD-of-residual map over the whole volume
    (`_hilo_stats`), and the statistics are pooled over the **shared** eroded
    phantom core — the intersection of the two scans' core masks — so `mean_high`
    and `mean_low` are averaged over identical voxels. `separate_noise` then does
    the flip-angle algebra. Raises if the two geometries differ or their cores do
    not overlap.

    Raises:
        IncompatibleScansError: If the two scans differ in geometry, or their
            phantom cores do not overlap.
    """
    validate_hilo_run(high, low, trim_sec=trim_sec, erode=erode)
    _require_compatible_scans(high, low)

    fh = high.meta.flip_angle if high.meta else None
    fl = low.meta.flip_angle if low.meta else None
    if fh is not None and fl is not None and fh <= fl:
        warnings.warn(
            f"high-flip scan flip angle ({fh:g}) is not greater than the low-flip "
            f"scan ({fl:g}); check the argument order (high first, low second).",
            stacklevel=2,
        )

    mean_h, sd_h, core_h = _hilo_stats(high, trim_sec, detrend, erode)
    mean_l, sd_l, core_l = _hilo_stats(low, trim_sec, detrend, erode)

    core = core_h & core_l
    n = int(core.sum())
    if n == 0:
        raise IncompatibleScansError(
            "phantom core overlap",
            int(core_h.sum()),
            int(core_l.sum()),
            "no shared voxels; check positioning or lower --erode",
        )

    mean_high = float(mean_h[core].mean())
    mean_low = float(mean_l[core].mean())
    var_high = (
        float(sd_h[core].mean()) ** 2
    )  # (core-mean per-voxel SD)**2, per the note
    var_low = float(sd_l[core].mean()) ** 2
    return separate_noise(
        mean_high, mean_low, var_high, var_low, n_voxels=n, flip_high=fh, flip_low=fl
    )
