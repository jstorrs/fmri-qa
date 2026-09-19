"""Compose one self-contained, offline HTML page from a completed artifact.

The page needs no companion file: the stylesheet is inlined and every figure
is embedded as a ``data:`` URI, so it opens from ``file://`` with no network
or sibling asset. It can be published inside a site (see :class:`SiteContext`)
or handed out entirely on its own, as a PDF alternative a physicist can
double-click, email, or drop into their own website.
"""

import html
import math
import re
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path
from string import Template

from fmriqc.analysis import Measurements, QAArtifact

from ...atomic import atomic_file
from ...content import METRIC_DOCS, MetricDoc
from ...summary import (
    acquisition_line,
    acquisition_notes,
    device_line,
    package_version,
    provenance_line,
)
from ...theme import DEFAULT_THEME, Theme
from . import resources
from .figures import RenderedFigure, render_figures

__all__ = ["SiteContext", "render_run_page", "write_run_page"]


_UNAVAILABLE = "Unavailable — estimator unresolved"

# Splits a formatted metric value ("4.03%", "0.04mm", "449.7") into its
# leading number and trailing unit; a bare number leaves ``u`` empty.
_VALUE = re.compile(r"(?P<n>-?[\d.,]+(?:[eE][-+]?\d+)?)\s*(?P<u>.*)\Z")


@dataclass(frozen=True, slots=True)
class SiteContext:
    """A run page's place inside a published site, when it is published in one.

    ``index_href`` is the fixed relative route from the page to the inventory
    that lists it; a publisher supplies it, and no artifact field ever reaches
    it.  ``incomplete`` can only be recorded alongside that route, because a
    standalone page has no inventory to say what is missing from.
    """

    index_href: str
    incomplete: bool = False

    def __post_init__(self) -> None:
        value = self.index_href
        if not value:
            raise ValueError("index_href must be a non-empty relative route")
        if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in value):
            raise ValueError(
                "index_href must be a relative route with no whitespace or "
                "control characters"
            )
        if "\\" in value:
            raise ValueError("index_href must be a relative route with no backslashes")
        if value.startswith("/"):
            raise ValueError(
                "index_href must be a relative route, not an absolute path"
            )
        if "#" in value or "?" in value:
            raise ValueError(
                "index_href must be a relative route with no fragment or query "
                "component; the page appends its own fragment"
            )
        head = value.split("/", maxsplit=1)[0]
        if ":" in head:
            raise ValueError("index_href must not carry a URL scheme")


def render_run_page(
    artifact: QAArtifact,
    *,
    title: str | None = None,
    report_version: str | None = None,
    site: SiteContext | None = None,
    theme: Theme = DEFAULT_THEME,
) -> str:
    """Return one complete, self-contained HTML document for ``artifact``.

    The result needs no companion file: the stylesheet is inlined and every
    figure is embedded as a ``data:`` URI, so it opens from ``file://`` with
    no network or sibling asset.  With no ``site`` it carries no link out at
    all.
    """
    page_title = (
        title or artifact.provenance.scan or Path(artifact.provenance.source).name
    )
    version = report_version or package_version()
    rendered_figures = render_figures(artifact, theme=theme)
    figures_image, figures_stability = _figures(rendered_figures)
    values = {
        "title": _text(page_title),
        "stylesheet": resources.read_stylesheet(),
        "subline": _subline(artifact),
        "idblock": _idblock(artifact),
        "nav": _nav(site),
        "metrics": _metrics(artifact),
        "notices": _notices(artifact, site),
        "acquisition": _acquisition(artifact),
        "figures_image": figures_image,
        "figures_stability": figures_stability,
        "methods": _methods(),
        "provenance": _provenance(artifact, version),
        "version": _text(version),
    }
    template = Template(resources.read_resource(resources.RUN_TEMPLATE))
    return template.substitute(values)


