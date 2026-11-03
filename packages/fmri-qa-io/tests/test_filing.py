"""`filing.plan_names`: the filed name of every file, from strings alone."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fmriqa.exceptions import InvalidChoiceError
from fmriqa.types import Sidecar
from fmriqa_io.convert.filing import Filed, plan_names, sidecar_or_none

QA: Sidecar = {
    "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
    "SeriesNumber": 2,
    "SeriesDescription": "QA EPI ISO",
}
QA_STEM = "20260909_143012_s002_QA_EPI_ISO"


def test_qa_style_files_a_series_and_its_companion_under_the_qa_stem() -> None:
    planned = plan_names(["raw.nii.gz", "raw.json"], {"raw": QA}, "qa")

    assert planned == {
        "raw.nii.gz": Filed("raw", f"{QA_STEM}.nii.gz"),
        "raw.json": Filed("raw", f"{QA_STEM}.json"),
    }


def test_dcm2niix_style_keeps_every_name() -> None:
    planned = plan_names(["raw.nii.gz", "raw.json"], {"raw": QA}, "dcm2niix")

    assert planned == {
        "raw.nii.gz": Filed("raw", "raw.nii.gz"),
        "raw.json": Filed("raw", "raw.json"),
    }


def test_a_series_without_a_sidecar_keeps_its_name_in_qa_style() -> None:
    planned = plan_names(["raw.nii"], {"raw": None}, "qa")

    assert planned == {"raw.nii": Filed("raw", "raw.nii")}


def test_a_stem_missing_from_sidecars_is_treated_as_having_none() -> None:
    assert plan_names(["raw.nii"], {}, "qa") == {"raw.nii": Filed("raw", "raw.nii")}


def test_the_longest_stem_owns_a_companion() -> None:
    sidecars: dict[str, Sidecar | None] = {
        "scan": {"SeriesNumber": 1},
        "scan.repeat": {"SeriesNumber": 2},
    }
    planned = plan_names(
        ["scan.nii.gz", "scan.json", "scan.repeat.nii.gz", "scan.repeat.json"],
        sidecars,
        "qa",
    )

    assert planned["scan.json"] == Filed("scan", "s001.json")
    assert planned["scan.repeat.json"] == Filed("scan.repeat", "s002.json")


def test_a_nifti_belongs_to_its_parsed_stem_even_when_another_stem_ends_nii() -> None:
    planned = plan_names(
        ["x.nii.gz", "x.nii.nii.gz", "x.nii.json"],
        {"x": None, "x.nii": None},
        "dcm2niix",
    )

    assert planned == {
        "x.nii.gz": Filed("x", "x.nii.gz"),
        "x.nii.nii.gz": Filed("x.nii", "x.nii.nii.gz"),
        "x.nii.json": Filed("x.nii", "x.nii.json"),
    }


def test_only_the_leading_stem_is_swapped() -> None:
    stem = "raw"
    sidecar: Sidecar = {"SeriesNumber": 3}
    planned = plan_names(["raw.nii.gz", "raw.raw.json"], {stem: sidecar}, "qa")

    assert planned["raw.raw.json"] == Filed("raw", "s003.raw.json")


def test_a_file_only_sharing_a_prefix_with_a_stem_is_not_its_companion() -> None:
    planned = plan_names(["raw.nii.gz", "raw_ph.json"], {"raw": QA}, "qa")

    # `raw_ph.json` does not start with `raw.`, so it is not raw's companion.
    assert "raw_ph.json" not in planned


def test_a_colliding_group_keeps_the_names_dcm2niix_made() -> None:
    names = ["a.nii.gz", "a.json", "a_e2.nii.gz", "a_e2.json"]
    planned = plan_names(names, {"a": QA, "a_e2": QA}, "qa")

    assert planned == {name: Filed(name.split(".")[0], name) for name in names}


def test_a_file_that_belongs_to_no_series_is_omitted() -> None:
    planned = plan_names(["raw.nii.gz", "notes.txt", "other.json"], {"raw": QA}, "qa")

    assert sorted(planned) == ["raw.nii.gz"]


def test_a_sidecar_key_naming_no_nifti_is_ignored() -> None:
    planned = plan_names(
        ["raw.nii.gz", "raw.json", "ghost.json"], {"raw": QA, "ghost": QA}, "qa"
    )

    assert planned == {
        "raw.nii.gz": Filed("raw", f"{QA_STEM}.nii.gz"),
        "raw.json": Filed("raw", f"{QA_STEM}.json"),
    }


@pytest.mark.parametrize("bad", ["out/raw.nii.gz", "out\\raw.json", ".", ".."])
def test_a_name_that_is_not_a_bare_filename_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="bare filenames") as excinfo:
        plan_names(["raw.nii.gz", bad], {"raw": QA}, "qa")

    assert repr(bad) in str(excinfo.value)


def test_an_unknown_style_is_refused_by_name() -> None:
    with pytest.raises(InvalidChoiceError, match="style"):
        plan_names(["raw.nii.gz"], {"raw": QA}, "bids")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"SeriesNumber": 2}', {"SeriesNumber": 2}),
        ("{}", {}),
        ("[]", None),
        ("2", None),
        ('{"SeriesNumber": ', None),
        ("", None),
    ],
)
def test_a_sidecar_is_a_json_object_or_none(
    text: str, expected: Sidecar | None
) -> None:
    assert sidecar_or_none(text) == expected, text


def test_nothing_in_nothing_out() -> None:
    assert plan_names([], {}, "qa") == {}


_stems = st.text(alphabet="abcs0123_.", min_size=1, max_size=6).filter(
    lambda s: not s.endswith((".nii", ".gz")) and not s.startswith(".")
)
_sidecars = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {"SeriesNumber": st.integers(0, 3), "SeriesDescription": st.sampled_from("ab")}
    ),
)


@st.composite
def _series(draw: st.DrawFn) -> tuple[list[str], dict[str, Sidecar | None]]:
    stems = draw(st.lists(_stems, min_size=1, max_size=4, unique=True))
    # Some stems get no key, which `plan_names` reads as no sidecar.
    sidecars = {stem: draw(_sidecars) for stem in stems if draw(st.booleans())}
    names = [f"{stem}{ext}" for stem in stems for ext in (".nii.gz", ".json")]
    return names, sidecars


@given(_series(), st.sampled_from(["qa", "dcm2niix"]))
def test_filed_names_are_unique_when_the_inputs_are(
    series: tuple[list[str], dict[str, Sidecar | None]], style
) -> None:
    names, sidecars = series
    planned = plan_names(names, sidecars, style)

    filed = [entry.name for entry in planned.values()]
    assert len(filed) == len(set(filed)), f"{names} -> {filed}"


@given(_series(), st.sampled_from(["qa", "dcm2niix"]))
def test_a_companion_is_filed_under_its_niftis_stem(
    series: tuple[list[str], dict[str, Sidecar | None]], style
) -> None:
    names, sidecars = series
    planned = plan_names(names, sidecars, style)

    for name, entry in planned.items():
        if name.endswith(".json"):
            nifti = planned[f"{entry.stem}.nii.gz"].name
            assert nifti.removesuffix(".nii.gz") + ".json" == entry.name, name
