# The report

A report is a single page, intended to be read from top to bottom. A masthead
gives the title of the scan, a one-line summary of its acquisition, and the
scanner, coil and acquisition time. A bar beneath it links to each section.

## Sections

The sections appear in the following order.

1. **Metrics.** A tile is shown for each of the fifteen headline metrics: SNR,
   SFNR, RDC, the four ghost measures, drift, percent fluctuation, the three
   outlier and spike scores, the largest translation and center-of-mass
   displacement, and FWHM. Each tile gives the recorded unit and a one-line
   definition. A measurement whose estimator could not resolve a value shows a
   dash and a statement to that effect in place of a number. The values are
   descriptive, and the report applies no acceptance thresholds. Beneath the
   tiles, a note carries any
   {doc}`localization </user-guide/analyses/localization>` or
   {doc}`clipping </user-guide/analyses/saturation>` warning recorded in the
   analysis file, or states that there was none.
2. **Acquisition and analysis settings.** These describe what was acquired
   (series, times, trimmed frames, recorded phase-encode direction) and how the
   analysis was configured (trim, detrending, ROI center and size, and any
   phase-encode override).
3. **Figures**, in the two groups listed below.
4. **Definitions and methods.** The definition and method of each metric, as
   one collapsible entry per metric.
5. **Source and provenance.** The source, the scan name, the acquisition and
   analysis times, the version of the core package that wrote the analysis file,
   the schema version of the analysis file as loaded, and the report version.

## Figures

Every figure is drawn from values stored in the analysis file. The tables below
list each figure with the analysis that computes what it plots. The phantom
outline and the summary ROI on the image figures, and the invalid image edge
marked on the ghost figure when one is present, are provided by
{doc}`/user-guide/analyses/localization`.

**Image diagnostics** are per-frame and static spatial views of the phantom,
noise and ghost regions:

| Figure | What it draws | Computed by |
| --- | --- | --- |
| Signal | mean phantom signal, with the phantom outline and the summary ROI | {doc}`/user-guide/analyses/stability` |
| SFNR | voxelwise signal-to-fluctuation-noise ratio, with the ROI | {doc}`/user-guide/analyses/stability` |
| Fluctuation noise | temporal fluctuation-noise image, log-scaled, with outline and ROI | {doc}`/user-guide/analyses/stability` |
| Static noise | odd–even static-noise image, with outline and ROI | {doc}`/user-guide/analyses/stability` |
| N/2 ghost regions | mean image with the phase-encode and readout ghost sampling regions | {doc}`/user-guide/analyses/ghosting` |

**Temporal and spatial diagnostics** show the stability of the time series, the
motion, and the spatial resolution over the run:

| Figure | What it draws | Computed by |
| --- | --- | --- |
| Weisskoff curve | coefficient of variation by ROI width, against the ideal | {doc}`/user-guide/analyses/stability` |
| Decorrelation factor by ROI width | the RDC by ROI width, against the ideal | {doc}`/user-guide/analyses/stability` |
| ROI mean signal | ROI mean over time, with its fitted trend | {doc}`/user-guide/analyses/stability` |
| ROI residual | the detrended ROI mean, titled with its spike score | {doc}`/user-guide/analyses/stability`; the score from {doc}`/user-guide/analyses/outliers` |
| Residual spectrum | magnitude spectrum of the residual, titled with its spike score | {doc}`/user-guide/analyses/stability`; the score from {doc}`/user-guide/analyses/outliers` |
| Outlier fraction | per-volume fraction of outlier voxels | {doc}`/user-guide/analyses/outliers` |
| In-plane motion | registration translation, scale and shear over time | {doc}`/user-guide/analyses/motion` |
| Whole-slice center of mass | the centroid's deviation over time | {doc}`/user-guide/analyses/motion` |
| Directional point-spread function | empirical and Gaussian point-spread profiles per direction | {doc}`/user-guide/analyses/smoothness` |

## The page as a file

A report is a single HTML file with no external dependencies. It can be sent by
email, attached to a QA record, or placed on an existing website.

- **Self-contained.** The stylesheet is inlined in a `<style>` element, and
  every figure is an SVG embedded as a `data:` URI. The page makes no network
  request and refers to no accompanying file.
- **No JavaScript.** The page contains no script and sets no
  Content-Security-Policy of its own. A site that serves it under such a policy
  needs to allow only inline styles (`style-src 'unsafe-inline'`, or the hash of
  the stylesheet) and `data:` images (`img-src data:`).
- **Enlargeable figures.** Clicking a figure enlarges it to fill the window, and
  clicking again closes it. The behavior relies on the CSS `:target` selector,
  so it works where scripts are blocked, and each figure also has a fragment
  address (`#fig-sfnr`, `#fig-motion`, …).
- **Dark mode** follows the setting of the reader's operating system, and there
  is no toggle. The figures remain on a white background in both modes, so that
  plotted data keep their colors.
- **Print layout.** A print stylesheet omits the section bar, arranges the
  figures two or three to a row, keeps each figure, tile and definition whole on
  one page, and prints every collapsed definition expanded. An enlarged figure
  prints in its normal position.
