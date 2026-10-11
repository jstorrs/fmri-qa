# What the report shows

A report is one page, read top to bottom. A masthead gives the scan's title,
its acquisition in a line, and the scanner, coil and acquisition time; a bar
beneath it links to each section.

## The sections

In the order they appear:

1. **Metrics** — a tile for each of the fifteen headline metrics (SNR, SFNR,
   RDC, the four ghost measures, drift, percent fluctuation, the three outlier
   and spike scores, the largest translation and center-of-mass displacement,
   and FWHM), each with its recorded unit and a one-line definition. A
   measurement whose estimator could not be resolved shows a dash and says so
   instead of a number. The values are descriptive: the report applies no
   acceptance thresholds. Beneath the tiles, a note carries any
   {doc}`localization </user-guide/analyses/localization>` or
   {doc}`clipping </user-guide/analyses/saturation>` warning the artifact
   recorded, or says that none was.
2. **Acquisition and analysis settings** — what was acquired (series, times,
   trimmed frames, recorded phase-encode direction) and how the analysis was
   configured (trim, detrending, ROI center and size, any phase-encode
   override).
3. **Figures**, in two groups, listed below.
4. **Definitions and methods** — each metric's definition and method, one
   collapsible entry per metric.
5. **Source and provenance** — the source, scan name, acquisition and analysis
   times, the core version that wrote the artifact, the artifact schema version
   loaded, and the report version.

## The figures

Every figure is drawn from values stored in the artifact. Each is listed with
the analysis that computes what it plots. The phantom outline and summary ROI
drawn over the image figures, and the invalid image edge marked on the ghost
figure when there is one, come from {doc}`/user-guide/analyses/localization`.

**Image diagnostics** — per-frame and static spatial views of the phantom,
noise and ghost regions:

| Figure | What it draws | Computed by |
| --- | --- | --- |
| Signal | mean phantom signal, with the phantom outline and the summary ROI | {doc}`/user-guide/analyses/stability` |
| SFNR | voxelwise signal-to-fluctuation-noise ratio, with the ROI | {doc}`/user-guide/analyses/stability` |
| Fluctuation noise | temporal fluctuation-noise image, log-scaled, with outline and ROI | {doc}`/user-guide/analyses/stability` |
| Static noise | odd–even static-noise image, with outline and ROI | {doc}`/user-guide/analyses/stability` |
| N/2 ghost regions | mean image with the phase-encode and readout ghost sampling regions | {doc}`/user-guide/analyses/ghosting` |

**Temporal and spatial diagnostics** — time-series stability, motion and
spatial resolution across the run:

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

A report is a single HTML file that needs nothing beside it, so it can be
emailed, attached to a QA record, or dropped as-is into an existing website.

- **Self-contained.** The stylesheet is inlined in a `<style>` element and
  every figure is an SVG embedded as a `data:` URI. The page makes no network
  request and refers to no sibling file.
- **No JavaScript.** The page has no script at all, and sets no
  Content-Security-Policy of its own. A site that serves it under one needs to
  allow only inline styles (`style-src 'unsafe-inline'`, or the stylesheet's
  hash) and `data:` images (`img-src data:`).
- **Click to enlarge.** Clicking a figure enlarges it to fill the window, and
  clicking it again closes it — done in CSS alone, with the `:target`
  selector, so it works where scripts are blocked. Each figure is therefore
  also addressable by a fragment (`#fig-sfnr`, `#fig-motion`, …).
- **Dark mode** follows the reader's operating-system setting; there is no
  toggle. The figures stay on a white plate in both, so plotted data keeps its
  colors.
- **Print-ready.** A print stylesheet drops the section bar, lays the figures
  out two or three to a row, keeps each figure, tile and definition whole on
  one page, and prints every collapsed definition open. An enlarged figure
  prints in place like the rest.
