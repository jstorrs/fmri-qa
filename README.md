# fmri-qa

fmri-qa measures how stable an MRI scanner is during an fMRI acquisition, from
a phantom series. It follows the Glover/FBIRN stability protocol (Friedman &
Glover, 2006): SNR, SFNR, the Weisskoff radius of decorrelation, drift and
fluctuation, with Nyquist ghosting, receiver clipping, outlier volumes and
spikes, gradient-heating motion, and noise smoothness beside them. Each series
gets a self-contained HTML report, and its numbers are saved in a file that
MATLAB, R, Python or a trend database can read.

**[Open fmri-qa in your browser](https://jstorrs.github.io/fmri-qa/app/)** to try
it with nothing to install. It converts and analyzes DICOM on your own computer
and sends nothing anywhere. The
**[documentation](https://jstorrs.github.io/fmri-qa/)** covers everything below
in more detail.

## Running QA

Three ways, all running the same analysis:

- **[In the browser](https://jstorrs.github.io/fmri-qa/user-guide/browser.html)**:
  open the page, give it DICOM, choose the series. You can save the page (one
  HTML file) and run it offline on a machine where nothing can be installed.
- **[The desktop panel](https://jstorrs.github.io/fmri-qa/user-guide/panel.html)**:
  `fmri-qa-panel` opens a window that runs a DICOM folder into an output folder.
- **[From a terminal](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa-run.html)**:

  ```console
  $ fmri-qa-run DICOM_DIR OUTPUT_DIR
  ```

Each series found under `DICOM_DIR` is converted with
[dcm2niix](https://github.com/rordenlab/dcm2niix), analyzed, and written to a
folder of its own:

```text
OUTPUT_DIR/
  20260909_143012_s002_QA_EPI_ISO/
    20260909_143012_s002_QA_EPI_ISO.nii.gz   the converted scan
    20260909_143012_s002_QA_EPI_ISO.json     its acquisition sidecar
    20260909_143012_s002_QA_EPI_ISO.qa.nc    the analysis file
    20260909_143012_s002_QA_EPI_ISO.html     the report: double-click to open
```

Patient identifiers are stripped from the sidecar, and the dates kept. A series
that already has a folder is left alone, so running the same DICOM again adds
only the new series. A failure in one series is reported and the rest still run.

## Installing

The panel and the commands install from GitHub with
[uv](https://docs.astral.sh/uv/getting-started/installation/), which also
fetches Python 3.13 if needed. dcm2niix is included:

```console
$ uv tool install "fmri-qa-launcher @ git+https://github.com/jstorrs/fmri-qa#subdirectory=packages/fmri-qa-launcher" --with-executables-from fmri-qa-cli
```

[Installing](https://jstorrs.github.io/fmri-qa/user-guide/install.html) has the
details, including using your own dcm2niix build.

## What you get

- **The report**: one HTML page per series with the headline numbers, any
  localization or clipping warning, the acquisition and analysis settings,
  fourteen figures, and each metric's definition. It applies no pass or fail
  thresholds. It needs no network or other file, so you can email it, attach it
  to a QA record or put it on a website, and it prints well.
  [What the report shows](https://jstorrs.github.io/fmri-qa/user-guide/report-page.html).
- **The numbers**: `fmri-qa` prints a table, or JSON for a trend database, and
  the `.qa.nc` analysis file holds every number, curve and image for MATLAB, R
  or Python. [Analyzing NIfTI scans](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa.html)
  and [the analysis file](https://jstorrs.github.io/fmri-qa/user-guide/analysis-file.html).

## What it measures

Each analysis has a page with its purpose, method and equations, and a figure
from a synthetic phantom.

| Analysis | Measures |
| --- | --- |
| [FBIRN stability](https://jstorrs.github.io/fmri-qa/user-guide/analyses/stability.html) | SNR, SFNR, drift and percent fluctuation over a fixed ROI, and the Weisskoff radius of decorrelation |
| [Phantom localization](https://jstorrs.github.io/fmri-qa/user-guide/analyses/localization.html) | where the phantom and the summary ROI are, and whether either landed correctly |
| [Nyquist ghosting](https://jstorrs.github.io/fmri-qa/user-guide/analyses/ghosting.html) | the N/2 ghost: FBIRN percent ghost, its brightest-10% companion, the readout baseline, and the ACR/AAPM ghosting ratio |
| [ADC saturation](https://jstorrs.github.io/fmri-qa/user-guide/analyses/saturation.html) | whether the receiver clipped, before and after the warm-up volumes dropped, or that it cannot be told |
| [Outliers and spikes](https://jstorrs.github.io/fmri-qa/user-guide/analyses/outliers.html) | the worst volume's outlier-voxel fraction (as AFNI `3dToutcount`), and spike scores in time and frequency |
| [Motion and deformation](https://jstorrs.github.io/fmri-qa/user-guide/analyses/motion.html) | the translation, scale and shear that gradient heating produces, and the center-of-mass shift |
| [Smoothness and point spread](https://jstorrs.github.io/fmri-qa/user-guide/analyses/smoothness.html) | the noise smoothness (FWHM) along phase-encode and readout (as AFNI `3dFWHMx`), against which the RDC is read |
| [Thermal versus instability noise](https://jstorrs.github.io/fmri-qa/user-guide/analyses/hilo.html) | `fmri-qa-hilo`: a high/low flip-angle pair split into thermal and instability noise (Greve) |

## The commands

| Command | Does |
| --- | --- |
| [`fmri-qa-run`](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa-run.html) | DICOM in, one report folder per series out; with no arguments, opens the panel |
| [`fmri-qa-panel`](https://jstorrs.github.io/fmri-qa/user-guide/panel.html) | the desktop panel |
| [`fmri-qa-import`](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa-import.html) | DICOM to NIfTI, with dcm2niix settings that keep the QA checks valid, and names that sort |
| [`fmri-qa`](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa.html) | analyze NIfTI scans into a table, JSON, or analysis files |
| [`fmri-qa-hilo`](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa.html#thermal-and-instability-noise-fmri-qa-hilo) | thermal versus instability noise from a flip-angle pair |
| [`fmri-qa-report`](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa-report.html) | render an analysis file as a report |

Each takes `--help` and `--version`.

## For developers

fmri-qa is a [uv](https://docs.astral.sh/uv/) workspace of Python packages:
calculation (`fmri-qa-core`), file IO (`fmri-qa-io`), the commands
(`fmri-qa-cli`), the report (`fmri-qa-report`) and the launcher
(`fmri-qa-launcher`). Calculation reads no files, which is what lets it run in
the browser. `uv sync --all-packages` sets up the development environment and
`make check` runs the tests.
[For developers](https://jstorrs.github.io/fmri-qa/user-guide/developers.html)
covers the packages, calling fmri-qa from Python, and building the project, and
`web/README.md` covers the browser page.

## Citing, changes and licence

Published work using fmri-qa should cite the software metadata in
[`CITATION.cff`](CITATION.cff). User-facing changes are recorded in
[`CHANGELOG.md`](CHANGELOG.md).

fmri-qa is available under the [MIT License](LICENSE). The browser page bundles
third-party software under its own licences, listed under "About & licences" in
its footer. If you pass the HTML file on, keep that footer, or ship
`web/THIRD_PARTY_NOTICES.md` next to it.
