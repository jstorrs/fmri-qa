# Analyzing NIfTI scans

`fmri-qa` analyzes phantom series that are already in NIfTI format, such as
those written by {doc}`fmri-qa-import`. It prints one table row per scan, and it
can also write the results as JSON or save the
{doc}`analysis file <analysis-file>` of each scan for a report.
{doc}`fmri-qa-run` performs the import, the analysis and the report in a single
step. `fmri-qa` is the appropriate command when only the numerical results are
required.

```console
$ fmri-qa [options] scan.nii.gz [more.nii.gz ...]
```

Each scan is read together with its BIDS sidecar (`scan.json`) when one exists.
The sidecar supplies the TR, the phase-encode direction, and the acquisition
details shown in the report. Without it, the TR is taken from the NIfTI header,
and the phase-encode axis from the header or, failing that, from the position of
the ghost.

## The table

```text
# detrend=poly  trim_sec=5.0  center=image  roi_size=21
scan                                      PE      loc       SNR      SFNR      RDC   drift%   ghost%     ghT%      RO%    ACRg%   outl%   tcOut  spcOut   clip  clipPre    motn    scl%    shr%    com   fwPE   fwRO
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FBIRN_QA_fMRI_flip77_13.nii.gz           col       ok     467.3     452.0   10.953    0.303    4.092    6.643    4.059    0.033   0.211    2.48    5.19      0        0   0.017   0.198   0.015  0.007   2.19   2.72
ABCD_QA_fMRI_16.nii.gz                   col       ok      76.7      75.3   13.355    0.682    5.074   10.084    3.192    1.882   0.077    3.30    5.86      0       68   0.025   0.268   0.034  0.094   1.53   2.17
```

| Column | Meaning | Defined in |
| --- | --- | --- |
| `PE` | the phase-encode axis, `row` or `col` | {doc}`analyses/ghosting` |
| `loc` | `ok`, or which of the phantom mask and the summary ROI failed. When either failed, the mask-based columns were measured on background | {doc}`analyses/localization` |
| `SNR`, `SFNR`, `RDC` | static SNR, signal-to-fluctuation-noise ratio, Weisskoff radius of decorrelation | {doc}`analyses/stability` |
| `drift%` | drift as a percentage of the mean signal | {doc}`analyses/stability` |
| `ghost%`, `ghT%` | FBIRN percent N/2 ghost, and the same over the brightest 10% of ghost voxels, so a localized ghost the mean dilutes still shows | {doc}`analyses/ghosting` |
| `RO%`, `ACRg%` | the readout-direction baseline, and the ACR/AAPM ghosting ratio | {doc}`analyses/ghosting` |
| `outl%` | the worst single volume's outlier-voxel percentage | {doc}`analyses/outliers` |
| `tcOut`, `spcOut` | spike scores of the ROI residual, in time (a transient volume) and in frequency (a periodic artifact). A clean phantom scores a few | {doc}`analyses/outliers` |
| `clip`, `clipPre` | clipped samples in the analyzed volumes (a trailing `!` flags any) and in the dropped warm-up volumes only. `?` means the data did not arrive as the scanner's integers, so clipping could not be tested | {doc}`analyses/saturation` |
| `motn`, `scl%`, `shr%` | peak in-plane translation, and the scale and shear strain gradient heating produces | {doc}`analyses/motion` |
| `com` | peak shift of the whole-slice center of mass, a mask-free check beside `motn` | {doc}`analyses/motion` |
| `fwPE`, `fwRO` | noise smoothness (FWHM) along phase-encode and readout. `?` when the phase-encode axis is unknown | {doc}`analyses/smoothness` |

Distances are in millimeters when the voxel size is known and in voxels
otherwise. Several scans share one table. A file that fails is reported on
stderr, and the remaining files are still analyzed. The command exits with a
nonzero status if any file failed.

Wildcards behave identically on every platform. Where the shell does not expand
them (PowerShell, cmd), `fmri-qa` does, so the examples on this page can be used
verbatim.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--trim-sec` | `5` | seconds of initial, not yet steady-state, volumes to drop |
| `--pe-axis` | from the scan | override the in-plane phase-encode axis (`0` or `1`) |
| `--detrend` | `poly` | detrending method, `poly` or `spline` |
| `--center` | `image` | localization: the middle slice and the image center (the Glover convention), or `phantom`: the slice with the largest phantom cross-section and the phantom's detected center |
| `--roi-size` | `21` | side of the summary and Weisskoff ROI, in voxels |
| `--json` | — | write the numbers as JSON on stdout instead of the table |
| `--analysis-file PATH` | — | save each scan's analysis file, for a report or for trending |
| `--version` | — | print the version and exit |

{doc}`fmri-qa-run` indicates where each analysis setting is used.

## Saving the analysis file

`--analysis-file PATH` saves everything the analysis produced (the settings,
the origin of the data, every measurement and curve, and the summary images) as
a single compressed netCDF-4 file. {doc}`fmri-qa-report` renders that file as a
report, and MATLAB, R and Python read it directly ({doc}`analysis-file`).

For a single scan, `PATH` is the file to be written. For several scans, or when
`PATH` is an existing directory, one `<scan>.qa.nc` is written into it per scan:

```console
$ fmri-qa data/*_fMRI_*.nii.gz --analysis-file results/
```

An existing file is replaced atomically, so a reader never observes a partial
file. An output that would replace one of the inputs of the run (a scan or its
sidecar) is refused before anything is read.

## JSON for trending

Under `--json`, standard output carries a single JSON document in place of the
table, suitable for a trend database or a spreadsheet. The banner, the errors
and the save notices are written to stderr, so the output can be piped directly:

```console
$ fmri-qa --json data/*_fMRI_*.nii.gz > qa.json
```

The document has the form
`{"schema_version": 6, "config": {...}, "requested": [...], "scans": [...], "errors": [...]}`:

- `scans` holds one record per scan, with the columns of the table as raw
  numbers. A value that could not be computed (for example, a ghost ratio with
  no identifiable ghost region) is `null`, never `NaN`.
- Each record begins with `phantom_fraction`, `phantom_mask_ok` and
  `roi_inside_phantom`, the checks that underlie the `loc` column. When either
  check fails, every mask-based number in the record was measured on background.
- Each record also carries the fields a trend database needs to key and date
  it: `source` and `datetime`, and `tr`, `n_frames` and `n_trimmed` for the
  series it describes. `outlier_worst_frame` is counted from the first analyzed
  volume, so adding `n_trimmed` gives the acquired volume number.
- `requested` lists every path given, and `errors` holds one entry (`scan`,
  `source`, `error`) per input that failed, so that a failed scan can be
  distinguished from one that was never requested.

## Thermal and instability noise: `fmri-qa-hilo`

`fmri-qa-hilo` takes two scans that differ only in flip angle and separates
thermal (additive) from instability (multiplicative) noise by the method of
Greve et al. (2011), which is described in {doc}`analyses/hilo`.

```console
$ fmri-qa-hilo HIGH_flip.nii.gz LOW_flip.nii.gz
```

The high-flip scan is given first. `--trim-sec` and `--detrend` behave as they
do for `fmri-qa`, and `--erode` (default `5`) sets the number of voxel layers
removed from the phantom to form its core mask. The command prints its result
and writes no analysis file.
