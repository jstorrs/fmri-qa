"""Compose one self-contained, offline HTML page from a completed artifact.

The site publisher owns the run directory and writes the SVG figures before it
calls :func:`render_run`.  This renderer only assembles the page that refers to
that fixed local inventory; it never redraws figures or opens an input scan.
"""

import html
import math
from importlib.resources import files
from pathlib import Path
from string import Template

from fmriqc.analysis import Measurements, QAArtifact

from ...content import METRIC_DOCS, MetricDoc
from ...summary import (
    acquisition_line,
    acquisition_notes,
    device_line,
    package_version,
    provenance_line,
)
from .figures import FIGURE_ASSETS

__all__ = ["render_run"]


_TEMPLATE = "templates/run.html"
_UNAVAILABLE = "Unavailable — estimator unresolved"


def render_run(
    artifact: QAArtifact,
    run_directory: Path | str,
    *,
    title: str | None = None,
    report_version: str | None = None,
    incomplete: bool = False,
) -> Path:
    """Write ``index.html`` for a run whose complete SVG inventory exists.

    ``run_directory`` is the final ``runs/<digest>`` directory.  The page has
    fixed routes to the report index, stylesheet, and known SVG inventory; no
    artifact field is used as a URL.  Missing figures fail before ``index.html``
    is opened so a publisher never leaves a page with broken figure links.
    """
    destination = Path(run_directory)
    _require_figures(destination)

    page_title = (
        title or artifact.provenance.scan or Path(artifact.provenance.source).name
    )
    values = {
        "title": _text(page_title),
        "overview": _overview(artifact),
        "warning": _warnings(artifact, incomplete),
        "metrics": _metrics(artifact),
        "acquisition": _acquisition(artifact),
        "figures": _figures(),
        "methods": _methods(),
        "provenance": _provenance(artifact, report_version or package_version()),
    }
    template = Template(files(__package__).joinpath(_TEMPLATE).read_text("utf-8"))
    page = template.substitute(values)
    path = destination / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def _require_figures(run_directory: Path) -> None:
    """Raise before creating the page when any required local SVG is absent."""
    missing = [
        asset.name
        for asset in FIGURE_ASSETS
        if not (run_directory / "figures" / f"{asset.name}.svg").is_file()
    ]
    if missing:
        names = ", ".join(missing)
        raise FileNotFoundError(f"run report needs complete figure inventory: {names}")


def _overview(artifact: QAArtifact) -> str:
    device = device_line(artifact.provenance) or "Device metadata unavailable"
    return "\n".join(
        (
            _metadata("Acquisition", acquisition_line(artifact)),
            _metadata("Device", device),
            _metadata("Localization and clipping", "See the warning notice below."),
        )
    )


def _warnings(artifact: QAArtifact, incomplete: bool) -> str:
    notes = acquisition_notes(artifact)
    messages = []
    if incomplete:
        messages.append(
            '<p class="notice notice-incomplete"><strong>Site incomplete.</strong> '
            "One or more requested inputs were not rendered. "
            '<a href="../../index.html#omissions">View omitted inputs.</a></p>'
        )
    if notes:
        messages.append(
            '<p class="notice notice-warning">'
            "<strong>Localization or clipping warning.</strong> "
            f"{_text(notes)}</p>"
        )
    else:
        messages.append(
            '<p class="notice">No localization or clipping warnings recorded.</p>'
        )
    messages.append(
        '<p class="threshold-note">These values are descriptive. '
        "This report applies no acceptance thresholds.</p>"
    )
    return "\n".join(messages)


def _metrics(artifact: QAArtifact) -> str:
    measurements = artifact.measurements
    return "\n".join(_metric_card(doc, measurements) for doc in METRIC_DOCS)


def _metric_card(doc: MetricDoc, measurements: Measurements) -> str:
    value = doc.value(measurements)
    unit = doc.unit(measurements)
    display = doc.fmt(measurements) if math.isfinite(value) else _UNAVAILABLE
    return f"""<article class="metric-card">
  <h3>{_text(doc.label)}</h3>
  <p class="metric-value">{_text(display)}</p>
  <p class="metric-unit">Unit: {_text(_unit_label(unit))}</p>
  <p>{_text(doc.definition)}</p>
</article>"""


def _unit_label(unit: str) -> str:
    return "dimensionless" if unit == "1" else unit


def _acquisition(artifact: QAArtifact) -> str:
    settings = artifact.settings
    provenance = artifact.provenance
    rows = (
        ("Acquisition", acquisition_line(artifact)),
        (
            "Scanner and acquisition details",
            provenance_line(provenance) or "Unavailable",
        ),
        ("Series", _unknown(provenance.series)),
        ("Acquired at", provenance.datetime or "Unknown"),
        ("Analyzed at", provenance.created or "Unknown"),
        ("Trimmed frames", _unknown(provenance.n_trimmed)),
        ("Recorded PE direction", _unknown(provenance.pe_dir)),
        ("Trim duration", f"{settings.trim_sec:g} s"),
        ("Detrend method", settings.detrend),
        ("Resolved detrend order", _unknown(settings.detrend_order)),
        ("ROI center", settings.center),
        ("Requested ROI side", f"{settings.roi_size} voxels"),
        ("PE axis override", _unknown(settings.pe_axis_override)),
    )
    return "\n".join(_metadata(label, value) for label, value in rows)


def _figures() -> str:
    groups = (
        ("Image diagnostics", FIGURE_ASSETS[:5]),
        ("Temporal and spatial diagnostics", FIGURE_ASSETS[5:]),
    )
    sections = []
    for heading, assets in groups:
        cards = "\n".join(
            f'''<figure class="figure-card">
  <a href="figures/{asset.name}.svg" aria-label="Open {_attribute(asset.title)} SVG">
    <img src="figures/{asset.name}.svg" alt="{_attribute(asset.description)}">
  </a>
  <figcaption><strong>{_text(asset.title)}</strong>
    {_text(asset.description)}</figcaption>
</figure>'''
            for asset in assets
        )
        sections.append(
            f"<section><h3>{_text(heading)}</h3>"
            f'<div class="figure-grid">{cards}</div></section>'
        )
    return "\n".join(sections)


def _methods() -> str:
    return "\n".join(
        f"""<details>
  <summary>{_text(doc.label)}</summary>
  <p><strong>Definition:</strong> {_text(doc.definition)}</p>
  <p><strong>Method:</strong> {_text(doc.method)}</p>
</details>"""
        for doc in METRIC_DOCS
    )


def _provenance(artifact: QAArtifact, report_version: str) -> str:
    provenance = artifact.provenance
    rows = (
        ("Source", provenance.source or "Unknown"),
        ("Scan name", provenance.scan or "Unknown"),
        ("Core version", provenance.core_version or "Unknown"),
        ("Loaded artifact schema", str(artifact.schema_version)),
        ("Report version", report_version or "Unknown"),
    )
    return "\n".join(_metadata(label, value) for label, value in rows)


def _metadata(label: str, value: object) -> str:
    return f"<div><dt>{_text(label)}</dt><dd>{_text(value)}</dd></div>"


def _unknown(value: object | None) -> object:
    return "Unknown" if value is None else value


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _attribute(value: object) -> str:
    return html.escape(str(value), quote=True)