def write_run_page(
    artifact: QAArtifact,
    path: Path | str,
    *,
    title: str | None = None,
    report_version: str | None = None,
    site: SiteContext | None = None,
    theme: Theme = DEFAULT_THEME,
) -> Path:
    """Write :func:`render_run_page`'s document to ``path`` and return it.

    The write is atomic, matching ``formats.reportlab.packet``'s convention:
    the page is rendered fully in memory first, then written to a sibling
    temporary file and moved into place with :meth:`Path.replace`, so a reader
    never observes a partial file and a failed render or write never disturbs
    an existing destination.
    """
    target = Path(path)
    page = render_run_page(
        artifact, title=title, report_version=report_version, site=site, theme=theme
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_file(target) as temporary:
        temporary.write_text(page, encoding="utf-8")
    return target


def _subline(artifact: QAArtifact) -> str:
    return _text(acquisition_line(artifact))


def _idblock(artifact: QAArtifact) -> str:
    prov = artifact.provenance
    rows = (
        ("Scanner", device_line(prov) or "Unknown"),
        ("Coil", prov.coil or "Unknown"),
        ("Acquired", prov.datetime or "Unknown"),
    )
    return "\n".join(
        f"<div><dt>{_text(label)}</dt><dd>{_text(value)}</dd></div>"
        for label, value in rows
    )


def _nav(site: SiteContext | None) -> str:
    links = [
        ("#metrics", "Metrics"),
        ("#acquisition", "Acquisition"),
        ("#figures", "Figures"),
        ("#methods", "Definitions"),
        ("#provenance", "Provenance"),
    ]
    if site is not None:
        links.append((site.index_href, "Report index"))
    return "\n    ".join(
        f'<a href="{_text(href)}">{_text(label)}</a>' for href, label in links
    )


def _figure_src(rendered: RenderedFigure) -> str:
    """Return the complete, self-contained ``data:`` source for one figure."""
    return "data:image/svg+xml;base64," + b64encode(rendered.svg).decode("ascii")


def _notices(artifact: QAArtifact, site: SiteContext | None) -> str:
    notes = acquisition_notes(artifact)
    messages = []
    if site is not None and site.incomplete:
        messages.append(
            '<p class="note alert"><span class="pill warn">Incomplete</span> '
            "<strong>Site incomplete.</strong> One or more requested inputs were "
            f'not rendered. <a href="{_text(site.index_href)}#omissions">'
            "View omitted inputs.</a></p>"
        )
    if notes:
        messages.append(
            '<p class="note alert"><span class="pill warn">Warning</span> '
            f"<strong>Localization or clipping warning.</strong> {_text(notes)}</p>"
        )
    else:
        messages.append(
            '<p class="note"><span class="pill muted">None recorded</span> '
            "No localization or clipping warnings recorded.</p>"
        )
    return "\n".join(messages)


def _metrics(artifact: QAArtifact) -> str:
    measurements = artifact.measurements
    return "\n".join(_metric_tile(doc, measurements) for doc in METRIC_DOCS)


def _metric_tile(doc: MetricDoc, measurements: Measurements) -> str:
    value = doc.value(measurements)
    if math.isfinite(value):
        value_html = _split_value(doc.fmt(measurements))
        note_html = _text(doc.definition)
    else:
        value_html = "—"
        note_html = (
            f'<span class="pill muted">{_text(_UNAVAILABLE)}</span> '
            f"{_text(doc.definition)}"
        )
    return (
        f'<div class="tile metric" id="metric-{_text(doc.name)}">'
        f'<span class="k">{_text(doc.label)}</span>'
        f'<span class="v num">{value_html}</span>'
        f'<span class="n">{note_html}</span></div>'
    )


def _split_value(text: str) -> str:
    match = _VALUE.match(text)
    if not match or not match.group("u"):
        return _text(text)
    return f"{_text(match.group('n'))}<small>{_text(match.group('u'))}</small>"


def _kv_row(label: str, value: object) -> str:
    return f'<tr><th scope="row">{_text(label)}</th><td>{_text(value)}</td></tr>'


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
    return "\n".join(_kv_row(label, value) for label, value in rows)


def _figure(rendered: RenderedFigure) -> str:
    asset = rendered.asset
    name = _text(asset.name)
    return (
        f'<figure class="fig" id="fig-{name}">'
        f'<img src="{_figure_src(rendered)}" alt="{_text(asset.title)}">'
        '<figcaption><div class="zoomrow">'
        f"<strong>{_text(asset.title)}</strong> "
        f'<a class="zoom" href="#fig-{name}">Enlarge</a>'
        '<a class="zoom close" href="#figures">Close</a></div>'
        f"<span>{_text(asset.description)}</span></figcaption></figure>"
    )


def _figures(rendered_figures: tuple[RenderedFigure, ...]) -> tuple[str, str]:
    image_html = "\n".join(_figure(rendered) for rendered in rendered_figures[:5])
    stability_html = "\n".join(_figure(rendered) for rendered in rendered_figures[5:])
    return image_html, stability_html


def _methods() -> str:
    return "\n".join(
        f'<details class="method"><summary>{_text(doc.label)}</summary>'
        f"<p><strong>Definition:</strong> {_text(doc.definition)}</p>"
        f"<p><strong>Method:</strong> {_text(doc.method)}</p></details>"
        for doc in METRIC_DOCS
    )


def _provenance(artifact: QAArtifact, report_version: str) -> str:
    provenance = artifact.provenance
    rows = (
        ("Source", provenance.source or "Unknown"),
        ("Scan name", provenance.scan or "Unknown"),
        ("Acquired at", provenance.datetime or "Unknown"),
        ("Analyzed at", provenance.created or "Unknown"),
        ("Core version", provenance.core_version or "Unknown"),
        ("Loaded artifact schema", str(artifact.schema_version)),
        ("Report version", report_version or "Unknown"),
    )
    return "\n".join(_kv_row(label, value) for label, value in rows)


def _unknown(value: object | None) -> object:
    return "Unknown" if value is None else value


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)
