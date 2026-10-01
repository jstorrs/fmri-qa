"""The `fmri-qa-report` command line: an artifact on disk in, one HTML page out."""

from pathlib import Path

import pytest

import fmriqc as q
from fmriqc_report import cli


@pytest.fixture
def saved(tmp_path, artifact) -> str:
    """The shared artifact written to disk, as the CLI would receive it."""
    return str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))


def test_main_reports_a_write_failure_without_a_traceback(
    tmp_path, saved, capsys
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")  # a file where a parent dir must go
    rc = cli.main([saved, "--html", str(blocked / "qa.html")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR: could not write HTML" in captured.err
    assert "Traceback" not in captured.err
    # the atomic write's temporary file is an implementation detail, not an error
    assert ".tmp" not in captured.err


def test_main_creates_the_html_destination_directory(tmp_path, saved) -> None:
    """A missing output directory is created, as `--artifact` already does."""
    html = tmp_path / "reports" / "2026-01" / "qa.html"
    assert cli.main([saved, "--html", str(html)]) == 0
    assert html.is_file()


def test_main_writes_a_single_file_html_report(tmp_path, saved, capsys) -> None:
    """The end-to-end render: a saved artifact in, one self-contained page out."""
    html = tmp_path / "qa.html"
    rc = cli.main([saved, "--html", str(html)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "# wrote" in captured.out
    text = html.read_text(encoding="utf-8")
    assert "data:image/svg+xml;base64," in text
    assert "<style" in text
    assert "<link" not in text
    assert "<script" not in text


def test_html_refuses_more_than_one_artifact(tmp_path, saved, capsys) -> None:
    html = tmp_path / "qa.html"
    with pytest.raises(SystemExit) as info:
        cli.main([saved, saved, "--html", str(html)])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "--html renders one artifact to one file" in err
    assert not html.exists()


def test_html_refuses_to_overwrite_an_input(
    tmp_path, saved, capsys, monkeypatch
) -> None:
    """`--html` naming an input must fail before the artifact is read or replaced.

    The artifact is loaded first and the HTML is moved over its destination
    last, so without the guard the run succeeds and leaves a report where the
    archive was. The relative spelling is the one a shell produces.
    """
    archive = Path(saved)
    before = archive.read_bytes()
    monkeypatch.chdir(tmp_path)
    rc = cli.main([saved, "--html", f"./{archive.name}"])
    assert rc == 1
    assert "would overwrite the input" in capsys.readouterr().err
    assert archive.read_bytes() == before


def test_main_fails_when_the_artifact_cannot_be_read(tmp_path, capsys) -> None:
    html = tmp_path / "qa.html"
    rc = cli.main([str(tmp_path / "missing.nc"), "--html", str(html)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in captured.err
    assert not html.exists()


def test_main_titles_a_section_from_the_artifact_provenance(tmp_path, artifact) -> None:
    """The recorded scan name is the section title, whatever the file is called."""
    path = q.save_artifact(artifact, tmp_path / "unrelated-name.nc")
    assert cli._title(q.load_artifact(path), str(path)) == "scan.nii.gz"


def test_main_falls_back_to_the_file_name(tmp_path, bare_artifact) -> None:
    from dataclasses import replace

    anonymous = replace(
        bare_artifact, provenance=replace(bare_artifact.provenance, scan="")
    )
    path = q.save_artifact(anonymous, tmp_path / "run-7.qa.nc")
    assert cli._title(q.load_artifact(path), str(path)) == "run-7.qa.nc"


def test_version_flag_prints_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert "fmri-qa-report" in capsys.readouterr().out


def test_html_is_required(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["scan.qa.nc"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "--html" in err


def test_help_renders(capsys) -> None:
    """`-h`, which argparse %-formats; see the core suite's twin."""
    with pytest.raises(SystemExit) as info:
        cli.main(["-h"])
    assert info.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_a_wildcard_argument_is_expanded(tmp_path, artifact) -> None:
    """PowerShell hands `artifacts/*.qa.nc` over with the `*` still in it."""
    q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    html = tmp_path / "qa.html"
    rc = cli.main([f"{tmp_path}/*.qa.nc", "--html", str(html)])
    assert rc == 0
    assert html.is_file()


def test_a_wildcard_matching_nothing_is_reported_not_dropped(tmp_path, capsys) -> None:
    """A pattern that names no artifact must fail, not render an empty report."""
    rc = cli.main([f"{tmp_path}/*.qa.nc", "--html", str(tmp_path / "qa.html")])
    assert rc == 1
    assert "*.qa.nc" in capsys.readouterr().err
