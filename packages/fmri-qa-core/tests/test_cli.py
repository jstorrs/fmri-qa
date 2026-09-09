"""End-to-end smoke tests for the calculation command-line entry points.

These exercise the layers unit tests skip: argument wiring, the batch loop and
its error handling, the JSON document, and saving artifacts to disk. A tiny
synthetic phantom is written as a NIfTI + BIDS sidecar (see `conftest`) so
`QAScan.from_nifti` runs its real file-I/O path. Rendering those artifacts into
a PDF is `fmri-qa-report`'s job and is tested there.
"""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc import cli
from fmriqc.cli import table
from fmriqc.cli.record import metric_record


def test_main_prints_table_and_succeeds(tmp_path, write_scan, capsys) -> None:
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SNR" in out and "SFNR" in out and "fwPE" in out  # the header row
    assert "scan.nii.gz" in out  # the scan's data row


def test_main_reports_bad_file_and_continues_batch(
    tmp_path, write_scan, capsys
) -> None:
    good = write_scan(tmp_path, name="good")
    bad = tmp_path / "missing.nii.gz"  # no file, no sidecar
    rc = cli.main([str(bad), good, "--roi-size", "9"])
    captured = capsys.readouterr()
    assert rc == 1  # a failure makes the batch exit non-zero
    assert "ERROR" in captured.err and "missing.nii.gz" in captured.err
    assert "good.nii.gz" in captured.out  # the good scan still ran


def test_main_saves_a_loadable_artifact(tmp_path, write_scan, capsys) -> None:
    out = tmp_path / "qa.npz"
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--artifact", str(out)])
    assert rc == 0
    assert f"# wrote {out}" in capsys.readouterr().out
    artifact = q.load_artifact(out)
    assert artifact.provenance.scan == "scan.nii.gz"
    assert artifact.settings.roi_size == 9
    assert artifact.measurements.snr > 0


def test_main_saves_one_artifact_per_scan_in_a_batch(
    tmp_path, write_scan, capsys
) -> None:
    first = write_scan(tmp_path, name="first")
    second = write_scan(tmp_path, name="second", seed=3)
    out = tmp_path / "artifacts"
    rc = cli.main([first, second, "--roi-size", "9", "--artifact", str(out)])
    assert rc == 0
    written = sorted(p.name for p in out.glob("*.npz"))
    assert written == ["first.qa.npz", "second.qa.npz"]
    assert q.load_artifact(out / "first.qa.npz").provenance.scan == "first.nii.gz"


def test_main_refuses_a_batch_whose_artifacts_would_collide(
    tmp_path, write_scan, capsys
) -> None:
    """Same-named scans from different directories must not overwrite silently.

    A batch names each artifact after the scan's stem, so `a/scan.nii.gz` and
    `b/scan.nii.gz` land on one file: the second analysis replaces the first and
    a later `fmri-qa-report BASE/*.npz` renders a packet quietly missing a scan.
    The run is refused up front instead, before any analysis is done.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = write_scan(tmp_path / "a", name="scan")
    second = write_scan(tmp_path / "b", name="scan", seed=3)
    out = tmp_path / "artifacts"

    rc = cli.main([first, second, "--roi-size", "9", "--artifact", str(out)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "would both be saved as" in err
    assert not out.exists()  # refused before analyzing, so nothing was written


def test_main_refuses_an_artifact_that_would_overwrite_the_scan(
    tmp_path, write_scan, capsys, monkeypatch
) -> None:
    """`--artifact` naming the input must fail before anything is read or written.

    The scan is loaded first and the archive is moved over its destination last,
    so without the guard the run succeeds and leaves an `.npz` where the NIfTI
    was. The relative spelling is the one a shell produces, and it must not
    slip past a comparison of the literal strings.
    """
    scan = Path(write_scan(tmp_path))
    before = scan.read_bytes()
    monkeypatch.chdir(tmp_path)

    rc = cli.main([str(scan), "--roi-size", "9", "--artifact", f"./{scan.name}"])

    assert rc == 1
    captured = capsys.readouterr()
    assert "would overwrite the input" in captured.err
    assert "scan" not in captured.out  # refused before the table was printed
    assert scan.read_bytes() == before


def test_main_refuses_an_artifact_that_would_overwrite_the_sidecar(
    tmp_path, write_scan, capsys
) -> None:
    """The sidecar is read too, so it is an input the output must not replace."""
    scan = write_scan(tmp_path)
    sidecar = tmp_path / "scan.json"
    before = sidecar.read_bytes()
    rc = cli.main([scan, "--roi-size", "9", "--artifact", str(sidecar)])
    assert rc == 1
    assert "would overwrite the input" in capsys.readouterr().err
    assert sidecar.read_bytes() == before


def test_main_refuses_a_batch_destination_that_is_another_input(
    tmp_path, write_scan, capsys
) -> None:
    """Every destination is checked against every input, not only its own scan.

    A batch names `a.nii.gz`'s artifact `BASE/a.qa.npz`; if that file is itself
    one of the inputs, analyzing `a.nii.gz` would replace it. The whole run is
    refused, so the other input is never analyzed either.
    """
    scan = write_scan(tmp_path, name="a")
    other = tmp_path / "a.qa.npz"  # named like the batch's output for `a`
    other.write_bytes(b"not a scan, but an input all the same")

    rc = cli.main([scan, str(other), "--roi-size", "9", "--artifact", str(tmp_path)])

    assert rc == 1
    assert "would overwrite the input" in capsys.readouterr().err
    assert other.read_bytes() == b"not a scan, but an input all the same"


def test_main_allows_a_batch_of_distinctly_named_scans(
    tmp_path, write_scan, capsys
) -> None:
    """The guard keys on the destination, not on the directory: no false alarm."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = write_scan(tmp_path / "a", name="run1")
    second = write_scan(tmp_path / "b", name="run2", seed=3)
    out = tmp_path / "artifacts"
    rc = cli.main([first, second, "--roi-size", "9", "--artifact", str(out)])
    assert rc == 0
    assert sorted(p.name for p in out.glob("*.npz")) == ["run1.qa.npz", "run2.qa.npz"]


