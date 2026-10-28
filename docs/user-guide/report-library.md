# From Python

The command loads the artifact, renders it with `render_run_page` from
`fmriqa_report`, and writes the string it returns. `fmriqa_report` itself reads and
writes no file, so the load and the write are yours. Load an artifact with
`fmriqa_io.load_artifact`, which reads any file the command would (see
{doc}`/user-guide/artifact`). `fmriqa_io.rename.write_text_atomically` writes the
page the way the command does: through a temporary file moved into place, with
missing parent directories created, so a reader never sees a partial page.

```python
from fmriqa_io import load_artifact
from fmriqa_io.rename import write_text_atomically
from fmriqa_report import Theme, render_run_page

artifact = load_artifact("qa.nc")
page = render_run_page(
    artifact,
    title="Bay 2 weekly phantom",
    theme=Theme(panel_accent="#8a1538"),
)
write_text_atomically("reports/2026-09-24.html", page)
```

## The function

`render_run_page(artifact, *, title=None, report_version=None, theme=DEFAULT_THEME)`
returns the complete page as a string. Nothing is written. The
{doc}`API reference </api/fmri-qa-report>` has the signature and parameters.

The keyword arguments:

- `title`: the page's heading and `<title>`. Without one, the scan name recorded
  in the artifact, else the file name of the series it was computed from.
- `report_version`: the version the page names in its provenance table and
  footer. Without one, the installed `fmri-qa-report` version.
- `theme`: how the figures are drawn (below).

`load_artifact` raises `fmriqa.analysis.InvalidArtifactError` for a file it
cannot read, and a caller catches that, as the command does.

## Themes

A `Theme` is a frozen dataclass of the visual choices the figures are drawn with.
Its fields and their defaults:

| Field | Default | What it sets |
| --- | --- | --- |
| `panel_cmap` | `"gray"` | the colormap of the image figures |
| `panel_accent` | `"#1f77b4"` (matplotlib's `tab:blue`) | the color of the measured series in the Weisskoff, decorrelation, ROI signal, residual, spectrum and outlier-fraction plots |
| `panel_font_family` | `None` (matplotlib's default family) | the figures' font |

`DEFAULT_THEME` is `Theme()`, the report's usual look. To rebrand, pass your own,
such as `Theme(panel_accent=..., panel_font_family=...)`, as `theme`. The accent
replaces only the first color in the plot cycle. The multi-series plots (in-plane
motion, center of mass and point spread) set their colors explicitly and keep
them, so each trace keeps its meaning. A theme styles the figures only. The
page's colors come from its stylesheet.

## Importing

Importing `fmriqa_report`, `Theme` or `DEFAULT_THEME` does not import matplotlib.
The renderer, and with it matplotlib, loads when `render_run_page` is first
looked up on the package, including by `from fmriqa_report import render_run_page`.
Figures are built as
`matplotlib.figure.Figure` objects and saved straight to SVG under a local
`rc_context` for the theme. Rendering needs no `pyplot`, selects no backend, and
leaves the process's matplotlib settings unchanged.
