"""ADC saturation (signal clipping) detection.

A clipped magnitude image piles up on a hardware `2**n - 1` rail. The ceiling is
sequence-dependent and unrecorded, so it is inferred from the series maximum,
and the pile-up is counted — split at the trim boundary so clips in the dropped
warm-up volumes are reported apart from clips that bias the analyzed metrics.
"""

import numpy as np

from .constants import SATURATION_BITS, FloatArray
from .types import SaturationResult


def _saturation_bits(stored_max: float) -> int | None:
    """Return n if `stored_max` is a `2**n - 1` rail for a plausible n, else None.

    `stored_max` is the series maximum in stored-integer units; it must round to
    an integer of the form `2**n - 1` (all low bits set) with n in
    `SATURATION_BITS`. A non-integer or off-rail maximum means no clipping.
    """
    k = round(stored_max)
    if abs(stored_max - k) > 1e-4 or k <= 0:
        return None
    if k & (k + 1):  # k+1 not a power of two -> k is not 2**n - 1
        return None
    n = k.bit_length()  # k = 2**n - 1  ->  bit_length is n
    return n if n in SATURATION_BITS else None


def detect_saturation(
    data: FloatArray, slope: float = 1.0, inter: float = 0.0, trim: int = 0
) -> SaturationResult:
    """Detect ADC saturation (signal clipped at a `2**n - 1` rail) in a 4-D series.

    The clip ceiling is sequence-dependent and unrecorded, so it is inferred
    from the data: reconstructed magnitude images are stored as unsigned
    integers, so a clipped acquisition piles up on the hardware rail `2**n - 1`
    (12-bit ADC -> 4095 is the classic case). A series maximum that is not a
    `2**n - 1` value means no clipping occurred and the check reports clean.

    `slope`/`inter` recover the stored integer from scaled image units for the
    rail test; the pile-up is then counted in image units, where every clipped
    voxel shares the identical maximum value. The full untrimmed series is
    checked because clipping is worst in the high-signal warm-up volumes -- but
    the count is split at `trim` (the number of initial volumes the analysis
    drops): clips in the first `trim` volumes (`n_clipped_pre`) don't reach the
    statistics, while clips in the kept volumes (`n_clipped_kept`) bias them.
    A lone sample on the rail is likely a bright voxel; a pile-up is saturation.
    """
    ceiling = float(np.max(data))
    bits = _saturation_bits((ceiling - inter) / slope)
    if bits is None:
        return SaturationResult(
            ceiling=None,
            bits=None,
            n_clipped_pre=0,
            n_clipped_kept=0,
            worst_volume=None,
            worst_count=0,
        )
    per_volume = (data == ceiling).reshape(-1, data.shape[-1]).sum(axis=0)
    worst = int(np.argmax(per_volume))
    return SaturationResult(
        ceiling=ceiling,
        bits=bits,
        n_clipped_pre=int(per_volume[:trim].sum()),
        n_clipped_kept=int(per_volume[trim:].sum()),
        worst_volume=worst,
        worst_count=int(per_volume[worst]),
    )
