"""The DICOM import: the flags it pins, the names it builds, and the files it moves.

Most of this runs against a *stub* dcm2niix -- a script that writes the files a
real conversion would, named on demand. That is deliberate: what `convert.session`
has to get right is everything around the converter (staging, naming, refusing a
destination it would damage, cleaning up after a failure), and driving those
cases through real DICOM would mean synthesizing a study per case. The one test
that does use the real binary is the one that can only be answered by it --
whether the pinned flags actually produce a series the saturation check can read.
"""

import json
import shutil
import stat
import sys
from itertools import pairwise, permutations
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc import cli
from fmriqc.convert import naming
from fmriqc.convert.dcm2niix import PINNED, build_args, find_dcm2niix, run, version
from fmriqc.convert.session import import_dicom
from fmriqc.types import Sidecar

FIXTURE_STUDY = Path(__file__).parent / "fixtures" / "dicom"

# A sidecar with every field the name is built from, as dcm2niix writes them.
FULL_SIDECAR = {
    "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
    "AcquisitionTime": "14:30:12.500000",
    "SeriesNumber": 2,
    "SeriesDescription": "QA_EPI_ISO",
    "ProtocolName": "ep2d_bold_qa",
}


@pytest.fixture
def fake_dcm2niix(tmp_path):
    """Build a stub dcm2niix that writes the outputs a test asks for.

    Takes `{stem: sidecar-or-None}` and writes a NIfTI containing the
    encoded stem for each, plus `<stem>.json` where a sidecar was given, into
    whatever directory the `-o` argument names. Prints dcm2niix's real banner
    line so the version parser has something true to read.
    """

    def build(
        outputs, returncode=0, name="dcm2niix", *, suffix=".nii.gz", companions=None
    ):
        script = tmp_path / name
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            f"outputs = {outputs!r}\n"
            f"companions = {companions or {}!r}\n"
            f"suffix = {suffix!r}\n"
            "args = sys.argv[1:]\n"
            "out = Path(args[args.index('-o') + 1])\n"
            'print("Chris Rorden\'s dcm2niiX version v1.0.20260724 (JP2:OpenJPEG)")\n'
            "for stem, sidecar in outputs.items():\n"
            "    (out / f'{stem}{suffix}').write_bytes(stem.encode())\n"
            "    if sidecar is not None:\n"
            "        (out / f'{stem}.json').write_text(json.dumps(sidecar))\n"
            "for filename, content in companions.items():\n"
            "    (out / filename).write_bytes(content)\n"
            f"sys.exit({returncode})\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    return build


# --------------------------------------------------------------------------
# naming: the four fields, and what happens when one is missing
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# naming.plan: which series keep the name dcm2niix gave them
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# dcm2niix: the flags that are not a matter of taste
# --------------------------------------------------------------------------


def test_every_conversion_pins_the_flags_that_keep_a_series_checkable() -> None:
    """`-l o` above all: see `convert.dcm2niix` for what `-l y` costs.

    Asserted as adjacent pairs rather than mere membership, because `-l` and
    its value are only load-bearing together.
    """
    args = build_args(Path("in"), Path("out"))
    pairs = set(pairwise(args))

    assert {("-l", "o"), ("-g", "i"), ("-b", "y"), ("-w", "2")} <= pairs
    assert args[: len(PINNED)] == list(PINNED)


def test_the_source_directory_is_the_last_argument() -> None:
    """dcm2niix takes its input folder positionally, after every option."""
    assert build_args(Path("study"), Path("out"))[-1] == "study"


def test_anonymizing_defaults_to_keeping_the_dates_the_name_needs() -> None:
    """`-ba o` strips the patient and keeps the dates; `-ba y` would drop both.

    dcm2niix's own default is `y`, so this is a deliberate departure: a QA name
    is built from the series' acquisition date.
    """
    assert "-ba" in build_args(Path("in"), Path("out"))
    for mode, flag in (("pii", "o"), ("all", "y"), ("none", "n")):
        args = build_args(Path("in"), Path("out"), anonymize=mode)
        assert args[args.index("-ba") + 1] == flag


def test_passthrough_arguments_come_after_everything_chosen_here() -> None:
    """Last wins in dcm2niix, so an escape hatch has to be last to be one."""
    args = build_args(Path("in"), Path("out"), extra=["-i", "y"])

    assert args[-3:] == ["-i", "y", "in"]


