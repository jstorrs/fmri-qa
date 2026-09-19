"""The versioned static-report summary is a pure projection of an artifact."""

import json
from dataclasses import replace

import pytest

from fmriqc.analysis import ARTIFACT_SCHEMA_VERSION
from fmriqc_report.content import METRIC_DOCS
from fmriqc_report.web_summary import (
    OmittedInput,
    RenderedRun,
    build_web_summary,
    web_summary_json,
)

_DIGEST = "a" * 64
_SECOND_DIGEST = "b" * 64


def _rendered(
    artifact, digest: str = _DIGEST, names: tuple[str, ...] = ("scan.qa.nc",)
):
    return RenderedRun(digest, artifact, names)


def test_summary_preserves_artifact_identity_and_accounts_for_every_request(
    artifact,
) -> None:
    summary = build_web_summary(
        "0.1.0",
        [_rendered(artifact, names=("first.qa.nc", "again.qa.nc"))],
        [OmittedInput("broken.qa.nc", "not an artifact")],
    )

    assert summary["schema_version"] == 1
    assert summary["report_version"] == "0.1.0"
    assert summary["counts"] == {
        "requested_inputs": 3,
        "unique_rendered_runs": 1,
        "duplicate_inputs": 1,
        "omitted_inputs": 1,
    }
    run = summary["runs"][0]
    assert run["artifact_sha256"] == _DIGEST
    assert run["report_url"] == f"runs/{_DIGEST}/index.html"
    assert run["input_names"] == ["first.qa.nc", "again.qa.nc"]
    assert summary["omitted_inputs"] == [
        {"input_name": "broken.qa.nc", "reason": "not an artifact"}
    ]


def test_summary_maps_fixed_artifact_fields_without_display_formatting(
    artifact,
) -> None:
    summary = build_web_summary("0.1.0", [_rendered(artifact)])
    run = summary["runs"][0]
    provenance = run["provenance"]
    acquisition = provenance["acquisition"]

    assert run["title"] == artifact.provenance.scan
    assert provenance["source"] == artifact.provenance.source
    assert provenance["acquired_at"] == artifact.provenance.datetime
    assert provenance["analyzed_at"] == artifact.provenance.created
    assert provenance["core_version"] == artifact.provenance.core_version
    assert provenance["artifact_model_schema_version"] == artifact.schema_version
    assert acquisition["tr"] == {
        "value": artifact.provenance.tr,
        "availability": "available",
    }
    assert acquisition["matrix"] == list(artifact.provenance.matrix)
    assert acquisition["voxel_mm"] == [
        {"value": value, "availability": "available"}
        for value in artifact.provenance.voxel_mm
    ]
    assert run["settings"] == {
        "trim_sec": {"value": artifact.settings.trim_sec, "availability": "available"},
        "detrend": artifact.settings.detrend,
        "center": artifact.settings.center,
        "roi_size": artifact.settings.roi_size,
        "pe_axis_override": artifact.settings.pe_axis_override,
        "detrend_order": artifact.settings.detrend_order,
    }
    assert set(run["metrics"]) == {doc.name for doc in METRIC_DOCS}


def test_summary_keeps_missing_metadata_and_partial_time_unknown(bare_artifact) -> None:
    provenance = replace(bare_artifact.provenance, datetime="2026-01-02")
    artifact = replace(bare_artifact, provenance=provenance)

    summary = build_web_summary("0.1.0", [_rendered(artifact)])
    record = summary["runs"][0]["provenance"]

    assert record["acquired_at"] == "2026-01-02"
    assert record["device"] == {
        "manufacturer": None,
        "model": None,
        "serial": None,
        "coil": None,
        "field_strength": None,
        "software": None,
    }
    assert record["acquisition"]["series"] is None
    assert record["acquisition"]["te"] is None


def test_summary_uses_loaded_artifact_schema_version_not_a_source_name(
    artifact,
) -> None:
    provenance = replace(artifact.provenance, source="schema-v1.qa.nc")
    loaded = replace(
        artifact, provenance=provenance, schema_version=ARTIFACT_SCHEMA_VERSION
    )

    summary = build_web_summary("0.1.0", [_rendered(loaded)])

    assert summary["runs"][0]["provenance"]["artifact_model_schema_version"] == (
        ARTIFACT_SCHEMA_VERSION
    )


