"""Versioned, JSON-safe summaries for static web reports.

This module turns already-loaded artifacts into the small, stable record a
static report index and a later trend reader need.  It deliberately neither
loads artifacts nor hashes their bytes: the command that writes a web report
owns both operations and passes their results in through ``RenderedRun``.
"""

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fmriqc.analysis import QAArtifact

from .content import METRIC_DOCS

__all__ = [
    "WEB_SUMMARY_SCHEMA_VERSION",
    "OmittedInput",
    "RenderedRun",
    "WebSummary",
    "build_web_summary",
    "web_summary_json",
]


WEB_SUMMARY_SCHEMA_VERSION = 1
"""The current version of the web-report summary wire format."""

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
type WebSummary = dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class RenderedRun:
    """One successfully rendered artifact and every requested input it represents.

    ``artifact_sha256`` is the lowercase SHA-256 digest of the exact artifact
    bytes.  It identifies report output only; it is not an acquisition,
    session, or logical-analysis identifier.  ``input_names`` may contain
    duplicate requests and is normalized to source basenames in the wire record.
    """

    artifact_sha256: str
    artifact: QAArtifact
    input_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.artifact_sha256) is None:
            raise ValueError("artifact_sha256 must be a lowercase 64-character SHA-256")
        if not self.input_names:
            raise ValueError(
                "a rendered run must represent at least one requested input"
            )
        if any(not _basename(name) for name in self.input_names):
            raise ValueError("input_names must have a basename")


@dataclass(frozen=True, slots=True)
class OmittedInput:
    """One requested artifact that could not be rendered, with its reported reason."""

    input_name: str
    reason: str

    def __post_init__(self) -> None:
        if not _basename(self.input_name):
            raise ValueError("input_name must have a basename")
        if not self.reason:
            raise ValueError("an omitted input must include a reason")


def build_web_summary(
    report_version: str,
    rendered_runs: Iterable[RenderedRun],
    omitted_inputs: Iterable[OmittedInput] = (),
) -> WebSummary:
    """Build schema-version 1 from rendered artifacts and omitted requests.

    The caller supplies the report package version and the digest it computed
    while writing each artifact's output.  Duplicate digests are rejected:
    accepting them would make the unique-run and duplicate-input counts lie.
    """
    runs = tuple(rendered_runs)
    omitted = tuple(omitted_inputs)
    _reject_duplicate_digests(runs)

    requested_successes = sum(len(run.input_names) for run in runs)
    requested_inputs = requested_successes + len(omitted)
    unique_rendered_runs = len(runs)
    return {
        "schema_version": WEB_SUMMARY_SCHEMA_VERSION,
        "report_version": report_version,
        "counts": {
            "requested_inputs": requested_inputs,
            "unique_rendered_runs": unique_rendered_runs,
            "duplicate_inputs": requested_successes - unique_rendered_runs,
            "omitted_inputs": len(omitted),
        },
        "runs": [_run_record(run) for run in runs],
        "omitted_inputs": [_omitted_record(item) for item in omitted],
    }


