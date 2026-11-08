"""The published JSON record: the same metrics as a row a trend database can file.

This is what `fmri-qa --json` writes. It mirrors the table's columns as raw
numbers instead of fixed-width text, with enough provenance that a stored row
still means something months later. The layout is a published contract pinned
by `JSON_SCHEMA_VERSION`. Adding or renaming a field means editing it here and
bumping the version.

Pure: it maps an analysis file and settings to plain data and does no IO, so the
command line and any other front end build the identical record. Only the
analysis file, settings and version modules are imported, so importing this does not
load the pipeline (see `fmriqa.analysis`).
"""

import math
from collections.abc import Mapping, Sequence

from ..settings import AnalysisSettings
from ..version import core_version
from .values import QAAnalysis

JSON_SCHEMA_VERSION = 6


def metric_record(analysis: QAAnalysis) -> dict[str, object]:
    """Build the scalar metrics for one scan as a JSON-serializable record.

    Mirrors the human table's columns as raw numbers, so downstream tools can
    read the published JSON record directly. The table's one `loc` cell is three
    fields here: the measured fraction, the contrast and both verdicts, which the
    trend database needs.

    A directional FWHM the run could not name (no phase-encode axis) is `null`,
    with the combined `fwhm` and its `fwhm_unit` alongside. `motn` and `com`
    carry their unit in `displacement_unit`: "mm" when the header's voxel size
    is known, else "vox". An analysis file migrated from schema <= 5 always reads
    "vox", since those schemas published both peaks in voxels whatever the voxel
    size (see `analysis.serialize.migrate`).

    The record carries more than the table because a stored row outlives the
    terminal. The source path and acquisition timestamp key and date it, and
    `tr`, `n_frames` and `n_trimmed` say what series the numbers describe.
    Without them the frame index in `outlier_worst_frame` names a volume nobody
    can find again.
    """
    m = analysis.measurements
    prov = analysis.provenance
    record: dict[str, object] = {
        "scan": prov.scan,
        # Enough provenance to key and date a row without opening the analysis file:
        # the path analyzed and the acquisition timestamp (null without a
        # sidecar), then the shape of the series the numbers were measured on.
        "source": prov.source,
        "datetime": prov.datetime,
        "tr": prov.tr,
        "n_frames": prov.n_frames,  # frames analyzed, after the warm-up trim
        "n_trimmed": prov.n_trimmed,  # warm-up volumes dropped; null = unrecorded
        "slice_index": prov.slice_index,  # plane analyzed, 0-based; null = unrecorded
        "pe": m.pe_label,
        "pe_axis": m.pe_axis,
        # Localization first: these say whether the rest of the row means
        # anything (see `localization_flag`).
        "phantom_fraction": m.phantom_fraction,
        "phantom_contrast": m.phantom_contrast,  # null when infinite (zero background)
        "phantom_mask_ok": m.phantom_mask_ok,
        "roi_inside_phantom": m.roi_inside_phantom,
        "snr": m.snr,
        "sfnr": m.sfnr,
        "rdc": m.rdc,
        "drift_pct": m.drift_pct,
        "ghost_pct": m.ghost_pct,
        "ghost_top_pct": m.ghost_top_pct,
        "ro_ghost_pct": m.ro_ghost_pct,
        "acr_ghost_pct": m.acr_ghost_pct,
        "outl_pct": m.outlier_max_pct,
        # Indexes the analyzed series, so frame 0 is the first volume kept.
        # Add `n_trimmed` to get the acquired volume number.
        "outlier_worst_frame": m.outlier_worst_frame,
        "tc_outlier": m.tc_outlier,
        "spec_outlier": m.spec_outlier,
        "clip": m.n_clipped_kept,
        "clip_kept": m.clipped_kept,  # any clip biases the analyzed data
        "clip_pre": m.n_clipped_pre,
        "motn": m.max_translation,
        "scl_pct": m.max_scale_pct,
        "shr_pct": m.max_shear_pct,
        "com": m.max_com_displacement,
        "displacement_unit": m.displacement_unit,  # "mm", or "vox" if unknown
        "fw_pe": m.fwhm_pe,
        "fw_ro": m.fwhm_ro,
        "fwhm": m.fwhm,  # combined (AFNI ccomb), defined on either axis or none
        "fwhm_unit": m.fwhm_unit,  # "mm", or "vox" when the voxel size is unknown
    }
    # Undefined numerical metrics are JSON null, not Python's non-standard NaN
    # or Infinity tokens, so strict JSON parsers can read the record.
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in record.items()
    }


def config_record(settings: AnalysisSettings) -> dict[str, object]:
    """Build the run parameters echoed into the JSON record's header."""
    return {
        "version": core_version(),
        "detrend": settings.detrend,
        "trim_sec": settings.trim_sec,
        "center": settings.center,
        "roi_size": settings.roi_size,
        "pe_axis_override": settings.pe_axis_override,
    }


def record_document(
    settings: AnalysisSettings,
    requested: Sequence[str],
    scans: Sequence[Mapping[str, object]],
    errors: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    """Wrap per-scan records in the envelope `fmri-qa --json` writes.

    `requested` lists every path asked for, so a scan that failed is told apart
    from one never requested. `scans` are `metric_record` results for the scans
    that succeeded, and `errors` the failures. The lists are copied, so the
    result shares no mutable state with the arguments and is JSON-serializable
    when they are.
    """
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "config": config_record(settings),
        "requested": list(requested),
        "scans": list(scans),
        "errors": list(errors),
    }
