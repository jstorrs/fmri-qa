"""Local partial stub for scipy.ndimage — only the functions fmriqa calls.

scipy's shipped types are correct but conservative: the transforms are
overloaded on flags that change the return type, so `distance_transform_edt`
and `label` come back as broad unions and `affine_transform` types `offset` as a
scalar even though it accepts a coordinate vector. These signatures pin the
single-return, array-offset forms the pipeline actually uses.
"""

import numpy as np
import numpy.typing as npt

def distance_transform_edt(input: npt.ArrayLike) -> npt.NDArray[np.float64]: ...
def label(
    input: npt.ArrayLike, structure: npt.ArrayLike | None = ...
) -> tuple[npt.NDArray[np.intp], int]: ...
def affine_transform(
    input: npt.ArrayLike,
    matrix: npt.ArrayLike,
    offset: npt.ArrayLike | float = ...,
    output_shape: tuple[int, ...] | None = ...,
    order: int = ...,
    mode: str = ...,
    cval: float = ...,
    prefilter: bool = ...,
) -> npt.NDArray[np.float64]: ...
def binary_fill_holes(
    input: npt.ArrayLike, structure: npt.ArrayLike | None = ...
) -> npt.NDArray[np.bool_]: ...
def binary_erosion(
    input: npt.ArrayLike,
    structure: npt.ArrayLike | None = ...,
    iterations: int = ...,
) -> npt.NDArray[np.bool_]: ...
