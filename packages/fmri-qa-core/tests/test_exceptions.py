"""The exception contract: every promised error, and its dual catchability."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import fmriqc as q
from fmriqc.exceptions import (
    FmriqcError,
    IncompatibleScansError,
    InvalidChoiceError,
)
from fmriqc.hilo.compatibility import require_compatible_scans
from fmriqc.prep.detrend import Detrender
from fmriqc.prep.geometry import resolve_roi
from fmriqc.prep.imaging import extract_center_slice


def test_detrender_rejects_unknown_method() -> None:
    with pytest.raises(InvalidChoiceError, match="detrend method"):
        Detrender.for_series(np.zeros((2, 2, 10)), 2.0, "bogus")  # type: ignore[arg-type]


def test_extract_center_slice_rejects_unknown_center() -> None:
    with pytest.raises(InvalidChoiceError, match="center"):
        extract_center_slice(np.zeros((4, 4, 3, 5)), "middle")  # type: ignore[arg-type]


def test_resolve_roi_rejects_unknown_center() -> None:
    images = q.preprocess(_flat_scan())
    geom = q.detect_phantom(images)
    with pytest.raises(InvalidChoiceError, match="ROI center"):
        resolve_roi(images, geom, center="corner")  # type: ignore[arg-type]


def test_import_dicom_rejects_unknown_name_style(tmp_path: Path) -> None:
    destination = tmp_path / "out"
    with pytest.raises(InvalidChoiceError, match="names"):
        q.import_dicom(tmp_path, destination, names="QA")  # type: ignore[arg-type]
    assert not destination.exists()


def test_import_dicom_rejects_unknown_anonymize_mode(tmp_path: Path) -> None:
    destination = tmp_path / "out"
    with pytest.raises(InvalidChoiceError, match="anonymize"):
        q.import_dicom(tmp_path, destination, anonymize="y")  # type: ignore[arg-type]
    assert not destination.exists()


def test_invalid_choice_is_fmriqc_error_and_value_error() -> None:
    with pytest.raises(FmriqcError) as info:
        Detrender.for_series(np.zeros((2, 2, 10)), 2.0, "bogus")  # type: ignore[arg-type]
    assert isinstance(info.value, ValueError)


def test_invalid_choice_carries_structured_payload() -> None:
    with pytest.raises(InvalidChoiceError) as info:
        Detrender.for_series(np.zeros((2, 2, 10)), 2.0, "bogus")  # type: ignore[arg-type]
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


@pytest.mark.parametrize(
    "kwargs", [{"erode": -1}, {"trim_sec": -1.0}, {"trim_sec": 1_000.0}]
)
def test_run_hilo_validates_parameters_before_processing(
    kwargs: dict[str, object],
) -> None:
    scan = _flat_scan()
    with pytest.raises(q.InvalidScanError):
        q.run_hilo(scan, scan, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("shape", "settings_kwargs", "field"),
    [
        ((16, 16, 3, 3), {}, "frame count"),
        ((16, 16, 3, 20), {"trim_sec": 1_000.0}, "trim_sec"),
        ((16, 16, 3, 20), {"pe_axis_override": 2}, "phase-encode axis"),
    ],
)
def test_run_qa_rejects_invalid_inputs(
    shape: tuple[int, int, int, int], settings_kwargs: dict[str, object], field: str
) -> None:
    scan = _flat_scan(shape=shape)
    # Built outside the `raises` block so the refusal has to come from `run_qa`:
    # a record that refused the value itself would satisfy `raises` without the
    # pipeline ever having checked it.
    settings = q.AnalysisSettings(**settings_kwargs)  # type: ignore[arg-type]
    with pytest.raises(q.InvalidScanError) as info:
        q.run_qa(scan, settings)
    assert info.value.field == field


@pytest.mark.parametrize("trim_sec", [float("nan"), float("inf"), -1.0])
def test_a_trim_that_names_no_real_duration_cannot_be_constructed(
    trim_sec: float,
) -> None:
    """The warm-up trim is a span of seconds to drop, not an arbitrary float."""
    with pytest.raises(q.InvalidScanError) as info:
        q.AnalysisSettings(trim_sec=trim_sec)
    assert info.value.field == "trim_sec"


@pytest.mark.parametrize("roi_size", [0, -1])
def test_an_roi_with_no_positive_side_cannot_be_constructed(roi_size: int) -> None:
    """The summary and Weisskoff ROIs are squares of this side; zero has none."""
    with pytest.raises(q.InvalidScanError) as info:
        q.AnalysisSettings(roi_size=roi_size)
    assert info.value.field == "roi_size"


def test_a_negative_detrend_order_cannot_be_constructed() -> None:
    """The order is a polynomial degree or a knot count; neither runs negative."""
    with pytest.raises(q.InvalidScanError) as info:
        q.AnalysisSettings(detrend_order=-1)
    assert info.value.field == "detrend_order"


def test_an_unresolved_or_constant_detrend_order_is_legal() -> None:
    """None is "the run has not resolved one yet"; 0 is a constant fit."""
    assert q.AnalysisSettings(detrend_order=None).detrend_order is None
    assert q.AnalysisSettings(detrend_order=0).detrend_order == 0


def test_a_valid_request_cannot_be_edited_into_an_impossible_one() -> None:
    """`replace` builds a new record, so the frozen copy is held to the same domain."""
    settings = q.AnalysisSettings(roi_size=9)
    with pytest.raises(q.InvalidScanError) as info:
        replace(settings, roi_size=0)
    assert info.value.field == "roi_size"


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


def test_an_explicit_pe_axis_is_not_refused_for_the_header_it_overrides() -> None:
    """Only the axis the run would measure on is held to in-plane.

    A header naming the through-plane axis is refused when it is the answer,
    and ignored when an explicit axis has already replaced it.
    """
    scan = q.QAScan(data=_flat_scan().data, tr=2.0, pe_axis=2)
    settings = q.AnalysisSettings(roi_size=5, pe_axis_override=0)
    assert q.run_qa(scan, settings).metrics.pe_axis == 0


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
