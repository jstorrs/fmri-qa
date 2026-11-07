# Rendering a report

`fmri-qa-report` renders an {doc}`analysis file </user-guide/analysis-file>` as a
self-contained HTML report ({doc}`report-page`). `fmri-qa-run` does this for
every series it publishes, so you need it only for files saved with
`fmri-qa --analysis-file`.

```console
$ fmri-qa-report ANALYSIS_FILE --html FILE
```

`ANALYSIS_FILE` is the `.qa.nc` file written by `fmri-qa --analysis-file`, the
{doc}`analysis file </user-guide/analysis-file>`. Older analysis files still work: the
loader reads the old `.qa.npz` format and upgrades older schemas, with a warning.
`FILE` is the HTML page to write. `--html` is required.

```console
$ fmri-qa scan.nii.gz --analysis-file qa.nc
$ fmri-qa-report qa.nc --html report.html
```

On success it prints one line to stdout:

```text
# wrote report.html (1 scan)
```

The page is titled with the scan name recorded in the analysis file, or the
analysis file's file name when none was recorded.

## One analysis file, one page

`--html` renders one analysis file. `ANALYSIS_FILE` may be a wildcard pattern. The command
expands it itself, since PowerShell and cmd pass `*.qa.nc` through unexpanded, so
`fmri-qa-report results\*-0924.qa.nc --html report.html` works on Windows as in
a POSIX shell. A pattern or list of names that matches more than one analysis file is
a usage error:

```text
fmri-qa-report: error: --html renders one analysis file into one page
```

A pattern that matches nothing is kept as a literal name, and so fails as an
unreadable analysis file (below).

## Errors and exit codes

| Exit | When | Message on stderr |
| --- | --- | --- |
| 0 | the page was written | — (`# wrote FILE (1 scan)` on stdout) |
| 2 | a usage error: no `--html`, no analysis file, or more than one analysis file | argparse's usage line and `fmri-qa-report: error: …` |
| 1 | `--html` names the analysis file itself | `ERROR: --html FILE would overwrite the input ANALYSIS_FILE` |
| 1 | the analysis file cannot be read, is not an analysis file, or is from a schema this build cannot reach | `ERROR: cannot read analysis file …` |
| 1 | rendering or writing the page failed | `ERROR: could not write HTML FILE: …` |

The overwrite check runs before anything is read. It compares file identity, so it
also catches the same file reached through a relative path or a link.

## How the page is written

The page is written in one step, so a reader never sees half of one, and a
failed render leaves an existing `FILE` as it was. It gets the permissions of
any new file (0644 under the usual umask of 022). Missing parent directories of
`FILE` are created.
