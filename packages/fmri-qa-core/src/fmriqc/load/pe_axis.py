"""Phase-encode axis resolution from the BIDS sidecar and NIfTI header.

The two authoritative, header-only PE-axis sources, kept apart from the ghost
metric that provides the last-resort estimate. The sidecar
`PhaseEncodingDirection` is authoritative (see the project notes); the NIfTI
`dim_info` phase field is the fallback. `scan.from_nifti` tries these in order
and leaves the axis unresolved if neither answers, for `pipeline.run_qa` to
estimate from the Nyquist ghost.

Both sources answer with a plain axis index, because both can legitimately name
the through-plane axis. `in_plane` is the single point that narrows one to the
`PeAxis` the pipeline measures on.
"""

from typing import Any

from ..exceptions import InvalidScanError
from ..types import PE_AXES, PeAxis, PeLabel

# DICOM in-plane phase-encode axis -> row/col: NIfTI i (axis 0) is the DICOM
# row direction, j (axis 1) the column direction (verified against dcm2niix
# InPlanePhaseEncodingDirectionDICOM on a Siemens acquisition). The single source
# of truth for the row/col label the metadata, report, and CLI all show.
#
# Keyed by `PeAxis`, so it is *total*: every in-plane axis has a word, and a
# caller holding one indexes straight into it. That is what lets the artifact
# builder publish a `PeLabel` without a lookup default standing in for a case
# that cannot arise (see `analysis.build._pe_label`).
PE_ROWCOL: dict[PeAxis, PeLabel] = {0: "row", 1: "col"}


def in_plane(axis: int | None) -> PeAxis | None:
    """`axis` as an in-plane `PeAxis`, or None if it is not one.

    The single narrowing point between what a header can *say* and what the
    single-slice pipeline can *measure*. A BIDS sidecar may name the
    through-plane axis (`k` -> 2), which is a perfectly well-formed answer to a
    question this pipeline does not ask: every ghost statistic is defined by
    rolling the phantom half the FOV along an in-plane axis. Rather than let a 2
    travel inward as a plain `int` and be re-tested wherever it lands, it is
    narrowed once, here, to the type the rest of the package speaks.

    None means "no in-plane axis to work with", which is the same answer as an
    absent one -- and `run_qa` treats it the same way, estimating the axis from
    the Nyquist ghost. `validate_qa_run` still *rejects* an explicit
    through-plane axis by name, so a caller who asked for one is told so rather
    than quietly given an estimate.
    """
    return axis if axis in PE_AXES else None


def _pe_axis_from_sidecar(sidecar: dict[str, Any]) -> int | None:
    """PE axis (0/1/2) from the sidecar, or None if it carries no PE field.

    `PhaseEncodingDirection` (BIDS i/j/k, with an optional polarity we drop) maps
    straight to the array axis; `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) is
    the DICOM fallback (row = i = axis 0, col = j = axis 1).
    """
    if ped := sidecar.get("PhaseEncodingDirection"):
        value = str(ped)
        try:
            return {"i": 0, "i-": 0, "j": 1, "j-": 1, "k": 2, "k-": 2}[value]
        except KeyError:
            raise InvalidScanError(
                "PhaseEncodingDirection",
                ped,
                "expected one of 'i', 'i-', 'j', 'j-', 'k', or 'k-'",
            ) from None
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        value = str(dicom).upper()
        try:
            return {"ROW": 0, "COL": 1}[value]
        except KeyError:
            raise InvalidScanError(
                "InPlanePhaseEncodingDirectionDICOM",
                dicom,
                "expected 'ROW' or 'COL'",
            ) from None
    return None


def _pe_axis_from_header(header: Any) -> int | None:
    """PE axis from the NIfTI `dim_info` phase field, or None if unset/invalid.

    `dim_info` carries no polarity, which we don't need for ghost placement.
    """
    phase = header.get_dim_info()[1]
    return int(phase) if phase in (0, 1, 2) else None
