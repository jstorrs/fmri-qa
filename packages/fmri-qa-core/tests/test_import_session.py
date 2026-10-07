"""`convert.session`: staging, naming, filing and refusing.

Runs against a *stub* dcm2niix -- the `fake_dcm2niix` fixture, a script that
writes the files a real conversion would, named on demand. What the session has
to get right is everything around the converter: staging, naming, refusing a
destination it would damage, cleaning up after a failure and -- when a move
starts and cannot finish -- undoing it or saying exactly what is left. Driving
those cases through real DICOM would mean synthesizing a study per case.
"""

import json
import shutil
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc.convert.session import import_dicom

# A sidecar with every field the name is built from, as dcm2niix writes them.
FULL_SIDECAR = {
    "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
    "AcquisitionTime": "14:30:12.500000",
    "SeriesNumber": 2,
    "SeriesDescription": "QA_EPI_ISO",
    "ProtocolName": "ep2d_bold_qa",
}


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


def test_a_series_lists_its_nifti_then_its_sidecar(tmp_path, fake_dcm2niix) -> None:
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"

    (series,) = import_dicom(tmp_path, out, binary=binary).series

    stem = "20260909_143012_s002_QA_EPI_ISO"
    assert series.files == (out / f"{stem}.nii.gz", out / f"{stem}.json")


def test_each_overlapping_series_lists_only_its_own_files(
    tmp_path, fake_dcm2niix
) -> None:
    stems = ("scan", "scan.rep")
    binary = fake_dcm2niix(
        {stem: {"SeriesNumber": number} for number, stem in enumerate(stems, 1)},
        companions={f"{stem}.bval": b"" for stem in stems},
    )
    out = tmp_path / "nifti"

    result = import_dicom(tmp_path, out, binary=binary, names="dcm2niix")

    assert {
        entry.path.name: [f.name for f in entry.files] for entry in result.series
    } == {
        "scan.nii.gz": ["scan.nii.gz", "scan.bval", "scan.json"],
        "scan.rep.nii.gz": ["scan.rep.nii.gz", "scan.rep.bval", "scan.rep.json"],
    }


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


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("symlink", [False, True])
@pytest.mark.parametrize("target_name", ["z.nii.gz", "z.json", "z.trace.txt"])
def test_directory_targets_are_refused_before_any_file_moves(
    tmp_path, fake_dcm2niix, monkeypatch, force, symlink, target_name
) -> None:
    """Even a later series' companion must be checked before replacing a file."""
    binary = fake_dcm2niix(
        {"a": None, "z": FULL_SIDECAR}, companions={"z.trace.txt": b"new companion"}
    )
    out = tmp_path / "nifti"
    out.mkdir()
    (out / "a.nii.gz").write_bytes(b"an earlier scan")
    target = out / target_name
    directory = tmp_path / "linked-directory" if symlink else target
    directory.mkdir()
    sentinel = directory / "keep.txt"
    sentinel.write_bytes(b"the caller's own file")
    if symlink:
        try:
            target.symlink_to(directory, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"cannot create directory symlinks: {exc}")
    before = _listing(out)
    asked = _refusing(monkeypatch, lambda _source, _target: False)

    with pytest.raises(q.ConversionError) as excinfo:
        import_dicom(tmp_path, out, binary=binary, names="dcm2niix", force=force)

    assert excinfo.value.stage == "destination"
    assert target_name in str(excinfo.value)
    assert "director" in str(excinfo.value)
    assert asked == []
    assert _listing(out) == before
    assert sentinel.read_bytes() == b"the caller's own file"
    assert target.is_dir()
    if symlink:
        assert target.is_symlink()
        assert target.readlink() == directory


def test_a_move_that_fails_part_way_is_undone(
    tmp_path, fake_dcm2niix, monkeypatch
) -> None:
    """Files move in name order: the sidecar lands, the NIfTI is refused and
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
