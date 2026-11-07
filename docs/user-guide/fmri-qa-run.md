# The command line

```console
$ fmri-qa-run DICOM_DIR OUTPUT_DIR [options]
```

`DICOM_DIR` is searched down to five levels of sub-directories. Each series found
is converted and, unless its folder already exists, analyzed and published as a
folder under `OUTPUT_DIR` (see {doc}`run-output`). `OUTPUT_DIR` is created if
missing and must not be `DICOM_DIR`.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--trim-sec TRIM_SEC` | `5` | seconds of initial, not yet steady-state, volumes to drop before anything is measured; a finite number, zero or more |
| `--detrend {poly,spline}` | `poly` | how each voxel's time course is detrended |
| `--center {image,phantom}` | `image` | slice and ROI localization: the middle slice and the image center (the Glover convention), or the slice with the largest phantom cross-section and the phantom's detected center |
| `--roi-size ROI_SIZE` | `21` | side of the fixed summary and Weisskoff ROI, in voxels; a positive whole number |
| `--anonymize {pii,all,none}` | `pii` | what the published sidecar keeps: `pii` strips the patient and keeps the dates the series names are built from, `all` strips the dates too, `none` keeps everything |
| `--dcm2niix PATH` | the bundled one, else `dcm2niix` on `PATH` | the dcm2niix executable to run, by path or by a name looked up on `PATH` |
| `--open` | off | once the run finishes, open the report in a browser if exactly one series was published, or the output directory if several were, so the browser lists the series folders; nothing if none was |
| `--version` | — | print the installed version and exit |

The four analysis settings match `fmri-qa`'s, with the same defaults. Each is
recorded in the analysis file and shown in the report, and explained where it is
used:

- `--trim-sec`: {doc}`/user-guide/analyses/stability` describes the trim every
  analysis shares. {doc}`/user-guide/analyses/saturation` counts clipping on
  either side of it.
- `--detrend`: {doc}`/user-guide/analyses/stability`, with the polynomial and
  spline fits.
- `--center` and `--roi-size`: {doc}`/user-guide/analyses/localization`, under
  choosing the slice and placing the ROI.

`fmri-qa-run --help` lists them too, in the wording the panel shows under
each field.

## No arguments: the desktop panel

With neither directory, `fmri-qa-run` opens the {doc}`panel`. If it cannot,
because this Python has no `tkinter` or there is no display, it prints a message
and the usage line to stderr and exits `2`.

The panel takes no options. One directory alone, or any other option without both
(only `--help` and `--version` stand alone), is a usage error, not a partly
filled panel.

## Output and exit codes

stdout carries only the path of each published report, one per line, so the
command composes with other tools. The paths are printed after the whole run
finishes, in the order the series were found.

stderr carries everything else: a line as each stage begins, one line per refused
series, per failed series and why, and per warning, and a final summary line.

```text
Importing DICOM series
Analyzing 1 of 2: 20260909_143012_s002_QA_EPI_ISO
Rendering report 1 of 2: 20260909_143012_s002_QA_EPI_ISO
Publishing 1 of 2: 20260909_143012_s002_QA_EPI_ISO
...
refusing to replace existing results: OUTPUT_DIR/20260909_140101_s001_QA_EPI_ISO
# 2 of 3 series published to OUTPUT_DIR
```

A refused series is found while the series are listed, before any analysis. It
has no progress lines and is not counted in "1 of 2". The summary counts every
series found.

| Exit | When | On stderr |
| --- | --- | --- |
| 0 | every series found was published | progress and the summary |
| 1 | any series was refused or failed | `refusing to replace existing results: …` or `ERROR: SERIES: …` per series |
| 1 | the run could not start: a DICOM directory that does not exist, an output directory that is the DICOM directory or a file, or one that cannot be created or written to | `ERROR: …`, one line per problem |
| 1 | the import failed outright (no usable dcm2niix, or dcm2niix failed) or produced no series | `ERROR: …` |
| 2 | a usage error, or no panel to open | argparse's usage line and `fmri-qa-run: error: …`, or the panel message |

A warning is printed as `WARNING: SERIES: …` and does not change the exit
code.