def test_a_passthrough_that_rescales_the_integers_does_not_pass_quietly() -> None:
    """`-l y` disarms the saturation check without breaking anything visibly.

    It leaves an integer NIfTI, so `QAScan.stored_integer` stays True and the
    loader's storage warning never fires -- the check simply reports a clipped
    acquisition as clean. Overriding the pin is allowed; doing it silently is not.
    """
    with pytest.warns(UserWarning, match="saturation check"):
        build_args(Path("in"), Path("out"), extra=["-l", "y"])


def test_pinning_is_not_re_warned_when_the_passthrough_agrees_with_it() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_args(Path("in"), Path("out"), extra=["-l", "o", "-i", "y"])


def test_the_version_is_read_out_of_dcm2niix_s_own_banner() -> None:
    banner = "Chris Rorden's dcm2niiX version v1.0.20260724 (JP2:OpenJPEG) GCC10"

    assert version(banner) == "v1.0.20260724"
    assert version("no banner here") is None


def test_the_bundled_binary_is_what_an_unconfigured_import_runs() -> None:
    """dcm2niix is a dependency, so `fmri-qa-import DIR` needs nothing else.

    Not skipped when the binary is absent: that it is always there is the point
    of depending on it, so an environment without one is a failure to report.
    """
    assert find_dcm2niix().name.startswith("dcm2niix")


def test_having_no_dcm2niix_at_all_says_how_to_get_one(monkeypatch) -> None:
    """The message is the whole error recovery, so it names all three routes."""
    monkeypatch.setitem(sys.modules, "dcm2niix", None)  # import raises ImportError
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(q.ConversionError) as excinfo:
        find_dcm2niix()

    message = str(excinfo.value)
    assert "reinstall fmri-qa-core" in message
    assert "PATH" in message
    assert "--dcm2niix" in message


def test_a_binary_that_vanishes_between_finding_and_running_is_reported(
    tmp_path,
) -> None:
    """`run` is reachable with a path `find_dcm2niix` never vetted."""
    with pytest.raises(q.ConversionError, match="could not run"):
        run(tmp_path / "gone", ["-o", str(tmp_path)])


def test_naming_a_dcm2niix_that_cannot_be_run_is_reported_not_fallen_past(
    tmp_path,
) -> None:
    """An explicit --dcm2niix is a decision; silently using another would hide it."""
    not_executable = tmp_path / "dcm2niix"
    not_executable.write_text("")

    with pytest.raises(q.ConversionError) as excinfo:
        find_dcm2niix(not_executable)
    assert excinfo.value.stage == "dcm2niix"


# --------------------------------------------------------------------------
# session: staging, filing, and refusing
# --------------------------------------------------------------------------


def test_an_import_files_each_series_under_its_qa_name(tmp_path, fake_dcm2niix) -> None:
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary)

    assert [entry.path.name for entry in result.series] == [
        "20260909_143012_s002_QA_EPI_ISO.nii.gz"
    ]
    assert result.tool_version == "v1.0.20260724"
    assert result.series[0].renamed_from == "2_QA"
    assert result.series[0].series == 2
    assert result.series[0].description == "QA_EPI_ISO"


def test_a_boolean_series_number_is_not_read_as_one(tmp_path, fake_dcm2niix) -> None:
    """A JSON boolean `SeriesNumber` is not a series count: `series` stays None."""
    binary = fake_dcm2niix({"2_QA": {**FULL_SIDECAR, "SeriesNumber": True}})
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary)

    assert result.series[0].series is None


def test_an_import_preserves_both_scans_when_a_qa_name_is_already_retained(
    tmp_path, fake_dcm2niix
) -> None:
    binary = fake_dcm2niix({"raw": {"SeriesNumber": 2}, "s002": None})
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary)

    assert [entry.path.name for entry in result.series] == [
        "raw.nii.gz",
        "s002.nii.gz",
    ]
    assert {entry.path.name: entry.path.read_bytes() for entry in result.series} == {
        "raw.nii.gz": b"raw",
        "s002.nii.gz": b"s002",
    }
    assert all(entry.renamed_from is None for entry in result.series)
    assert json.loads((out / "raw.json").read_text()) == {"SeriesNumber": 2}
    assert not (out / "s002.json").exists()


