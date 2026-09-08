"""The scan-level metadata lines built from an artifact's provenance."""

import warnings
from dataclasses import replace

import numpy as np

import fmriqc as q
from fmriqc_report import summary


def _clipped(artifact: q.QAArtifact, **changes) -> q.QAArtifact:
    """The artifact with its saturation measurements overridden."""
    return replace(artifact, measurements=replace(artifact.measurements, **changes))


def test_acquisition_line_reports_the_geometry_and_settings(artifact) -> None:
    line = summary._acquisition_line(artifact)
    assert "TR 2s" in line
    assert "flip 77°" in line
    assert "3×3mm" in line and "32×32 px" in line
    assert f"{artifact.provenance.n_frames} frames" in line
    assert "PE col" in line
    assert "detrend poly (deg" in line  # the resolved order is shown


def test_acquisition_line_omits_absent_sidecar_fields(bare_artifact) -> None:
    """Without a sidecar the line degrades to what the header alone supports."""
    line = summary._acquisition_line(bare_artifact)
    assert "TR 2s" in line and "frames" in line
    assert "flip" not in line and "px" not in line and "mm slice" not in line


def test_clipping_in_the_analyzed_data_is_called_out(artifact) -> None:
    biased = _clipped(
        artifact,
        clipped_any=True,
        clipped_kept=True,
        n_clipped_kept=12,
        n_clipped_pre=3,
        clip_ceiling=4095.0,
        clip_bits=12,
    )
    line = summary._acquisition_line(biased)
    assert "CLIP 12 in analyzed data (+3 pre-SS) @ 4095 (12-bit)" in line


def test_clipping_confined_to_warm_up_is_reported_quietly(artifact) -> None:
    """Clips in the dropped volumes don't bias the metrics, so they don't shout."""
    warmup = _clipped(
        artifact,
        clipped_any=True,
        clipped_kept=False,
        n_clipped_kept=0,
        n_clipped_pre=7,
        clip_ceiling=4095.0,
        clip_bits=12,
    )
    line = summary._acquisition_line(warmup)
    assert "clip 7 pre-SS only @ 4095 (12-bit)" in line
    assert "CLIP" not in line


def test_a_clean_run_carries_no_clipping_note(artifact) -> None:
    assert summary._clipping_note(artifact) == ""


def test_device_and_provenance_lines_read_the_sidecar(artifact) -> None:
    prov = artifact.provenance
    assert summary._device_line(prov) == "Acme Scanner 3T   ·   3T"
    line = summary._provenance_line(prov)
    assert "SN 12345" in line and "2026-01-02 03:04:05" in line


def test_device_and_provenance_lines_are_empty_without_metadata(
    bare_artifact,
) -> None:
    prov = bare_artifact.provenance
    assert summary._device_line(prov) == ""
    assert summary._provenance_line(prov) == ""


def test_appendix_rows_name_the_computing_version(artifact) -> None:
    ((title, detail),) = summary._appendix_rows([("run-1", artifact)])
    assert title == "run-1"
    assert "Acme Scanner 3T" in detail
    assert f"computed by fmri-qa-core {artifact.provenance.core_version}" in detail


def test_appendix_accounts_for_a_scan_without_a_sidecar(bare_artifact) -> None:
    ((_, detail),) = summary._appendix_rows([("bare", bare_artifact)])
    assert "computed by fmri-qa-core" in detail  # still accounted for


def test_a_collapsed_phantom_mask_is_called_out(artifact) -> None:
    """A bad mask invalidates every mask-based number on the page.

    It has to say so on the acquisition line: the metrics themselves still look
    like ordinary measurements, so a reader has nothing else to go on. The
    verdict is the artifact's -- the bounds it was reached by live with the
    segmentation, in a package this one cannot import -- and the fraction beside
    it is what the reader is shown.
    """
    collapsed = _clipped(artifact, phantom_fraction=1.0, phantom_mask_ok=False)
    assert "BAD PHANTOM MASK (100% of frame)" in summary._acquisition_line(collapsed)


def test_acquisition_line_flags_an_analysis_of_background() -> None:
    """A noise-only scan's failed verdict reaches the page as the analysis made it.

    End to end rather than by overriding the field: the calculation half once
    warned that no slice held a phantom and then recorded the mask as good, and
    this is the page that would have shown ordinary-looking numbers for it.
    """
    noise = np.abs(np.random.default_rng(0).normal(size=(32, 32, 1, 40)))
    settings = q.AnalysisSettings(trim_sec=0, center="phantom", roi_size=3)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the analysis warns; the page is under test
        artifact = q.analyze(q.QAScan(data=noise, tr=2.0), settings)
    assert "BAD PHANTOM MASK" in summary._acquisition_line(artifact)


def test_an_off_phantom_roi_is_called_out(artifact) -> None:
    outside = _clipped(artifact, roi_inside_phantom=False)
    assert "ROI NOT INSIDE PHANTOM" in summary._acquisition_line(outside)


def test_a_well_localized_run_carries_no_localization_note(artifact) -> None:
    assert summary._localization_note(artifact) == ""


def test_an_unrecorded_localization_is_noted_without_alarm(artifact) -> None:
    """A migrated artifact predating the check is neither vouched for nor damned.

    The page must not read as though the checks were made and passed, but there
    is nothing to condemn either -- so it is stated plainly, in lower case, apart
    from the failures that are called out in capitals.
    """
    migrated = _clipped(artifact, phantom_mask_ok=None, roi_inside_phantom=None)
    assert summary._localization_note(migrated) == "localization not recorded"
