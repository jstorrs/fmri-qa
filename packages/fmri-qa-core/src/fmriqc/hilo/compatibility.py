"""Geometry and acquisition checks a hi/lo scan pair must satisfy before pooling."""

import numpy as np

from ..exceptions import IncompatibleScansError
from ..load.scan import QAScan

_GEOMETRY_RTOL = 1e-5
_GEOMETRY_ATOL = 1e-4


def require_compatible_scans(high: QAScan, low: QAScan) -> None:
    """Require matching geometry and acquisition parameters before pooling.

    Both scans' affines and voxel sizes are in millimeters, as supplied by the
    NIfTI loader or by callers constructing `QAScan` directly.
    """
    if high.data.shape != low.data.shape:
        raise IncompatibleScansError(
            "data geometry",
            high.data.shape,
            low.data.shape,
            "the scans must differ only in flip angle",
        )
    if not np.isclose(high.tr, low.tr, rtol=_GEOMETRY_RTOL, atol=_GEOMETRY_ATOL):
        raise IncompatibleScansError("TR", high.tr, low.tr)

    if (high.affine is None) != (low.affine is None):
        raise IncompatibleScansError("affine", high.affine, low.affine)
    if (
        high.affine is not None
        and low.affine is not None
        and not np.allclose(
            high.affine,
            low.affine,
            rtol=_GEOMETRY_RTOL,
            atol=_GEOMETRY_ATOL,
        )
    ):
        raise IncompatibleScansError("affine", high.affine, low.affine)

    if high.meta is None or low.meta is None:
        return
    if not np.allclose(
        high.meta.voxel_mm,
        low.meta.voxel_mm,
        rtol=_GEOMETRY_RTOL,
        atol=_GEOMETRY_ATOL,
    ):
        raise IncompatibleScansError(
            "voxel size", high.meta.voxel_mm, low.meta.voxel_mm
        )
    if (
        high.meta.te is not None
        and low.meta.te is not None
        and not np.isclose(
            high.meta.te,
            low.meta.te,
            rtol=_GEOMETRY_RTOL,
            atol=_GEOMETRY_ATOL,
        )
    ):
        raise IncompatibleScansError("TE", high.meta.te, low.meta.te)
