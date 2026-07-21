"""End-to-end smoke tests for the command-line entry points and PDF report.

These exercise the layers unit tests skip: argument wiring, the batch loop and
its error handling, and the whole `report/` subpackage (summary text, panels,
and the ReportLab driver). A tiny synthetic phantom is written to disk as a
NIfTI + BIDS sidecar so `QAScan.from_nifti` runs its real file-I/O path.
"""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from fmriqc import cli


def _write_scan(
    directory: Path,
    name: str = "scan",
    n: int = 32,
    z: int = 3,
    t: int = 40,
    seed: int = 0,
    flip: float = 77,
) -> str:
    """Write a synthetic phantom NIfTI + sidecar; return the NIfTI path.

    A bright central disk with seeded temporal noise, 3 mm isotropic voxels and
    TR 2 s. The sidecar sets `PhaseEncodingDirection` so the PE axis resolves
    from metadata (no ghost-estimate fallback warning).
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    base = np.where(disk, 1000.0, 0.0)
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    data = base[:, :, None, None] + noise

    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    nifti = directory / f"{name}.nii.gz"
    nib.save(img, str(nifti))
    (directory / f"{name}.json").write_text(
        json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": flip})
    )
    return str(nifti)


def test_main_prints_table_and_succeeds(tmp_path, capsys) -> None:
    rc = cli.main([_write_scan(tmp_path), "--roi-size", "9"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SNR" in out and "SFNR" in out and "fwPE" in out  # the header row
    assert "scan.nii.gz" in out  # the scan's data row


def test_main_writes_a_nonempty_pdf(tmp_path) -> None:
    pdf = tmp_path / "qa.pdf"
    rc = cli.main([_write_scan(tmp_path), "--roi-size", "9", "--pdf", str(pdf)])
    assert rc == 0
    assert pdf.is_file() and pdf.stat().st_size > 0
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_physics_tier_renders(tmp_path) -> None:
    pdf = tmp_path / "qa2.pdf"
    rc = cli.main(
        [
            _write_scan(tmp_path),
            "--roi-size",
            "9",
            "--pdf",
            str(pdf),
            "--pdf-tier",
            "physics",
        ]
    )
    assert rc == 0
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_reports_bad_file_and_continues_batch(tmp_path, capsys) -> None:
    good = _write_scan(tmp_path, name="good")
    bad = tmp_path / "missing.nii.gz"  # no file, no sidecar
    rc = cli.main([str(bad), good, "--roi-size", "9"])
    captured = capsys.readouterr()
    assert rc == 1  # a failure makes the batch exit non-zero
    assert "ERROR" in captured.err and "missing.nii.gz" in captured.err
    assert "good.nii.gz" in captured.out  # the good scan still ran


def test_json_emits_a_parseable_document(tmp_path, capsys) -> None:
    rc = cli.main([_write_scan(tmp_path), "--roi-size", "9", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    doc = json.loads(captured.out)  # stdout is pure JSON, nothing else
    assert doc["config"]["detrend"] == "poly"
    assert "version" in doc["config"]
    assert len(doc["scans"]) == 1
    scan = doc["scans"][0]
    assert scan["scan"] == "scan.nii.gz"
    assert scan["snr"] > 0 and scan["pe_axis"] == 1
    assert "# detrend" in captured.err  # the banner moved off stdout


def test_json_stdout_stays_pure_with_pdf(tmp_path, capsys) -> None:
    pdf = tmp_path / "qa.pdf"
    rc = cli.main(
        [_write_scan(tmp_path), "--roi-size", "9", "--json", "--pdf", str(pdf)]
    )
    captured = capsys.readouterr()
    assert rc == 0
    json.loads(captured.out)  # still parses -- the "wrote" notice is on stderr
    assert "wrote" in captured.err
    assert pdf.read_bytes().startswith(b"%PDF")


def test_json_excludes_failed_scans(tmp_path, capsys) -> None:
    good = _write_scan(tmp_path, name="good")
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


def test_hilo_main_succeeds_on_a_pair(tmp_path, capsys) -> None:
    high = _write_scan(tmp_path, name="high", seed=1, flip=77)
    low = _write_scan(tmp_path, name="low", seed=2, flip=10)
    rc = cli.hilo_main([high, low, "--erode", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ThermalFSNR" in out and "InstabilityFSNR" in out


def test_hilo_main_reports_bad_file(tmp_path, capsys) -> None:
    rc = cli.hilo_main([str(tmp_path / "nope.nii.gz"), str(tmp_path / "nah.nii.gz")])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_write_report_honours_a_custom_theme(tmp_path) -> None:
    from reportlab.lib.pagesizes import A4

    import fmriqc as q
    from fmriqc import report

    scan = q.QAScan.from_nifti(_write_scan(tmp_path))
    result = q.run_qa(scan, roi_size=9)
    theme = report.Theme(
        page_size=A4,
        margin=24.0,
        font_body="Times-Roman",
        panel_cmap="magma",
        panel_accent="#8e44ad",
        panel_font_family="serif",
    )
    pdf = tmp_path / "themed.pdf"
    pages = report.write_report([("scan", result)], pdf, theme=theme)
    assert pages == 1
    assert pdf.read_bytes().startswith(b"%PDF")
