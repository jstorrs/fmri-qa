"""The `--json` document: the same metrics as a record a trend database can file.

Mirrors the table's columns as raw numbers rather than fixed-width text, with
enough provenance that a stored row still means something months later. The
layout is a published contract, pinned by `JSON_SCHEMA_VERSION`; adding or
renaming a field is a deliberate edit here and a bump there.
"""

# The `q.*` parameter annotations below name artifact types that live behind
# `fmriqc`'s lazy re-exports; evaluated at `def` time they would resolve the
# whole calculation stack just to import this module. Deferring them keeps a
# `--help` or a usage error from paying for numpy, scipy and nibabel.
from __future__ import annotations

import argparse
import math

import fmriqc as q

JSON_SCHEMA_VERSION = 6


def metric_record(artifact: q.QAArtifact) -> dict[str, object]:
    """The scalar metrics for one scan as a JSON-serializable record.

    Mirrors the human table's columns, but as raw numbers (not the fixed-width
    formatting), so downstream tools can consume `--json` directly. The table's
    one `loc` cell is three fields here: a consumer that files these away —
    the trend database this output exists for — needs the measured fraction and
    contrast and both verdicts, not the abbreviation an operator reads.

    A directional FWHM the run could not name (no phase-encode axis) is `null`,
    with the combined `fwhm` and its `fwhm_unit` alongside so the numbers that
    *were* measured stay interpretable. `motn` and `com` carry their own unit
    the same way, in `displacement_unit` -- "mm" when the header's voxel size
    is known, else "vox" (an artifact migrated from schema <= 5 always reads
    "vox" here, since those schemas published both peaks in voxels regardless
    of the voxel size; see `analysis.serialize.migrate`).

    The record carries a little more than the table does, because a stored row
    outlives the terminal it was printed to: the source path and acquisition
    timestamp key and date it, and `tr`/`n_frames`/`n_trimmed` say what series
    the numbers describe — without which the frame index in
    `outlier_worst_frame` names a volume nobody can find again.
    """
    m = artifact.measurements
    prov = artifact.provenance
    record: dict[str, object] = {
        "scan": prov.scan,
        # Enough provenance to key and date a row without opening the artifact:
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
        # Indexes the *analyzed* series, so frame 0 is the first volume kept;
        # add `n_trimmed` to reach the acquired volume number.
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
    # or Infinity tokens. This keeps stdout consumable by strict JSON parsers.
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in record.items()
    }


def config_record(args: argparse.Namespace) -> dict[str, object]:
    """The run parameters echoed into the JSON document's header."""
    return {
        "version": q.core_version(),
        "detrend": args.detrend,
        "trim_sec": args.trim_sec,
        "center": args.center,
        "roi_size": args.roi_size,
        "pe_axis_override": args.pe_axis,
    }
