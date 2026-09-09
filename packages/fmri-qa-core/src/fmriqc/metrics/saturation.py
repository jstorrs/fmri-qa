"""ADC saturation (signal clipping) detection.

A clipped magnitude image piles up on a hardware `2**n - 1` rail. The ceiling is
sequence-dependent and unrecorded, so it is inferred from the series maximum,
and the pile-up is counted — split at the trim boundary so clips in the dropped
warm-up volumes are reported apart from clips that bias the analyzed metrics.
"""

from dataclasses import dataclass

import numpy as np

from ..exceptions import InvalidScanError
from ..types import FloatArray

# Plausible ADC saturation rails. A clipped magnitude image piles up at a
# hardware 2**n - 1 ceiling; only these n are realistic for MR (12-bit -> 4095).
SATURATION_BITS = range(8, 17)  # 255 .. 65535


@dataclass(frozen=True, slots=True)
class ClipRail:
    """The hardware rail a clipped series piled up on, and where it hit hardest.

    Every field here is undefined without a rail, which is why they sit together
    behind one `SaturationResult.rail` that is either present or `None`: there is
    no ceiling without a detected rail, and no "worst volume" either -- the
    question does not arise for a series that never touched one.

    The two trim-split counts stay outside, on the result, because *zero* is a
    true answer for them: a clean series clipped no samples before the trim and
    none after. "Which volume was worst" has no such answer, and an `int | None`
    beside a rail that might independently be `None` is two ways to say one
    thing, kept in step by hand.
    """

    ceiling: float  # clip level (image units)
    bits: int  # n such that the stored ceiling is 2**n - 1
    worst_volume: int  # volume index (full series) with the most clipped samples
    worst_count: int  # clipped samples in that worst volume


@dataclass(frozen=True, slots=True)
class SaturationResult:
    """ADC-saturation (signal-clipping) check for one scan.

    The clip ceiling is sequence-dependent and not recorded, so it is inferred:
    a clipped magnitude image piles up on a hardware `2**n - 1` rail. `rail`
    describes that rail when the series maximum sits on one, and is `None` when
    it does not -- a maximum that is not a `2**n - 1` value means no clipping.
    """

    rail: ClipRail | None
    n_clipped_pre: int  # clipped samples in the dropped warm-up volumes
    n_clipped_kept: int  # clipped samples in the analyzed volumes (bias the metrics)

    @property
    def ceiling(self) -> float | None:
        """The clip level in image units, or None if no rail was detected."""
        return None if self.rail is None else self.rail.ceiling

    @property
    def bits(self) -> int | None:
        """`n` such that the stored ceiling is `2**n - 1`, or None without a rail."""
        return None if self.rail is None else self.rail.bits

    @property
    def n_clipped(self) -> int:
        """Total voxel*time samples pinned at the ceiling, across the full series."""
        return self.n_clipped_pre + self.n_clipped_kept

    @property
    def suspected(self) -> bool:
        """True if the series maximum sits exactly on a 2**n-1 hardware rail."""
        return self.rail is not None

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

    Raises:
        InvalidScanError: If `slope` is zero, infinite, or NaN. The rail test
            below divides by `slope` to undo the scaling, so a non-finite or
            zero value makes it meaningless -- not a series with no clipping,
            which is what a caller silently getting `suspected=False` back
            would read this as. Refusing is safer than a wrong "clean" verdict.
    """
    if not np.isfinite(slope) or slope == 0.0:
        raise InvalidScanError(
            "slope", slope, "expected a finite, nonzero scaling to recover stored units"
        )
    # A negative NIfTI slope reverses the extrema in image units; the rail is
    # always the maximum in stored units.
    ceiling = float(np.max(data) if slope > 0 else np.min(data))
    bits = _saturation_bits((ceiling - inter) / slope)
    if bits is None:
        return SaturationResult(rail=None, n_clipped_pre=0, n_clipped_kept=0)
    per_volume = (data == ceiling).reshape(-1, data.shape[-1]).sum(axis=0)
    worst = int(np.argmax(per_volume))
    return SaturationResult(
        rail=ClipRail(
            ceiling=ceiling,
            bits=bits,
            worst_volume=worst,
            worst_count=int(per_volume[worst]),
        ),
        n_clipped_pre=int(per_volume[:trim].sum()),
        n_clipped_kept=int(per_volume[trim:].sum()),
    )
