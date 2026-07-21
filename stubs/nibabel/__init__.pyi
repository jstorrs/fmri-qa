"""Local partial stub for nibabel — only the surface `fmriqc.scan` uses.

nibabel ships type information, but `load` is annotated to return the
`FileBasedImage` base class, which lacks the NIfTI accessors (`get_fdata`,
`affine`, and a `SpatialHeader` with `get_zooms`/`get_slope_inter`) the loader
actually calls, and its `get_zooms` is mistyped. This stub narrows `load` to a
NIfTI image with just those accessors, typed as the pipeline expects them.
"""

import numpy as np
import numpy.typing as npt

class Nifti1Header:
    def get_zooms(self) -> tuple[float, ...]: ...
    def get_slope_inter(self) -> tuple[float | None, float | None]: ...
    def get_dim_info(self) -> tuple[int | None, int | None, int | None]: ...

class Nifti1Image:
    header: Nifti1Header
    affine: npt.NDArray[np.float64]
    shape: tuple[int, ...]
    def get_fdata(self) -> npt.NDArray[np.float64]: ...

def load(filename: str) -> Nifti1Image: ...
