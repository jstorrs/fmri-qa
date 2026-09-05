"""ADC saturation (signal clipping) detection.

A clipped magnitude image piles up on a hardware `2**n - 1` rail. The ceiling is
sequence-dependent and unrecorded, so it is inferred from the series maximum,
and the pile-up is counted — split at the trim boundary so clips in the dropped
warm-up volumes are reported apart from clips that bias the analyzed metrics.
"""

from dataclasses import dataclass

import numpy as np

from ..types import FloatArray

# Plausible ADC saturation rails. A clipped magnitude image piles up at a
# hardware 2**n - 1 ceiling; only these n are realistic for MR (12-bit -> 4095).
SATURATION_BITS = range(8, 17)  # 255 .. 65535


@dataclass(frozen=True)
class SaturationResult:
    """ADC-saturation (signal-clipping) check for one scan.

    The clip ceiling is sequence-dependent and not recorded, so it is inferred:
    a clipped magnitude image piles up on a hardware `2**n - 1` rail. `ceiling`
    is that rail (in image units) when the series maximum sits on one, else
    `None` -- a maximum that is not a `2**n - 1` value means no clipping.
    """

    ceiling: float | None  # clip level (image units); None if max is not a 2**n-1 rail
    bits: int | None  # n such that the stored ceiling is 2**n - 1
    n_clipped_pre: int  # clipped samples in the dropped warm-up volumes
    n_clipped_kept: int  # clipped samples in the analyzed volumes (bias the metrics)
    worst_volume: int | None  # volume index (full series) with the most clipped samples
    worst_count: int  # clipped samples in that worst volume

    @property
    def n_clipped(self) -> int:
        """Total voxel*time samples pinned at the ceiling, across the full series."""
        return self.n_clipped_pre + self.n_clipped_kept

    @property
    def suspected(self) -> bool:
        """True if the series maximum sits exactly on a 2**n-1 hardware rail."""
        return self.ceiling is not None

    @property
    def clipped(self) -> bool:
        """True if any sample reaches that rail, anywhere in the series."""
        return self.n_clipped > 0

    @property
    def clipped_kept(self) -> bool:
        """True if clipping falls in the analyzed data, where it biases the metrics.

        Clips confined to the dropped warm-up volumes (`clipped and not
        clipped_kept`) don't affect the statistics — and are expected for
        sequences that deliberately acquire through the approach to steady state.
        """
        return self.n_clipped_kept > 0


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
