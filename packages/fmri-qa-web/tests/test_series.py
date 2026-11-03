"""`analyze_series`: a series' report, or its failure as a value."""

import warnings

import pytest

import fmriqa
from fmriqa import AnalysisSettings
from fmriqa.analysis.record import metric_record
from fmriqa.validation import MIN_ANALYSIS_FRAMES
from fmriqa_io.decode import scan_from_bytes
from fmriqa_web import SeriesFailure, SeriesReport, analyze_series

# The 32-pixel phantom is too small for the default 21x21 ROI to fit its disc.
_SMALL_ROI = AnalysisSettings(roi_size=9)


def _NO_SIDECAR_WARNINGS(stem: str) -> tuple[str, str]:
    return (
        f"{stem}.nii.gz: no BIDS JSON sidecar found beside the NIfTI; the "
        "acquisition metadata, including the sidecar phase-encode direction and "
        "TR, will be absent",
        f"{stem}.nii.gz: no phase-encode axis in sidecar or NIfTI dim_info; the "
        "pipeline will estimate it from the Nyquist ghost. Pass --pe-axis to "
        "name the acquisition's direction instead.",
    )


def test_a_phantom_gives_the_record_the_cli_would_write(phantom_bytes) -> None:
    nifti, sidecar = phantom_bytes

    result = analyze_series(nifti, sidecar, stem="phantom", settings=_SMALL_ROI)

    scan = scan_from_bytes(
        nifti, sidecar, name="phantom.nii.gz", sidecar_name="phantom.json"
    )
    artifact = fmriqa.analyze(
        scan, _SMALL_ROI, name="phantom.nii.gz", source="phantom.nii.gz"
    )
    assert isinstance(result, SeriesReport)
    assert result.record == metric_record(artifact)
    assert result.stem == "phantom"
    assert result.warnings == ()


def test_the_page_is_titled_by_the_stem_and_carries_no_script(phantom_bytes) -> None:
    result = analyze_series(*phantom_bytes, stem="my_series", settings=_SMALL_ROI)

    assert isinstance(result, SeriesReport)
    assert "<title>my_series" in result.html
    assert "<script" not in result.html


def test_a_missing_sidecar_is_a_warning_not_a_failure(phantom_bytes) -> None:
    result = analyze_series(phantom_bytes[0], None, stem="bare", settings=_SMALL_ROI)

    assert isinstance(result, SeriesReport)
    assert result.warnings == _NO_SIDECAR_WARNINGS("bare")


def test_a_scan_below_the_frame_minimum_fails_at_analyze(short_phantom_bytes) -> None:
    result = analyze_series(short_phantom_bytes, None, stem="short")

    assert isinstance(result, SeriesFailure)
    assert result.stem == "short"
    assert result.stage == "analyze"
    assert result.reason == (
        f"invalid frame count 2: expected at least {MIN_ANALYSIS_FRAMES} frame(s)"
    )


def test_undecodable_bytes_fail_at_decode() -> None:
    result = analyze_series(b"not a nifti", None, stem="junk")

    assert isinstance(result, SeriesFailure)
    assert result.stage == "decode"
    assert result.reason == (
        "invalid NIfTI 'junk.nii.gz': not a single-file NIfTI-1 or NIfTI-2 image"
    )


def test_a_failure_with_an_empty_message_names_its_type(monkeypatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError

    monkeypatch.setattr("fmriqa_web.series.scan_from_bytes", boom)

    result = analyze_series(b"", None, stem="x")

    assert result == SeriesFailure("x", "decode", "RuntimeError", ())


def test_a_render_failure_is_a_value_and_keeps_the_warnings(
    phantom_bytes, monkeypatch
) -> None:
    def boom(*args: object, **kwargs: object) -> str:
        raise ValueError("no figure")

    monkeypatch.setattr("fmriqa_web.series.render_run_page", boom)

    result = analyze_series(phantom_bytes[0], None, stem="r", settings=_SMALL_ROI)

    assert isinstance(result, SeriesFailure)
    assert (result.stage, result.reason) == ("render", "no figure")
    assert result.warnings == _NO_SIDECAR_WARNINGS("r")  # survives a later failure


def test_the_callers_warning_filters_are_restored(phantom_bytes) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = analyze_series(*phantom_bytes, stem="p", settings=_SMALL_ROI)
        assert warnings.filters[0][0] == "error"
    assert isinstance(result, SeriesReport)


@pytest.mark.parametrize("stem", ["a", "20260909_143012_s002_QA_EPI_ISO"])
def test_the_record_names_the_scan_by_its_stem(phantom_bytes, stem: str) -> None:
    result = analyze_series(*phantom_bytes, stem=stem, settings=_SMALL_ROI)

    assert isinstance(result, SeriesReport)
    assert result.record["scan"] == f"{stem}.nii.gz"
    assert result.record["source"] == f"{stem}.nii.gz"