def test_summary_encodes_nonfinite_numbers_and_strict_json(artifact) -> None:
    measurements = replace(
        artifact.measurements,
        snr=float("nan"),
        sfnr=float("inf"),
        rdc=float("-inf"),
        phantom_fraction=float("nan"),
        phantom_contrast=float("inf"),
    )
    provenance = replace(artifact.provenance, field_strength=float("-inf"))
    changed = replace(artifact, measurements=measurements, provenance=provenance)

    summary = build_web_summary("0.1.0", [_rendered(changed)])
    run = summary["runs"][0]

    assert run["metrics"]["snr"]["availability"] == "nan"
    assert run["metrics"]["sfnr"]["availability"] == "positive_infinity"
    assert run["metrics"]["rdc"]["availability"] == "negative_infinity"
    assert run["localization"]["fraction"]["availability"] == "nan"
    assert run["localization"]["contrast"]["availability"] == "positive_infinity"
    assert run["provenance"]["device"]["field_strength"]["availability"] == (
        "negative_infinity"
    )
    assert json.loads(web_summary_json(summary))["runs"][0]["metrics"]["snr"] == {
        "availability": "nan",
        "unit": "1",
        "value": None,
    }


def test_summary_marks_legacy_localization_verdicts_as_not_recorded(artifact) -> None:
    measurements = replace(
        artifact.measurements, phantom_mask_ok=None, roi_inside_phantom=None
    )

    summary = build_web_summary(
        "0.1.0", [_rendered(replace(artifact, measurements=measurements))]
    )
    localization = summary["runs"][0]["localization"]

    assert localization["phantom_mask_ok"] == {
        "value": None,
        "availability": "not_recorded",
    }
    assert localization["roi_inside_phantom"] == {
        "value": None,
        "availability": "not_recorded",
    }


def test_summary_distinguishes_undeterminable_clipping_from_clean_no_rail(
    artifact,
) -> None:
    unknown = replace(
        artifact.measurements,
        clip_ceiling=None,
        clip_bits=None,
        n_clipped_kept=None,
        n_clipped_pre=None,
        clipped_kept=None,
        clipped_any=None,
    )
    clean = replace(
        artifact.measurements,
        clip_ceiling=None,
        clip_bits=None,
        n_clipped_kept=0,
        n_clipped_pre=0,
        clipped_kept=False,
        clipped_any=False,
    )

    unknown_summary = build_web_summary(
        "0.1.0", [_rendered(replace(artifact, measurements=unknown))]
    )
    clean_summary = build_web_summary(
        "0.1.0", [_rendered(replace(artifact, measurements=clean))]
    )

    assert unknown_summary["runs"][0]["clipping"] == {
        "availability": "not_determinable",
        "ceiling": None,
        "bits": None,
        "kept_count": None,
        "pre_count": None,
        "kept": None,
        "any": None,
    }
    assert clean_summary["runs"][0]["clipping"] == {
        "availability": "available",
        "ceiling": None,
        "bits": None,
        "kept_count": 0,
        "pre_count": 0,
        "kept": False,
        "any": False,
    }


def test_summary_rejects_duplicate_digests_and_invalid_route_digest(artifact) -> None:
    with pytest.raises(ValueError, match="duplicate artifact_sha256"):
        build_web_summary(
            "0.1.0", [_rendered(artifact), _rendered(artifact, _DIGEST, ("two.qa.nc",))]
        )
    with pytest.raises(ValueError, match="lowercase"):
        _rendered(artifact, "not-a-digest")


def test_reordering_runs_does_not_change_their_digest_routes(artifact) -> None:
    first = _rendered(artifact, _DIGEST)
    second = _rendered(artifact, _SECOND_DIGEST, ("second.qa.nc",))

    ordered = build_web_summary("0.1.0", [first, second])
    reordered = build_web_summary("0.1.0", [second, first])

    assert {run["artifact_sha256"]: run["report_url"] for run in ordered["runs"]} == {
        run["artifact_sha256"]: run["report_url"] for run in reordered["runs"]
    }
