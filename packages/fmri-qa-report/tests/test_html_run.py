"""The offline per-run HTML report is one self-contained, embedded document."""

import os
import re
import stat
import sys
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest

import fmriqc as q
from fmriqc_report.content import METRIC_DOCS
from fmriqc_report.formats.html import resources
from fmriqc_report.formats.html import run as run_module
from fmriqc_report.formats.html.figures import FIGURE_ASSETS, RenderedFigure
from fmriqc_report.formats.html.run import render_run_page, write_run_page

_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\Z")


class _Page(HTMLParser):
    """Small structural inspector for the generated page."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.append(dict(attrs))


def _tiny_rendered_figures() -> tuple[RenderedFigure, ...]:
    """A cheap stand-in inventory for tests that are not about figure content."""
    return tuple(
        RenderedFigure(asset, f"<?xml version='1.0'?><svg>{asset.name}</svg>".encode())
        for asset in FIGURE_ASSETS
    )


@pytest.fixture(scope="module")
def standalone_page(artifact) -> str:
    """One real rendering, shared across read-only tests."""
    return render_run_page(artifact, title="Test run", report_version="report-test")


def test_run_page_contains_complete_offline_report_content(standalone_page) -> None:
    page = standalone_page
    parsed = _Page()
    parsed.feed(page)

    assert "Test run" in page
    assert {
        "header",
        "main",
        "nav",
        "section",
        "figure",
        "details",
        "table",
        "dl",
        "footer",
    } <= set(parsed.tags)
    assert page.count('class="tile metric"') == len(METRIC_DOCS) == 15
    assert page.count('class="fig"') == len(FIGURE_ASSETS) == 14
    assert "Image diagnostics" in page and "Temporal and spatial diagnostics" in page
    assert "Definitions and methods" in page
    assert "Core version" in page and "Loaded artifact schema" in page
    assert "Report version" in page and "report-test" in page
    assert "Trim duration" in page and "PE axis override" in page
    assert "Resolved detrend order" in page and "Requested ROI side" in page
    assert "These values are descriptive." in page


def test_figure_alt_text_is_the_title_not_the_visible_caption_sentence(
    standalone_page,
) -> None:
    """A screen reader must not read the description twice: once as `alt`,
    once as the figcaption text right beside it."""
    page = standalone_page
    parsed = _Page()
    parsed.feed(page)

    alt_values = {attrs["alt"] for attrs in parsed.attributes if "alt" in attrs}
    for asset in FIGURE_ASSETS:
        assert f'alt="{asset.title}"' in page
        assert f'alt="{asset.description}"' not in page
    assert alt_values == {asset.title for asset in FIGURE_ASSETS}


def test_run_page_offers_a_scriptless_enlarge_target_for_every_figure(
    standalone_page,
) -> None:
    page = standalone_page
    parsed = _Page()
    parsed.feed(page)

    for asset in FIGURE_ASSETS:
        assert f'id="fig-{asset.name}"' in page
        assert f'href="#fig-{asset.name}"' in page

    href_values = [
        value for attributes in parsed.attributes if (value := attributes.get("href"))
    ]
    assert href_values
    assert all(value.startswith("#") for value in href_values)


def test_run_page_ids_are_unique_and_every_internal_reference_resolves(
    standalone_page,
) -> None:
    page = standalone_page
    parsed = _Page()
    parsed.feed(page)

    ids = [value for attrs in parsed.attributes if (value := attrs.get("id"))]
    assert ids
    assert len(ids) == len(set(ids))
    assert all(_ID.match(value) for value in ids)

    id_set = set(ids)
    for attrs in parsed.attributes:
        href = attrs.get("href")
        if href and href.startswith("#"):
            assert href[1:] in id_set
        labelledby = attrs.get("aria-labelledby")
        if labelledby:
            assert all(ref in id_set for ref in labelledby.split())


def test_run_page_is_self_contained(standalone_page) -> None:
    page = standalone_page
    parsed = _Page()
    parsed.feed(page)

    assert "<style" in page and "<link" not in page
    assert page.count("data:image/svg+xml;base64,") == len(FIGURE_ASSETS) == 14
    image_sources = [
        attributes["src"] for attributes in parsed.attributes if "src" in attributes
    ]
    assert image_sources
    assert all(
        src is not None and src.startswith("data:image/svg+xml;base64,")
        for src in image_sources
    )
    link_values = [
        value
        for attributes in parsed.attributes
        for key in ("href", "src")
        if (value := attributes.get(key)) is not None
    ]
    assert not any(
        value.startswith(("http://", "https://", "//")) for value in link_values
    )
    assert not any("figures/" in value for value in link_values)
    assert "http://" not in page and "https://" not in page
    assert len(page) < 4_000_000


def test_run_page_carries_no_script_or_event_handlers(standalone_page) -> None:
    page = standalone_page
    parsed = _Page()
    parsed.feed(page)

    assert "script" not in parsed.tags
    assert "<script" not in page.lower()
    attribute_names = {name for attributes in parsed.attributes for name in attributes}
    assert not any(name.lower().startswith("on") for name in attribute_names)
    assert re.search(r"\son[a-z]+\s*=", page) is None


def test_run_page_is_byte_reproducible(artifact) -> None:
    first = render_run_page(artifact, title="Test run", report_version="report-test")
    second = render_run_page(artifact, title="Test run", report_version="report-test")

    assert first == second


def test_a_reloaded_artifact_renders_identically(tmp_path, artifact) -> None:
    """The seam's payoff: a saved artifact is as good as a freshly computed one."""
    reloaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "qa.nc"))
    live = render_run_page(artifact, title="Test run", report_version="report-test")
    disk = render_run_page(reloaded, title="Test run", report_version="report-test")
    assert live == disk


