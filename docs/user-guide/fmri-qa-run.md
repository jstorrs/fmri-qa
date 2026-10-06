# The command line

```console
$ fmri-qa-run DICOM_DIR OUTPUT_DIR [options]
```

`DICOM_DIR` is searched for DICOM files, down to five levels of
sub-directories, and every series found there is converted and, unless its
folder already exists, analyzed and published as its own folder under
`OUTPUT_DIR` — see {doc}`run-output` for what each folder holds. `OUTPUT_DIR` is
created if it does not exist, and must not be `DICOM_DIR` itself.

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

The four analysis settings are the ones `fmri-qa` takes, with the same
defaults, and each is recorded in the artifact and shown in the report. Each
is explained where it is used:

- `--trim-sec` — {doc}`/user-guide/analyses/stability`, which describes the
  trim every analysis shares; {doc}`/user-guide/analyses/saturation` counts
  clipping on either side of it.
- `--detrend` — {doc}`/user-guide/analyses/stability`, with the polynomial
  and spline fits.
- `--center` and `--roi-size` — {doc}`/user-guide/analyses/localization`,
  under choosing the slice and placing the ROI.

`fmri-qa-run --help` lists them too, in the wording the panel shows under
each field.

## No arguments: the desktop panel

With neither directory given, `fmri-qa-run` opens the {doc}`panel` instead.
When it cannot — this Python was built without `tkinter`, or there is no
graphical display to attach to — it prints a message saying so, and the usage
line, to stderr and exits `2`.

The panel takes no options of its own. Giving only one of the two directories,
or any other option without both (only `--help` and `--version` stand
alone), is a usage error rather than a partly filled panel.

## Output and exit codes

stdout carries only the path of each published report's HTML file, one per
line and nothing else, so the command composes with whatever reads it. The
paths are printed once the whole run has finished, in the order the series
were found.

stderr carries everything else: a line as each stage begins, then one line
for each series refused, each series that failed and why, and each warning a
series raised, and last a summary line.

```text
Importing DICOM series
Analyzing 1 of 2: 20260909_143012_s002_QA_EPI_ISO
Rendering report 1 of 2: 20260909_143012_s002_QA_EPI_ISO
Publishing 1 of 2: 20260909_143012_s002_QA_EPI_ISO
...
refusing to replace existing results: OUTPUT_DIR/20260909_140101_s001_QA_EPI_ISO
# 2 of 3 series published to OUTPUT_DIR
```

A refused series is found while the series are listed, before any analysis,
so it has no progress lines and is not counted in "1 of 2"; the summary
counts every series found.

| Exit | When | On stderr |
| --- | --- | --- |
| 0 | every series found was published | progress and the summary |
| 1 | any series was refused or failed | `refusing to replace existing results: …` or `ERROR: SERIES: …` per series |
| 1 | the run could not start: a DICOM directory that does not exist, an output directory that is the DICOM directory or a file, or one that cannot be created or written to | `ERROR: …`, one line per problem |
| 1 | the import failed outright (no usable dcm2niix, or dcm2niix failed) or produced no series | `ERROR: …` |
| 2 | a usage error, or no panel to open | argparse's usage line and `fmri-qa-run: error: …`, or the panel message |

A warning is printed as `WARNING: SERIES: …` and does not change the exit
code.