def web_summary_json(summary: Mapping[str, JSONValue]) -> str:
    """Serialize a summary as deterministic strict JSON.

    ``allow_nan=False`` makes an accidental unencoded non-finite float a loud
    error rather than JavaScript's non-standard ``NaN``/``Infinity`` token.
    """
    return json.dumps(summary, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _reject_duplicate_digests(runs: tuple[RenderedRun, ...]) -> None:
    digests = [run.artifact_sha256 for run in runs]
    if len(digests) != len(set(digests)):
        raise ValueError(
            "rendered runs must not contain duplicate artifact_sha256 values"
        )


def _run_record(run: RenderedRun) -> dict[str, JSONValue]:
    artifact = run.artifact
    provenance = artifact.provenance
    input_names: list[JSONValue] = [_basename(name) for name in run.input_names]
    return {
        "artifact_sha256": run.artifact_sha256,
        "report_url": f"runs/{run.artifact_sha256}/index.html",
        "title": provenance.scan or _basename(run.input_names[0]),
        "input_names": input_names,
        "provenance": {
            "source": provenance.source,
            "scan": provenance.scan,
            "acquired_at": provenance.datetime,
            "analyzed_at": provenance.created,
            "core_version": provenance.core_version,
            "artifact_model_schema_version": artifact.schema_version,
            "device": {
                "manufacturer": provenance.manufacturer,
                "model": provenance.model,
                "serial": provenance.serial,
                "coil": provenance.coil,
                "field_strength": _optional_float(provenance.field_strength),
                "software": provenance.software,
            },
            "acquisition": {
                "series": provenance.series,
                "tr": _float_record(provenance.tr),
                "te": _optional_float(provenance.te),
                "flip_angle": _optional_float(provenance.flip_angle),
                "matrix": (
                    list(provenance.matrix) if provenance.matrix is not None else None
                ),
                "voxel_mm": _optional_float_list(provenance.voxel_mm),
                "slice_thickness": _optional_float(provenance.slice_thickness),
                "pe_dir": provenance.pe_dir,
                "n_frames": provenance.n_frames,
                "n_trimmed": provenance.n_trimmed,
                "slice_index": provenance.slice_index,
                "n_slices": provenance.n_slices,
            },
        },
        "settings": {
            "trim_sec": _float_record(artifact.settings.trim_sec),
            "detrend": artifact.settings.detrend,
            "center": artifact.settings.center,
            "roi_size": artifact.settings.roi_size,
            "pe_axis_override": artifact.settings.pe_axis_override,
            "detrend_order": artifact.settings.detrend_order,
        },
        "metrics": _metric_records(artifact),
        "localization": _localization_record(artifact),
        "clipping": _clipping_record(artifact),
    }


def _metric_records(artifact: QAArtifact) -> dict[str, JSONValue]:
    measurements = artifact.measurements
    return {
        doc.name: _metric_record(doc.value(measurements), doc.unit(measurements))
        for doc in METRIC_DOCS
    }


def _localization_record(artifact: QAArtifact) -> dict[str, JSONValue]:
    measurements = artifact.measurements
    return {
        "fraction": _float_record(measurements.phantom_fraction),
        "contrast": _float_record(measurements.phantom_contrast),
        "phantom_mask_ok": _verdict_record(measurements.phantom_mask_ok),
        "roi_inside_phantom": _verdict_record(measurements.roi_inside_phantom),
    }


def _clipping_record(artifact: QAArtifact) -> dict[str, JSONValue]:
    measurements = artifact.measurements
    availability = (
        "not_determinable" if measurements.clipped_any is None else "available"
    )
    return {
        "availability": availability,
        "ceiling": _optional_float(measurements.clip_ceiling),
        "bits": measurements.clip_bits,
        "kept_count": measurements.n_clipped_kept,
        "pre_count": measurements.n_clipped_pre,
        "kept": measurements.clipped_kept,
        "any": measurements.clipped_any,
    }


def _omitted_record(item: OmittedInput) -> dict[str, JSONValue]:
    return {"input_name": _basename(item.input_name), "reason": item.reason}


def _basename(name: str) -> str:
    """Return the basename the report exposes for one requested source."""
    return Path(name).name


def _optional_float(value: float | None) -> JSONValue:
    return None if value is None else _float_record(value)


def _optional_float_list(values: tuple[float, float, float] | None) -> JSONValue:
    return None if values is None else [_float_record(value) for value in values]


def _float_record(value: float) -> dict[str, JSONValue]:
    if math.isnan(value):
        return {"value": None, "availability": "nan"}
    if value == math.inf:
        return {"value": None, "availability": "positive_infinity"}
    if value == -math.inf:
        return {"value": None, "availability": "negative_infinity"}
    return {"value": value, "availability": "available"}


def _metric_record(value: float, unit: str) -> dict[str, JSONValue]:
    numeric = _float_record(value)
    return {
        "value": numeric["value"],
        "unit": unit,
        "availability": numeric["availability"],
    }


def _verdict_record(value: bool | None) -> dict[str, JSONValue]:
    if value is None:
        return {"value": None, "availability": "not_recorded"}
    return {"value": value, "availability": "available"}
