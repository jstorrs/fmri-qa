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
    construction also prevents a caller's writable alias from changing a value
    or keeping a much larger input allocation alive through a slice view.

    Every frozen dataclass in this package that holds an `ndarray` field
    inherits this: every metric result, geometry object and published artifact
    value of the calculation layer alike, not only the ones that cross
    the `analysis` package's seam. The uniform rule exists because scoping it
    ever looked cheaper than it is: the temptation is "only protect what a
    report or a caller outside this package can reach", but every one of
    these objects is *also* handed across metric functions inside `run_qa`
    while the rest of the pipeline keeps running, so an aliased, writable
    array is exactly as much of a hazard three calls before the seam as after
    it. And the cost of not scoping it is negligible: measured on a
    representative `run_qa` (64x64 in-plane, 30 slices, 200 volumes, ~200 MB
    raw 4-D input), the whole run takes seconds, while copying every array
    field of every metric result that is *not* `QAImages` -- the ROI/PSF/ghost
    masks, motion and centroid traces, the Weisskoff and smoothness curves --
    measured under 100 microseconds combined, because each is one 2-D slice's
    worth of mask or a handful of per-frame scalars (a few bytes to a few KB
    apiece). `QAImages.center_slice`/`fluctuations` are the only fields here
    large enough for the copy itself to matter (a few MB apiece at these
    dimensions, scaling with series length), and they inherit for a second
    reason beyond immutability: copying them at construction is what lets
    `preprocess`'s caller drop the full ~200 MB 4-D series, since `QAImages`
    no longer holds a view into it. A value object cheap enough to copy gets
    no exemption for being "merely internal" — the exemption would save
    microseconds and cost the next reader the ability to tell, by looking at
    one place, whether array contents can move under them.

    `readonly` (below) is this same idea applied by hand, for the one case
    `__post_init__` cannot reach: a `cached_property` computed lazily after
    construction, from already-frozen fields (`QAImages.mean_image` and
    friends, `prep/images.py`). There is nothing left to copy — the inputs are
    already owned — so the property wraps its result in `readonly` directly
    instead of manufacturing a one-field `ArrayValue` wrapper around a cache.
    """

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, np.ndarray):
                object.__setattr__(self, field.name, readonly(value.copy()))
