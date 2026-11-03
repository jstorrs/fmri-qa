"""`name_outputs`: the names `import_dicom` files dcm2niix's outputs under."""

import json

import pytest

from fmriqa_web import NameCollisionError, name_outputs

RAW = "dcm2niix_name"
SIDECAR = json.dumps(
    {
        "SeriesNumber": 2,
        "SeriesDescription": "QA_EPI_ISO",
        "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
    }
).encode()


def test_a_sidecar_gives_the_qa_name_to_every_file_of_the_series() -> None:
    files = {f"{RAW}.nii.gz": b"", f"{RAW}.json": SIDECAR, f"{RAW}.bval": b""}

    filed = name_outputs(files)

    qa = "20260909_143012_s002_QA_EPI_ISO"
    assert filed == {
        f"{RAW}.nii.gz": f"{qa}.nii.gz",
        f"{RAW}.json": f"{qa}.json",
        f"{RAW}.bval": f"{qa}.bval",
    }


def test_a_sidecar_that_is_not_utf8_keeps_the_dcm2niix_name() -> None:
    files = {"a.nii.gz": b"", "a.json": b"\xff\xfe{"}

    assert name_outputs(files) == {"a.nii.gz": "a.nii.gz", "a.json": "a.json"}


def test_a_series_without_a_sidecar_keeps_the_dcm2niix_name() -> None:
    assert name_outputs({"a.nii.gz": b""}) == {"a.nii.gz": "a.nii.gz"}


def test_a_file_belonging_to_no_nifti_is_left_out() -> None:
    assert name_outputs({"a.nii.gz": b"", "notes.txt": b""}) == {"a.nii.gz": "a.nii.gz"}


def test_a_file_taking_the_name_of_one_left_out_is_refused() -> None:
    qa = name_outputs({"a.nii.gz": b"", "a.json": SIDECAR})["a.json"]
    # A stray file already holds the name the sidecar would be filed under.
    files = {"a.nii.gz": b"", "a.json": SIDECAR, qa: b""}

    with pytest.raises(NameCollisionError) as raised:
        name_outputs(files)

    assert raised.value.collisions == {qa: (qa, "a.json")}
    assert qa in str(raised.value)


def test_a_path_is_refused_as_not_a_bare_filename() -> None:
    with pytest.raises(ValueError, match="bare filenames"):
        name_outputs({"dir/a.nii.gz": b""})


def test_two_filed_inputs_taking_one_name_are_refused() -> None:
    """`a` is filed as `<qa>`, so `a.x.json` becomes `<qa>.x.json`, which series
    `<qa>.x` already holds (it has no sidecar and keeps its own name)."""
    qa = "20260909_143012_s002_QA"
    sidecar = json.dumps(
        {
            "SeriesNumber": 2,
            "SeriesDescription": "QA",
            "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
        }
    ).encode()
    files = {
        "a.nii.gz": b"",
        "a.json": sidecar,
        "a.x.json": b"",
        f"{qa}.x.nii.gz": b"",
        f"{qa}.x.json": b"",
    }

    with pytest.raises(NameCollisionError) as raised:
        name_outputs(files)

    assert raised.value.collisions == {f"{qa}.x.json": ("a.x.json", f"{qa}.x.json")}
