# Installing

You do not need to install anything to try fmri-qa. The
{doc}`browser version <browser>` runs from a web page or a saved HTML file.
Install it to get the desktop panel and the commands, to run it from scripts,
or to keep the analysis files for trending.

## With uv

fmri-qa is not on PyPI yet. Install it from GitHub with
[uv](https://docs.astral.sh/uv/getting-started/installation/), which also
fetches Python 3.13 if you do not have it:

```console
$ uv tool install "fmri-qa-launcher @ git+https://github.com/jstorrs/fmri-qa#subdirectory=packages/fmri-qa-launcher" --with-executables-from fmri-qa-cli
```

This installs six commands:

| Command | What it does |
| --- | --- |
| `fmri-qa-run` | DICOM in, one report folder per series out ({doc}`fmri-qa-run`) |
| `fmri-qa-panel` | the same run from a desktop window ({doc}`panel`) |
| `fmri-qa-import` | DICOM to NIfTI, with QA-safe settings and sortable names ({doc}`fmri-qa-import`) |
| `fmri-qa` | analyze NIfTI scans: a table, JSON, or analysis files ({doc}`fmri-qa`) |
| `fmri-qa-hilo` | split thermal from instability noise with a flip-angle pair ({doc}`fmri-qa`) |
| `fmri-qa-report` | render an analysis file as an HTML report ({doc}`fmri-qa-report`) |

Run any of them with `--version` to check the install. To update, run
`uv tool upgrade fmri-qa-launcher`.

## dcm2niix

DICOM conversion uses [dcm2niix](https://github.com/rordenlab/dcm2niix). The
install includes a copy, so there is nothing else to set up. To use another
build (a newer one, or one with vendor patches), pass its path with
`--dcm2niix`. You have to name it: the included copy is used before any
dcm2niix on `PATH`.

## The desktop panel

The panel needs `tkinter` and a graphical display. The Python that uv installs
includes `tkinter`. A system Python on Linux may not: install your
distribution's `python3-tk` package, or let uv manage Python.

## Without Python

A single executable with Python, fmri-qa and dcm2niix inside can be built for
machines where nothing can be installed. See {doc}`developers`.
