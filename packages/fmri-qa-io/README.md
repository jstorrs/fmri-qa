# fmri-qa-io

The file formats and filesystem IO for [fmri-qa](../../README.md): reading
scans, the `.qa.nc` artifact file, and DICOM import.

[`fmri-qa-core`](../fmri-qa-core) stays pure, with no filesystem or
native-library dependency, so it can run in the browser under Pyodide. Anything
that touches a file or an external program lives here instead.

```bash
pip install fmri-qa-io
```

```python
import fmriqa as q
import fmriqa_io

scan = fmriqa_io.load_scan("scan.nii.gz")  # NIfTI + BIDS sidecar beside it
artifact = q.analyze(scan, name="scan.nii.gz")
fmriqa_io.save_artifact(artifact, "qa.nc")  # netCDF-4
same = fmriqa_io.load_artifact("qa.nc")
```

## What it exports

- `load_scan(path)`: read a 4-D NIfTI (`.nii` or `.nii.gz`) and the `.json`
  sidecar with the same stem, and return a `fmriqa.QAScan`.
- `scan_from_bytes(nifti, sidecar)`: the same decode from bytes. It is what a
  browser page calls with the bytes of a dropped file. `fmriqa_io.decode` imports
  only the standard library, numpy, nibabel and core, so it works under Pyodide.
- `save_artifact(artifact, path)` and `load_artifact(path)`: the artifact as one
  netCDF-4 file, written through `netCDF4`. The artifact's schema (compose,
  decompose, migrate, validation) is core's. This package is only the container.
  Files an earlier build wrote as `.qa.npz` still load, and nothing writes one.
- `import_dicom(source, destination, ...)`: run dcm2niix over a DICOM directory
  and file each series under `destination`, named from its metadata. It raises
  `ConversionError` when conversion fails.

Also here: `fmriqa_io.rename` (atomic file writes and directory moves, retried where Windows refuses a rename),
`fmriqa_io.paths` (the NIfTI stem and sidecar rules), `fmriqa_io.path_arguments`
(wildcard expansion for command lines), and `fmriqa_io.testing.write_phantom`
(a synthetic phantom NIfTI and sidecar for tests and docs).

## Dependencies

numpy, nibabel and `fmri-qa-core`. `netCDF4` and `dcm2niix` are native, so both
are declared with `sys_platform != 'emscripten'` and a browser install skips
them. There the artifact container and DICOM import are unavailable, and
`scan_from_bytes` still works.

The package root is lazy. Importing a Pyodide-safe submodule never imports the
filesystem-bound ones.

The workspace's [user guide](../../docs/user-guide/index.md) documents the
artifact file in [`artifact.md`](../../docs/user-guide/artifact.md). Build the
site from the workspace root with `make sync-docs && make docs`.
