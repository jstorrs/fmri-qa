# Rendering a report

`fmri-qa-report` renders an {doc}`analysis file </user-guide/analysis-file>` as
a self-contained HTML report ({doc}`report-page`). `fmri-qa-run` does this for
every series it publishes, so the command is needed only for files saved with
`fmri-qa --analysis-file`.

```console
$ fmri-qa-report ANALYSIS_FILE --html FILE
```

`ANALYSIS_FILE` is the `.qa.nc` file written by `fmri-qa --analysis-file`. Files
from earlier versions remain usable: the loader reads the former `.qa.npz`
format and upgrades older schemas, with a warning. `FILE` is the HTML page to be
written, and `--html` is required.

```console
$ fmri-qa scan.nii.gz --analysis-file qa.nc
$ fmri-qa-report qa.nc --html report.html
```

On success the command prints one line to stdout:

```text
# wrote report.html (1 scan)
```

The page is titled with the scan name recorded in the analysis file, or with the
name of the analysis file itself when no scan name was recorded.

## One analysis file per page

`--html` renders a single analysis file. `ANALYSIS_FILE` may be a wildcard
pattern, which the command expands itself because PowerShell and cmd pass
`*.qa.nc` through unexpanded. Thus
`fmri-qa-report results\*-0924.qa.nc --html report.html` behaves on Windows as
it does in a POSIX shell. A pattern or a list of names that matches more than
one analysis file is a usage error:

```text
fmri-qa-report: error: --html renders one analysis file into one page
```

A pattern that matches nothing is retained as a literal name, and the command
then fails because the analysis file cannot be read (see below).

## Errors and exit status

| Exit | When | Message on stderr |
| --- | --- | --- |
| 0 | the page was written | — (`# wrote FILE (1 scan)` on stdout) |
| 2 | a usage error: no `--html`, no analysis file, or more than one analysis file | argparse's usage line and `fmri-qa-report: error: …` |
| 1 | `--html` names the analysis file itself | `ERROR: --html FILE would overwrite the input ANALYSIS_FILE` |
| 1 | the analysis file cannot be read, is not an analysis file, or is from a schema this build cannot reach | `ERROR: cannot read analysis file …` |
| 1 | rendering or writing the page failed | `ERROR: could not write HTML FILE: …` |

The overwrite check is made before anything is read. It compares the identity
of the files and not their names, so it also detects the same file reached
through a relative path or a link.

## How the page is written

The page is written atomically, so a reader never observes a partial page, and a
failed render leaves an existing `FILE` unchanged. The page receives the
permissions of any newly created file (0644 under the usual umask of 022).
Missing parent directories of `FILE` are created.
