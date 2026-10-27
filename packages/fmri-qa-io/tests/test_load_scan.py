"""The NIfTI loader's contract: spatial/TR units, and the optional BIDS sidecar.

Both concerns are file-I/O boundaries, so these use real files. The TR cases
matter because pixdim[4] has no unit of its own: a header in milliseconds must
still arrive in seconds, or the pipeline trims no warm-up and fits an absurd
detrend order. The sidecar cases pin that a NIfTI straight off the scanner still
analyzes, with a warning and empty acquisition metadata.

These build their own files instead of `fmriqa_io.testing.write_phantom`, which
always writes a sidecar at a 2 s TR.
"""

import json
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

import fmriqa as q
from fmriqa.hilo.compatibility import require_compatible_scans
from fmriqa_io import load_scan


def _write_scan(
    directory: Path,
    sidecar: dict | None = None,
    *,
    pixdim_t: float = 2.0,
    time_unit: str | None = None,
    phase: int | None = 1,
) -> Path:
    """Write a minimal 4-D NIfTI; write a sidecar only when one is given.

    Integer-stored, like `write_phantom`, so a float image does not add an unrelated
    "storage cannot support the saturation check" warning to each test.
    """
    data = np.ones((8, 8, 2, 6), dtype=np.uint16)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, pixdim_t))
    img.header.set_xyzt_units(xyz="mm")
    if time_unit is not None:
        img.header.set_xyzt_units(xyz="mm", t=time_unit)
    if phase is not None:
        img.header.set_dim_info(freq=None, phase=phase, slice=None)
    nifti = directory / "scan.nii.gz"
    nib.save(img, str(nifti))
    if sidecar is not None:
        (directory / "scan.json").write_text(json.dumps(sidecar))
    return nifti


@pytest.mark.parametrize(
    ("time_unit", "pixdim_t", "expected"),
    [
        ("sec", 2.0, 2.0),
        ("msec", 2000.0, 2.0),
        ("usec", 2_000_000.0, 2.0),
        (None, 2.0, 2.0),  # unlabeled pixdim is read as seconds
    ],
)
def test_header_tr_converts_by_its_time_unit(
    tmp_path, time_unit: str | None, pixdim_t: float, expected: float
) -> None:
    nifti = _write_scan(tmp_path, {}, pixdim_t=pixdim_t, time_unit=time_unit)
    assert load_scan(nifti).tr == pytest.approx(expected)


def test_sidecar_repetition_time_wins_over_the_header(tmp_path) -> None:
    # The header claims 3 s, the sidecar 2 s. BIDS fixes its unit, so the sidecar
    # wins, with a warning that one file describes a different acquisition.
    nifti = _write_scan(tmp_path, {"RepetitionTime": 2.0}, pixdim_t=3.0)
    with pytest.warns(UserWarning, match="disagrees"):
        scan = load_scan(nifti)
    assert scan.tr == pytest.approx(2.0)


