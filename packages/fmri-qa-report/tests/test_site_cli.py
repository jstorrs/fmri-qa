"""The static-site command owns artifact snapshots and request accounting."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc_report import site_cli
from fmriqc_report.formats.html import site
from fmriqc_report.formats.html.run import SiteContext


def _tiny_page(_artifact, path: Path, *, site: SiteContext, **_kwargs) -> Path:
    """Keep command tests focused on loading and publication bookkeeping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"incomplete={site.incomplete}", encoding="utf-8")
    return path


@pytest.fixture
def saved(tmp_path, artifact) -> Path:
    """A real artifact, so the command exercises the core artifact reader."""
    return q.save_artifact(artifact, tmp_path / "scan.qa.nc")


def test_main_publishes_a_site_and_reports_actual_counts(
    tmp_path, saved, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
    output = tmp_path / "site"

    assert site_cli.main([str(saved), "--output", str(output)]) == 0

    captured = capsys.readouterr()
    summary = json.loads((output / "summary.json").read_text())
    assert captured.out == ""
    assert "1 requested input(s)" in captured.err
    assert summary["counts"] == {
        "duplicate_inputs": 0,
        "omitted_inputs": 0,
        "requested_inputs": 1,
        "unique_rendered_runs": 1,
    }
    assert (output / "index.html").is_file()
    assert (output / "runs" / hashlib.sha256(saved.read_bytes()).hexdigest()).is_dir()


def test_main_groups_duplicate_requests_and_keeps_their_aliases(
    tmp_path, saved, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
    output = tmp_path / "site"

    assert site_cli.main([str(saved), str(saved), "--output", str(output)]) == 0

    summary = json.loads((output / "summary.json").read_text())
    assert summary["counts"]["duplicate_inputs"] == 1
    assert summary["runs"][0]["input_names"] == ["scan.qa.nc", "scan.qa.nc"]
    assert "1 duplicate input(s)" in capsys.readouterr().err


def test_main_publishes_an_incomplete_site_for_a_missing_artifact(
    tmp_path, saved, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
    output = tmp_path / "site"
    missing = tmp_path / "missing.qa.nc"

    assert site_cli.main([str(missing), str(saved), "--output", str(output)]) == 1

    summary = json.loads((output / "summary.json").read_text())
    assert summary["counts"]["omitted_inputs"] == 1
    assert "Site incomplete." in (output / "index.html").read_text()
    assert "missing.qa.nc" in capsys.readouterr().err


def test_main_publishes_a_failure_only_site_when_every_input_is_bad(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
    output = tmp_path / "site"

    assert (
        site_cli.main([str(tmp_path / "missing.qa.nc"), "--output", str(output)]) == 1
    )

    summary = json.loads((output / "summary.json").read_text())
    assert summary["counts"]["unique_rendered_runs"] == 0
    assert summary["counts"]["omitted_inputs"] == 1
    assert "No run reports were rendered." in (output / "index.html").read_text()


def test_main_refuses_an_existing_destination_before_reading_inputs(
    tmp_path, saved, monkeypatch, capsys
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "keep").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(site_cli, "_load_runs", lambda _paths: pytest.fail("read"))

    assert site_cli.main([str(saved), "--output", str(output)]) == 1

    assert (output / "keep").read_text() == "keep"
    assert "refusing to replace" in capsys.readouterr().err


def test_main_handles_snapshot_read_errors_as_omissions(
    tmp_path, saved, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)

    def denied(_path: str, _directory: Path) -> tuple[str, object]:
        raise OSError("read denied")

    monkeypatch.setattr(site_cli, "_snapshot_artifact", denied)
    output = tmp_path / "site"
    assert site_cli.main([str(saved), "--output", str(output)]) == 1
    assert "read denied" in capsys.readouterr().err
    assert (
        json.loads((output / "summary.json").read_text())["counts"]["omitted_inputs"]
        == 1
    )


def test_snapshot_loads_the_same_bytes_it_hashed_when_the_input_is_replaced(
    tmp_path, saved, artifact, monkeypatch
) -> None:
    replacement = q.save_artifact(
        replace(artifact, provenance=replace(artifact.provenance, scan="replacement")),
        tmp_path / "replacement.qa.nc",
    )
    expected_digest = hashlib.sha256(saved.read_bytes()).hexdigest()
    original_loader = site_cli.load_artifact

    def replace_before_load(snapshot: Path):
        saved.write_bytes(replacement.read_bytes())
        return original_loader(snapshot)

    monkeypatch.setattr(site_cli, "load_artifact", replace_before_load)
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
    output = tmp_path / "site"

    assert site_cli.main([str(saved), "--output", str(output)]) == 0

    summary = json.loads((output / "summary.json").read_text())
    assert summary["runs"][0]["artifact_sha256"] == expected_digest
    assert summary["runs"][0]["title"] != "replacement"


def test_parser_help_version_and_required_output(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        site_cli.main(["--help"])
    assert "usage:" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="0"):
        site_cli.main(["--version"])
    assert "fmri-qa-site" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="2"):
        site_cli.main(["artifact.qa.nc"])
    assert "--output" in capsys.readouterr().err
