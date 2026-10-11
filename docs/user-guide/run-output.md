# What a run writes

## One folder per series

Each published series gets its own folder in the output directory. The folder is
named for the series the way `fmri-qa-import` names it, usually
`<date>_<time>_s<NNN>_<description>` from its sidecar, and holds:

```text
OUTPUT_DIR/
  <series>/
    <series>.nii.gz   converted scan
    <series>.json     acquisition sidecar
    <series>.qa.nc    analysis artifact
    <series>.html     report
```

- **`<series>.nii.gz`** is the scan as dcm2niix converted it, with its stored
  integers kept.
- **`<series>.json`** is the BIDS sidecar dcm2niix wrote beside it, anonymized as
  `--anonymize` says. It is there when dcm2niix wrote one. Any other file the
  import filed under the series' name travels with the scan the same way.
- **`<series>.qa.nc`** is the {doc}`analysis artifact </user-guide/artifact>`:
  every number, curve and image the analysis produced, and the settings it used.
  Its recorded source is the scan's path in this folder, not the temporary one it
  was analyzed from.
- **`<series>.html`** is the report rendered from that artifact, titled with the
  series name. It is a single self-contained file, described in
  {doc}`the report page </user-guide/report-page>`. It opens by double-click.

## Existing results are refused, not replaced

A series whose folder already exists in the output directory is refused. The
existing folder is left as it is, and the series is reported as refused and costs
no analysis or rendering. Running the same DICOM directory into the same output
directory again publishes only the new series. The rest are refused, so
`fmri-qa-run` exits `1`. To redo a series, delete or move its folder first.

The check is made again when a series is published. If another run has published
a folder of the same name in the meantime, the series fails with a message saying
so, instead of replacing it.

## A failed series is skipped

A failure in one series (an unreadable scan, a sidecar that is not valid JSON,
too few volumes to analyze, a report that cannot be written) does not stop the
run. That series is reported as failed, with the reason. Nothing of it reaches
the output directory, and every other series is still attempted. The run counts
as incomplete, and `fmri-qa-run` exits `1`.

A failure before any series is reached is different. If the output directory
cannot be created or written to, or the import fails or finds nothing, there is
no run, and no series folder is written.

## How a series arrives

Nothing is worked on in the output directory. A run converts, analyzes and
renders in a staging directory, `fmri-qa-run.<random>`, in the system's
temporary directory (where `TMPDIR`, or `TEMP` on Windows, points). It needs room for the whole converted session plus the artifact and
report of the series in progress. Each series' files leave it once published. If
the temporary directory is small or in memory, point `TMPDIR` somewhere larger.
The staging directory is removed when the run ends, whether or not it succeeded.
One left behind holds nothing finished and can be deleted. Cleanup warnings name
leftovers on stderr or in the panel log, without changing the result or exit
code.

A finished series is copied into a dot-named directory beside its final place,
`.<series>.<token>.partial` (hidden on macOS and Linux), and renamed to
`<series>` once every file is copied. A reader of the output directory, or a sync
client watching it, therefore only sees complete series folders. If the copy or
rename fails, the `.partial` directory is removed and the series fails. A run
killed before the rename can leave one behind silently, since no code can run
after an outright process kill. If cleanup is refused (a sync client holding a
file open can do that), a warning names the leftover path. It is never mistaken
for a series, never blocks one, and no later run removes it. It is safe to delete by hand.

Before starting, a run also checks that the output directory can be written to by
making and removing an empty dot-named directory (hidden on macOS and Linux),
`.fmri-qa-probe.<token>`. If removal is refused, the same cleanup warning names
this probe. The run can still proceed.