def test_agreeing_sidecar_and_header_do_not_warn(tmp_path) -> None:
    # 2000 msec in the header is 2 s in the sidecar: the same acquisition.
    nifti = _write_scan(
        tmp_path, {"RepetitionTime": 2.0}, pixdim_t=2000.0, time_unit="msec"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert load_scan(nifti).tr == pytest.approx(2.0)


def test_empty_header_tr_disagrees_with_nothing(tmp_path) -> None:
    # A zeroed pixdim[4] makes no claim about the acquisition, so the sidecar
    # supplying the TR is not a disagreement.
    nifti = _write_scan(tmp_path, {"RepetitionTime": 2.0}, pixdim_t=0.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert load_scan(nifti).tr == pytest.approx(2.0)


def test_sidecar_without_repetition_time_falls_back_to_the_header(tmp_path) -> None:
    nifti = _write_scan(tmp_path, {"FlipAngle": 77}, pixdim_t=2500.0, time_unit="msec")
    assert load_scan(nifti).tr == pytest.approx(2.5)


@pytest.mark.parametrize("value", [0, -2.0, "2000", None, float("nan"), True])
def test_unusable_sidecar_repetition_time_falls_back_to_the_header(
    tmp_path, value: object
) -> None:
    nifti = _write_scan(tmp_path, {"RepetitionTime": value}, pixdim_t=2.0)
    with pytest.warns(UserWarning, match="ignoring sidecar RepetitionTime"):
        scan = load_scan(nifti)
    assert scan.tr == pytest.approx(2.0)


def test_meta_tr_is_the_tr_the_pipeline_runs_on(tmp_path) -> None:
    # The report header must not quote a TR the metrics were never computed at.
    nifti = _write_scan(tmp_path, {}, pixdim_t=2000.0, time_unit="msec")
    scan = load_scan(nifti)
    assert scan.meta is not None
    assert scan.meta.tr == scan.tr == pytest.approx(2.0)


def test_missing_sidecar_warns_and_still_loads(tmp_path) -> None:
    nifti = _write_scan(tmp_path, sidecar=None, phase=1)
    with pytest.warns(UserWarning, match="no BIDS JSON sidecar"):
        scan = load_scan(nifti)

    assert scan.pe_axis == 1  # from the header dim_info
    assert scan.tr == pytest.approx(2.0)
    assert scan.meta is not None
    # Geometry survives; everything the sidecar would have supplied is absent.
    assert scan.meta.matrix == (8, 8)
    assert scan.meta.pe_dir == "col"  # derived from the header axis
    assert scan.meta.te is None
    assert scan.meta.flip_angle is None
    assert scan.meta.slice_thickness is None
    assert scan.meta.manufacturer is None
    assert scan.meta.model is None
    assert scan.meta.serial is None
    assert scan.meta.coil is None
    assert scan.meta.field_strength is None
    assert scan.meta.software is None
    assert scan.meta.datetime is None
    assert scan.meta.series is None


def test_missing_sidecar_and_dim_info_leaves_the_axis_unresolved(tmp_path) -> None:
    # No sidecar and no dim_info: the loader has nothing to read, and warns
    # twice, for the absent sidecar and for the axis it leaves to the pipeline.
    nifti = _write_scan(tmp_path, sidecar=None, phase=None)
    with pytest.warns(UserWarning) as caught:
        scan = load_scan(nifti)

    messages = [str(warning.message) for warning in caught]
    assert any("no BIDS JSON sidecar" in message for message in messages)
    assert any("estimate it from the Nyquist ghost" in message for message in messages)
    assert scan.pe_axis is None  # for `run_qa` to estimate on the analyzed slice


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("EchoTime", "0.03", "te"),  # a number written as text
        ("FlipAngle", True, "flip_angle"),  # JSON true is not an angle
        ("SliceThickness", [3.0], "slice_thickness"),
        ("MagneticFieldStrength", float("nan"), "field_strength"),
        ("Manufacturer", {"name": "Acme"}, "manufacturer"),
        ("SeriesDescription", ["qa"], "series"),
    ],
)
def test_a_malformed_sidecar_field_is_unknown_and_named(
    tmp_path, key: str, value: object, field: str
) -> None:
    """A field of the wrong type is dropped with a warning naming it, at load.

    These fields only describe the acquisition, so a bad one must not stop the
    analysis, but it must not be copied through either. A string where the
    schema promises a number saves fine and fails when the report opens it,
    months later and far from the sidecar. The value is not coerced: "0.03" may
    be 30 ms, but deciding so is guessing. fmri-qa-io's
    `test_artifact_roundtrip.py` checks that what it produces reads back.
    """
    nifti = _write_scan(tmp_path, {"PhaseEncodingDirection": "j", key: value})
    with pytest.warns(UserWarning, match=f"sidecar {key} .* recording it as unknown"):
        scan = load_scan(nifti)
    assert scan.meta is not None
    assert getattr(scan.meta, field) is None


def test_a_numeric_serial_number_is_kept_as_text(tmp_path) -> None:
    """A serial written unquoted is still a serial. Only bad structure is refused."""
    nifti = _write_scan(tmp_path, {"DeviceSerialNumber": 12345, "EchoTime": 0.03})
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # nothing here is malformed
        scan = load_scan(nifti)
    assert scan.meta is not None
    assert scan.meta.serial == "12345"
    assert scan.meta.te == 0.03


