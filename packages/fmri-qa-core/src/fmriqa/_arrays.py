"""Array ownership for immutable numerical value objects."""

from dataclasses import dataclass, fields

import numpy as np
from numpy.typing import NDArray


def readonly[T: np.generic](array: NDArray[T]) -> NDArray[T]:
    """Protect a newly allocated result from accidental in-place modification."""
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True, eq=False)
class ArrayValue:
    """Owner of read-only copies of immediate array fields, detached from inputs.

    Frozen dataclasses protect attributes, but not array contents. Copying at
    construction also stops a caller's writable alias from changing a value, or
    keeping a much larger input allocation alive through a slice view.

    Every frozen dataclass in this package with an `ndarray` field inherits
    this, not only the ones that cross the `analysis` package's seam. These
    objects are also passed between metric functions inside `run_qa`, so a
    writable alias is as much of a hazard there as after the seam. Copying is
    cheap. On a representative `run_qa` (64x64 in-plane, 30 slices, 200 volumes,
    ~200 MB raw 4-D input) the run takes seconds, and copying every array field
    of every metric result other than `QAImages` took under 100 microseconds
    combined (masks, traces and curves: one 2-D mask or a few per-frame scalars
    each). `QAImages.center_slice` and `fluctuations` are the only fields large
    enough for the copy to matter (a few MB apiece, growing with series length).
    Copying them also lets `preprocess`'s caller drop the full 4-D series, since
    `QAImages` no longer holds a view into it. Don't exempt a value object for
    being "internal": the exemption saves microseconds and costs the reader the
    ability to tell from one place whether array contents can change.

    `readonly` (below) applies the same idea by hand to a `cached_property`
    computed after construction from already-frozen fields (`QAImages.mean_image`
    and friends, `prep/images.py`). The inputs are already owned, so the
    property just wraps its result in `readonly`.
    """

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, np.ndarray):
                object.__setattr__(self, field.name, readonly(value.copy()))
