# From Python

The command is a thin shell over `write_run_page`; it and `render_run_page` are
importable from `fmriqc_report`. Both take a loaded `QAArtifact`; reading one from disk is
core's job, through `fmriqc.analysis.load_artifact`, which reads any file the
command would (see {doc}`/user-guide/artifact`).

```python
from fmriqc.analysis import load_artifact
from fmriqc_report import Theme, write_run_page

artifact = load_artifact("qa.nc")
write_run_page(
    artifact,
    "reports/2026-09-24.html",
    title="Bay 2 weekly phantom",
    theme=Theme(panel_accent="#8a1538"),
)
```

## The two functions

`render_run_page(artifact, *, title=None, report_version=None, theme=DEFAULT_THEME)`
returns the complete page as a string. Nothing is written.

`write_run_page(artifact, path, *, title=None, report_version=None, theme=DEFAULT_THEME)`
renders the same page and writes it to `path`, returning the path. The write
is the command's: rendered fully in memory first, then moved into place
atomically, with missing parent directories created (see
{doc}`fmri-qa-report`).

The keyword arguments are the same for both:

- `title` — the page's heading and `<title>`. Without one, the scan name
  recorded in the artifact, else the file name of the series it was computed
  from.
- `report_version` — the version the page names in its provenance table and
  footer. Without one, the installed `fmri-qa-report` version.
- `theme` — how the figures are drawn (below).

`load_artifact` raises `fmriqc.analysis.InvalidArtifactError` for a file it
cannot read, and a caller catches that, as the command does.

## Themes

A `Theme` is a frozen dataclass of the visual decisions the figures are drawn
with. Its fields and their defaults:

| Field | Default | What it sets |
| --- | --- | --- |
| `panel_cmap` | `"gray"` | the colormap of the image figures |
| `panel_accent` | `"#1f77b4"` (matplotlib's `tab:blue`) | the color of the measured series in the Weisskoff, decorrelation, ROI signal, residual, spectrum and outlier-fraction plots |
| `panel_font_family` | `None` (matplotlib's default family) | the figures' font |

`DEFAULT_THEME` is `Theme()`, the report's established look. A group rebrands
by constructing its own — `Theme(panel_accent=..., panel_font_family=...)` —
and passing it as `theme`. The accent replaces only the first color in the
plot cycle. The multi-series plots — in-plane motion, center of mass and point
spread — name their colors explicitly and keep them, so each trace keeps its
meaning. A theme styles the figures only: the page's own colors come from its
stylesheet.

## Importing

`import fmriqc_report`, and importing `Theme` or `DEFAULT_THEME` from it, does
not import matplotlib. The renderer, and with it matplotlib, is loaded when
`render_run_page` or `write_run_page` is first looked up on the package —
including by `from fmriqc_report import write_run_page`. Figures are built as `matplotlib.figure.Figure` objects and saved
straight to SVG, under a local `rc_context` for the theme, so rendering needs
no `pyplot`, selects no backend, and leaves the process's matplotlib settings
as it found them.