def test_a_numeric_acquisition_date_is_kept_as_text(tmp_path) -> None:
    """A date written unquoted is still a date; it must not crash the join."""
    nifti = _write_scan(
        tmp_path, {"AcquisitionDate": 20260909, "AcquisitionTime": "14:30:12.500000"}
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # nothing here is malformed
        scan = load_scan(nifti)
    assert scan.meta is not None
    assert scan.meta.datetime == "20260909 14:30:12"


def test_missing_nifti_fails_on_the_nifti_not_the_sidecar(tmp_path) -> None:
    # The sidecar warning would be noise when the image itself is not there.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(FileNotFoundError):
            load_scan(tmp_path / "absent.nii.gz")


def test_unparseable_sidecar_is_an_error(tmp_path) -> None:
    nifti = _write_scan(tmp_path, {})
    (tmp_path / "scan.json").write_text("{not json at all")
    with pytest.raises(q.InvalidScanError, match="BIDS JSON sidecar") as info:
        load_scan(nifti)
    assert info.value.value == str(tmp_path / "scan.json")


def test_sidecar_that_is_not_an_object_is_an_error(tmp_path) -> None:
    nifti = _write_scan(tmp_path, {})
    (tmp_path / "scan.json").write_text("[1, 2, 3]")
    with pytest.raises(q.InvalidScanError, match="JSON object"):
        load_scan(nifti)


def test_rejects_a_three_dimensional_nifti(tmp_path) -> None:
    img = nib.Nifti1Image(np.ones((8, 8, 2), dtype=np.float32), affine=np.eye(4))
    nifti = tmp_path / "scan.nii.gz"
    nib.save(img, str(nifti))
    with pytest.raises(q.InvalidScanError, match="data shape"):
        load_scan(nifti)


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("slope,inter", [(1, 0), (2, 10), (-2, 10000)])
def test_loaded_scaling_preserves_clipping_and_dead_edges(
    tmp_path, compressed, slope, inter
) -> None:
    raw = np.full((8, 8, 3, 8), 100, dtype=np.int16)
    raw[0] = 0
    raw[4, 4, 1, 3] = 4095
    img = nib.Nifti1Image(raw, np.eye(4))
    img.header.set_zooms((3, 3, 3, 2))
    img.header.set_xyzt_units("mm", "sec")
    img.header.set_slope_inter(slope, inter)
    path = tmp_path / ("scaled.nii.gz" if compressed else "scaled.nii")
    nib.save(img, path)
    (tmp_path / "scaled.json").write_text('{"PhaseEncodingDirection": "j"}')

    scan = load_scan(path)
    assert (scan.slope, scan.inter) == (slope, inter)
    assert np.array_equal(scan.data, raw.astype(float) * slope + inter)
    saturation = q.detect_saturation(scan.data, slope=scan.slope, inter=scan.inter)
    assert saturation.n_clipped == 1 and saturation.bits == 12
    assert saturation.ceiling == 4095 * slope + inter
    images = q.preprocess(scan, q.AnalysisSettings(trim_sec=0))
    assert not images.valid_mask[0].any()
    assert images.valid_mask[1:].all()


def _spatial_affine_mm() -> np.ndarray:
    """A rotated, translated grid with unequal voxel sizes of 2, 3 and 4 mm."""
    return np.array(
        [
            [1.2, -2.4, 0, 12.5],
            [1.6, 1.8, 0, -7.25],
            [0, 0, 4, 25],
            [0, 0, 0, 1],
        ]
    )


def _write_spatial_scan(path: Path, affine_mm: np.ndarray, unit: str) -> Path:
    """Encode matching zooms and world coordinates in the declared unit."""
    factor = {"mm": 1, "meter": 1000, "micron": 0.001, "unknown": 1}[unit]
    affine = affine_mm.copy()
    affine[:3, :] /= factor
    data = np.arange(8 * 8 * 2 * 6, dtype=np.uint16).reshape((8, 8, 2, 6))
    img = nib.Nifti1Image(data, affine)
    img.header.set_zooms((*img.header.get_zooms()[:3], 2))
    img.header.set_xyzt_units(unit, "sec")
    nib.save(img, path)
    path.with_suffix(".json").write_text('{"PhaseEncodingDirection": "j"}')
    return path


@pytest.mark.parametrize("unit", ["mm", "meter", "micron"])
def test_spatial_units_are_converted_to_mm(tmp_path, unit) -> None:
    affine_mm = _spatial_affine_mm()
    path = _write_spatial_scan(tmp_path / "units.nii", affine_mm, unit)
    reference_path = _write_spatial_scan(tmp_path / "reference.nii", affine_mm, "mm")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scan = load_scan(path)
        reference = load_scan(reference_path)

    assert scan.meta.voxel_mm == pytest.approx((2, 3, 4))
    np.testing.assert_allclose(scan.affine, affine_mm, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(scan.affine[3], [0, 0, 0, 1])
    np.testing.assert_array_equal(scan.data, reference.data)
    assert scan.tr == reference.tr == 2
    require_compatible_scans(scan, reference)
    if unit == "mm":
        np.testing.assert_array_equal(scan.affine, nib.load(path).affine)


@pytest.mark.parametrize("unit", ["mm", "meter", "micron"])
@pytest.mark.parametrize("difference", ["translation", "orientation"])
def test_converted_spatial_units_still_reject_different_geometry(
    tmp_path, unit, difference
) -> None:
    affine_mm = _spatial_affine_mm()
    high_path = _write_spatial_scan(tmp_path / "high.nii", affine_mm, "mm")
    if difference == "translation":
        affine_mm[0, 3] += 1
    else:
        affine_mm[:3, 0] *= -1
    low_path = _write_spatial_scan(tmp_path / "low.nii", affine_mm, unit)
    high = load_scan(high_path)
    low = load_scan(low_path)

    assert low.meta.voxel_mm == pytest.approx(high.meta.voxel_mm)
    with pytest.raises(q.IncompatibleScansError) as info:
        require_compatible_scans(high, low)
    assert info.value.field == "affine"


def test_unknown_spatial_units_warn_and_assume_mm(tmp_path) -> None:
    affine_mm = _spatial_affine_mm()
    path = _write_spatial_scan(tmp_path / "unknown.nii", affine_mm, "unknown")
    with pytest.warns(
        UserWarning, match="spatial unit is unknown; assuming millimeters"
    ) as caught:
        scan = load_scan(path)
    assert len(caught) == 1
    assert scan.meta.voxel_mm == pytest.approx((2, 3, 4))
    np.testing.assert_array_equal(scan.affine, nib.load(path).affine)
    np.testing.assert_allclose(scan.affine, affine_mm, rtol=1e-6, atol=1e-6)


def test_float_storage_warns_and_is_recorded_on_the_scan(tmp_path) -> None:
    """A float NIfTI loads, but says the ADC samples are gone.

    The saturation check needs integer samples to see whether the acquisition
    piled up on a hardware rail. A converter that rescaled into floats threw
    that away. The warning names the fix, reconverting with the datatype
    preserved, since otherwise a receiver-gain problem goes unreported.
    """
    data = np.ones((8, 8, 2, 6), dtype=np.float32)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    img.header.set_xyzt_units(xyz="mm", t="sec")
    img.header.set_dim_info(freq=None, phase=1, slice=None)
    nifti = tmp_path / "scan.nii.gz"
    nib.save(img, str(nifti))
    (tmp_path / "scan.json").write_text(json.dumps({"PhaseEncodingDirection": "j"}))

    with pytest.warns(UserWarning, match="not an integer type"):
        scan = load_scan(nifti)
    assert scan.stored_integer is False


def test_integer_storage_is_recorded_without_a_warning(tmp_path) -> None:
    nifti = _write_scan(tmp_path, {"PhaseEncodingDirection": "j"})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scan = load_scan(nifti)
    assert scan.stored_integer is True
