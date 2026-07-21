"""Phase-encode axis resolution from the BIDS sidecar and NIfTI header.

The two authoritative, header-only PE-axis sources, kept apart from the ghost
metric that provides the last-resort estimate. The sidecar
`PhaseEncodingDirection` is authoritative (see the project notes); the NIfTI
`dim_info` phase field is the fallback. `scan.from_nifti` tries these in order
and only then falls back to `metrics.ghost.phase_encode_axis`.
"""

from typing import Any

# DICOM in-plane phase-encode axis -> row/col: NIfTI i (axis 0) is the DICOM
# row direction, j (axis 1) the column direction (verified against dcm2niix
# InPlanePhaseEncodingDirectionDICOM on a Siemens acquisition). The single source
# of truth for the row/col label the metadata, report, and CLI all show.
PE_ROWCOL: dict[int, str] = {0: "row", 1: "col"}


def _pe_axis_from_sidecar(sidecar: dict[str, Any]) -> int | None:
    """PE axis (0/1/2) from the sidecar, or None if it carries no PE field.

    `PhaseEncodingDirection` (BIDS i/j/k, with an optional polarity we drop) maps
    straight to the array axis; `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) is
    the DICOM fallback (row = i = axis 0, col = j = axis 1).
    """
    if ped := sidecar.get("PhaseEncodingDirection"):
        return {"i": 0, "j": 1, "k": 2}.get(str(ped)[0])
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return {"ROW": 0, "COL": 1}.get(str(dicom).upper())
    return None


def _pe_axis_from_header(header: Any) -> int | None:
    """PE axis from the NIfTI `dim_info` phase field, or None if unset/invalid.

    `dim_info` carries no polarity, which we don't need for ghost placement.
    """
    phase = header.get_dim_info()[1]
    return int(phase) if phase in (0, 1, 2) else None
