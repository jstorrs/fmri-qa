# Output of a run

## One folder per series

Each published series receives a folder of its own in the output directory. The
folder is named as `fmri-qa-import` names the series, usually
`<date>_<time>_s<NNN>_<description>` from its sidecar, and contains:

```text
OUTPUT_DIR/
  <series>/
    <series>.nii.gz   converted scan
    <series>.json     acquisition sidecar
    <series>.qa.nc    analysis file
    <series>.html     report
```

- **`<series>.nii.gz`** is the scan as dcm2niix converted it, with its stored
  integers preserved.
- **`<series>.json`** is the BIDS sidecar that dcm2niix wrote beside it,
  anonymized as `--anonymize` specifies. It is present whenever dcm2niix wrote
  one. Any other file that the import placed under the name of the series
  accompanies the scan in the same way.
- **`<series>.qa.nc`** is the {doc}`analysis file </user-guide/analysis-file>`:
  every number, curve and image that the analysis produced, and the settings it
  used. The source it records is the path of the scan in this folder, not the
  temporary path from which it was analyzed.
- **`<series>.html`** is the report rendered from that analysis file, titled
  with the name of the series. It is a single self-contained file that opens
  directly in a browser, and it is described in
  {doc}`the report page </user-guide/report-page>`.

## Existing results are never replaced

A series whose folder already exists in the output directory is refused. The
existing folder is left unchanged, the series is reported as refused, and no
analysis or rendering is performed for it. Running the same DICOM directory into
the same output directory a second time therefore publishes only the new series.
The others are refused, and `fmri-qa-run` exits with status `1`. To repeat a
series, its folder must first be deleted or moved.

The check is repeated when a series is published. If another run has published
a folder of the same name in the meantime, the series fails with a message to
that effect and the folder is not replaced.

## Failed series

A failure in one series (an unreadable scan, a sidecar that is not valid JSON,
too few volumes to analyze, or a report that cannot be written) does not stop
the run. The series is reported as failed, with the reason. None of its files
reach the output directory, and every other series is still attempted. The run
is counted as incomplete, and `fmri-qa-run` exits with status `1`.

A failure that occurs before any series is reached is treated differently. If
the output directory cannot be created or written to, or if the import fails or
finds nothing, there is no run and no series folder is written.

## Staging and publication

No work is done in the output directory itself. A run converts, analyzes and
renders in a staging directory, `fmri-qa-run.<random>`, in the system's
temporary directory (the location given by `TMPDIR`, or by `TEMP` on Windows).
The staging directory must hold the whole converted session together with the
analysis file and report of the series in progress. The files of each series
leave it once the series is published. If the temporary directory is small or
held in memory, `TMPDIR` should point to a larger location. The staging
directory is removed when the run ends, whether or not the run succeeded. One
that is left behind contains nothing finished and can be deleted. Cleanup
warnings name any leftovers on stderr or in the panel log, and they change
neither the result nor the exit status.

A finished series is copied into a directory beside its final location,
`.<series>.<token>.partial`, whose leading dot hides it on macOS and Linux. The
directory is renamed to `<series>` once every file has been copied. A reader of
the output directory, or a synchronization client watching it, therefore sees
only complete series folders. If the copy or the rename fails, the `.partial`
directory is removed and the series fails. A run that is killed before the
rename can leave such a directory behind without notice, since no code can run
after a process is killed outright. If the cleanup is refused, as can happen
when a synchronization client holds a file open, a warning names the path that
remains. A leftover directory is never mistaken for a series and never blocks
one, and no later run removes it. It can safely be deleted by hand.

Before starting, a run also verifies that the output directory is writable by
creating and removing an empty directory, `.fmri-qa-probe.<token>`, which is
likewise hidden on macOS and Linux. If its removal is refused, the same cleanup
warning names the probe, and the run can still proceed.
