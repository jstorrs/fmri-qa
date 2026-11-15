# Rendering from Python

The `fmri-qa-report` command loads an analysis file, renders it with
`render_run_page` from `fmriqa_report`, and writes the string that the function
returns. `fmriqa_report` itself neither reads nor writes any file, so loading
and writing are left to the caller. An analysis file is loaded with
`fmriqa_io.load_analysis`, which reads every file the command accepts (see
{doc}`/user-guide/analysis-file`). `fmriqa_io.rename.write_text_atomically`
writes the page as the command does: through a temporary file that is moved into
place, with missing parent directories created, so that a reader never observes
a partial page.

```python
from fmriqa_io import load_analysis
from fmriqa_io.rename import write_text_atomically
from fmriqa_report import Theme, render_run_page

analysis = load_analysis("qa.nc")
page = render_run_page(
    analysis,
    title="Bay 2 weekly phantom",
    theme=Theme(panel_accent="#8a1538"),
)
write_text_atomically("reports/2026-09-24.html", page)
```

## The function

`render_run_page(analysis, *, title=None, report_version=None, theme=DEFAULT_THEME)`
returns the complete page as a string and writes nothing. The
{doc}`API reference </api/fmri-qa-report>` gives the signature and parameters.
The keyword arguments are as follows:

- `title` is the heading of the page and its `<title>`. The default is the scan
  name recorded in the analysis file or, failing that, the file name of the
  series from which it was computed.
- `report_version` is the version that the page states in its provenance table
  and footer. The default is the installed version of `fmri-qa-report`.
- `theme` determines how the figures are drawn, as described below.

`load_analysis` raises `fmriqa.analysis.InvalidAnalysisFileError` for a file it
cannot read. A caller should catch that exception, as the command does.

## Themes

A `Theme` is a frozen dataclass of the visual parameters with which the figures
are drawn. Its fields and their defaults are:

| Field | Default | What it sets |
| --- | --- | --- |
| `panel_cmap` | `"gray"` | the colormap of the image figures |
| `panel_accent` | `"#1f77b4"` (matplotlib's `tab:blue`) | the color of the measured series in the Weisskoff, decorrelation, ROI signal, residual, spectrum and outlier-fraction plots |
| `panel_font_family` | `None` (matplotlib's default family) | the figures' font |

`DEFAULT_THEME` is `Theme()`, the standard appearance of the report. A custom
appearance is obtained by passing another instance, such as
`Theme(panel_accent=..., panel_font_family=...)`, as `theme`. The accent
replaces only the first color of the plot cycle. The multi-series plots
(in-plane motion, center of mass, and point spread) set their colors explicitly
and retain them, so that each trace keeps its meaning. A theme affects the
figures only. The colors of the page are set by its stylesheet.

## Import behavior

Importing `fmriqa_report`, `Theme` or `DEFAULT_THEME` does not import
matplotlib. The renderer, and matplotlib with it, is loaded when
`render_run_page` is first accessed on the package, which includes
`from fmriqa_report import render_run_page`. Figures are constructed as
`matplotlib.figure.Figure` objects and saved directly to SVG under a local
`rc_context` for the theme. Rendering requires no `pyplot`, selects no backend,
and leaves the matplotlib settings of the process unchanged.
