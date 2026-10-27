"""Phase-encode axis resolution from the BIDS sidecar, and the row/col labels.

The authoritative, header-only PE-axis sources, kept apart from the ghost metric
that provides the last-resort estimate. The BIDS sidecar comes first (see the
project notes). Within it, dcm2niix's own conclusions (`PhaseEncodingDirection`,
then `PhaseEncodingAxis`) come before the raw DICOM row/col tag. The NIfTI
`dim_info` phase field is the last header answer, read by
`fmriqa_io.decode.nifti.pe_axis_from_header`. `fmriqa_io.decode.scan` tries them
in that order and leaves the axis unresolved if none answers, for
`pipeline.run_qa` to estimate from the Nyquist ghost.

Every source answers with a plain axis index, because any of them can
legitimately name the through-plane axis. `in_plane` is the single point that
narrows one to the `PeAxis` the pipeline measures on.
"""

from ..exceptions import InvalidScanError
from ..types import PE_AXES, PeAxis, PeLabel, Sidecar

__all__ = [
    "pe_axis_from_sidecar",
]

# DICOM in-plane phase-encode axis -> row/col: NIfTI i (axis 0) is the DICOM
# row direction, j (axis 1) the column direction (verified against dcm2niix
# InPlanePhaseEncodingDirectionDICOM on a Siemens acquisition). The single source
# of truth for the row/col label the metadata, report and CLI all show.
#
# Keyed by `PeAxis`, so a caller holding one can index straight in and the
# artifact builder needs no lookup default for a case that cannot arise (see
# `analysis.build._pe_label`).
PE_ROWCOL: dict[PeAxis, PeLabel] = {0: "row", 1: "col"}


def in_plane(axis: int | None) -> PeAxis | None:
    """Narrow `axis` to an in-plane `PeAxis`, or None if it is not one.

    The single narrowing point between what a header can say and what the
    single-slice pipeline can measure. A BIDS sidecar may name the through-plane
    axis (`k` -> 2), which this pipeline can't use, since every ghost statistic
    rolls the phantom half the FOV along an in-plane axis. Narrowing once here
    keeps a 2 from traveling inward as a plain `int`.

    None means "no in-plane axis to work with", and `validate_qa_run`'s return
    value carries it inward that way. `run_qa` treats the two causes
    differently. An absent axis falls through to the Nyquist-ghost estimate. A
    header that named the through-plane axis is refused by `validate_qa_run`, by
    name. (An explicitly passed axis can't be through-plane, because the
    parameter is a `PeAxis`.)
    """
    return axis if axis in PE_AXES else None


# BIDS axis letters -> NIfTI array axis. The polarity suffix is dropped: ghost
# placement rolls the phantom half the FOV along the axis, which is symmetric,
# so the phase-encoding direction changes no mask. Both fields in
# `_SIDECAR_PE_FIELDS` use these letters, so they share one map.
_BIDS_AXES: dict[str, int] = {"i": 0, "i-": 0, "j": 1, "j-": 1, "k": 2, "k-": 2}

# The sidecar's phase-encode fields, most authoritative first. Both are
# dcm2niix's conclusions, already in NIfTI array terms: `PhaseEncodingDirection`
# when it could determine polarity from vendor private data,
# `PhaseEncodingAxis` when it could only determine the axis. The axis is all
# this pipeline needs, so the weaker field is as good here.
#
# Both outrank `InPlanePhaseEncodingDirectionDICOM`, DICOM (0018,1312) verbatim
# in row/col image terms. Turning that into an array axis needs the mapping
# `PE_ROWCOL` records as verified on one vendor and orientation. Preferring
# dcm2niix's fields is the same choice `fmriqa_io.convert` makes. The synthetic
# study in fmri-qa-io's `tests/fixtures/dicom` has only `PhaseEncodingAxis`, since
# it has no CSA header to determine polarity from.
_SIDECAR_PE_FIELDS = ("PhaseEncodingDirection", "PhaseEncodingAxis")


def pe_axis_from_sidecar(sidecar: Sidecar) -> int | None:
    """Read the PE axis (0/1/2) from the sidecar, or None if it has no PE field.

    dcm2niix's two BIDS answers are tried in turn, then
    `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) as the DICOM fallback
    (row = i = axis 0, col = j = axis 1). See `_SIDECAR_PE_FIELDS` for the order.

    Raises
    ------
    InvalidScanError
        If the first present PE field has an invalid value.
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
