"""The exception contract: every promised error, and its dual catchability."""

from dataclasses import replace

import numpy as np
import pytest

import fmriqc as q
from fmriqc.exceptions import (
    FmriqcError,
    IncompatibleScansError,
    InvalidChoiceError,
)
from fmriqc.hilo.compatibility import require_compatible_scans
from fmriqc.prep.detrend import detrend_fn
from fmriqc.prep.geometry import resolve_roi
from fmriqc.prep.imaging import extract_center_slice


def test_detrend_fn_rejects_unknown_method() -> None:
    with pytest.raises(InvalidChoiceError, match="detrend method"):
        detrend_fn(np.zeros((2, 2, 10)), 2.0, "bogus")  # type: ignore[arg-type]


def test_extract_center_slice_rejects_unknown_center() -> None:
    with pytest.raises(InvalidChoiceError, match="center"):
        extract_center_slice(np.zeros((4, 4, 3, 5)), "middle")  # type: ignore[arg-type]


def test_resolve_roi_rejects_unknown_center() -> None:
    images = q.preprocess(_flat_scan())
    geom = q.detect_phantom(images)
    with pytest.raises(InvalidChoiceError, match="ROI center"):
        resolve_roi(images, geom, center="corner")  # type: ignore[arg-type]


def test_invalid_choice_is_fmriqc_error_and_value_error() -> None:
    with pytest.raises(FmriqcError) as info:
        detrend_fn(np.zeros((2, 2, 10)), 2.0, "bogus")  # type: ignore[arg-type]
    assert isinstance(info.value, ValueError)


def test_invalid_choice_carries_structured_payload() -> None:
    with pytest.raises(InvalidChoiceError) as info:
        detrend_fn(np.zeros((2, 2, 10)), 2.0, "bogus")  # type: ignore[arg-type]
    err = info.value
    assert err.name == "detrend method"
    assert err.value == "bogus"
    assert err.choices == q.DETREND_METHODS


def test_run_hilo_rejects_mismatched_geometry() -> None:
    high = _flat_scan(shape=(8, 8, 2, 12))
    low = _flat_scan(shape=(8, 8, 3, 12))  # different Z
    with pytest.raises(IncompatibleScansError, match="geometry"):
        q.run_hilo(high, low)


@pytest.mark.parametrize("field", ["TR", "affine", "voxel size", "TE"])
def test_hilo_rejects_mismatched_acquisition(field: str) -> None:
    meta = q.ScanMeta(voxel_mm=(3.0, 3.0, 3.0), matrix=(16, 16), tr=2.0, te=0.03)
    high = replace(_flat_scan(), affine=np.eye(4), meta=meta)
    low = high
    if field == "TR":
        low = replace(low, tr=2.1)
    elif field == "affine":
        affine = np.eye(4)
        affine[0, 3] = 1.0
        low = replace(low, affine=affine)
    elif field == "voxel size":
        low = replace(low, meta=replace(meta, voxel_mm=(2.0, 3.0, 3.0)))
    else:
        low = replace(low, meta=replace(meta, te=0.04))

    with pytest.raises(IncompatibleScansError) as info:
        require_compatible_scans(high, low)
    assert info.value.field == field
    assert repr(info.value.high_value) != repr(info.value.low_value)


def test_hilo_accepts_small_affine_roundoff() -> None:
    high = replace(_flat_scan(), affine=np.eye(4))
    affine = np.eye(4)
    affine[0, 3] = 1e-6
    low = replace(high, affine=affine)
    require_compatible_scans(high, low)


@pytest.mark.parametrize("kwargs", [{"erode": -1}, {"trim_sec": 1_000.0}])
def test_run_hilo_validates_parameters_before_processing(
    kwargs: dict[str, object],
) -> None:
    scan = _flat_scan()
    with pytest.raises(q.InvalidScanError):
        q.run_hilo(scan, scan, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("shape", "kwargs", "field"),
    [
        ((16, 16, 3, 3), {}, "frame count"),
        ((16, 16, 3, 20), {"roi_size": 0}, "roi_size"),
        ((16, 16, 3, 20), {"trim_sec": 1_000.0}, "trim_sec"),
        ((16, 16, 3, 20), {"pe_axis": 2}, "phase-encode axis"),
    ],
)
def test_run_qa_rejects_invalid_inputs(
    shape: tuple[int, int, int, int], kwargs: dict[str, object], field: str
) -> None:
    scan = _flat_scan(shape=shape)
    with pytest.raises(q.InvalidScanError) as info:
        q.run_qa(scan, **kwargs)  # type: ignore[arg-type]
    assert info.value.field == field


def test_run_qa_rejects_nonfinite_data_and_tr() -> None:
    bad_data = _flat_scan()
    bad_data.data[0, 0, 0, 0] = np.nan
    with pytest.raises(q.InvalidScanError, match="non-finite"):
        q.run_qa(bad_data)

    bad_tr = q.QAScan(data=_flat_scan().data, tr=0.0, pe_axis=1)
    with pytest.raises(q.InvalidScanError, match="TR"):
        q.run_qa(bad_tr)


def test_run_qa_rejects_through_plane_pe_from_scan() -> None:
    scan = q.QAScan(data=_flat_scan().data, tr=2.0, pe_axis=2)
    with pytest.raises(q.InvalidScanError, match="in-plane"):
        q.run_qa(scan)


def _flat_scan(shape: tuple[int, int, int, int] = (16, 16, 3, 20)) -> q.QAScan:
    """A minimal scan with a bright central block, built without file I/O."""
    x, y = shape[0], shape[1]
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:x, 0:y]
    disk = ((xx - x / 2) ** 2 + (yy - y / 2) ** 2) < (x / 4) ** 2
    noise = rng.normal(scale=3.0, size=shape) * disk[:, :, None, None]
    data = base_from_disk(disk) + noise
    return q.QAScan(data=data, tr=2.0, pe_axis=1)


def base_from_disk(disk: np.ndarray) -> np.ndarray:
    """(X, Y, 1, 1) bright-disk baseline broadcastable over Z and T."""
    return np.where(disk, 1000.0, 0.0)[:, :, None, None]