def test_main_reports_artifact_failure_without_a_traceback(
    tmp_path, write_scan, capsys
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")  # a file where a parent dir must go
    rc = cli.main(
        [
            write_scan(tmp_path),
            "--roi-size",
            "9",
            "--artifact",
            str(blocked / "qa.npz"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR: could not write artifact" in captured.err
    assert "Traceback" not in captured.err


def test_main_reports_a_refused_artifact_without_a_traceback(
    tmp_path, write_scan, capsys, monkeypatch
) -> None:
    """An artifact the reader would refuse is a per-scan error, and the run says so.

    Nothing the CLI computes should trip this, so the analysis is stubbed to
    hand back an artifact with a text echo time; what is under test is that the
    refusal is reported like any other write failure and the batch goes on.
    """
    real = q.analyze

    def broken(*args, **kwargs):
        artifact = real(*args, **kwargs)
        return replace(artifact, provenance=replace(artifact.provenance, te="0.03"))

    monkeypatch.setattr(q, "analyze", broken)
    out = tmp_path / "qa.npz"
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--artifact", str(out)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR: could not write artifact" in captured.err
    assert "provenance.te" in captured.err
    assert "Traceback" not in captured.err
    assert not out.exists()


def test_json_emits_a_parseable_document(tmp_path, write_scan, capsys) -> None:
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    doc = json.loads(captured.out)  # stdout is pure JSON, nothing else
    assert doc["schema_version"] == 6
    assert doc["config"]["detrend"] == "poly"
    assert "version" in doc["config"]
    assert len(doc["scans"]) == 1
    scan = doc["scans"][0]
    assert scan["scan"] == "scan.nii.gz"
    assert scan["snr"] > 0 and scan["pe_axis"] == 1
    assert "# detrend" in captured.err  # the banner moved off stdout


def test_json_record_says_what_series_the_numbers_describe(
    tmp_path, write_scan, capsys
) -> None:
    """A stored row must be identifiable and its frame indices mappable.

    `outlier_worst_frame` counts from the analyzed series, so on its own it
    names a volume nobody can find in the acquisition again; `n_trimmed` is what
    turns it back into an acquired volume number. The source path and TR/frame
    count let a trend database key and interpret the row without the artifact.
    """
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--json"])
    assert rc == 0
    scan = json.loads(capsys.readouterr().out)["scans"][0]
    assert scan["source"].endswith("scan.nii.gz")
    assert scan["tr"] == 2.0
    assert scan["n_frames"] == 38  # 40 volumes, 5 s of warm-up dropped at TR 2 s
    assert scan["n_trimmed"] == 2
    assert scan["slice_index"] == 1  # the middle of the fixture's three planes
    assert scan["phantom_contrast"] > 4.0  # beside the verdict it was reached from
    assert 0 <= scan["outlier_worst_frame"] < scan["n_frames"]
    assert scan["datetime"] is None  # the sidecar carries no acquisition time


def test_json_record_carries_the_localization_verdicts(
    tmp_path, write_scan, capsys
) -> None:
    """A consumer must be able to tell measurements from measurements of air.

    The report says so on the page; a trend database reading `--json` had no way
    to know, and would file a scan whose phantom mask collapsed alongside good
    ones. The measured fraction rides along with the verdicts so a consumer can
    set its own bar.
    """
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--json"])
    assert rc == 0
    scan = json.loads(capsys.readouterr().out)["scans"][0]
    assert scan["phantom_mask_ok"] is True
    assert scan["roi_inside_phantom"] is True
    assert 0.0 < scan["phantom_fraction"] < 0.95


def test_table_flags_a_localization_failure(tmp_path, write_scan, capsys) -> None:
    """The `loc` column names what failed, ahead of the numbers it invalidates.

    An oversized ROI still produces a full row of plausible-looking metrics --
    measured, at the corners, on background. The warning that says so is
    transient; the row must carry it.
    """
    rc = cli.main([write_scan(tmp_path), "--roi-size", "31"])
    captured = capsys.readouterr()
    header, _rule, row = captured.out.splitlines()[1:4]
    assert rc == 0
    assert "loc" in header
    assert "ROI" in row
    # the transient form of the same news, now attributed (see `print_warnings`)
    assert "scan.nii.gz: warning: " in captured.err
    assert "not fully inside the phantom" in captured.err


def test_batch_warnings_name_the_scan_that_raised_them(
    tmp_path, write_scan, capsys
) -> None:
    """A batch's warnings are useless unless they say which scan they are about.

    Python's default formatter prints the `warnings.warn` call site inside this
    package and the category, so two scans warning about the same thing produce
    two identical lines naming a source file the operator does not have. Each is
    reprinted on stderr against the scan's name instead.
    """
    first = write_scan(tmp_path, name="first")
    second = write_scan(tmp_path, name="second", seed=3)

    rc = cli.main([first, second, "--roi-size", "31"])

    assert rc == 0
    err = capsys.readouterr().err
    attributed = [
        line for line in err.splitlines() if "not fully inside the phantom" in line
    ]
    assert len(attributed) == 2
    assert attributed[0].startswith("first.nii.gz: warning: ")
    assert attributed[1].startswith("second.nii.gz: warning: ")
    assert "UserWarning" not in err  # no category, and no path into this package
    assert "qa.py" not in err and "pipeline.py" not in err


def test_localization_flag_names_every_failure(tmp_path, write_scan) -> None:
    """Both localizations can fail at once, and the cell says so."""
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    m = q.analyze(scan, q.AnalysisSettings(roi_size=9)).measurements
    assert table.localization_flag(m) == "ok"
    assert table.localization_flag(replace(m, phantom_mask_ok=False)) == "MASK"
    assert table.localization_flag(replace(m, roi_inside_phantom=False)) == "ROI"
    both = replace(m, phantom_mask_ok=False, roi_inside_phantom=False)
    assert table.localization_flag(both) == "MASK+ROI"
    # an artifact migrated from a schema without the check: not a pass
    unrecorded = replace(m, phantom_mask_ok=None, roi_inside_phantom=None)
    assert table.localization_flag(unrecorded) == "?"


def test_json_document_is_strict_json(tmp_path, write_scan, capsys) -> None:
    """stdout must parse under a strict reader: no NaN/Infinity tokens."""
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "NaN" not in captured.out and "Infinity" not in captured.out
    doc = json.loads(captured.out, parse_constant=_reject_json_constant)
    assert doc["scans"][0]["snr"] > 0


def test_json_record_maps_undefined_metrics_to_null(tmp_path, write_scan) -> None:
    """A NaN measurement becomes `null`, not Python's non-standard `NaN` token.

    Driven by injecting the NaN rather than by finding a phantom that produces
    one: an undefined metric is an estimator outcome the record has to survive,
    and pinning it to whichever metric happens to be NaN on the fixture would
    make this test a hostage to the fixture's geometry.
    """
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9))
    undefined = replace(
        artifact.measurements, ghost_pct=float("nan"), sfnr=float("inf")
    )
    record = metric_record(replace(artifact, measurements=undefined))
    assert record["ghost_pct"] is None
    assert record["sfnr"] is None
    assert record["snr"] == artifact.measurements.snr  # finite values pass through


def test_json_record_leaves_an_unnamed_direction_null(tmp_path, write_scan) -> None:
    """No phase-encode axis means no PE or RO number -- not the combined one.

    `fwhm` is the geometric mean of both axes; publishing it as `fw_pe` would
    file a different quantity under that name, and a trend database would never
    see the substitution. The combined value rides along under its own key, so
    nothing is lost by refusing to rename it.
    """
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9))
    unnamed = replace(artifact.measurements, fwhm_pe=None, fwhm_ro=None)
    record = metric_record(replace(artifact, measurements=unnamed))
    assert record["fw_pe"] is None
    assert record["fw_ro"] is None
    assert record["fwhm"] == artifact.measurements.fwhm
    assert record["fwhm_unit"] == "mm"


