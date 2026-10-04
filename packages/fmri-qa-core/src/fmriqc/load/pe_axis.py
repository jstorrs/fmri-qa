"""Phase-encode axis resolution from the BIDS sidecar and NIfTI header.

The authoritative, header-only PE-axis sources, kept apart from the ghost metric
that provides the last-resort estimate. The BIDS sidecar comes first (see the
project notes), and within it dcm2niix's own conclusions -- `PhaseEncodingDirection`,
then `PhaseEncodingAxis` -- before the raw DICOM row/col tag; the NIfTI `dim_info`
phase field is the last header answer. `scan.from_nifti` tries them in that order
and leaves the axis unresolved if none answers, for `pipeline.run_qa` to estimate
from the Nyquist ghost.

Every source answers with a plain axis index, because any of them can legitimately
name the through-plane axis. `in_plane` is the single point that narrows one to
the `PeAxis` the pipeline measures on.
"""

from typing import Any

from ..exceptions import InvalidScanError
from ..types import PE_AXES, PeAxis, PeLabel, Sidecar

__all__: list[str] = []

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

    None means "no in-plane axis to work with", and `validate_qa_run`'s return
    value carries it inward as exactly that. `run_qa` does not treat the two
    ways of getting there alike, though: an *absent* axis falls through to the
    Nyquist-ghost estimate, while a scan whose header *named* the through-plane
    axis is refused by `validate_qa_run`, by name, rather than quietly given an
    estimate. (An explicitly passed axis cannot be through-plane at all: the
    parameter is a `PeAxis`.)
    """
    return axis if axis in PE_AXES else None


# BIDS axis letters -> NIfTI array axis. The polarity suffix is dropped: ghost
# placement rolls the phantom half the FOV along the axis, which is symmetric,
# so which way the phase encoding ran changes no mask. Both fields in
# `_SIDECAR_PE_FIELDS` speak this vocabulary, so they read it from one map.
_BIDS_AXES: dict[str, int] = {"i": 0, "i-": 0, "j": 1, "j-": 1, "k": 2, "k-": 2}

# The sidecar's phase-encode fields, most authoritative first, and both ahead of
# the raw DICOM tag. Both are dcm2niix's *conclusions* about the series, already
# expressed in NIfTI array terms: `PhaseEncodingDirection` when it could
# determine the polarity from vendor private data, `PhaseEncodingAxis` when it
# could only determine the axis. The axis is the entire answer this pipeline
# needs, so the weaker field is worth exactly as much here as the stronger one.
#
# Both outrank `InPlanePhaseEncodingDirectionDICOM`, which is DICOM (0018,1312)
# verbatim, in DICOM's row/col *image* terms -- turning that into an array axis
# needs the mapping `PE_ROWCOL`'s comment records having verified on one vendor
# and one orientation, while these two arrive needing no mapping at all. Reading
# them is the same choice `convert` makes: rely on dcm2niix's vendor work rather
# than redo a piece of it. A series dcm2niix could not determine polarity for
# gets exactly this -- see the synthetic study in `tests/fixtures/dicom`, which
# has no CSA header and so is described by `PhaseEncodingAxis` alone.
_SIDECAR_PE_FIELDS = ("PhaseEncodingDirection", "PhaseEncodingAxis")


def _pe_axis_from_sidecar(sidecar: Sidecar) -> int | None:
    """PE axis (0/1/2) from the sidecar, or None if it carries no PE field.

    dcm2niix's two BIDS answers are tried in turn, then
    `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) as the DICOM fallback
    (row = i = axis 0, col = j = axis 1). See `_SIDECAR_PE_FIELDS` for the order.

    Raises
    ------
    InvalidScanError
        The first present PE field has an invalid value.
    """
    for field in _SIDECAR_PE_FIELDS:
        if field not in sidecar:
            continue
        value = sidecar[field]
        try:
            return _BIDS_AXES[str(value)]
        except KeyError:
            raise InvalidScanError(
                field,
                value,
                "expected one of 'i', 'i-', 'j', 'j-', 'k', or 'k-'",
            ) from None
    if "InPlanePhaseEncodingDirectionDICOM" not in sidecar:
        return None
    dicom = sidecar["InPlanePhaseEncodingDirectionDICOM"]
    try:
        return {"ROW": 0, "COL": 1}[str(dicom).upper()]
    except KeyError:
        raise InvalidScanError(
            "InPlanePhaseEncodingDirectionDICOM",
            dicom,
            "expected 'ROW' or 'COL'",
        ) from None


def _pe_axis_from_header(header: Any) -> int | None:
    """PE axis from the NIfTI `dim_info` phase field, or None if unset/invalid.

    `dim_info` carries no polarity, which we don't need for ghost placement.
    """
    phase = header.get_dim_info()[1]
    return int(phase) if phase in (0, 1, 2) else None
