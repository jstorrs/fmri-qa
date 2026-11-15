# Importing DICOM

`fmri-qa` analyzes NIfTI. `fmri-qa-import` converts a DICOM directory with
[dcm2niix](https://github.com/rordenlab/dcm2niix) (Li et al., 2016), under
settings that keep the QA checks valid, and it names each series so that a QA
archive is legible and sorts chronologically. {doc}`fmri-qa-run` performs the
import automatically. The command is used on its own when the analysis is run
separately with `fmri-qa`.

```console
$ fmri-qa-import /path/to/dicom/dir -o session_nifti
```

```text
# dcm2niix v1.0.20260724 (.../site-packages/dcm2niix/dcm2niix)
series  acquired             file
     2  2026-09-09 14:30:12  20260909_143012_s002_QA_EPI_ISO.nii.gz
    11  2026-09-09 14:55:33  20260909_145533_s011_QA_EPI_32ch_rep.nii.gz
# 2 series -> session_nifti
# analyze with:  fmri-qa session_nifti/*.nii.gz
```

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `-o`, `--out` | `./<source name>_nifti` | where to write the NIfTI |
| `--names` | `qa` | `qa` (date, time, series, description) or `dcm2niix` |
| `--filename` | `%t_%s_%d` | dcm2niix `-f` template: the name under `--names dcm2niix`, and the fallback under `qa` |
| `--anonymize` | `pii` | `pii` strips the patient and keeps the dates, `all` strips the dates too, `none` keeps everything |
| `--no-compress` | — | write `.nii` instead of `.nii.gz` |
| `--depth` | `5` | levels of sub-directories of the source to search |
| `--dcm2niix` | the included copy, else `PATH` | which dcm2niix to run; name your own build, since the included copy is used first |
| `--dcm2niix-arg` | — | an extra dcm2niix argument, repeatable, passed last so it wins |
| `--force` | — | replace files already in the output directory |
| `--log` | — | print everything dcm2niix said |
| `--version` | — | print the version and exit |

## Fixed dcm2niix settings

Four dcm2niix settings determine whether a conversion can be checked, so the
import always sets them:

| Flag | Why |
| --- | --- |
| `-l o` | keeps the stored integers exactly as the scanner sent them |
| `-b y` | writes the BIDS sidecar, which supplies the TR, the phase-encode direction and the acquisition details |
| `-w 2` | adds a suffix on a name conflict instead of overwriting |
| `-g i` | ignores `~/.dcm2nii.ini`, so the other three hold |

dcm2niix reads `~/.dcm2nii.ini` before applying its own defaults. A file written
by another tool months earlier could therefore alter a QA conversion without
appearing on any command line, and `-g i` excludes that possibility.

Of the four, `-l o` is the most important. Without it dcm2niix may rescale the
values, which conceals the ceiling of the receiver, and the
{doc}`ADC-saturation check <analyses/saturation>` then reports a clipped run as
clean.

`--dcm2niix-arg` passes any other dcm2niix option. A value that begins with `-`
requires the `=` form: `--dcm2niix-arg=-i --dcm2niix-arg=y`. Overriding `-l`
produces a warning, because doing so disables the saturation check with no other
visible indication.

## Series names

The default names have the form `<date>_<time>_s<NNN>_<description>`, for
example `20260909_143012_s002_QA_EPI_ISO.nii.gz`, and are constructed from the
sidecar of the series. The time precedes the series number because series
numbers restart in each study, so that a directory holding several sessions
still sorts in order of acquisition. The filename template of dcm2niix cannot
produce these names, for three reasons:

- `%t` is the date and time of the **study**, which is the same for every
  series in a session. No token gives the time of the series.
- `%s` is not zero-padded, so series 11 sorts before series 2.
- `%d` retains the punctuation of the protocol name, so `QA EPI 32ch (rep)`
  must be quoted in a shell.

Some exports omit a field, and the name is then constructed from the fields
that are present. A series whose sidecar contains none of them keeps the name
dcm2niix gave it. So does a series whose name would collide with that of
another, such as the echoes of a multi-echo series or the magnitude and phase
of one acquisition, which share all four fields. The command lists every file
that retains its dcm2niix name.

`--names dcm2niix` retains the dcm2niix naming throughout, as given by the
`--filename` template.

## Atomicity of the import

An import either completes or leaves nothing behind. The conversion is written
to a staging directory, and the result is moved into place only once every file
has been named and none would replace an existing file. A move that fails
partway, for example because a synchronization client holds a file open or the
disk reports an error, is reversed. Under `--force`, the files being replaced
are set aside until the import succeeds, so that a failure restores them and
never leaves a new scan beside an old sidecar.

## Rationale for conversion

Reading DICOM directly would require handling the layout of each vendor:
Siemens mosaics and CSA headers, GE private tags, the two rescale conventions of
Philips, enhanced multi-frame as opposed to classic objects, and the grouping of
frames into volumes across echoes, coils and dynamics. dcm2niix handles all of
these and is maintained as scanners change.

The analysis also depends on a quantity that dcm2niix derives. The phase-encode
direction it reports, `PhaseEncodingDirection` in the sidecar, is not a DICOM
tag. dcm2niix infers it from vendor-private data.

## Reference

- Li X, Morgan PS, Ashburner J, Smith J, Rorden C. The first step for
  neuroimaging data analysis: DICOM to NIfTI conversion. *J Neurosci Methods*
  2016;264:47–56.
  [doi:10.1016/j.jneumeth.2016.03.001](https://doi.org/10.1016/j.jneumeth.2016.03.001)