def test_the_sidecar_travels_with_the_nifti_it_describes(
    tmp_path, fake_dcm2niix
) -> None:
    """A NIfTI filed without its sidecar loses its TR and phase-encode direction."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"

    import_dicom(tmp_path, out, binary=binary)

    stem = "20260909_143012_s002_QA_EPI_ISO"
    assert (out / f"{stem}.nii.gz").exists()
    assert json.loads((out / f"{stem}.json").read_text())["SeriesNumber"] == 2


@pytest.mark.parametrize("stems", [("scan", "scan.repeat"), ("x", "x.nii")])
@pytest.mark.parametrize("suffix", [".nii", ".nii.gz"])
@pytest.mark.parametrize("names", ["qa", "dcm2niix"])
def test_overlapping_stems_keep_each_nifti_and_its_own_companions(
    tmp_path, fake_dcm2niix, stems, suffix, names
) -> None:
    outputs = {stem: {"SeriesNumber": number} for number, stem in enumerate(stems, 1)}
    companions = {
        f"{stem}{extension}": f"{stem}{extension}".encode()
        for stem in stems
        for extension in (".bval", ".bvec", ".trace.txt")
    }
    binary = fake_dcm2niix(outputs, suffix=suffix, companions=companions)
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary, names=names)

    expected_files = {}
    expected_niftis = {}
    for number, stem in enumerate(stems, 1):
        target = f"s{number:03d}" if names == "qa" else stem
        expected_niftis[f"{target}{suffix}"] = stem.encode()
        expected_files[f"{target}{suffix}"] = stem.encode()
        expected_files[f"{target}.json"] = json.dumps(outputs[stem]).encode()
        for extension in (".bval", ".bvec", ".trace.txt"):
            expected_files[f"{target}{extension}"] = companions[f"{stem}{extension}"]
    assert {entry.path.name: entry.path.read_bytes() for entry in result.series} == (
        expected_niftis
    )
    assert {path.name: path.read_bytes() for path in out.iterdir()} == expected_files


@pytest.mark.parametrize("force", [False, True])
def test_a_collision_between_companions_is_refused_before_any_file_moves(
    tmp_path, fake_dcm2niix, force
) -> None:
    """Unique series names can still map two companions to `a.b.json`."""
    binary = fake_dcm2niix(
        {"x": {"SeriesDescription": "a"}, "a.b": {}},
        companions={"x.b.json": b"companion of x"},
    )
    out = tmp_path / "nifti"
    out.mkdir()
    existing = out / "a.b.json"
    existing.write_bytes(b"an earlier import")

    with pytest.raises(q.ConversionError, match="would share destinations") as excinfo:
        import_dicom(tmp_path, out, binary=binary, force=force)

    assert excinfo.value.stage == "destination"
    assert "a.b.json" in str(excinfo.value)
    assert {path.name: path.read_bytes() for path in out.iterdir()} == {
        "a.b.json": b"an earlier import"
    }


@pytest.mark.parametrize("force", [False, True])
def test_existing_companions_are_checked_at_their_own_series_destination(
    tmp_path, fake_dcm2niix, force
) -> None:
    binary = fake_dcm2niix(
        {"scan": {"SeriesNumber": 1}, "scan.repeat": {"SeriesNumber": 2}},
        companions={"scan.repeat.trace.txt": b"new companion"},
    )
    out = tmp_path / "nifti"
    out.mkdir()
    existing = out / "s002.trace.txt"
    existing.write_bytes(b"an earlier import")

    if force:
        result = import_dicom(tmp_path, out, binary=binary, force=True)
        assert existing.read_bytes() == b"new companion"
        assert {
            entry.path.name: entry.path.read_bytes() for entry in result.series
        } == {
            "s001.nii.gz": b"scan",
            "s002.nii.gz": b"scan.repeat",
        }
    else:
        with pytest.raises(q.ConversionError, match=r"s002\.trace\.txt"):
            import_dicom(tmp_path, out, binary=binary)
        assert {path.name: path.read_bytes() for path in out.iterdir()} == {
            "s002.trace.txt": b"an earlier import"
        }


def test_nothing_of_the_staging_directory_survives_a_successful_import(
    tmp_path, fake_dcm2niix
) -> None:
    out = tmp_path / "nifti"

    import_dicom(tmp_path, out, binary=fake_dcm2niix({"2_QA": FULL_SIDECAR}))

    assert [p.name for p in out.iterdir() if p.is_dir()] == []


def test_the_staging_directory_is_removed_when_the_converter_fails(
    tmp_path, fake_dcm2niix
) -> None:
    """A failed import must not leave a half-converted directory behind."""
    out = tmp_path / "nifti"
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR}, returncode=2)

    with pytest.raises(q.ConversionError, match="exited 2"):
        import_dicom(tmp_path, out, binary=binary)
    assert not out.exists()  # not even the directory it staged into


def test_an_import_refuses_a_destination_it_would_overwrite(
    tmp_path, fake_dcm2niix
) -> None:
    """And leaves every existing file exactly as it was.

    The names come out of the DICOM, so they cannot be checked before
    converting the way `cli.destinations` checks an `--artifact` path. Checking
    them before the *move* is what keeps the destination all-or-nothing.
    """
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    existing = out / "20260909_143012_s002_QA_EPI_ISO.nii.gz"
    existing.write_text("an earlier import")

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary)

    assert excinfo.value.stage == "destination"
    assert existing.read_text() == "an earlier import"


def test_force_overwrites_what_the_refusal_protects(tmp_path, fake_dcm2niix) -> None:
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    existing = out / "20260909_143012_s002_QA_EPI_ISO.nii.gz"
    existing.write_text("an earlier import")

    import_dicom(tmp_path, out, binary=binary, force=True)

    assert existing.read_bytes() == b"2_QA"


# --------------------------------------------------------------------------
# filing: a move that starts and cannot finish
# --------------------------------------------------------------------------

QA_NIFTI = "20260909_143012_s002_QA_EPI_ISO.nii.gz"
QA_JSON = "20260909_143012_s002_QA_EPI_ISO.json"


def _refusing(monkeypatch, refuse) -> list[tuple[str, str]]:
    """Make the filing rename refuse whenever `refuse(source, target)` says so.

    Stands in for `replace_patiently` where `convert.session` looks it up, so
    no test waits out the real ladder; every rename asked for is logged as
    `(source name, target name)`, refused or not.
    """
    asked: list[tuple[str, str]] = []

    def replace(source: Path, target: Path) -> None:
        asked.append((source.name, target.name))
        if refuse(source, target):
            raise PermissionError(13, "held open by a sync client")
        source.replace(target)

    monkeypatch.setattr("fmriqc.convert.session.replace_patiently", replace)
    return asked


def _listing(directory: Path) -> dict[str, bytes | None]:
    """Everything under `directory`, by relative name: bytes, or None for a directory.

    Directories count, so that "as it was" notices an emptied set-aside
    directory left behind as surely as a file.
    """
    return {
        str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
        for path in sorted(directory.rglob("*"))
    }


def test_a_move_that_fails_part_way_is_undone(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """Files move in name order: the sidecar lands, the NIfTI is refused, and
    the sidecar goes back."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / "notes.txt").write_text("the caller's own file")
    before = _listing(out)
    asked = _refusing(
        monkeypatch, lambda _, target: target.parent == out and target.name == QA_NIFTI
    )

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary)

    assert excinfo.value.stage == "destination"
    assert f"could not move {QA_NIFTI}" in str(excinfo.value)
    assert "held open by a sync client" in str(excinfo.value)
    assert "was undone" in str(excinfo.value)
    assert _listing(out) == before
    # It really had been filed, and really was withdrawn -- not never moved.
    assert ("2_QA.json", QA_JSON) in asked
    assert (QA_JSON, "2_QA.json") in asked


