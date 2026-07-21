"""The exception contract: every promised error, and its dual catchability."""

import numpy as np
import pytest

import fmriqc as q
from fmriqc.detrend import detrend_fn
from fmriqc.exceptions import (
    FmriqcError,
    IncompatibleScansError,
    InvalidChoiceError,
    MissingSidecarError,
)
from fmriqc.geometry import resolve_roi
from fmriqc.imaging import extract_center_slice


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


def test_missing_sidecar_raised_for_absent_json(tmp_path) -> None:
    nifti = tmp_path / "scan.nii.gz"
    nifti.write_bytes(b"not really a nifti")  # never read: sidecar check comes first
    with pytest.raises(MissingSidecarError) as info:
        q.QAScan.from_nifti(nifti)
    assert info.value.sidecar == tmp_path / "scan.json"


def test_missing_sidecar_is_fmriqc_error_and_file_not_found(tmp_path) -> None:
    with pytest.raises(FmriqcError) as info:
        q.QAScan.from_nifti(tmp_path / "scan.nii")
    assert isinstance(info.value, FileNotFoundError)


def test_run_hilo_rejects_mismatched_geometry() -> None:
    high = _flat_scan(shape=(8, 8, 2, 12))
    low = _flat_scan(shape=(8, 8, 3, 12))  # different Z
    with pytest.raises(IncompatibleScansError, match="geometry"):
        q.run_hilo(high, low)


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
