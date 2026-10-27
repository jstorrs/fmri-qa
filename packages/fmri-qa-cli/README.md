# fmri-qa-cli

The command-line shell for [fmri-qa](../../README.md): `fmri-qa` analyzes
scans, `fmri-qa-hilo` separates thermal from instability noise on a flip-angle
pair, and `fmri-qa-import` converts a DICOM directory into QA-ready NIfTI.

It owns argument parsing, exit codes and printing, and nothing else.
[`fmri-qa-core`](../fmri-qa-core) does the calculation and
[`fmri-qa-io`](../fmri-qa-io) touches the files, so both stay libraries with no
entry points. `python -m fmriqa_cli` runs `fmri-qa`.

Startup is cheap. `--help` and `--version` do not import scipy or scikit-image.