def test_a_fresh_destination_is_removed_again_when_the_move_is_undone(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    _refusing(monkeypatch, lambda _, target: target.name == QA_NIFTI)

    with pytest.raises(q.ConversionError, match="was undone"):
        import_dicom(tmp_path, out, binary=binary)

    assert not out.exists()


def test_a_forced_move_that_fails_puts_back_what_it_had_replaced(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """The case that matters most: never a new scan beside an old sidecar."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    (out / QA_JSON).write_text("an earlier sidecar")
    before = _listing(out)
    # The earlier sidecar is set aside and the new one filed, the earlier scan
    # is set aside -- and then the new scan is refused.
    _refusing(
        monkeypatch,
        lambda source, target: source.name == "2_QA.nii.gz" and target.parent == out,
    )

    with pytest.raises(q.ConversionError, match="was undone"):
        import_dicom(tmp_path, out, binary=binary, force=True)

    assert _listing(out) == before


def test_nothing_is_filed_until_everything_in_its_way_has_been_set_aside(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """The order is the safety: a refused set-aside must find nothing new filed.

    Set one aside, file its replacement, go on to the next -- and the earlier
    scan that will not move is left beside a new sidecar, which may then refuse
    to come back out: a scan described by the wrong series, under final names,
    with nothing to say so. Done in two passes there is nothing to withdraw.
    """
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    (out / QA_JSON).write_text("an earlier sidecar")
    before = _listing(out)

    def refuse(source: Path, target: Path) -> bool:
        setting_the_scan_aside = source == out / QA_NIFTI
        withdrawing_anything = source.parent == out and target.name.startswith("2_QA")
        return setting_the_scan_aside or withdrawing_anything

    asked = _refusing(monkeypatch, refuse)

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary, force=True)

    assert f"could not set the existing {QA_NIFTI} aside" in str(excinfo.value)
    assert "was undone" in str(excinfo.value)
    assert not any(source.startswith("2_QA") for source, _ in asked)
    assert _listing(out) == before


def test_a_forced_move_refused_at_its_first_file_puts_everything_back(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """Everything is set aside and nothing filed: the undo starts from there."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    (out / QA_JSON).write_text("an earlier sidecar")
    before = _listing(out)
    _refusing(
        monkeypatch,
        lambda source, target: source.name == "2_QA.json" and target.parent == out,
    )

    with pytest.raises(q.ConversionError, match="was undone"):
        import_dicom(tmp_path, out, binary=binary, force=True)

    assert _listing(out) == before


def test_a_series_already_filed_is_withdrawn_when_a_later_one_is_refused(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """All or nothing is a promise about the session, not about each series."""
    later = FULL_SIDECAR | {
        "SeriesNumber": 3,
        "AcquisitionDateTime": "2026-09-09T14:41:00.000000",
        "AcquisitionTime": "14:41:00.000000",
    }
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR, "3_QA": later})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / "notes.txt").write_text("the caller's own file")
    before = _listing(out)
    asked = _refusing(
        monkeypatch,
        lambda source, target: source.name == "3_QA.nii.gz" and target.parent == out,
    )

    with pytest.raises(q.ConversionError, match="was undone"):
        import_dicom(tmp_path, out, binary=binary)

    # The whole of series 2 had landed, and the whole of it went back.
    assert ("2_QA.nii.gz", QA_NIFTI) in asked
    assert (QA_NIFTI, "2_QA.nii.gz") in asked
    assert _listing(out) == before


