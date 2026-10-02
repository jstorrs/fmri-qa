"""The QA name: the four fields it is built from, and which series keep dcm2niix's.

`naming.qa_stem` turns a BIDS sidecar into the name a series is filed under, and
degrades to a shorter name (or none) when fields are missing or malformed.
`naming.plan` decides across a whole session which series take their QA name and
which keep the one dcm2niix gave them, resolving collisions between the two.
"""

from itertools import permutations

import pytest

from fmriqc.convert import naming
from fmriqc.types import Sidecar

# A sidecar with every field the name is built from, as dcm2niix writes them.
FULL_SIDECAR = {
    "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
    "AcquisitionTime": "14:30:12.500000",
    "SeriesNumber": 2,
    "SeriesDescription": "QA_EPI_ISO",
    "ProtocolName": "ep2d_bold_qa",
}


def test_a_full_sidecar_names_all_four_fields() -> None:
    """Date, time, zero-padded series, sanitized description, in that order."""
    assert naming.qa_stem(FULL_SIDECAR) == "20260909_143012_s002_QA_EPI_ISO"


def test_the_padded_series_number_is_what_makes_a_listing_sort() -> None:
    """Series 2 before series 11 -- which dcm2niix's own `%s` gets backwards.

    This is the whole reason the name is rebuilt rather than templated: `%s` is
    not padded, so a directory listing puts series 11 first and looks ordered
    while being wrong.
    """
    second = naming.qa_stem({**FULL_SIDECAR, "SeriesNumber": 2})
    eleventh = naming.qa_stem({**FULL_SIDECAR, "SeriesNumber": 11})
    assert second is not None and eleventh is not None
    assert sorted([eleventh, second]) == [second, eleventh]
    assert sorted(["11_QA", "2_QA"]) == ["11_QA", "2_QA"]  # the unpadded order


def test_a_description_is_reduced_to_something_a_shell_needs_no_quoting_for() -> None:
    """Spaces and parentheses collapse to single underscores, ends trimmed."""
    stem = naming.qa_stem({**FULL_SIDECAR, "SeriesDescription": "QA EPI 32ch (rep)"})

    assert stem == "20260909_143012_s002_QA_EPI_32ch_rep"


def test_a_long_description_is_truncated_without_a_trailing_underscore() -> None:
    """A cut that lands on punctuation must not leave the separator behind."""
    assert naming.sanitize("a" * 30 + " " + "b" * 30, limit=31) == "a" * 30


def test_a_partial_sidecar_gives_a_shorter_name_rather_than_no_name() -> None:
    """Every field is a DICOM tag some export omits, so each one is optional.

    `AcquisitionTime` without `AcquisitionDateTime` is the case `--anonymize
    all` produces: the date is stripped but the series' own time survives, so
    the series still sorts chronologically within its session.
    """
    no_date = {k: v for k, v in FULL_SIDECAR.items() if k != "AcquisitionDateTime"}
    assert naming.qa_stem(no_date) == "143012_s002_QA_EPI_ISO"
    assert naming.qa_stem({"SeriesNumber": 2}) == "s002"
    assert naming.qa_stem({"SeriesDescription": "QA"}) == "QA"


def test_the_protocol_name_stands_in_for_a_missing_description() -> None:
    no_description = {k: v for k, v in FULL_SIDECAR.items() if k != "SeriesDescription"}

    assert naming.qa_stem(no_description) == "20260909_143012_s002_ep2d_bold_qa"


def test_a_sidecar_that_names_nothing_yields_no_stem() -> None:
    """None, not an empty string -- the caller falls back to dcm2niix's name."""
    assert naming.qa_stem({}) is None
    assert naming.qa_stem({"SeriesDescription": "!!!"}) is None  # sanitizes to nothing


def test_a_sidecar_field_of_the_wrong_type_is_ignored_not_trusted() -> None:
    """The sidecar is written by an external tool; nothing assumes its types.

    `True` is the sharp case: it is an `int` to `isinstance`, and would format
    as series `s001` if the check did not exclude it.
    """
    assert naming.qa_stem({"SeriesNumber": "2", "AcquisitionTime": 143012}) is None
    assert naming.qa_stem({"SeriesNumber": True}) is None


def test_plan_renames_what_it_can_and_leaves_alone_what_it_cannot() -> None:
    chosen = naming.plan({"2_QA": FULL_SIDECAR, "9_odd": {}, "4_none": None})

    assert chosen["2_QA"] == "20260909_143012_s002_QA_EPI_ISO"
    assert chosen["9_odd"] == "9_odd"  # sidecar named nothing
    assert chosen["4_none"] == "4_none"  # no readable sidecar at all


def test_two_series_that_would_share_a_name_both_keep_dcm2niix_s() -> None:
    """A multi-echo series is one series number, one description, several files.

    Renaming both to the one name they agree on would leave whichever moved
    last and silently drop the other, so the colliding group keeps the names
    dcm2niix already guaranteed unique. Nothing is invented; nothing is lost.
    """
    chosen = naming.plan({"2_QA_e1": FULL_SIDECAR, "2_QA_e2": dict(FULL_SIDECAR)})

    assert chosen == {"2_QA_e1": "2_QA_e1", "2_QA_e2": "2_QA_e2"}


@pytest.mark.parametrize("retained_sidecar", [None, {}, {"SeriesNumber": 2}])
def test_a_qa_name_cannot_replace_a_retained_original_name(retained_sidecar) -> None:
    chosen = naming.plan({"raw": {"SeriesNumber": 2}, "s002": retained_sidecar})

    assert chosen == {"raw": "raw", "s002": "s002"}


def test_fallback_collisions_are_resolved_until_every_name_is_unique() -> None:
    sidecars: dict[str, Sidecar | None] = {
        "s001": {"SeriesNumber": 2},
        "s002": {"SeriesNumber": 3},
        "s003": None,
        "raw": {"SeriesNumber": 1},
        "unambiguous": {"SeriesNumber": 4},
    }
    expected = {
        "s001": "s001",
        "s002": "s002",
        "s003": "s003",
        "raw": "raw",
        "unambiguous": "s004",
    }

    for ordered in permutations(sidecars.items()):
        assert naming.plan(dict(ordered)) == expected


def test_duplicate_proposals_can_introduce_a_further_collision() -> None:
    chosen = naming.plan(
        {
            "s001": {"SeriesNumber": 2},
            "duplicate": {"SeriesNumber": 2},
            "raw": {"SeriesNumber": 1},
            "unambiguous": {"SeriesNumber": 3},
        }
    )

    assert chosen == {
        "s001": "s001",
        "duplicate": "duplicate",
        "raw": "raw",
        "unambiguous": "s003",
    }


def test_original_names_do_not_block_unambiguous_qa_renames() -> None:
    chosen = naming.plan({"s001": {"SeriesNumber": 2}, "s002": {"SeriesNumber": 1}})

    assert chosen == {"s001": "s002", "s002": "s001"}
