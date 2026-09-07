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
    """Own read-only copies of immediate array fields, detached from inputs.

    Frozen dataclasses protect attributes, but not array contents. Copying at
    construction also prevents a caller's writable alias from changing a value
    or keeping a much larger input allocation alive through a slice view.
    """

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, np.ndarray):
                object.__setattr__(self, field.name, readonly(value.copy()))