def test_a_blank_scan_with_an_unresolved_rdc_still_renders(tmp_path) -> None:
    """Every panel must degrade to a page, not an exception, on a degenerate run."""
    artifact = q.analyze(
        q.QAScan(data=np.zeros((16, 16, 1, 10)), tr=2.0, pe_axis=1),
        q.AnalysisSettings(roi_size=3, trim_sec=0, detrend_order=0),
    )
    reloaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "blank.nc"))
    assert not np.isfinite(reloaded.curves.weisskoff.rdc).any()
    page = render_run_page(reloaded, title="blank", report_version="report-test")
    assert "Unavailable — estimator unresolved" in page


def test_run_page_marks_nonfinite_values_and_analysis_warnings(
    artifact, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )
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
    page = render_run_page(replace(artifact, measurements=measurements))

    assert page.count("Unavailable — estimator unresolved") >= 3
    assert (
        page.count('<span class="pill muted">Unavailable — estimator unresolved</span>')
        >= 3
    )
    assert (
        'id="metric-snr"><span class="k">SNR</span><span class="v num">—</span>' in page
    )
    assert "BAD PHANTOM MASK (70% of frame, 1.4× contrast)" in page
    assert "CLIP 2 in analyzed data (+1 pre-SS) @ 4095 (12-bit)" in page


@pytest.mark.parametrize(
    ("fmt_output", "expected_markup"),
    [
        ("449.7", "449.7"),
        ("4.03%", "4.03<small>%</small>"),
        ("0.04mm", "0.04<small>mm</small>"),
        ("-0.5%", "-0.5<small>%</small>"),
        ("nan", "nan"),
        ("< 0.01", "&lt; 0.01"),
        ("−0.5%", "−0.5%"),  # U+2212 MINUS SIGN, not ASCII '-'
    ],
)
def test_split_value_never_invents_a_space_and_always_keeps_the_text(
    fmt_output: str, expected_markup: str
) -> None:
    assert run_module._split_value(fmt_output) == expected_markup


def test_run_page_splits_metric_values_from_their_units(
    standalone_page, artifact
) -> None:
    page = standalone_page
    measurements = artifact.measurements
    # A unit-bearing metric ("4.03%") splits its formatted text into a number
    # and a <small> unit with no inserted space; a dimensionless one ("449.7")
    # stays a bare number. "ghost" and "SNR" are picked by label rather than a
    # unit lookup: the former always formats with a "%" suffix, the latter never.
    unit_bearing = next(doc for doc in METRIC_DOCS if doc.label == "ghost")
    dimensionless = next(doc for doc in METRIC_DOCS if doc.label == "SNR")
    assert run_module._split_value(unit_bearing.fmt(measurements)) in page
    dimensionless_text = dimensionless.fmt(measurements)
    assert f'<span class="v num">{dimensionless_text}</span>' in page


