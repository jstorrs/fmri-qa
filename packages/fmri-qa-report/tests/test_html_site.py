"""Static HTML site publication keeps each requested input accountable."""

import json
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from fmriqc_report.formats.html import resources, site
from fmriqc_report.formats.html.run import SiteContext
from fmriqc_report.web_summary import OmittedInput, RenderedRun


def _run(digest: str, artifact, *names: str) -> RenderedRun:
    return RenderedRun(digest * 64, artifact, names)


def _tiny_page(_artifact, path: Path, *, site: SiteContext, **_kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"incomplete={site.incomplete}", encoding="utf-8")
    return path


def test_write_site_publishes_a_complete_offline_inventory(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
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
    assert page == "incomplete=False"


def test_write_site_writes_no_figure_directory(tmp_path, artifact) -> None:
    """One real publish, with no figure-related stub, so this exercises the
    actual embedded-figure path rather than a fixture standing in for it."""
    destination = tmp_path / "site"

    result = site.write_site(
        [_run("a", artifact, "/inputs/scan.qa.nc")], destination, report_version="test"
    )

    run_directory = destination / "runs" / ("a" * 64)
    page = (run_directory / "index.html").read_text()
    assert result.status is site.SiteStatus.COMPLETE
    assert not (run_directory / "figures").exists()
    assert "data:image/svg+xml;base64," in page


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_write_site_output_respects_the_umask(tmp_path, artifact, monkeypatch) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: (),
    )
    destination = tmp_path / "site"
    old_umask = os.umask(0o022)
    try:
        result = site.write_site(
            [_run("a", artifact, "/inputs/scan.qa.nc")],
            destination,
            report_version="test",
        )
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(result.output.stat().st_mode) == 0o755
    run_page = result.output / "runs" / ("a" * 64) / "index.html"
    assert stat.S_IMODE(run_page.stat().st_mode) == 0o644


def test_write_site_deduplicates_digests_and_sorts_routes_and_aliases(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
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
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
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


def test_run_render_failure_omits_every_alias_and_removes_partial_run(
    tmp_path, artifact, monkeypatch
) -> None:
    def fail_page(_artifact, path: Path, *, site: SiteContext, **_kwargs) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "partial.html").write_text("partial", encoding="utf-8")
        raise RuntimeError("render failure")

    monkeypatch.setattr(site, "write_run_page", fail_page)
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
    calls: list[tuple[str, bool]] = []

    def render(_artifact, path: Path, *, site: SiteContext, **_kwargs) -> Path:
        digest = path.parent.name
        calls.append((digest, site.incomplete))
        if digest == "b" * 64 and not site.incomplete:
            raise RuntimeError("page failure")
        return _tiny_page(_artifact, path, site=site)

    monkeypatch.setattr(site, "write_run_page", render)
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
    tmp_path, artifact, kind: str
) -> None:
    destination = tmp_path / "site"
    if kind == "file":
        destination.write_text("keep", encoding="utf-8")
    elif kind == "directory":
        destination.mkdir()
        (destination / "keep").write_text("keep", encoding="utf-8")
    else:
        destination.symlink_to(tmp_path / "missing")

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
    def read_resource(name: str) -> str:
        if name == resources.RUN_TEMPLATE:
            raise FileNotFoundError("missing run template")
        return "body {}"

    calls: list[Path] = []

    def record_page(_artifact, path: Path, **_kwargs) -> Path:
        calls.append(path)
        return path

    monkeypatch.setattr(resources, "read_resource", read_resource)
    monkeypatch.setattr(site, "write_run_page", record_page)

    with pytest.raises(FileNotFoundError, match="missing run template"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], tmp_path / "site")

    assert not calls
    assert not (tmp_path / "site").exists()
    assert not list(tmp_path.glob(".site.*"))


def test_a_corrupt_packaged_stylesheet_fails_publication_before_any_run_renders(
    tmp_path, artifact, monkeypatch
) -> None:
    original_read_resource = resources.read_resource

    def hostile_resource(name: str) -> str:
        if name == resources.STYLESHEET:
            return "body {} </style><script>alert(1)</script>"
        return original_read_resource(name)

    calls: list[Path] = []

    def record_page(_artifact, path: Path, **_kwargs) -> Path:
        calls.append(path)
        return path

    monkeypatch.setattr(resources, "read_resource", hostile_resource)
    monkeypatch.setattr(site, "write_run_page", record_page)

    with pytest.raises(ValueError, match="style"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], tmp_path / "site")

    assert not calls
    assert not (tmp_path / "site").exists()
    assert not list(tmp_path.glob(".site.*"))


def test_index_lists_one_table_row_per_run_with_headline_metrics(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)
    first = replace(
        artifact, provenance=replace(artifact.provenance, scan="run-one.nii.gz")
    )
    second = replace(
        artifact, provenance=replace(artifact.provenance, scan="run-two.nii.gz")
    )

    result = site.write_site(
        [_run("a", first, "one.qa.nc"), _run("b", second, "two.qa.nc")],
        tmp_path / "site",
        report_version="test",
    )

    page = result.index.read_text()
    assert page.count('<th scope="row">') == 2
    assert 'href="runs/' + "a" * 64 + '/index.html"' in page
    assert 'href="runs/' + "b" * 64 + '/index.html"' in page
    for doc in site._HEADLINE_METRICS:
        assert f'<th scope="col" class="num">{doc.label}</th>' in page


def test_index_counts_appear_as_tiles(tmp_path, artifact, monkeypatch) -> None:
    monkeypatch.setattr(site, "write_run_page", _tiny_page)

    result = site.write_site(
        [_run("a", artifact, "one.qa.nc"), _run("b", artifact, "two.qa.nc")],
        tmp_path / "site",
        omitted=[OmittedInput("three.qa.nc", "boom")],
    )

    page = result.index.read_text()
    assert '<span class="k">Requested inputs</span><span class="v num">3</span>' in page
    assert (
        '<span class="k">Distinct run reports</span><span class="v num">2</span>'
        in page
    )
    assert '<span class="k">Duplicate inputs</span><span class="v num">0</span>' in page
    assert (
        '<span class="k">Omitted inputs</span><span class="v num">1</span>'
        '<span class="n"><span class="pill warn">incomplete</span></span>' in page
    )
    assert "Status</dt><dd>Incomplete" in page
    assert result.status is site.SiteStatus.INCOMPLETE


def test_index_empty_state_strings(tmp_path) -> None:
    result = site.write_site([], tmp_path / "site")

    page = result.index.read_text()
    assert "No run reports were rendered." in page
    assert "No requested inputs were omitted." in page


def test_write_site_preserves_a_target_created_while_rendering(
    tmp_path, artifact, monkeypatch
) -> None:
    destination = tmp_path / "site"

    def create_target(_artifact, path: Path, *, site: SiteContext, **_kwargs) -> Path:
        destination.write_text("another publisher", encoding="utf-8")
        return _tiny_page(_artifact, path, site=site)

    monkeypatch.setattr(site, "write_run_page", create_target)

    with pytest.raises(FileExistsError, match="refusing to replace"):
        site.write_site([_run("a", artifact, "scan.qa.nc")], destination)

    assert destination.read_text() == "another publisher"
    assert not list(tmp_path.glob(".site.*"))


def test_index_template_is_packaged_resource() -> None:
    assert resources.read_resource(resources.INDEX_TEMPLATE)
