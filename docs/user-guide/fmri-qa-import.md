# Importing DICOM

`fmri-qa` analyzes NIfTI. `fmri-qa-import` converts a DICOM directory with
[dcm2niix](https://github.com/rordenlab/dcm2niix), using settings that keep the
QA checks valid, and names each series so a QA archive reads and sorts well.
{doc}`fmri-qa-run` runs it for you. Use it on its own when you analyze with
`fmri-qa` yourself.

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

## The dcm2niix settings it fixes

Four dcm2niix settings decide whether a conversion can be checked, so the import
always sets them:

| Flag | Why |
| --- | --- |
| `-l o` | keeps the stored integers exactly as the scanner sent them |
| `-b y` | writes the BIDS sidecar, which supplies the TR, the phase-encode direction and the acquisition details |
| `-w 2` | adds a suffix on a name conflict instead of overwriting |
| `-g i` | ignores `~/.dcm2nii.ini`, so the other three hold |

dcm2niix reads `~/.dcm2nii.ini` before its own defaults, so a file another tool
wrote months ago could change a QA conversion without showing on any command
line. `-g i` rules that out.

`-l o` matters most. Without it dcm2niix may rescale the values, which hides the
receiver's ceiling, and the {doc}`ADC-saturation check <analyses/saturation>`
then reports a clipped run as clean.

`--dcm2niix-arg` is for anything else dcm2niix can do. A value that starts with
`-` needs the `=` form: `--dcm2niix-arg=-i --dcm2niix-arg=y`. Overriding `-l`
prints a warning, because it disables the saturation check without any other
visible sign.

## Series names

The default names are `<date>_<time>_s<NNN>_<description>`, for example
`20260909_143012_s002_QA_EPI_ISO.nii.gz`, built from the series' sidecar. Time
comes before the series number because series numbers restart in each study, so
a directory holding several sessions still sorts in acquisition order.
dcm2niix's own template cannot build these names:

- `%t` is the **study** date and time, the same for every series in a session.
  There is no series-time token.
- `%s` is not zero-padded, so series 11 sorts before series 2.
- `%d` keeps the protocol's punctuation, so `QA EPI 32ch (rep)` needs quoting in
  a shell.

Some exports leave out a field, and a name is then built from the fields there
are. A series whose sidecar has none of them keeps dcm2niix's name. So does a
series whose name would collide with another's, such as the echoes of a
multi-echo series or the magnitude and phase of one acquisition, which share all
four fields. The command lists every file it left with dcm2niix's name.

`--names dcm2niix` keeps dcm2niix's naming throughout, from the `--filename`
template.

## A failed import leaves nothing behind

The import is all or nothing. It converts into a staging directory, and moves
the result into place only once every file has its name and none would replace
an existing file. A move that fails partway (a sync client holding a file open,
a disk error) is undone. With `--force`, the files being replaced are set aside
until the import succeeds, so a failure puts them back instead of leaving a new
scan beside an old sidecar.

## Why it converts instead of reading DICOM

Reading DICOM directly would mean handling each vendor's own layout: Siemens
mosaics and CSA headers, GE private tags, Philips' two rescale conventions,
enhanced multi-frame against classic, and grouping frames into volumes across
echoes, coils and dynamics. dcm2niix handles all of these and keeps up as
scanners change.

The analysis also needs something dcm2niix works out. The phase-encode direction
it reads, `PhaseEncodingDirection` in the sidecar, is not a DICOM tag. dcm2niix
derives it from vendor private data.
