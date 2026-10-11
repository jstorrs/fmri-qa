"""The per-metric catalog: one source for every metric's label and format."""

import dataclasses
import math
from dataclasses import replace

from fmriqc.analysis import Measurements
from fmriqc_report import content


def test_metric_docs_keep_their_existing_labels_order_and_formatting(artifact) -> None:
    m = artifact.measurements
    assert [(d.label, d.number(m), d.unit_for(m)) for d in content.METRIC_DOCS] == [
        ("SNR", f"{m.snr:.1f}", ""),
        ("SFNR", f"{m.sfnr:.1f}", ""),
        ("RDC", f"{m.rdc:.2f}", ""),
        ("ghost", f"{m.ghost_pct:.2f}", "%"),
        ("ghostT", f"{m.ghost_top_pct:.2f}", "%"),
        ("RO", f"{m.ro_ghost_pct:.2f}", "%"),
        ("ACRg", f"{m.acr_ghost_pct:.2f}", "%"),
        ("drift", f"{m.drift_pct:.3f}", "%"),
        ("fluct", f"{m.percent_fluctuation:.3f}", "%"),
        ("outl", f"{m.outlier_max_pct:.2f}", "%"),
        ("tcOut", f"{m.tc_outlier:.1f}", ""),
        ("spec", f"{m.spec_outlier:.1f}", ""),
        ("motn", f"{m.max_translation:.2f}", m.displacement_unit),
        ("com", f"{m.max_com_displacement:.2f}", m.displacement_unit),
        ("fwhm", f"{m.fwhm:.2f}", m.fwhm_unit),
    ]


def test_every_metric_name_is_a_measurements_field() -> None:
    fields = {f.name for f in dataclasses.fields(Measurements)}
    assert {doc.name for doc in content.METRIC_DOCS} <= fields


def test_metric_names_are_stable_unique_measurement_fields() -> None:
    names = tuple(doc.name for doc in content.METRIC_DOCS)
    assert names == (
        "snr",
        "sfnr",
        "rdc",
        "ghost_pct",
        "ghost_top_pct",
        "ro_ghost_pct",
        "acr_ghost_pct",
        "drift_pct",
        "percent_fluctuation",
        "outlier_max_pct",
        "tc_outlier",
        "spec_outlier",
        "max_translation",
        "max_com_displacement",
        "fwhm",
    )
    assert len(names) == len(set(names))


def test_metric_value_accessors_return_raw_measurement_values(artifact) -> None:
    sentinel_values = {
        "snr": 1.0,
        "sfnr": 2.0,
        "rdc": 3.0,
        "ghost_pct": 4.0,
        "ghost_top_pct": 5.0,
        "ro_ghost_pct": 6.0,
        "acr_ghost_pct": 7.0,
        "drift_pct": 8.0,
        "percent_fluctuation": 9.0,
        "outlier_max_pct": 10.0,
        "tc_outlier": 11.0,
        "spec_outlier": 12.0,
        "max_translation": 13.0,
        "max_com_displacement": 14.0,
        "fwhm": 15.0,
    }
    measurements = replace(artifact.measurements, **sentinel_values)
    values = {doc.name: doc.value(measurements) for doc in content.METRIC_DOCS}
    assert values == sentinel_values


def test_metric_value_accessors_keep_unresolved_values_nonfinite(artifact) -> None:
    measurements = replace(artifact.measurements, ghost_pct=float("nan"))
    ghost = next(doc for doc in content.METRIC_DOCS if doc.name == "ghost_pct")
    assert math.isnan(ghost.value(measurements))


def test_methods_describe_the_implemented_order_of_operations() -> None:
    """The catalog's method text must name what the code does, not a synonym.

    SFNR averages voxelwise ratios (the ROI-mean form is `fluct`), the ghost
    denominator is the matched signal region, and ACRg is an absolute
    difference. Each once read as the other textbook form.
    """
    by_label = {doc.label: doc for doc in content.METRIC_DOCS}
    assert "per voxel" in by_label["SFNR"].method
    assert "ROI mean of those ratios" in by_label["SFNR"].method
    assert "ROI-mean series" in by_label["fluct"].method
    assert "matched signal region" in by_label["ghost"].method
    assert "|ghost - RO|" in by_label["ACRg"].method
    assert "at the full ROI" in by_label["RDC"].method


def test_every_metric_doc_is_documented(artifact) -> None:
    m = artifact.measurements
    for doc in content.METRIC_DOCS:
        assert doc.label and doc.definition and doc.method
        assert doc.number(m)  # the number is a non-empty string


def test_outlier_method_describes_threshold_tuning() -> None:
    method = next(doc.method for doc in content.METRIC_DOCS if doc.label == "outl")
    assert "qthr tunes a length-dependent threshold" in method
    assert "not an expected per-frame outlier fraction" in method
    assert "chance level" not in method


def test_motn_and_com_tiles_carry_the_displacement_unit(
    artifact, bare_artifact
) -> None:
    """`motn` and `com` render their unit the way `fwhm` does.

    `artifact` has a known voxel size and reports mm. `bare_artifact` has no
    sidecar metadata and falls back to voxels, the "mm when known, else voxels"
    rule `_fwhm_unit` applies, read off `displacement_unit`.
    """
    by_label = {doc.label: doc for doc in content.METRIC_DOCS}
    m = artifact.measurements
    assert by_label["motn"].unit_for(m) == "mm"
    assert by_label["com"].unit_for(m) == "mm"

    bare = bare_artifact.measurements
    assert by_label["motn"].unit_for(bare) == "vox"
    assert by_label["com"].unit_for(bare) == "vox"