def test_run_page_handles_missing_metadata_without_inventing_acquisition_time(
    bare_artifact, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )
    page = render_run_page(bare_artifact)

    assert "Scanner</dt><dd>Unknown" in page
    assert "Coil</dt><dd>Unknown" in page
    assert "Acquired</dt><dd>Unknown" in page
    assert "Acquired at</th><td>Unknown" in page
    assert "Analyzed at</th><td>" in page
    assert "Scanner and acquisition details</th><td>Unavailable" in page
    assert "Series</th><td>Unknown" in page
    assert f"Trimmed frames</th><td>{bare_artifact.provenance.n_trimmed}" in page
    assert "Recorded PE direction</th><td>Unknown" in page


def test_run_page_escapes_hostile_metadata_and_long_text(artifact, monkeypatch) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )
    hostile = '<script>alert("x")</script>'
    long_source = f"{hostile}/" + "very-long-source-" * 40
    provenance = replace(artifact.provenance, scan=hostile, source=long_source)
    page = render_run_page(
        replace(artifact, provenance=provenance),
        title=hostile,
    )
    parsed = _Page()
    parsed.feed(page)

    assert hostile not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "script" not in parsed.tags
    assert "very-long-source-" in page


def test_write_run_page_writes_exactly_one_file(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )
    destination = tmp_path / "out" / "report.html"

    result = write_run_page(artifact, destination)

    assert result == destination
    written = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert written == [destination]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_write_run_page_output_respects_the_umask(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )
    destination = tmp_path / "out" / "report.html"
    old_umask = os.umask(0o022)
    try:
        write_run_page(artifact, destination)
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o644


def test_write_run_page_leaves_no_file_when_a_figure_fails(
    tmp_path, artifact, monkeypatch
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("figure failure")

    monkeypatch.setattr("fmriqc_report.formats.html.run.render_figures", fail)
    destination = tmp_path / "out" / "report.html"

    with pytest.raises(RuntimeError, match="figure failure"):
        write_run_page(artifact, destination)

    assert not destination.exists()


def test_write_run_page_leaves_an_existing_destination_unchanged_when_rendering_fails(
    tmp_path, artifact, monkeypatch
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("figure failure")

    monkeypatch.setattr("fmriqc_report.formats.html.run.render_figures", fail)
    destination = tmp_path / "out"
    destination.mkdir()
    target = destination / "report.html"
    target.write_text("previous report", encoding="utf-8")

    with pytest.raises(RuntimeError, match="figure failure"):
        write_run_page(artifact, target)

    assert target.read_text(encoding="utf-8") == "previous report"
    assert [path.name for path in destination.iterdir()] == ["report.html"]


def test_write_run_page_is_atomic_when_the_write_step_itself_fails(
    tmp_path, artifact, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )
    destination = tmp_path / "out"
    destination.mkdir()
    target = destination / "report.html"
    target.write_text("previous report", encoding="utf-8")

    original_write_text = Path.write_text

    def fail_write_text(self, *args, **kwargs):
        if self.name.startswith(".report.html."):
            raise OSError("disk full")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(OSError, match="disk full"):
        write_run_page(artifact, target)

    assert target.read_text(encoding="utf-8") == "previous report"
    assert [path.name for path in destination.iterdir()] == ["report.html"]


def test_run_template_and_stylesheet_are_packaged_resources() -> None:
    assert resources.read_resource(resources.RUN_TEMPLATE)
    assert resources.read_resource(resources.STYLESHEET)


def test_run_page_refuses_a_stylesheet_that_could_break_out_of_its_style_block(
    artifact, monkeypatch
) -> None:
    monkeypatch.setattr(
        "fmriqc_report.formats.html.run.render_figures",
        lambda _artifact, **_kwargs: _tiny_rendered_figures(),
    )

    original_read_resource = resources.read_resource

    def hostile_resource(name: str) -> str:
        if name == resources.STYLESHEET:
            return "body {} </style><script>alert(1)</script>"
        return original_read_resource(name)

    monkeypatch.setattr(
        "fmriqc_report.formats.html.resources.read_resource", hostile_resource
    )

    with pytest.raises(ValueError, match="style"):
        render_run_page(artifact)