def test_json_record_carries_the_displacement_unit(tmp_path, write_scan) -> None:
    """`motn`/`com` carry their unit the same way `fwhm`/`fwhm_unit` do.

    `motn` is left loose against NaN-as-null (see
    `test_json_record_maps_undefined_metrics_to_null`): on this fixture the
    motion fit does not converge for every frame, so `max_translation` is
    itself NaN and the record maps it to `null` rather than the raw float.
    """
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9))
    m = artifact.measurements
    record = metric_record(artifact)
    assert record["motn"] == (
        None if math.isnan(m.max_translation) else m.max_translation
    )
    assert record["com"] == m.max_com_displacement
    assert record["displacement_unit"] == "mm"  # the fixture's voxel size is known
    assert record["displacement_unit"] == "mm"  # the fixture's voxel size is known


def test_table_marks_an_unnamed_direction_unknown(tmp_path, write_scan, capsys) -> None:
    """The `fwPE`/`fwRO` cells read `?`, not a plausible number from elsewhere."""
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9))
    unnamed = replace(artifact.measurements, fwhm_pe=None, fwhm_ro=None)
    table.print_row(replace(artifact, measurements=unnamed))
    assert capsys.readouterr().out.rstrip("\n").endswith("     ?      ?")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def test_json_stdout_stays_pure_with_an_artifact(tmp_path, write_scan, capsys) -> None:
    out = tmp_path / "qa.npz"
    rc = cli.main(
        [write_scan(tmp_path), "--roi-size", "9", "--json", "--artifact", str(out)]
    )
    captured = capsys.readouterr()
    assert rc == 0
    json.loads(captured.out)  # still parses -- the "wrote" notice is on stderr
    assert "wrote" in captured.err
    assert out.is_file()


