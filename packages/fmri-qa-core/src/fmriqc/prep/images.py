"""The `QAImages` value object: the preprocessed images every metric reads from.

Produced by `pipeline.preprocess` before phantom detection. Derived summary
images are computed from the two stored fields rather than stored beside them,
so there is no redundant state to keep in sync. The raw-array primitives the
properties call live in `imaging` (the leaf layer), which keeps this module free
of any dependency on the metric or report layers.
"""

from dataclasses import dataclass
from functools import cached_property

from ..types import BoolArray, DetrendMethod, FloatArray
from .imaging import edge_valid_mask, fluctuation_noise, odd_even_difference


@dataclass(frozen=True, eq=False)
class QAImages:
    """The center slice and its detrended fluctuations, plus derived FBIRN images.

    Produced by `preprocess` before phantom detection. Only the center slice is
    retained — the full multi-slice 4-D volume can be discarded once this exists,
    and everything downstream (phantom geometry, Weisskoff, ghost, drift) reads
    from here. `fluctuations` is the per-voxel detrended residual, so ROI-averaging
    it equals detrending the ROI mean (detrending is a fixed linear operator that
    commutes with the spatial mean); `trend = center_slice - fluctuations` is the
    fitted low-frequency drift needed for drift/SFNR summaries. `zero_value` is
    the image value a stored zero maps to — the scan's `scl_inter`, without
    which a nulled image edge is not recognizable as one.

    The summary images are derived, not stored: each is a full reduction over
    the (X, Y, T) slice, computed from the two fields above on first use and
    kept for later readers — the pipeline asks several of them for the same
    image many times. That is a cache, not second state: the fields it is
    derived from are frozen, so the answer cannot go stale, and there is still
    exactly one place a summary image is defined.
    """

    center_slice: FloatArray  # (X, Y, T) trimmed center slice (raw signal)
    fluctuations: FloatArray  # (X, Y, T) detrended residuals
    tr: float
    zero_value: float = 0.0  # image value a stored zero maps to (NIfTI scl_inter)
    pe_axis: int | None = None
    detrend_method: DetrendMethod = "poly"
    detrend_order: int | None = None  # poly degree / spline interior-knot count

    @cached_property
    def trend(self) -> FloatArray:
        """(X, Y, T) fitted low-frequency trend: signal minus fluctuations."""
        return self.center_slice - self.fluctuations

    @cached_property
    def mean_image(self) -> FloatArray:
        """(X, Y) temporal mean (FBIRN signal image)."""
        return self.center_slice.mean(axis=-1)

    @cached_property
    def mip(self) -> FloatArray:
        """(X, Y) max over time — phantom-segmentation target."""
        return self.center_slice.max(axis=-1)

    @cached_property
    def valid_mask(self) -> BoolArray:
        """(X, Y) real-data mask: True except on entirely-nulled image edges.

        Detected from the time-MIP so a voxel that ever carries signal counts as
        valid, and against `zero_value` rather than 0.0, since a stored zero
        reads back as the scan's intercept (see `edge_valid_mask`).
        """
        return edge_valid_mask(self.mip, zero=self.zero_value)

    @cached_property
    def static_noise(self) -> FloatArray:
        """(X, Y) odd/even difference (FBIRN static spatial noise)."""
        return odd_even_difference(self.center_slice)

    @cached_property
    def fluctuation_noise(self) -> FloatArray:
        """(X, Y) temporal RMS of the fluctuations."""
        return fluctuation_noise(self.fluctuations)