def test_a_set_aside_directory_that_will_not_go_does_not_hide_the_error(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """Removing it is cleanup; what the caller needs is the state of the import."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    real = Path.rmdir

    def rmdir(self: Path) -> None:
        if self.name.startswith(".fmri-qa-replaced-"):
            raise PermissionError(13, "held open by a sync client")
        real(self)

    monkeypatch.setattr(Path, "rmdir", rmdir)
    _refusing(
        monkeypatch,
        lambda source, target: source.name == "2_QA.nii.gz" and target.parent == out,
    )

    with pytest.raises(q.ConversionError, match="was undone"):
        import_dicom(tmp_path, out, binary=binary, force=True)

    assert (out / QA_NIFTI).read_text() == "an earlier scan"


def test_replaced_files_that_cannot_be_deleted_are_not_left_silently(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """The import succeeded, so this is a warning -- but it is not nothing."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    real = shutil.rmtree

    def rmtree(path: Path, **kwargs: object) -> None:
        if not Path(path).name.startswith(".fmri-qa-replaced-"):
            real(path, **kwargs)

    monkeypatch.setattr("fmriqc.convert.session.shutil.rmtree", rmtree)

    with pytest.warns(UserWarning, match="holds the files this import replaced"):
        result = import_dicom(tmp_path, out, binary=binary, force=True)

    assert [series.path.name for series in result.series] == [QA_NIFTI]
    assert (out / QA_NIFTI).read_bytes() == b"2_QA"
    (aside,) = out.glob(".fmri-qa-replaced-*")
    assert (aside / QA_NIFTI).read_text() == "an earlier scan"


def test_a_forced_move_that_succeeds_leaves_nothing_set_aside(
    tmp_path, fake_dcm2niix
) -> None:
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    (out / QA_JSON).write_text("an earlier sidecar")

    import_dicom(tmp_path, out, binary=binary, force=True)

    assert sorted(p.name for p in out.iterdir()) == [QA_JSON, QA_NIFTI]
    assert (out / QA_NIFTI).read_bytes() == b"2_QA"
    assert json.loads((out / QA_JSON).read_text()) == FULL_SIDECAR


def test_a_move_that_cannot_be_undone_says_exactly_what_is_left(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """The holder that refused the scan now refuses to let the sidecar go back.

    Nothing more is forced, and nothing is put back around it: the earlier scan
    *could* be restored, and would then sit beside this import's sidecar looking
    like a matching pair. So the new sidecar stays, named as this import's, and
    both earlier files are kept, set aside, where nothing will read them as a
    result.
    """
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    (out / QA_JSON).write_text("an earlier sidecar")

    def refuse(source: Path, target: Path) -> bool:
        filing_the_scan = source.name == "2_QA.nii.gz" and target.parent == out
        withdrawing_the_sidecar = source == out / QA_JSON and target.name == "2_QA.json"
        return filing_the_scan or withdrawing_the_sidecar

    _refusing(monkeypatch, refuse)

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary, force=True)

    message = str(excinfo.value)
    assert "undoing the import failed too" in message
    assert f"{QA_JSON} in it are from this import" in message
    (aside,) = out.glob(".fmri-qa-replaced-*")
    assert f"the {QA_JSON}, {QA_NIFTI} it replaced are kept in {aside}" in message

    left = _listing(out)
    assert json.loads(left.pop(QA_JSON) or b"") == FULL_SIDECAR
    assert left == {
        aside.name: None,
        f"{aside.name}/{QA_JSON}": b"an earlier sidecar",
        f"{aside.name}/{QA_NIFTI}": b"an earlier scan",
    }


def test_an_unforced_move_that_cannot_be_undone_names_what_it_left(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """Nothing was replaced, so nothing is set aside: only this import's file."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()

    def refuse(source: Path, target: Path) -> bool:
        filing_the_scan = source.name == "2_QA.nii.gz" and target.parent == out
        withdrawing_the_sidecar = source == out / QA_JSON
        return filing_the_scan or withdrawing_the_sidecar

    _refusing(monkeypatch, refuse)

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary)

    message = str(excinfo.value)
    assert "undoing the import failed too" in message
    assert f"{QA_JSON} in it are from this import" in message
    assert "it replaced" not in message
    assert sorted(p.name for p in out.iterdir()) == [QA_JSON]


def test_a_replaced_file_that_cannot_be_put_back_is_kept_and_named(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """Everything of this import is withdrawn; one earlier file will not go back.

    The rest are restored -- there is no new file left for them to be mistaken
    beside -- and the one that would not move is kept where it is, by name.
    """
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"
    out.mkdir()
    (out / QA_NIFTI).write_text("an earlier scan")
    (out / QA_JSON).write_text("an earlier sidecar")

    def refuse(source: Path, target: Path) -> bool:
        filing_the_scan = source.name == "2_QA.nii.gz" and target.parent == out
        restoring_the_sidecar = (
            ".fmri-qa-replaced-" in str(source) and target == out / QA_JSON
        )
        return filing_the_scan or restoring_the_sidecar

    _refusing(monkeypatch, refuse)

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary, force=True)

    message = str(excinfo.value)
    (aside,) = out.glob(".fmri-qa-replaced-*")
    assert "undoing the import failed too" in message
    assert "from this import" not in message
    assert f"the {QA_JSON} it replaced are kept in {aside}" in message
    assert _listing(out) == {
        QA_NIFTI: b"an earlier scan",
        aside.name: None,
        f"{aside.name}/{QA_JSON}": b"an earlier sidecar",
    }


def test_dcm2niix_names_are_kept_verbatim_when_asked_for(
    tmp_path, fake_dcm2niix
) -> None:
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary, names="dcm2niix")

    assert [entry.path.name for entry in result.series] == ["2_QA.nii.gz"]
    assert result.series[0].renamed_from is None


def test_a_series_with_no_readable_sidecar_still_gets_imported(
    tmp_path, fake_dcm2niix
) -> None:
    """It loses its QA name, not its conversion."""
    binary = fake_dcm2niix({"2_QA": None})
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary)

    assert [entry.path.name for entry in result.series] == ["2_QA.nii.gz"]
    assert result.series[0].series is None


def test_a_source_that_is_not_a_directory_is_refused_before_anything_runs(
    tmp_path,
) -> None:
    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path / "nowhere", tmp_path / "out")

    assert excinfo.value.stage == "source"
    assert not (tmp_path / "out").exists()


def test_a_destination_that_cannot_be_made_is_a_conversion_error_not_a_crash(
    tmp_path, fake_dcm2niix
) -> None:
    """A file already sitting where the destination goes must not raise `OSError`."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    blocked = tmp_path / "out"
    blocked.write_text("not a directory")

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, blocked, binary=binary)

    assert excinfo.value.stage == "destination"


# --------------------------------------------------------------------------
# the real converter, on real DICOM
# --------------------------------------------------------------------------


def test_a_real_study_converts_to_the_integer_nifti_the_metrics_need(
    tmp_path,
) -> None:
    """The end the stub cannot reach: does the pinned `-l o` actually hold?

    `detect_saturation` can only find an ADC rail in a series that still carries
    the scanner's integers, and `QAScan.stored_integer` decides that from the
    NIfTI datatype. If a future dcm2niix, or a stray `~/.dcm2nii.ini`, made the
    conversion write floats or rescale, every imported series would silently
    become one the saturation check declines to answer -- so the datatype is
    asserted here rather than assumed.

    See `fixtures/dicom/generate.py` for the synthetic study: two series
    numbered 2 and 11, one of them with a description that needs sanitizing.
    """
    nibabel = pytest.importorskip("nibabel")
    out = tmp_path / "nifti"

    result = import_dicom(FIXTURE_STUDY, out, binary=find_dcm2niix())

    assert [entry.path.name for entry in result.series] == [
        "20260909_143012_s002_QA_EPI_ISO.nii.gz",
        "20260909_145533_s011_QA_EPI_32ch_rep.nii.gz",
    ]
    for entry in result.series:
        scan = nibabel.load(entry.path)
        assert scan.header.get_data_dtype().kind in "iu"  # the saturation gate
        assert scan.dataobj.slope == 1.0  # not rescaled on the way through
        assert q.QAScan.from_nifti(entry.path).stored_integer


def test_the_real_study_is_named_by_its_own_series_times_not_the_study_s(
    tmp_path,
) -> None:
    """dcm2niix's `%t` is the study's time, identical for both series.

    The fixture gives the two series distinct `SeriesTime`s under one
    `StudyTime`, so a name templated on `%t` cannot tell them apart in time and
    a name built from the sidecar can. That difference is the reason
    `convert.naming` exists, so it is checked against the real converter.
    """
    templated = import_dicom(
        FIXTURE_STUDY, tmp_path / "raw", binary=find_dcm2niix(), names="dcm2niix"
    )
    named = import_dicom(FIXTURE_STUDY, tmp_path / "qa", binary=find_dcm2niix())

    study_times = {name.split("_")[0] for name in _stems(templated)}
    series_times = {stem.split("_")[1] for stem in _stems(named)}
    assert len(study_times) == 1  # `%t`: one time for the whole session
    assert len(series_times) == 2  # the sidecar: one time per series


def _stems(result: q.ImportResult) -> list[str]:
    return [entry.path.name.split(".")[0] for entry in result.series]


def test_the_committed_fixture_study_is_still_there() -> None:
    """Guard the guard: a vanished fixture must not read as a passing import."""
    assert len(list(FIXTURE_STUDY.rglob("*.dcm"))) == 8


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------


def test_import_main_lists_every_series_it_wrote(tmp_path, fake_dcm2niix, capsys):
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"

    rc = cli.import_main([str(tmp_path), "-o", str(out), "--dcm2niix", str(binary)])

    printed = capsys.readouterr().out
    assert rc == 0
    assert "20260909_143012_s002_QA_EPI_ISO.nii.gz" in printed
    assert "v1.0.20260724" in printed  # which dcm2niix did the work
    assert f"fmri-qa {out}/*.nii.gz" in printed  # the paste-able next step


def test_import_main_names_the_series_that_kept_dcm2niix_s_name(
    tmp_path, fake_dcm2niix, capsys
):
    """An unrenamed file in an otherwise uniform listing reads as a bug.

    It is a decision `naming.plan` made, so the command says which files and
    why rather than leaving the reader to notice.
    """
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR, "9_odd": {}})

    cli.import_main(
        [str(tmp_path), "-o", str(tmp_path / "nifti"), "--dcm2niix", str(binary)]
    )

    assert "1 of 2 series kept dcm2niix's name" in capsys.readouterr().err


