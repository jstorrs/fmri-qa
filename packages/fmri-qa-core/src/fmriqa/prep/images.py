"""The `QAImages` value object: the preprocessed images every metric reads from.

Produced by `pipeline.preprocess` before phantom detection. Derived summary
images are computed from the two stored fields, not stored beside them, so
there is no redundant state to keep in sync. The raw-array primitives the
properties call live in `imaging` (the leaf layer), so this module doesn't
depend on the metric or report layers.
"""

from dataclasses import dataclass
from functools import cached_property

from .._arrays import ArrayValue, readonly
from ..types import BoolArray, FloatArray
from .detrend import Detrender
from .imaging import (
    edge_valid_mask,
    fluctuation_noise,
    odd_even_difference,
    segment_phantom,
)

__all__ = [
    "QAImages",
]


# The one value object here without `slots=True`: the summary images below are
# `cached_property`, which needs a real instance `__dict__` to cache into.
@dataclass(frozen=True, eq=False)
class QAImages(ArrayValue):
    """The center slice and its detrended fluctuations, plus derived FBIRN images.

    Produced by `preprocess` before phantom detection. Only the center slice is
    kept. The full multi-slice 4-D volume can be discarded once this exists, and
    everything downstream (phantom geometry, Weisskoff, ghost, drift) reads from
    here. `fluctuations` is the per-voxel detrended residual, so ROI-averaging it
    equals detrending the ROI mean (detrending is a fixed linear operator that
    commutes with the spatial mean). `trend = center_slice - fluctuations` is the
    fitted low-frequency drift that `drift_percent` summarizes. `zero_value` is
    the image value a stored zero maps to, which is the scan's `scl_inter`.
    Without it a nulled image edge is not recognizable as one.

    The summary images are derived, not stored. Each is a full reduction over
    the (X, Y, T) slice, computed on first use and kept, since the pipeline asks
    for the same image many times. The fields it derives from are frozen, so the
    cache can't go stale.

    `n_trimmed` is how many warm-up volumes `preprocess` dropped. Frame indexes
    and times here count from the trimmed series, so `n_trimmed` is the only way
    back to an acquired volume number once `scan.data` is discarded.
    `slice_index` and `n_slices` say which plane of the volume this is, for the
    same reason. They are `None` only for images not cut from a volume by
    `preprocess`.
    """

    center_slice: FloatArray  # (X, Y, T) trimmed center slice (raw signal)
    fluctuations: FloatArray  # (X, Y, T) detrended residuals
    tr: float
    n_trimmed: int = 0  # warm-up volumes dropped ahead of `center_slice`
    zero_value: float = 0.0  # image value a stored zero maps to (NIfTI scl_inter)
    # The fit behind `fluctuations`. An order is a degree or a knot count
    # depending on the method (see `Detrender`). None for images assembled from
    # bare arrays, with no fit behind them.
    detrender: Detrender | None = None
    slice_index: int | None = None  # which plane of the volume this is (0-based)
    n_slices: int | None = None  # how many planes the volume had

    @cached_property
    def trend(self) -> FloatArray:
        """(X, Y, T) fitted low-frequency trend: signal minus fluctuations."""
        return readonly(self.center_slice - self.fluctuations)

    @cached_property
    def mean_image(self) -> FloatArray:
        """(X, Y) temporal mean (FBIRN signal image)."""
        return readonly(self.center_slice.mean(axis=-1))

    @cached_property
    def mip(self) -> FloatArray:
        """(X, Y) max over time — phantom-segmentation target."""
        return readonly(self.center_slice.max(axis=-1))

    @cached_property
    def phantom_mask(self) -> BoolArray:
        """(X, Y) watershed phantom mask, segmented from `mip`.

        The one definition `detect_phantom` reads. It is not a constructor
        field, so no `QAImages` can have a mask that disagrees with
        `segment_phantom(self.mip)`.
        """
        return readonly(segment_phantom(self.mip))

    @cached_property
    def valid_mask(self) -> BoolArray:
        """(X, Y) real-data mask: True except on entirely-nulled image edges.

        Detected from the time-MIP, so a voxel that ever carries signal counts
        as valid, and against `zero_value` instead of 0.0, since a stored zero
        reads back as the scan's intercept (see `edge_valid_mask`).
        """
        return readonly(edge_valid_mask(self.mip, zero=self.zero_value))

    @cached_property
    def static_noise(self) -> FloatArray:
        """(X, Y) ``|mean(even) - mean(odd)|``, published as `images.static_noise`.

        `snr` does not read it. It builds its own odd/even sum difference over
        an even frame count.
        """
        return readonly(odd_even_difference(self.center_slice))

    @cached_property
    def fluctuation_noise(self) -> FloatArray:
        """(X, Y) temporal RMS of the fluctuations."""
        return readonly(fluctuation_noise(self.fluctuations))
