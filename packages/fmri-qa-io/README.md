# fmri-qa-io

The file formats and filesystem IO for [fmri-qa](../../README.md): reading
scans, the `.qa.nc` artifact file, and DICOM import.

[`fmri-qa-core`](../fmri-qa-core) stays pure, with no filesystem or
native-library dependency, so it can run in the browser under Pyodide. Anything
that touches a file or an external program lives here instead.

The package root is lazy. Importing a Pyodide-safe submodule never imports the
filesystem-bound ones.
