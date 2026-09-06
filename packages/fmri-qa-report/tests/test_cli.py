"""The `fmri-qa-report` command line: artifacts on disk in, a PDF out."""

import pytest

import fmriqc as q
from fmriqc_report import cli


@pytest.fixture
def saved(tmp_path, artifact) -> str:
    """The shared artifact written to disk, as the CLI would receive it."""
    return str(q.save_artifact(artifact, tmp_path / "scan.qa.npz"))


def test_main_renders_a_saved_artifact(tmp_path, saved, capsys) -> None:
    pdf = tmp_path / "qa.pdf"
    rc = cli.main([saved, "--pdf", str(pdf)])
    assert rc == 0
    assert "# wrote" in capsys.readouterr().out
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_builds_a_packet_from_several_artifacts(tmp_path, saved) -> None:
    pdf = tmp_path / "packet.pdf"
    rc = cli.main([saved, saved, "--pdf", str(pdf), "--cover", "--appendix"])
    assert rc == 0  # cover + two dashboard pages + appendix
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_renders_the_physics_tier(tmp_path, saved) -> None:
    pdf = tmp_path / "physics.pdf"
    rc = cli.main([saved, "--pdf", str(pdf), "--tier", "physics"])
    assert rc == 0
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_skips_an_unreadable_artifact_but_renders_the_rest(
    tmp_path, saved, capsys
) -> None:
    pdf = tmp_path / "qa.pdf"
    rc = cli.main([str(tmp_path / "missing.npz"), saved, "--pdf", str(pdf)])
    captured = capsys.readouterr()
    assert rc == 1  # a failure makes the run exit non-zero
    assert "ERROR" in captured.err and "Traceback" not in captured.err
    assert pdf.read_bytes().startswith(b"%PDF")  # the readable one still rendered


def test_main_fails_when_no_artifact_can_be_read(tmp_path, capsys) -> None:
    rc = cli.main([str(tmp_path / "missing.npz"), "--pdf", str(tmp_path / "qa.pdf")])
    assert rc == 1
    assert "nothing to render" in capsys.readouterr().err
    assert not (tmp_path / "qa.pdf").exists()


def test_main_reports_a_write_failure_without_a_traceback(
    tmp_path, saved, capsys
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")  # a file where a parent dir must go
    rc = cli.main([saved, "--pdf", str(blocked / "qa.pdf")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR: could not write PDF" in captured.err
    assert "Traceback" not in captured.err
    # the atomic write's temporary file is an implementation detail, not an error
    assert ".tmp" not in captured.err


def test_main_creates_the_pdf_destination_directory(tmp_path, saved) -> None:
    """A missing output directory is created, as `--artifact` already does."""
    pdf = tmp_path / "reports" / "2026-01" / "qa.pdf"
    assert cli.main([saved, "--pdf", str(pdf)]) == 0
    assert pdf.is_file()


def test_main_titles_a_section_from_the_artifact_provenance(tmp_path, artifact) -> None:
    """The recorded scan name is the section title, whatever the file is called."""
    path = q.save_artifact(artifact, tmp_path / "unrelated-name.npz")
    assert cli._title(q.load_artifact(path), str(path)) == "scan.nii.gz"


def test_main_falls_back_to_the_file_name(tmp_path, bare_artifact) -> None:
    from dataclasses import replace

    anonymous = replace(
        bare_artifact, provenance=replace(bare_artifact.provenance, scan="")
    )
    path = q.save_artifact(anonymous, tmp_path / "run-7.qa.npz")
    assert cli._title(q.load_artifact(path), str(path)) == "run-7.qa.npz"


def test_version_flag_prints_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert "fmri-qa-report" in capsys.readouterr().out


def test_pdf_is_required(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["scan.qa.npz"])
    assert info.value.code == 2
    assert "error:" in capsys.readouterr().err
