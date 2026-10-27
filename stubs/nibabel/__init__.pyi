"""Local partial stub for nibabel — only the surface `fmriqa_io.decode` reads and
`fmriqa_io.testing` writes.

nibabel ships type information, but its image classes come back typed as the
`FileBasedImage` base class, which lacks the NIfTI accessors (`get_fdata`,
`affine`, the scaled array proxy and the spatial header) the decoder actually
uses, and its `get_zooms` is mistyped. This stub declares the NIfTI image
classes with just those accessors, typed as the pipeline expects them.
"""

from typing import Any, Self

import numpy as np
import numpy.typing as npt

class Nifti1Header:
    def get_zooms(self) -> tuple[float, ...]: ...
    def get_slope_inter(self) -> tuple[float | None, float | None]: ...
    def get_dim_info(self) -> tuple[int | None, int | None, int | None]: ...
    def get_xyzt_units(self) -> tuple[str, str]: ...
    def get_data_dtype(self) -> np.dtype[Any]: ...
    def set_zooms(self, zooms: tuple[float, ...]) -> None: ...
    def set_xyzt_units(self, xyz: str, t: str) -> None: ...

class ArrayProxy:
    slope: float
    inter: float

class Nifti1Image:
    header: Nifti1Header
    dataobj: ArrayProxy
    affine: npt.NDArray[np.float64]
    shape: tuple[int, ...]
    def __init__(
        self, dataobj: npt.NDArray[Any], affine: npt.NDArray[np.float64]
    ) -> None: ...
    @classmethod
    def from_bytes(cls, bytestring: bytes) -> Self: ...
    def get_fdata(self) -> npt.NDArray[np.float64]: ...

class Nifti2Image(Nifti1Image): ...

def save(img: Nifti1Image, filename: str) -> None: ...
