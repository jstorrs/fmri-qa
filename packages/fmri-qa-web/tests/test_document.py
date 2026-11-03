"""`batch_document`, `contract` and the JSON bridge."""

import json

import pytest

from fmriqa import AnalysisSettings
from fmriqa.analysis.record import JSON_SCHEMA_VERSION, record_document
from fmriqa.convert import dcm2niix
from fmriqa_web import (
    InvalidResultError,
    Recorded,
    SeriesFailure,
    SeriesReport,
    Unrecorded,
    analyze_series,
    batch_document,
    bridge,
    contract,
)


def test_the_envelope_lists_every_scan_and_each_failure() -> None:
    ok = SeriesReport("a", "<html>", {"scan": "a.nii.gz"}, ())
    bad = SeriesFailure("b", "analyze", "too short", ("w",))

    document = batch_document([ok, bad])

    assert document == record_document(
        AnalysisSettings(),
        ["a.nii.gz", "b.nii.gz"],
        [{"scan": "a.nii.gz"}],
        [{"scan": "b.nii.gz", "source": "b.nii.gz", "error": "too short"}],
    )
    assert list(document) == [
        "schema_version",
        "config",
        "requested",
        "scans",
        "errors",
    ]


def test_the_envelope_reads_only_stem_record_and_reason() -> None:
    document = batch_document(
        [Recorded("a", {"scan": "a.nii.gz"}), Unrecorded("b", "x")]
    )

    assert document["requested"] == ["a.nii.gz", "b.nii.gz"]
    assert document["scans"] == [{"scan": "a.nii.gz"}]
    assert document["errors"] == [
        {"scan": "b.nii.gz", "source": "b.nii.gz", "error": "x"}
    ]


def test_the_envelope_uses_the_settings_it_is_given() -> None:
    document = batch_document([], AnalysisSettings(detrend=1))

    config = document["config"]
    assert isinstance(config, dict)
    assert config["detrend"] == 1


def test_the_contract_pins_the_flags_schema_and_versions() -> None:
    result = contract()

    assert result["dcm2niix_flags"] == dcm2niix.flags()
    assert result["json_schema_version"] == JSON_SCHEMA_VERSION
    versions = result["versions"]
    assert isinstance(versions, dict)
    assert list(versions) == [
        "fmri-qa-core",
        "fmri-qa-io",
        "fmri-qa-report",
        "fmri-qa-web",
    ]
    assert all(isinstance(v, str) and v for v in versions.values())


def test_analyze_json_is_strict_json_for_a_report(phantom_bytes) -> None:
    text = bridge.analyze_json(*phantom_bytes, "p")

    parsed = json.loads(text, parse_constant=_refuse)
    assert parsed["kind"] == "report"
    assert parsed["stem"] == "p"
    assert parsed["record"]["scan"] == "p.nii.gz"
    assert "<title>p" in parsed["html"]


def test_analyze_json_is_strict_json_for_a_failure() -> None:
    parsed = json.loads(bridge.analyze_json(b"junk", None, "j"))

    assert parsed["kind"] == "failure"
    assert parsed["stage"] == "decode"
    assert parsed["warnings"] == []


def test_a_non_finite_float_is_refused_not_written() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        bridge._dumps({"x": float("nan")})


def test_document_json_rebuilds_the_envelope_from_analyze_json(phantom_bytes) -> None:
    report = bridge.analyze_json(*phantom_bytes, "p")
    failure = bridge.analyze_json(b"junk", None, "j")

    document = json.loads(
        bridge.document_json([report, failure]), parse_constant=_refuse
    )

    direct = batch_document(
        [
            analyze_series(*phantom_bytes, stem="p"),
            analyze_series(b"junk", None, stem="j"),
        ]
    )
    assert document == json.loads(json.dumps(direct))


def test_a_float_that_is_whole_stays_a_float_through_document_json(
    phantom_bytes,
) -> None:
    text = bridge.document_json([bridge.analyze_json(*phantom_bytes, "p")])

    assert '"tr": 2.0,' in text
    (scan,) = json.loads(text)["scans"]
    assert isinstance(scan["tr"], float)


@pytest.mark.parametrize(
    ("item", "problem"),
    [
        ("{", "not JSON"),
        ("[]", "expected an object, got list"),
        ('{"kind": "report", "stem": 3}', "stem must be a string, got 3"),
        (
            '{"kind": "rpt", "stem": "a"}',
            "kind must be 'report' or 'failure', got 'rpt'",
        ),
        (
            '{"kind": "report", "stem": "a", "record": []}',
            "record must be an object, got []",
        ),
        (
            '{"kind": "failure", "stem": "a", "stage": "save", "reason": "x"}',
            "stage must be one of ['analyze', 'decode', 'render'], got 'save'",
        ),
        (
            '{"kind": "failure", "stem": "a", "stage": "decode", "reason": 7}',
            "reason must be a string, got 7",
        ),
    ],
)
def test_a_malformed_result_is_refused_by_index_and_problem(
    item: str, problem: str
) -> None:
    good = bridge.analyze_json(b"junk", None, "j")

    with pytest.raises(InvalidResultError) as raised:
        bridge.document_json([good, item])

    assert raised.value.index == 1
    assert problem in raised.value.problem


def test_the_bridge_takes_memoryviews_as_pyodide_hands_them_over(phantom_bytes) -> None:
    nifti, sidecar = (memoryview(b) for b in phantom_bytes)

    parsed = json.loads(bridge.analyze_json(nifti, sidecar, "p"))

    assert parsed["kind"] == "report"
    assert parsed["record"]["scan"] == "p.nii.gz"
    assert json.loads(bridge.analyze_json(nifti, None, "q"))["kind"] == "report"


def test_names_json_takes_memoryviews() -> None:
    files = {
        "dcm2niix_name.nii.gz": memoryview(b""),
        "dcm2niix_name.json": memoryview(
            b'{"SeriesNumber": 2, "SeriesDescription": "QA_EPI_ISO",'
            b' "AcquisitionDateTime": "2026-09-09T14:30:12.500000"}'
        ),
    }

    assert json.loads(bridge.names_json(files)) == {
        "dcm2niix_name.nii.gz": "20260909_143012_s002_QA_EPI_ISO.nii.gz",
        "dcm2niix_name.json": "20260909_143012_s002_QA_EPI_ISO.json",
    }


def test_a_value_that_is_not_a_buffer_is_a_type_error_not_zero_bytes() -> None:
    with pytest.raises(TypeError, match="got int"):
        bridge.analyze_json(5, None, "x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="got str"):
        bridge.names_json({"a.nii.gz": "text"})  # type: ignore[dict-item]


def test_names_json_and_contract_json_round_trip() -> None:
    assert json.loads(bridge.names_json({"a.nii.gz": b""})) == {"a.nii.gz": "a.nii.gz"}
    assert json.loads(bridge.contract_json()) == json.loads(json.dumps(contract()))


def _refuse(token: str) -> object:
    raise AssertionError(f"non-standard JSON token {token}")
