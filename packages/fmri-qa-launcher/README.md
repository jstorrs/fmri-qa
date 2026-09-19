# fmri-qa-launcher

The application shell for [fmri-qa](../../README.md): a one-step "DICOM
directory in, one report directory per series out" pipeline built on top of
[`fmri-qa-core`](../fmri-qa-core) (conversion and analysis) and
[`fmri-qa-report`](../fmri-qa-report) (rendering). It adds no third-party
dependency of its own.

A command line and a desktop panel are forthcoming; this package is currently
just the exception hierarchy and version string the rest will be built on.
