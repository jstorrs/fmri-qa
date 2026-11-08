"""The published JSON record: per-scan metrics and the document envelope.

`fmri-qa --json` writes `record_document`; the command's end-to-end test lives
in fmri-qa-cli. These tests pin the record's contract without running a command.
"""

import json
import math
import subprocess
import sys
from dataclasses import replace

import fmriqa as q
from fmriqa.analysis.record import (
    JSON_SCHEMA_VERSION,
    config_record,
    metric_record,
    record_document,
)


def test_json_record_maps_undefined_metrics_to_null(analysis) -> None:
    """A NaN measurement becomes `null`, not Python's non-standard `NaN` token.

    The NaN is injected, since an undefined metric is an estimator outcome the
    record has to survive, and relying on whichever metric happens to be NaN on
    the fixture would tie the test to its geometry.
    """
    undefined = replace(
        analysis.measurements, ghost_pct=float("nan"), sfnr=float("inf")
    )
    record = metric_record(replace(analysis, measurements=undefined))
    assert record["ghost_pct"] is None
    assert record["sfnr"] is None
    assert record["snr"] == analysis.measurements.snr  # finite values pass through


def test_json_record_leaves_an_unnamed_direction_null(analysis) -> None:
    """No phase-encode axis means no PE or RO number -- not the combined one.

    `fwhm` is the geometric mean of both axes. Publishing it as `fw_pe` would file
    a different quantity under that name, unnoticed by a trend database. The
    combined value rides along under its own key.
    """
    unnamed = replace(
        analysis.measurements,
        pe_axis=None,
        pe_label="?",
        fwhm_pe=None,
        fwhm_ro=None,
    )
    record = metric_record(replace(analysis, measurements=unnamed))
    assert record["fw_pe"] is None
    assert record["fw_ro"] is None
    assert record["fwhm"] == analysis.measurements.fwhm
    assert record["fwhm_unit"] == "mm"


def test_json_record_carries_the_displacement_unit(analysis) -> None:
    """`motn`/`com` carry their unit the same way `fwhm`/`fwhm_unit` do.

    `motn` is left loose against NaN-as-null (see
    `test_json_record_maps_undefined_metrics_to_null`): the motion fit does not
    converge for every frame on this fixture, so `max_translation` is NaN and the
    record maps it to `null`.
    """
    m = analysis.measurements
    record = metric_record(analysis)
    assert record["motn"] == (
        None if math.isnan(m.max_translation) else m.max_translation
    )
    assert record["com"] == m.max_com_displacement
    assert record["displacement_unit"] == "mm"  # the fixture's voxel size is known


def test_record_document_has_the_published_envelope(analysis) -> None:
    settings = q.AnalysisSettings(roi_size=9, trim_sec=4.0)
    scans = [metric_record(analysis)]
    errors = [{"scan": "bad.nii.gz", "source": "dir/bad.nii.gz", "error": "boom"}]
    requested = ("dir/scan.nii.gz", "dir/bad.nii.gz")
    doc = record_document(settings, requested, scans, errors)
    assert list(doc) == ["schema_version", "config", "requested", "scans", "errors"]
    assert doc["schema_version"] == JSON_SCHEMA_VERSION == 6
    assert doc["config"] == config_record(settings)
    assert doc["requested"] == ["dir/scan.nii.gz", "dir/bad.nii.gz"]
    assert doc["scans"] == scans
    assert doc["errors"] == errors
    # Strict JSON: undefined metrics are already null, so NaN would raise here.
    assert json.loads(json.dumps(doc, allow_nan=False)) == doc


def test_record_document_returns_fresh_lists(analysis) -> None:
    scans = [metric_record(analysis)]
    doc = record_document(q.AnalysisSettings(), ["a"], scans, [])
    assert doc["scans"] is not scans
    scans.clear()
    assert len(doc["scans"]) == 1  # type: ignore[arg-type]


def test_config_record_echoes_the_run_parameters() -> None:
    settings = q.AnalysisSettings(roi_size=9, trim_sec=4.0)
    assert config_record(settings) == {
        "version": q.core_version(),
        "detrend": settings.detrend,
        "trim_sec": 4.0,
        "center": settings.center,
        "roi_size": 9,
        "pe_axis_override": settings.pe_axis_override,
    }


def test_importing_the_record_does_not_load_the_pipeline() -> None:
    code = (
        "import sys, fmriqa.analysis.record\n"
        "print('fmriqa.analysis.build' in sys.modules or 'scipy' in sys.modules"
        " or 'skimage' in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False", result.stdout + result.stderr
