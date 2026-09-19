"""Static HTML site publication keeps each requested input accountable."""

import json
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from fmriqc_report.formats.html import site
from fmriqc_report.formats.html.figures import FIGURE_ASSETS
from fmriqc_report.web_summary import OmittedInput, RenderedRun


def _run(digest: str, artifact, *names: str) -> RenderedRun:
    return RenderedRun(digest * 64, artifact, names)


def _tiny_figures(_artifact, output: Path) -> None:
    output.mkdir(parents=True)
    for asset in FIGURE_ASSETS:
        (output / f"{asset.name}.svg").write_text("<svg></svg>", encoding="utf-8")


def _tiny_page(_artifact, directory: Path, *, incomplete: bool, **_kwargs) -> Path:
    page = directory / "index.html"
    page.write_text(f"incomplete={incomplete}", encoding="utf-8")
    return page


def test_write_site_publishes_a_complete_offline_inventory(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_figures", _tiny_figures)
    destination = tmp_path / "site"

    result = site.write_site(
        [_run("a", artifact, "/inputs/scan.qa.nc")], destination, report_version="test"
    )

    summary = json.loads(result.summary.read_text())
    run_directory = destination / "runs" / ("a" * 64)
    page = (run_directory / "index.html").read_text()
    assert result.status is site.SiteStatus.COMPLETE
    assert result.successful_runs == result.successful_inputs == 1
    assert result.omitted_count == 0
    assert result.index == destination / "index.html"
    assert summary["counts"] == {
        "duplicate_inputs": 0,
        "omitted_inputs": 0,
        "requested_inputs": 1,
        "unique_rendered_runs": 1,
    }
    assert (destination / "assets" / "report.css").is_file()
    assert 'href="runs/' + "a" * 64 + '/index.html"' in result.index.read_text()
    assert all(
        f"figures/{asset.name}.svg" in page
        and (run_directory / "figures" / f"{asset.name}.svg").is_file()
        for asset in FIGURE_ASSETS
    )


def test_write_site_deduplicates_digests_and_sorts_routes_and_aliases(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_figures", _tiny_figures)
    monkeypatch.setattr(site, "render_run", _tiny_page)
    first = [
        _run("b", artifact, "/input/zeta.qa.nc"),
        _run("a", artifact, "/input/beta.qa.nc"),
        _run("b", artifact, "/input/alpha.qa.nc"),
    ]
    second = list(reversed(first))

    one = site.write_site(first, tmp_path / "one", report_version="test")
    two = site.write_site(second, tmp_path / "two", report_version="test")

    one_summary = json.loads(one.summary.read_text())
    two_summary = json.loads(two.summary.read_text())
    assert one_summary == two_summary
    assert [run["artifact_sha256"] for run in one_summary["runs"]] == [
        "a" * 64,
        "b" * 64,
    ]
    assert one_summary["runs"][1]["input_names"] == ["alpha.qa.nc", "zeta.qa.nc"]
    assert one_summary["counts"]["duplicate_inputs"] == 1


def test_write_site_escapes_root_inventory_metadata_names_and_omissions(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_figures", _tiny_figures)
    monkeypatch.setattr(site, "render_run", _tiny_page)
    hostile = '<script>alert("x")</script>'
    changed = replace(artifact, provenance=replace(artifact.provenance, scan=hostile))

    result = site.write_site(
        [_run("a", changed, f"/input/{hostile}.qa.nc")],
        tmp_path / "site",
        omitted=[OmittedInput(f"/input/{hostile}-bad.qa.nc", hostile)],
    )

    page = result.index.read_text()
    assert hostile not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "Site incomplete." in page and 'href="summary.json"' in page
    assert result.status is site.SiteStatus.INCOMPLETE


def test_figure_failure_omits_every_alias_and_removes_partial_run(
    tmp_path, artifact, monkeypatch
) -> None:
    def fail_figures(_artifact, output: Path) -> None:
        output.mkdir(parents=True)
        (output / "partial.svg").write_text("partial", encoding="utf-8")
        raise RuntimeError("figure failure")

    monkeypatch.setattr(site, "write_figures", fail_figures)
    monkeypatch.setattr(site, "render_run", _tiny_page)
    result = site.write_site(
        [_run("a", artifact, "/input/one.qa.nc", "/input/two.qa.nc")],
        tmp_path / "site",
    )

    summary = json.loads(result.summary.read_text())
    assert result.status is site.SiteStatus.FAILED
    assert result.successful_runs == result.successful_inputs == 0
    assert [item.input_name for item in result.omitted_inputs] == [
        "/input/one.qa.nc",
        "/input/two.qa.nc",
    ]
    assert summary["counts"]["omitted_inputs"] == 2
    assert not (result.output / "runs" / ("a" * 64)).exists()


def test_late_page_failure_rerenders_every_survivor_as_incomplete(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_figures", _tiny_figures)
    calls: list[tuple[str, bool]] = []

    def render(_artifact, directory: Path, *, incomplete: bool, **_kwargs) -> Path:
        digest = directory.name
        calls.append((digest, incomplete))
        if digest == "b" * 64 and not incomplete:
            raise RuntimeError("page failure")
        return _tiny_page(_artifact, directory, incomplete=incomplete)

    monkeypatch.setattr(site, "render_run", render)
    result = site.write_site(
        [_run("a", artifact, "one.qa.nc"), _run("b", artifact, "two.qa.nc")],
        tmp_path / "site",
    )

    assert result.status is site.SiteStatus.INCOMPLETE
    assert calls == [("a" * 64, False), ("b" * 64, False), ("a" * 64, True)]
    assert (result.output / "runs" / ("a" * 64) / "index.html").read_text() == (
        "incomplete=True"
    )
    assert not (result.output / "runs" / ("b" * 64)).exists()


@pytest.mark.parametrize("kind", ["file", "directory", "dangling-link"])
def test_write_site_refuses_existing_targets_without_touching_them(
    tmp_path, artifact, monkeypatch, kind: str
) -> None:
    destination = tmp_path / "site"
    if kind == "file":
        destination.write_text("keep", encoding="utf-8")
    elif kind == "directory":
        destination.mkdir()
        (destination / "keep").write_text("keep", encoding="utf-8")
    else:
        destination.symlink_to(tmp_path / "missing")
    monkeypatch.setattr(site, "write_figures", _tiny_figures)

    with pytest.raises(FileExistsError, match="refusing to replace"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], destination)

    if kind == "file":
        assert destination.read_text() == "keep"
    elif kind == "directory":
        assert (destination / "keep").read_text() == "keep"
    else:
        assert destination.is_symlink() and not destination.exists()


def test_fatal_staging_failure_cleans_the_unpublished_directory(
    tmp_path, artifact, monkeypatch
) -> None:
    def fail_stylesheet(_staging: Path) -> None:
        raise RuntimeError("missing shared resource")

    monkeypatch.setattr(site, "_write_stylesheet", fail_stylesheet)

    with pytest.raises(RuntimeError, match="missing shared resource"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], tmp_path / "site")

    assert not (tmp_path / "site").exists()
    assert not list(tmp_path.glob(".site.*"))


def test_missing_shared_run_template_stops_publication_before_rendering(
    tmp_path, artifact, monkeypatch
) -> None:
    class Resource:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            if self.text is None:
                raise FileNotFoundError("missing run template")
            return self.text

    class Resources:
        def joinpath(self, path: str) -> Resource:
            return {
                "assets/report.css": Resource("body {}"),
                "templates/run.html": Resource(None),
            }[path]

    calls: list[Path] = []

    def record_figures(_artifact, path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr(site, "files", lambda _package: Resources())
    monkeypatch.setattr(site, "write_figures", record_figures)

    with pytest.raises(FileNotFoundError, match="missing run template"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], tmp_path / "site")

    assert not calls
    assert not (tmp_path / "site").exists()
    assert not list(tmp_path.glob(".site.*"))


def test_write_site_preserves_a_target_created_while_rendering(
    tmp_path, artifact, monkeypatch
) -> None:
    destination = tmp_path / "site"
    monkeypatch.setattr(site, "write_figures", _tiny_figures)

    def create_target(_artifact, directory: Path, **kwargs) -> Path:
        destination.write_text("another publisher", encoding="utf-8")
        return _tiny_page(_artifact, directory, **kwargs)

    monkeypatch.setattr(site, "render_run", create_target)

    with pytest.raises(FileExistsError, match="refusing to replace"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], destination)

    assert destination.read_text() == "another publisher"
    assert not list(tmp_path.glob(".site.*"))


def test_index_template_is_packaged_resource() -> None:
    package = files("fmriqc_report.formats.html")
    assert package.joinpath("templates/index.html").is_file()
