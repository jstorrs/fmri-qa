# fmri-qa-cli

The command-line shell for [fmri-qa](../../README.md): `fmri-qa` analyzes
scans, `fmri-qa-hilo` separates thermal from instability noise on a flip-angle
pair, `fmri-qa-import` converts a DICOM directory into QA-ready NIfTI, and
`fmri-qa-report` renders a saved artifact into a one-file HTML report. The report
page itself is drawn by [`fmri-qa-report`](../fmri-qa-report), which installs as
a dependency.

```bash
pip install fmri-qa-cli
fmri-qa-import STUDY_DIR --out nifti/
fmri-qa nifti/*.nii.gz --artifact artifacts/
fmri-qa-report artifacts/scan.qa.nc --html report.html
```

With one scan, `--artifact` names the file to write, unless it is an existing
directory. With several scans it is a directory, and each scan gets
`<scan stem>.qa.nc` inside it.

It owns argument parsing, exit codes and printing, and nothing else.
[`fmri-qa-core`](../fmri-qa-core) does the calculation and
[`fmri-qa-io`](../fmri-qa-io) touches the files, so both stay libraries with no
entry points. `python -m fmriqa_cli` runs `fmri-qa`.

Startup is cheap. `--help` and `--version` do not import scipy or scikit-image.

It depends on `fmri-qa-core` and `fmri-qa-io` and on nothing that draws.
Rendering an artifact into a report is
[`fmri-qa-report`](../fmri-qa-report)'s job. The one-step pipeline from DICOM to
report is [`fmri-qa-launcher`](../fmri-qa-launcher)'s.

The workspace's [user guide](../../docs/user-guide/index.md) documents the
analyses these commands run. Build it from the workspace root with
`make sync-docs && make docs`. It lands under `build/site`.