def test_import_main_says_nothing_about_names_it_was_told_to_keep(
    tmp_path, fake_dcm2niix, capsys
):
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})

    cli.import_main(
        [
            str(tmp_path),
            "-o",
            str(tmp_path / "nifti"),
            "--dcm2niix",
            str(binary),
            "--names",
            "dcm2niix",
        ]
    )

    assert "kept dcm2niix's name" not in capsys.readouterr().err


def test_import_main_reports_a_bad_source_without_a_traceback(tmp_path, capsys):
    rc = cli.import_main([str(tmp_path / "nowhere"), "-o", str(tmp_path / "out")])

    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_import_main_reports_a_destination_that_cannot_be_made_without_a_traceback(
    tmp_path, fake_dcm2niix, capsys
):
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    blocked = tmp_path / "out"
    blocked.write_text("not a directory")

    rc = cli.import_main([str(tmp_path), "-o", str(blocked), "--dcm2niix", str(binary)])

    err = capsys.readouterr().err
    assert rc == 1
    assert "ERROR" in err
    assert "Traceback" not in err


def test_import_main_fails_when_a_directory_holds_no_dicom(
    tmp_path, fake_dcm2niix, capsys
):
    """An empty conversion is a failed import, not a successful empty one."""
    binary = fake_dcm2niix({})

    rc = cli.import_main(
        [str(tmp_path), "-o", str(tmp_path / "nifti"), "--dcm2niix", str(binary)]
    )

    assert rc == 1
    assert "no DICOM series converted" in capsys.readouterr().err


