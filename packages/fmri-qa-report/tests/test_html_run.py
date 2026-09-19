"""The offline per-run HTML report references the completed SVG inventory."""

from dataclasses import replace
from html.parser import HTMLParser
from importlib.resources import files
from shutil import copytree

import pytest

from fmriqc_report.content import METRIC_DOCS
from fmriqc_report.formats.html.figures import FIGURE_ASSETS, write_figures
from fmriqc_report.formats.html.run import render_run


class _Page(HTMLParser):
    """Small structural inspector for the generated page."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.append(dict(attrs))


@pytest.fixture(scope="module")
def figure_directory(tmp_path_factory, artifact):
    """One real fixed SVG inventory for the renderer's integration tests."""
    directory = tmp_path_factory.mktemp("html-run-figures") / "figures"
    write_figures(artifact, directory)
    return directory


def _run_directory(tmp_path, figure_directory):
    run_directory = tmp_path / "runs" / ("a" * 64)
    copytree(figure_directory, run_directory / "figures")
    return run_directory


def _render(tmp_path, artifact, figure_directory, **kwargs) -> str:
    run_directory = _run_directory(tmp_path, figure_directory)
    return render_run(
        artifact, run_directory, report_version="report-test", **kwargs
    ).read_text()


def test_run_page_contains_complete_offline_report_content(
    tmp_path, artifact, figure_directory
) -> None:
    page = _render(tmp_path, artifact, figure_directory, title="Test run")
    parsed = _Page()
    parsed.feed(page)

    assert "Test run" in page
    assert "../../index.html" in page and "../../assets/report.css" in page
    assert {"header", "main", "nav", "section", "figure", "details"} <= set(parsed.tags)
    assert page.count('class="metric-card"') == len(METRIC_DOCS) == 15
    assert page.count('class="figure-card"') == len(FIGURE_ASSETS) == 14
    assert "Image diagnostics" in page and "Temporal and spatial diagnostics" in page
    assert "Definitions and methods" in page
    assert "Core version" in page and "Loaded artifact schema" in page
    assert "Report version" in page and "report-test" in page
    assert "Trim duration" in page and "PE axis override" in page
    assert "Resolved detrend order" in page and "Requested ROI side" in page
    assert "These values are descriptive." in page

    image_sources = {
        attributes["src"] for attributes in parsed.attributes if "src" in attributes
    }
    figure_links = {
        attributes["href"]
        for attributes in parsed.attributes
        if attributes.get("href", "").startswith("figures/")
    }
    expected = {f"figures/{asset.name}.svg" for asset in FIGURE_ASSETS}
    assert image_sources == expected
    assert figure_links == expected


def test_run_page_marks_nonfinite_values_and_analysis_warnings(
    tmp_path, artifact, figure_directory
) -> None:
    measurements = replace(
        artifact.measurements,
        snr=float("nan"),
        sfnr=float("inf"),
        rdc=float("-inf"),
        phantom_mask_ok=False,
        phantom_fraction=0.7,
        phantom_contrast=1.4,
        clipped_any=True,
        clipped_kept=True,
        n_clipped_kept=2,
        n_clipped_pre=1,
        clip_ceiling=4095.0,
        clip_bits=12,
    )
    page = _render(
        tmp_path, replace(artifact, measurements=measurements), figure_directory
    )

    assert page.count("Unavailable — estimator unresolved") >= 3
    assert "BAD PHANTOM MASK (70% of frame, 1.4× contrast)" in page
    assert "CLIP 2 in analyzed data (+1 pre-SS) @ 4095 (12-bit)" in page


def test_run_page_handles_missing_metadata_without_inventing_acquisition_time(
    tmp_path, bare_artifact, figure_directory
) -> None:
    page = _render(tmp_path, bare_artifact, figure_directory)

    assert "Device metadata unavailable" in page
    assert "Acquired at</dt><dd>Unknown" in page
    assert "Analyzed at</dt><dd>" in page
    assert "Scanner and acquisition details</dt><dd>Unavailable" in page
    assert "Series</dt><dd>Unknown" in page
    assert f"Trimmed frames</dt><dd>{bare_artifact.provenance.n_trimmed}" in page
    assert "Recorded PE direction</dt><dd>Unknown" in page


def test_run_page_flags_an_incomplete_site_with_the_fixed_omissions_route(
    tmp_path, artifact, figure_directory
) -> None:
    page = _render(tmp_path, artifact, figure_directory, incomplete=True)

    assert "Site incomplete." in page
    assert 'href="../../index.html#omissions"' in page


def test_run_page_escapes_hostile_metadata_and_long_text(
    tmp_path, artifact, figure_directory
) -> None:
    hostile = '<script>alert("x")</script>'
    long_source = f"{hostile}/" + "very-long-source-" * 40
    provenance = replace(artifact.provenance, scan=hostile, source=long_source)
    page = _render(
        tmp_path,
        replace(artifact, provenance=provenance),
        figure_directory,
        title=hostile,
    )
    parsed = _Page()
    parsed.feed(page)

    assert hostile not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "script" not in parsed.tags
    assert "very-long-source-" in page


def test_run_page_refuses_to_write_when_a_figure_is_missing(
    tmp_path, artifact, figure_directory
) -> None:
    run_directory = _run_directory(tmp_path, figure_directory)
    (run_directory / "figures" / "spectrum.svg").unlink()

    with pytest.raises(FileNotFoundError, match="spectrum"):
        render_run(artifact, run_directory, report_version="report-test")

    assert not (run_directory / "index.html").exists()


def test_run_template_and_stylesheet_are_packaged_resources() -> None:
    package = files("fmriqc_report.formats.html")
    assert package.joinpath("templates/run.html").is_file()
    assert package.joinpath("assets/report.css").is_file()