def test_json_lists_failed_scans_in_an_error_inventory(
    tmp_path, write_scan, capsys
) -> None:
    """A document must account for every input it was asked about.

    `scans` holds only the analyses that ran; a consumer holding nothing but
    the JSON could not otherwise tell a scan that failed from one that was
    never requested. So the document also carries what was requested and,
    per failure, which input and why -- and the terminal gets a one-line tally.
    """
    missing = str(tmp_path / "missing.nii.gz")
    good = write_scan(tmp_path, name="good")
    rc = cli.main([missing, good, "--roi-size", "9", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    doc = json.loads(captured.out)
    assert [s["scan"] for s in doc["scans"]] == ["good.nii.gz"]  # only the one that ran
    assert doc["requested"] == [missing, good]
    (error,) = doc["errors"]
    assert error["scan"] == "missing.nii.gz" and error["source"] == missing
    assert error["error"]  # the message the terminal was shown
    assert "ERROR" in captured.err
    assert "1 of 2 scan(s) failed: missing.nii.gz" in captured.err


def test_version_flag_prints_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert "fmri-qa" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args", [["--roi-size", "0"], ["--trim-sec", "-1"], ["--pe-axis", "2"]]
)
def test_main_rejects_invalid_numeric_options(args: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main([*args, "scan.nii.gz"])
    assert info.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_hilo_main_succeeds_on_a_pair(tmp_path, write_scan, capsys) -> None:
    high = write_scan(tmp_path, name="high", seed=1, flip=77)
    low = write_scan(tmp_path, name="low", seed=2, flip=10)
    rc = cli.hilo_main([high, low, "--erode", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ThermalFSNR" in out and "InstabilityFSNR" in out


def test_hilo_main_reports_bad_file(tmp_path, capsys) -> None:
    rc = cli.hilo_main([str(tmp_path / "nope.nii.gz"), str(tmp_path / "nah.nii.gz")])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--erode", "-1"], ["--trim-sec", "-1"]])
def test_hilo_main_rejects_invalid_numeric_options(args: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.hilo_main([*args, "high.nii.gz", "low.nii.gz"])
    assert info.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "entry", [cli.main, cli.hilo_main, cli.import_main], ids=["qa", "hilo", "import"]
)
def test_help_renders(entry, capsys) -> None:
    """`-h` on every command.

    argparse %-formats each help string only when it renders one, so a stray
    format code in a default sits there until someone asks for help; the rest
    of the suite never asks.
    """
    with pytest.raises(SystemExit) as info:
        entry(["-h"])
    assert info.value.code == 0
    assert "usage:" in capsys.readouterr().out
