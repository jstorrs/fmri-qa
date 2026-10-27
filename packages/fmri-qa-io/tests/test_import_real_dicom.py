"""The real converter, on real DICOM.

The stub dcm2niix cannot show that the pinned flags produce a series the
saturation check can read, or that names come from each series' own times.
Needs the bundled binary and the committed fixture study.
"""

from pathlib import Path

import pytest

from fmriqa_io import ImportResult, load_scan
from fmriqa_io.convert.dcm2niix import find_dcm2niix
from fmriqa_io.convert.session import import_dicom

FIXTURE_STUDY = Path(__file__).parent / "fixtures" / "dicom"


def test_a_real_study_converts_to_the_integer_nifti_the_metrics_need(
    tmp_path,
) -> None:
    """The pinned `-l o` keeps the scanner's integers.

    `detect_saturation` needs the scanner's integers, and `QAScan.stored_integer`
    reads that from the NIfTI datatype. A future dcm2niix or a stray
    `~/.dcm2nii.ini` could write floats or rescale, silently disabling the
    saturation check for every import.

    See `fixtures/dicom/generate.py` for the synthetic study: two series
    numbered 2 and 11, one with a description that needs sanitizing.
    """
    nibabel = pytest.importorskip("nibabel")
    out = tmp_path / "nifti"

    result = import_dicom(FIXTURE_STUDY, out, binary=find_dcm2niix())

    assert [entry.path.name for entry in result.series] == [
        "20260909_143012_s002_QA_EPI_ISO.nii.gz",
        "20260909_145533_s011_QA_EPI_32ch_rep.nii.gz",
    ]
    for entry in result.series:
        scan = nibabel.load(entry.path)
        assert scan.header.get_data_dtype().kind in "iu"  # the saturation gate
        assert scan.dataobj.slope == 1.0  # not rescaled on the way through
        assert load_scan(entry.path).stored_integer


def test_the_real_study_is_named_by_its_own_series_times_not_the_study_s(
    tmp_path,
) -> None:
    """dcm2niix's `%t` is the study's time, identical for both series.

    The fixture gives the two series distinct `SeriesTime`s under one
    `StudyTime`. A name templated on `%t` cannot tell them apart, but one built
    from the sidecar can. That is why `convert.naming` exists.
    """
    templated = import_dicom(
        FIXTURE_STUDY, tmp_path / "raw", binary=find_dcm2niix(), names="dcm2niix"
    )
    named = import_dicom(FIXTURE_STUDY, tmp_path / "qa", binary=find_dcm2niix())

    study_times = {name.split("_")[0] for name in _stems(templated)}
    series_times = {stem.split("_")[1] for stem in _stems(named)}
    assert len(study_times) == 1  # `%t`: one time for the whole session
    assert len(series_times) == 2  # the sidecar: one time per series


def _stems(result: ImportResult) -> list[str]:
    return [entry.path.name.split(".")[0] for entry in result.series]


def test_the_committed_fixture_study_is_still_there() -> None:
    """A missing fixture must fail, not read as a passing import."""
    assert len(list(FIXTURE_STUDY.rglob("*.dcm"))) == 8
