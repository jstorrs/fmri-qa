"""End-to-end smoke tests for the calculation command-line entry points.

These exercise the layers unit tests skip: argument wiring, the batch loop and
its error handling, the JSON document, and saving artifacts to disk. A tiny
synthetic phantom is written as a NIfTI + BIDS sidecar (see `conftest`) so
`QAScan.from_nifti` runs its real file-I/O path. Rendering those artifacts into
a PDF is `fmri-qa-report`'s job and is tested there.
"""

import json
from dataclasses import replace

import pytest

import fmriqc as q
from fmriqc import cli


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


def test_json_emits_a_parseable_document(tmp_path, write_scan, capsys) -> None:
    rc = cli.main([write_scan(tmp_path), "--roi-size", "9", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    doc = json.loads(captured.out)  # stdout is pure JSON, nothing else
    assert doc["schema_version"] == 1
    assert doc["config"]["detrend"] == "poly"
    assert "version" in doc["config"]
    assert len(doc["scans"]) == 1
    scan = doc["scans"][0]
    assert scan["scan"] == "scan.nii.gz"
    assert scan["snr"] > 0 and scan["pe_axis"] == 1
    assert "# detrend" in captured.err  # the banner moved off stdout


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
    record = cli._metric_record(replace(artifact, measurements=undefined))
    assert record["ghost_pct"] is None
    assert record["sfnr"] is None
    assert record["snr"] == artifact.measurements.snr  # finite values pass through


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


def test_json_excludes_failed_scans(tmp_path, write_scan, capsys) -> None:
    good = write_scan(tmp_path, name="good")
    rc = cli.main([str(tmp_path / "missing.nii.gz"), good, "--roi-size", "9", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    doc = json.loads(captured.out)
    assert [s["scan"] for s in doc["scans"]] == ["good.nii.gz"]  # only the one that ran
    assert "ERROR" in captured.err


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
