"""Phase-encode axis resolution from the BIDS sidecar, and its priority chain.

The PE axis drives the ghost masks and the report's row/col labels, so source
order matters. The BIDS sidecar is authoritative, with dcm2niix's
`PhaseEncodingDirection` and `PhaseEncodingAxis` ahead of the raw DICOM row/col
tag. These tests pin that order on a sidecar mapping. The NIfTI `dim_info`
fallback, and the whole chain on a loaded file, are tested in fmri-qa-io's
`test_pe_axis.py`.
"""

import pytest

import fmriqa as q
from fmriqa.load.pe_axis import pe_axis_from_sidecar


@pytest.mark.parametrize(
    ("sidecar", "expected"),
    [
        ({"PhaseEncodingDirection": "i"}, 0),
        ({"PhaseEncodingDirection": "j"}, 1),
        ({"PhaseEncodingDirection": "k"}, 2),
        ({"PhaseEncodingDirection": "i-"}, 0),
        ({"PhaseEncodingDirection": "j-"}, 1),  # polarity is dropped
        ({"PhaseEncodingDirection": "k-"}, 2),
        # What dcm2niix writes when it resolved the axis but not the polarity.
        ({"PhaseEncodingAxis": "i"}, 0),
        ({"PhaseEncodingAxis": "j"}, 1),
        ({"PhaseEncodingAxis": "k"}, 2),
        ({"PhaseEncodingAxis": "i-"}, 0),
        ({"PhaseEncodingAxis": "j-"}, 1),
        ({"PhaseEncodingAxis": "k-"}, 2),
        ({"InPlanePhaseEncodingDirectionDICOM": "ROW"}, 0),
        ({"InPlanePhaseEncodingDirectionDICOM": "COL"}, 1),
        ({"InPlanePhaseEncodingDirectionDICOM": "col"}, 1),  # case-insensitive
        ({}, None),  # no PE field
    ],
)
def test_pe_axis_from_sidecar(sidecar: dict, expected: int | None) -> None:
    assert pe_axis_from_sidecar(sidecar) == expected


@pytest.mark.parametrize(
    "sidecar",
    [
        {"PhaseEncodingDirection": "junk"},
        {"PhaseEncodingDirection": "j+"},
        {"PhaseEncodingAxis": "junk"},
        {"InPlanePhaseEncodingDirectionDICOM": "diagonal"},
    ],
)
def test_pe_axis_from_sidecar_rejects_malformed_values(sidecar: dict) -> None:
    with pytest.raises(q.InvalidScanError):
        pe_axis_from_sidecar(sidecar)


@pytest.mark.parametrize("value", ["", None, False, 0, [], {}])
@pytest.mark.parametrize(
    ("field", "fallback"),
    [
        (
            "PhaseEncodingDirection",
            {"PhaseEncodingAxis": "j", "InPlanePhaseEncodingDirectionDICOM": "COL"},
        ),
        ("PhaseEncodingAxis", {"InPlanePhaseEncodingDirectionDICOM": "COL"}),
        ("InPlanePhaseEncodingDirectionDICOM", {}),
    ],
)
def test_present_empty_pe_values_reject_instead_of_falling_back(
    field: str, value: object, fallback: dict[str, object]
) -> None:
    with pytest.raises(q.InvalidScanError) as excinfo:
        pe_axis_from_sidecar({field: value, **fallback})

    assert excinfo.value.field == field
    assert excinfo.value.value == value


@pytest.mark.parametrize(
    ("sidecar", "expected"),
    [
        (
            {
                "PhaseEncodingDirection": "i",
                "PhaseEncodingAxis": None,
                "InPlanePhaseEncodingDirectionDICOM": "diagonal",
            },
            0,
        ),
        ({"PhaseEncodingAxis": "j", "InPlanePhaseEncodingDirectionDICOM": False}, 1),
    ],
)
def test_valid_authoritative_pe_field_ignores_malformed_weaker_fields(
    sidecar: dict[str, object], expected: int
) -> None:
    assert pe_axis_from_sidecar(sidecar) == expected


def test_sidecar_bids_direction_wins_over_dicom() -> None:
    # PhaseEncodingDirection is checked before the DICOM row/col fallback.
    sidecar = {
        "PhaseEncodingDirection": "i",  # axis 0
        "InPlanePhaseEncodingDirectionDICOM": "COL",  # axis 1
    }
    assert pe_axis_from_sidecar(sidecar) == 0


def test_the_axis_dcm2niix_derived_wins_over_the_raw_dicom_tag() -> None:
    """`PhaseEncodingAxis` outranks `InPlanePhaseEncodingDirectionDICOM`.

    The DICOM tag is (0018,1312) verbatim, in DICOM's row/col image frame, and
    reaching an array axis from it needs the row = i mapping that `PE_ROWCOL`
    records as verified on one vendor and orientation. `PhaseEncodingAxis` is
    dcm2niix's conclusion, already in NIfTI array letters, so it wins on
    disagreement.
    """
    sidecar = {
        "PhaseEncodingAxis": "i",  # axis 0
        "InPlanePhaseEncodingDirectionDICOM": "COL",  # axis 1
    }
    assert pe_axis_from_sidecar(sidecar) == 0


def test_a_stated_polarity_wins_over_an_axis_alone() -> None:
    """The stronger of dcm2niix's two answers is still tried first.

    They cannot disagree in practice. The order makes that a fact about our
    code, not about dcm2niix.
    """
    sidecar = {"PhaseEncodingDirection": "j-", "PhaseEncodingAxis": "i"}
    assert pe_axis_from_sidecar(sidecar) == 1


def test_a_malformed_axis_is_named_by_the_field_it_came_from() -> None:
    """Two fields share one parser, so the error must say which one failed."""
    with pytest.raises(q.InvalidScanError) as excinfo:
        pe_axis_from_sidecar({"PhaseEncodingAxis": "sideways"})

    assert excinfo.value.field == "PhaseEncodingAxis"
