"""The real converter, on real DICOM.

The one place the stub dcm2niix cannot answer: whether the pinned flags actually
produce a series the saturation check can read, and whether the names come from
each series' own times. Needs the bundled binary and the committed fixture study.
"""

from pathlib import Path

import pytest

import fmriqc as q
from fmriqc.convert.dcm2niix import find_dcm2niix
from fmriqc.convert.session import import_dicom

FIXTURE_STUDY = Path(__file__).parent / "fixtures" / "dicom"


def test_a_real_study_converts_to_the_integer_nifti_the_metrics_need(
    tmp_path,
) -> None:
    """The end the stub cannot reach: does the pinned `-l o` actually hold?

    `detect_saturation` can only find an ADC rail in a series that still carries
    the scanner's integers, and `QAScan.stored_integer` decides that from the
    NIfTI datatype. If a future dcm2niix, or a stray `~/.dcm2nii.ini`, made the
    conversion write floats or rescale, every imported series would silently
    become one the saturation check declines to answer -- so the datatype is
    asserted here rather than assumed.

    See `fixtures/dicom/generate.py` for the synthetic study: two series
    numbered 2 and 11, one of them with a description that needs sanitizing.
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
        assert q.QAScan.from_nifti(entry.path).stored_integer


def test_the_real_study_is_named_by_its_own_series_times_not_the_study_s(
    tmp_path,
) -> None:
    """dcm2niix's `%t` is the study's time, identical for both series.

    The fixture gives the two series distinct `SeriesTime`s under one
    `StudyTime`, so a name templated on `%t` cannot tell them apart in time and
    a name built from the sidecar can. That difference is the reason
    `convert.naming` exists, so it is checked against the real converter.
    """
    templated = import_dicom(
        FIXTURE_STUDY, tmp_path / "raw", binary=find_dcm2niix(), names="dcm2niix"
    )
    named = import_dicom(FIXTURE_STUDY, tmp_path / "qa", binary=find_dcm2niix())

    study_times = {name.split("_")[0] for name in _stems(templated)}
    series_times = {stem.split("_")[1] for stem in _stems(named)}
    assert len(study_times) == 1  # `%t`: one time for the whole session
    assert len(series_times) == 2  # the sidecar: one time per series


def _stems(result: q.ImportResult) -> list[str]:
    return [entry.path.name.split(".")[0] for entry in result.series]


def test_the_committed_fixture_study_is_still_there() -> None:
    """Guard the guard: a vanished fixture must not read as a passing import."""
    assert len(list(FIXTURE_STUDY.rglob("*.dcm"))) == 8