def test_import_main_defaults_its_output_to_a_directory_named_for_the_source(
    tmp_path, fake_dcm2niix, monkeypatch, capsys
):
    """The one-argument call has to put a session somewhere predictable."""
    study = tmp_path / "QA_20260909"
    study.mkdir()
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    monkeypatch.chdir(tmp_path)

    rc = cli.import_main([str(study), "--dcm2niix", str(binary)])

    assert rc == 0
    assert (tmp_path / "QA_20260909_nifti").is_dir()
    assert "QA_20260909_nifti" in capsys.readouterr().out


def test_import_main_warns_when_a_passthrough_disarms_the_saturation_check(
    tmp_path, fake_dcm2niix, capsys
):
    """The warning has to reach the operator, not just the warnings filter."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})

    cli.import_main(
        [
            str(tmp_path),
            "-o",
            str(tmp_path / "nifti"),
            "--dcm2niix",
            str(binary),
            "--dcm2niix-arg=-l",
            "--dcm2niix-arg=y",
        ]
    )

    assert "saturation check" in capsys.readouterr().err


def test_import_main_version_prints_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.import_main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("fmri-qa-import ")


def test_log_shows_what_the_converter_actually_said(
    tmp_path, fake_dcm2niix, capsys
) -> None:
    """dcm2niix's own diagnostics are the ones that name a DICOM problem."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    argv = [str(tmp_path), "-o", str(tmp_path / "nifti"), "--dcm2niix", str(binary)]

    cli.import_main(argv)
    assert "Chris Rorden" not in capsys.readouterr().err

    cli.import_main([*argv, "--force", "--log"])
    assert "Chris Rorden" in capsys.readouterr().err


def test_a_destination_the_caller_already_had_survives_a_failed_import(
    tmp_path, fake_dcm2niix
) -> None:
    """Only a directory this call created is cleaned up, and only while empty."""
    out = tmp_path / "nifti"
    out.mkdir()
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR}, returncode=2)

    with pytest.raises(q.ConversionError):
        import_dicom(tmp_path, out, binary=binary)

    assert out.is_dir()
