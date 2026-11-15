# Installation

No installation is needed to try fmri-qa: the {doc}`browser version <browser>`
runs from a web page or from a saved HTML file. Installation provides the
desktop panel and the commands, allows the analysis to be scripted, and makes it
possible to retain the analysis files for trending.

## Installation with uv

fmri-qa is not yet published on PyPI. It is installed from GitHub with
[uv](https://docs.astral.sh/uv/getting-started/installation/), which also
obtains Python 3.13 when it is not already present:

```console
$ uv tool install "fmri-qa-launcher @ git+https://github.com/jstorrs/fmri-qa#subdirectory=packages/fmri-qa-launcher" --with-executables-from fmri-qa-cli
```

Six commands are installed:

| Command | Function |
| --- | --- |
| `fmri-qa-run` | converts and analyzes a DICOM folder into one report folder per series ({doc}`fmri-qa-run`) |
| `fmri-qa-panel` | performs the same run from a desktop window ({doc}`panel`) |
| `fmri-qa-import` | converts DICOM to NIfTI, with settings suited to QA and sortable names ({doc}`fmri-qa-import`) |
| `fmri-qa` | analyzes NIfTI scans into a table, JSON, or analysis files ({doc}`fmri-qa`) |
| `fmri-qa-hilo` | separates thermal from instability noise with a flip-angle pair ({doc}`fmri-qa`) |
| `fmri-qa-report` | renders an analysis file as an HTML report ({doc}`fmri-qa-report`) |

Running any of them with `--version` verifies the installation. To update, run
`uv tool upgrade fmri-qa-launcher`.

## dcm2niix

DICOM conversion relies on [dcm2niix](https://github.com/rordenlab/dcm2niix).
The installation includes a copy, so no further setup is required. Another
build, such as a newer release or one carrying vendor patches, is selected by
passing its path with `--dcm2niix`. The path must be given explicitly, because
the included copy takes precedence over any dcm2niix on `PATH`.

## The desktop panel

The panel requires `tkinter` and a graphical display. The Python that uv
installs includes `tkinter`. A system Python on Linux may not, in which case
either the distribution's `python3-tk` package should be installed or Python
should be left to uv.

## Use without Python

For computers on which nothing can be installed, a single executable containing
Python, fmri-qa and dcm2niix can be built. See {doc}`developers`.
