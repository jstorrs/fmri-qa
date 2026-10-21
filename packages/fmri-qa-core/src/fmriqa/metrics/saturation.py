"""ADC saturation (signal clipping) detection.

A clipped magnitude image piles up on a hardware `2**n - 1` rail. The ceiling is
sequence-dependent and unrecorded, so it is inferred from the series maximum.
The pile-up is counted separately for the dropped warm-up volumes and the
analyzed volumes, since only the latter bias the metrics.

The samples must still be the scanner's integers. A rail is an artifact of the
receiver's integer ADC, and a converter that wrote rescaled floats has destroyed
the evidence. On such a series `detect_saturation` returns `None` (not
determinable), a third answer distinct from "no clipping". Reporting clean there
would be wrong, the same reasoning the zero-slope guard already applies (see
`detect_saturation`). It would hide exactly what this check exists to catch: a
saturated run whose receiver gain needs turning down.
"""

from dataclasses import dataclass

import numpy as np

from ..exceptions import InvalidScanError
from ..types import FloatArray

__all__ = [
    "SATURATION_BITS",
    "ClipRail",
    "SaturationResult",
    "detect_saturation",
]

# Only these n are realistic for MR (12-bit gives 4095).
#: ADC bit depths whose ``2**n - 1`` ceiling is tested as a clipping rail.
SATURATION_BITS = range(8, 17)  # 255 .. 65535


@dataclass(frozen=True, slots=True)
class ClipRail:
    """The hardware rail a clipped series piled up on, and where it hit hardest.

    Every field here is undefined without a rail, so they sit together behind
    one `SaturationResult.rail` that is either present or `None`. There is no
    ceiling and no worst volume for a series that never touched a rail.

    The two trim-split counts stay on the result, because zero is a true answer
    for them: a clean series clipped no samples before the trim or after. "Which
    volume was worst" has no such answer, and an `int | None` beside a rail that
    might independently be `None` would be two ways to say one thing, kept in
    step by hand.
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
    describes that rail when the series maximum sits on one. It is `None` when
    the maximum is not a `2**n - 1` value, which means no clipping.
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
        clipped_kept`) don't affect the statistics. They are expected for
        sequences that deliberately acquire through the approach to steady state.
        """
        return self.n_clipped_kept > 0


def _saturation_bits(stored_max: float) -> int | None:
    """Return n if `stored_max` is a `2**n - 1` rail for a plausible n, else None.

    `stored_max` is the series maximum in stored-integer units. It must round to
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
    data: FloatArray,
    *,
    slope: float = 1.0,
    inter: float = 0.0,
    trim: int = 0,
    stored_integer: bool = True,
) -> SaturationResult | None:
    """Detect ADC saturation (clipping at a `2**n - 1` rail) in a 4-D series.

    Returns `None` when `stored_integer` is False. The series did not reach us
    as the scanner's integer samples, so there is no rail to find and no honest
    verdict to give. See the module docstring. `QAScan.stored_integer` carries
    this from the NIfTI datatype and warns at load.

    The clip ceiling is sequence-dependent and unrecorded, so it is inferred
    from the data. Reconstructed magnitude images are stored as unsigned
    integers, so a clipped acquisition piles up on the hardware rail `2**n - 1`
    (a 12-bit ADC gives 4095). A series maximum that is not a `2**n - 1` value
    means no clipping, and the check reports clean.

    `slope` and `inter` recover the stored integer from scaled image units for
    the rail test. The pile-up is then counted in image units, where every
    clipped voxel shares the same maximum value. The full untrimmed series is
    checked because clipping is worst in the high-signal warm-up volumes. The
    count is split at `trim` (the number of initial volumes the analysis drops).
    Clips in the first `trim` volumes (`n_clipped_pre`) don't reach the
    statistics, and clips in the kept volumes (`n_clipped_kept`) bias them.
    NOTE: the ceiling is inferred from the series maximum, so at least one
    sample always sits on it and `clipped` is True for any detected rail. That
    includes a lone bright voxel that happens to land there, which is not
    saturation. Judge severity by the counts, not the flag.

    Raises
    ------
    InvalidScanError
        If `slope` is zero, infinite or NaN. The rail test divides by `slope` to
        undo the scaling, so such a value makes it meaningless. A caller
        silently getting `suspected=False` back would read that as no clipping,
        so refusing is safer than a wrong "clean" verdict.
    """
    if not stored_integer:
        return None
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
