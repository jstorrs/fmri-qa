# Rendering a report

```console
$ fmri-qa-report ARTIFACT --html FILE
```

`ARTIFACT` is the `.qa.nc` file `fmri-qa --artifact` writes — the
{doc}`analysis artifact </user-guide/artifact>`. An artifact from an earlier
build still renders: the loader also reads the retired `.qa.npz` container,
and migrates a file written under an older schema forward, with a warning.
`FILE` is the HTML page to write; `--html` is required.

```console
$ fmri-qa scan.nii.gz --artifact qa.nc
$ fmri-qa-report qa.nc --html report.html
```

On success it prints one line to stdout:

```text
# wrote report.html (1 scan)
```

The page is titled with the scan name recorded in the artifact, or the
artifact's file name when none was recorded.

## One artifact, one page

`--html` renders exactly one artifact. `ARTIFACT` may be a wildcard pattern,
which the command expands itself — PowerShell and cmd pass `*.qa.nc` through
unexpanded — so `fmri-qa-report artifacts\*-0924.qa.nc --html report.html` works on
Windows as it does in a POSIX shell. A pattern (or a list of names) that comes
to more than one artifact is a usage error:

```text
fmri-qa-report: error: --html renders one artifact to one file
```

A pattern that matches nothing is kept as a literal name, and so fails as an
unreadable artifact (below).

## Errors and exit codes

| Exit | When | Message on stderr |
| --- | --- | --- |
| 0 | the page was written | — (`# wrote FILE (1 scan)` on stdout) |
| 2 | a usage error: no `--html`, no artifact, or more than one artifact | argparse's usage line and `fmri-qa-report: error: …` |
| 1 | `--html` names the artifact itself | `ERROR: --html FILE would overwrite the input ARTIFACT` |
| 1 | the artifact cannot be read, is not an artifact, or is from a schema this build cannot reach | `ERROR: cannot read artifact …` |
| 1 | rendering or writing the page failed | `ERROR: could not write HTML FILE: …` |

The overwrite check runs before anything is read, and compares files by
identity, so it catches the same file reached through a relative path or a
link as well as the same spelling.

## How the page is written

The page is rendered completely in memory before anything is written,
then written to a temporary file beside `FILE` and renamed onto it. A reader
never sees a partial page, and a render or write that fails leaves an existing
`FILE` exactly as it was. The page is created with ordinary permissions — the
process umask applies, not the owner-only mode a temporary file usually gets —
so it gets the permissions any new file the process creates would (0644 under
the usual umask of 022). Missing parent
directories of `FILE` are created.
