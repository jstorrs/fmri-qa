"""The scan-level metadata lines built from an analysis's provenance."""

import warnings
from dataclasses import replace

import numpy as np

import fmriqa as q
from fmriqa_report import summary


def _clipped(analysis: q.QAAnalysis, **changes) -> q.QAAnalysis:
    """Return the analysis with some of its measurements overridden."""
    return replace(analysis, measurements=replace(analysis.measurements, **changes))


def test_acquisition_line_reports_the_geometry_and_settings(analysis) -> None:
    line = summary.acquisition_line(analysis)
    assert "TR 2s" in line
    assert "flip 77°" in line
    assert "3×3mm" in line and "32×32 px" in line
    assert f"{analysis.provenance.n_frames} frames" in line
    assert "slice index 1/3" in line  # the plane analyzed, as the analysis stores it
    assert "PE col" in line
    assert "detrend poly (deg" in line  # the resolved order is shown


def test_acquisition_line_omits_absent_sidecar_fields(bare_analysis) -> None:
    """Without a sidecar the line degrades to what the header alone supports."""
    line = summary.acquisition_line(bare_analysis)
    assert "TR 2s" in line and "frames" in line
    assert "flip" not in line and "px" not in line and "mm slice" not in line


def test_clipping_in_the_analyzed_data_is_called_out(analysis) -> None:
    biased = _clipped(
        analysis,
        clipped_any=True,
        clipped_kept=True,
        n_clipped_kept=12,
        n_clipped_pre=3,
        clip_ceiling=4095.0,
        clip_bits=12,
    )
    assert "CLIP" not in summary.acquisition_line(biased)
    line = summary.acquisition_notes(biased)
    assert "CLIP 12 in analyzed data (+3 pre-SS) @ 4095 (12-bit)" in line


def test_clipping_confined_to_warm_up_is_reported_quietly(analysis) -> None:
    """Clips in the dropped volumes don't bias the metrics, so they don't shout."""
    warmup = _clipped(
        analysis,
        clipped_any=True,
        clipped_kept=False,
        n_clipped_kept=0,
        n_clipped_pre=7,
        clip_ceiling=4095.0,
        clip_bits=12,
    )
    line = summary.acquisition_notes(warmup)
    assert "clip 7 pre-SS only @ 4095 (12-bit)" in line
    assert "CLIP" not in line


def test_a_clean_run_carries_no_clipping_note(analysis) -> None:
    assert summary._clipping_note(analysis) == ""


def test_device_and_provenance_lines_read_the_sidecar(analysis) -> None:
    prov = analysis.provenance
    assert summary.device_line(prov) == "Acme Scanner 3T   ·   3T"
    line = summary.provenance_line(prov)
    assert "SN 12345" in line and "2026-01-02 03:04:05" in line


def test_device_and_provenance_lines_are_empty_without_metadata(
    bare_analysis,
) -> None:
    prov = bare_analysis.provenance
    assert summary.device_line(prov) == ""
    assert summary.provenance_line(prov) == ""


def test_a_collapsed_phantom_mask_is_called_out(analysis) -> None:
    """A bad mask invalidates every mask-based number on the page.

    The notes block has to say so, since the metrics still look like ordinary
    measurements. The verdict is the analysis's, because the bounds it was
    judged by live with the segmentation, in a package this one cannot import.
    The fraction beside it is what the reader is shown.
    """
    collapsed = _clipped(analysis, phantom_fraction=1.0, phantom_mask_ok=False)
    assert "BAD PHANTOM MASK (100% of frame" in summary.acquisition_notes(collapsed)


def test_a_bad_mask_note_shows_the_contrast_when_the_analysis_has_it(analysis) -> None:
    """The note shows which test the mask failed.

    A collapse shows in the share, noise in the contrast. An analysis migrated
    from before the contrast was recorded shows the share alone, not a NaN.
    """
    noisy = _clipped(
        analysis, phantom_fraction=0.54, phantom_contrast=1.7, phantom_mask_ok=False
    )
    assert "(54% of frame, 1.7× contrast)" in summary.acquisition_notes(noisy)
    migrated = _clipped(noisy, phantom_contrast=float("nan"))
    assert "(54% of frame)" in summary.acquisition_notes(migrated)


def test_acquisition_notes_flag_an_analysis_of_background() -> None:
    """A noise-only scan's failed verdict reaches the page unchanged.

    This runs end to end instead of overriding the field. The calculation half
    once warned that no slice held a phantom yet recorded the mask as good, and
    this page showed ordinary-looking numbers for it.
    """
    noise = np.abs(np.random.default_rng(0).normal(size=(32, 32, 1, 40)))
    settings = q.AnalysisSettings(trim_sec=0, center="phantom", roi_size=3)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the analysis warns; the page is under test
        analysis = q.analyze(q.QAScan(data=noise, tr=2.0), settings)
    assert "BAD PHANTOM MASK" in summary.acquisition_notes(analysis)
    assert "× contrast" in summary.acquisition_notes(analysis)


def test_an_off_phantom_roi_is_called_out(analysis) -> None:
    outside = _clipped(analysis, roi_inside_phantom=False)
    assert "ROI NOT INSIDE PHANTOM" in summary.acquisition_notes(outside)


def test_a_well_localized_run_carries_no_localization_note(analysis) -> None:
    assert summary._localization_note(analysis) == ""


def test_an_unrecorded_localization_is_noted_without_alarm(analysis) -> None:
    """A migrated analysis predating the check is neither vouched for nor damned.

    The page must not read as though the checks passed, and there is nothing to
    condemn, so it says so in lower case, apart from the failures in capitals.
    """
    migrated = _clipped(analysis, phantom_mask_ok=None, roi_inside_phantom=None)
    assert summary._localization_note(migrated) == "localization not recorded"
