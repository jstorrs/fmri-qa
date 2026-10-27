"""`scan_meta`: the report header's metadata from geometry plus a sidecar."""

import pytest

import fmriqa as q
from fmriqa.load.metadata import scan_meta

_GEOMETRY = {"voxel_mm": (3.0, 3.0, 4.0), "matrix": (64, 64), "pe_axis": 1, "tr": 2.0}


def test_fields_are_filled_from_the_sidecar() -> None:
    sidecar = {"EchoTime": 0.03, "FlipAngle": 77, "Manufacturer": "Acme"}
    meta = scan_meta(sidecar, **_GEOMETRY)
    assert (meta.voxel_mm, meta.matrix, meta.tr) == ((3.0, 3.0, 4.0), (64, 64), 2.0)
    assert (meta.te, meta.flip_angle, meta.manufacturer) == (0.03, 77.0, "Acme")
    assert meta.pe_dir == "col"
    assert meta.model is None


@pytest.mark.parametrize(
    "voxel_mm", [(3.0, 0.0, 3.0), (3.0, 3.0, -1.0), (float("nan"), 3.0, 3.0)]
)
def test_a_voxel_size_that_is_not_positive_and_finite_is_refused(
    voxel_mm: tuple[float, float, float],
) -> None:
    with pytest.raises(q.InvalidScanError, match="voxel size") as info:
        scan_meta({}, **{**_GEOMETRY, "voxel_mm": voxel_mm})
    assert info.value.value == voxel_mm
