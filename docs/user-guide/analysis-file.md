# The analysis file

The analysis file, a `.qa.nc`, is the whole result of analyzing one series. The
analysis pages and the Python API call it the analysis file. It holds the
settings the run was asked for, where the data came from, every scalar
measurement, every curve, and the summary images with the geometry drawn on them.
`fmri-qa --analysis-file` and `fmri-qa-run` write it, and a report is rendered from it
alone. Every value is already computed, so a reader never recomputes a metric.

To open one in MATLAB, R, Python or `ncdump`, see
[reading an analysis file elsewhere](#reading-an-analysis-file-elsewhere). The rest of this
page documents the file. What each analysis puts into it is on that analysis's
own page, and the [list of analyses](analyses/index.md) maps names to pages.

## The container

The file is netCDF-4, written through the `netCDF4` package, which wraps the
Unidata C library that MATLAB, R and Octave use. MATLAB needs no toolbox to read
it, and R needs only `ncdf4` from CRAN. Each array is stored with:

- **compression**: zlib level 4 with the byte shuffle filter;
- **a checksum**: `fletcher32`, verified on every read, so a flipped bit inside
  an array's stored bytes is an error and not a plausible number;
- **its own dimensions**, which may be zero-length: `images.phantom_hull` is
  $(0, 2)$ when the mask is too small to have an outline.

Everything is in the root group. `Conventions` is CF-1.10, which the mask flags
and labeled units follow. Variable names are dotted paths, such as
`images.sfnr`, the names these pages use. {doc}`developers` explains these
choices.

## Dimensions and coordinates

Every array is declared over shared, named dimensions, so a reader can see which
arrays share an axis without comparing lengths. Axes of equal size stay separate:
`image_axis`, `psf_direction` and `hull_coord` are three different length-2
meanings, and merging them would imply a relationship that is not there.

Every dimension also has a coordinate variable of the same name. CF, and so
xarray and `ncdisp`, reads only that as the axis. Without it a reader gets
"dimensions without coordinates" and plots against 0…n−1.

| Dimension | Coordinate | Owned by |
| --- | --- | --- |
| `frame` | 0-based index into the **analyzed** series | [stability](analyses/stability.md) |
| `frequency` | the spectrum's own frequencies, in Hz (the values of `curves.spectrum_hz`) | [stability](analyses/stability.md) |
| `roi_width` | the Weisskoff ROI widths, in voxels (the values of `curves.weisskoff.roi_sizes`) | [stability](analyses/stability.md) |
| `row`, `col` | image position, in array-index order | [stability](analyses/stability.md) |
| `image_axis` | flags `row col` | [motion](analyses/motion.md) |
| `psf_direction` | flags, named by the document (`PE`/`RO`, or `axis0`/`axis1`) | [smoothness](analyses/smoothness.md) |
| `psf_lag`, `psf_model_sample` | index along the empirical and model PSF curves | [smoothness](analyses/smoothness.md) |
| `hull_vertex` | vertex of the closed phantom outline | [localization](analyses/localization.md) |
| `hull_coord` | flags `x y`, in plot order | [localization](analyses/localization.md) |

Three of the label axes are stored as CF-flagged `NC_INT` instead of `NC_STRING`.
Strings are a netCDF-4-only type that Octave's netCDF package and older readers
handle poorly, and the flag vocabulary uses the same terms as the masks.

Where an axis's real values are not one-dimensional, they stay where they are and
the axis points at them with a CF `coordinates` attribute. `frame` is an index
and the seconds along it are `curves.time`. The PSF lags differ by direction and
so are 2-D. This is why xarray gives
`ds["curves.roi_signal"].coords["curves.time"]` beside the frame index.

`frame` counts along the **analyzed** series, after the warm-up trim: the
acquired volume number is the index plus `provenance.n_trimmed`, and
`measurements.outlier_worst_frame` indexes this axis directly.

All coordinates are derived at encode time and **none is ever read back**. The
dotted arrays and the JSON document remain the single source of truth for
`load_artifact`, so a coordinate cannot drift from what it was derived from.

## Masks are flagged bytes

netCDF-4 has no boolean type, so each mask (`images.phantom_mask`,
`images.invalid_mask`, and the four `images.ghost.*` regions) is stored as `uint8`
0/1 bytes carrying CF's `flag_values = [0, 1]` and
`flag_meanings = "outside inside"`. That makes the bytes self-describing enough to
be turned back into `bool` on read. The analysis file in memory is the same either
way.

## Global attributes

### `document`

Everything that is not an array rides as one JSON string in the global attribute
`document`, with six top-level keys:

| Key | Holds |
| --- | --- |
| `schema_version` | the layout this file was written under |
| `settings` | the knobs, the same values as the `settings.*` attributes |
| `provenance` | the fields listed below |
| `measurements` | every scalar, the same values as the `measurements.*` attributes |
| `curves` | the curve scalars, the same values as the `curves.*` attributes |
| `images` | the ROI box and the ghost flag, the same values as the `images.*` attributes |

### Every scalar, as an attribute

**Every scalar the document holds is also a global attribute of its own**, named
for its document path, with a nested object flattening into the name:
`settings.roi_size`, `measurements.snr`, `provenance.tr`, `curves.psf.fwhm`,
`images.roi.row0`. No reader has to decode JSON. `ncdisp` lists them all and
`ncreadatt` hands one over.

A float is an `NC_DOUBLE`, an integer an `NC_INT`, a bool an `NC_UBYTE` 0 or 1, a
string `NC_CHAR`, and a JSON list of numbers the vector of its element type.
`provenance.voxel_mm` is three doubles and `provenance.matrix` two ints, a shape
a netCDF attribute has and a reader gets whole. A list of words is one
space-separated text, the way CF spells `flag_meanings`: `curves.psf.labels` reads
`PE RO`.

These attributes are a convenience for foreign readers. The JSON document is the
single source of truth for `load_artifact`, which never consults them. So the two can only disagree if the document does.

### The settings

What the run was asked for, and the one thing it resolved. A setting that was
not given (`pe_axis_override` unless `--pe-axis` was passed) has no attribute, by
the same rule as a `null` provenance field.

| Attribute | Type | Meaning |
| --- | --- | --- |
| `settings.trim_sec` | double | warm-up seconds dropped before analysis |
| `settings.detrend` | text | `poly` or `spline`, the detrending method |
| `settings.center` | text | `image` or `phantom`, where the ROI was centered |
| `settings.roi_size` | int | side of the square ROI requested, in voxels |
| `settings.pe_axis_override` | int | the phase-encode axis forced by `--pe-axis`; absent unless one was |
| `settings.detrend_order` | int | the polynomial or spline order the run resolved from its duration |

### The provenance fields

| Attribute | Type | Meaning |
| --- | --- | --- |
| `provenance.scan` | text | display name of the analyzed series |
| `provenance.source` | text | path it was read from |
| `provenance.created` | text | ISO-8601 UTC timestamp of the analysis |
| `provenance.core_version` | text | version of `fmri-qa-core` that computed it |
| `provenance.tr` | double | repetition time, seconds |
| `provenance.n_frames` | int | frames in the **analyzed** series, after the trim |
| `provenance.n_trimmed` | int | warm-up volumes the trim dropped |
| `provenance.slice_index` | int | 0-based plane of the volume analyzed |
| `provenance.n_slices` | int | planes in the volume |
| `provenance.voxel_mm` | double[3] | voxel size (row, col, slice spacing), mm |
| `provenance.matrix` | int[2] | in-plane acquisition matrix |
| `provenance.te` | double | echo time, seconds |
| `provenance.flip_angle` | double | flip angle, degrees |
| `provenance.slice_thickness` | double | slice thickness, mm |
| `provenance.pe_dir` | text | phase-encode direction as DICOM names it (`ROW`/`COL`) |
| `provenance.coil` | text | receive coil |
| `provenance.manufacturer` | text | scanner manufacturer |
| `provenance.model` | text | scanner model |
| `provenance.serial` | text | scanner serial number |
| `provenance.field_strength` | double | field strength, tesla |
| `provenance.software` | text | scanner software version |
| `provenance.datetime` | text | acquisition date and time |
| `provenance.series` | text | series description |

Everything from `voxel_mm` down is acquisition metadata copied from the BIDS
sidecar and the NIfTI header. All of it is optional, and a scan without a sidecar
still analyzes. A sidecar field of the wrong type (an `EchoTime` written as a
string, say) is recorded as unknown, with a warning naming it. It is not guessed
at.

Text is written as `NC_CHAR`, UTF-8 encoded. Measurement strings come from closed
ASCII vocabularies (`mm`/`vox`, `row`/`col`/`?`). Provenance strings come from
file names and scanner headers, which this package cannot constrain. The one
string with no UTF-8 form is the lone surrogate a Windows file name with an
undecodable byte becomes in Python. It is written as its `\udcff` escape. That
attribute is lossy where the document is not, which is better for a convenience
copy than failing the save.

## NaN, and absent

The distinction runs through the whole file:

- **NaN** means *the estimator ran and could not resolve the value*. The
  attribute is present and holds a NaN. The document spells it with the bare
  token `NaN`.
- **Absent** means *the quantity does not apply here*, or, in provenance,
  *nothing recorded it*. There is **no attribute at all**, and the document
  spells it `null`.

A netCDF attribute cannot be null, so absence is the encoding. Writing NaN for
both would lose a distinction a physicist reads. The clipping ceiling of a series
with no ADC rail is absent. A ghost ratio whose region came back empty is NaN.
See [saturation](analyses/saturation.md) for the first case and
[ghosting](analyses/ghosting.md) for the second.

## Reading an analysis file elsewhere

The readers a site already has can open netCDF-4 without a package that
understands NumPy's format. Each array is a variable under its dotted name
(`curves.roi_signal`, `images.sfnr`), declared over shared named dimensions
(`frame`, `frequency`, `row`, `col`, …). Each dimension carries a coordinate
variable of its own, so an axis has values and not only a name. Boolean masks are
flagged `uint8` bytes in CF style. Every setting, scalar measurement and recorded
provenance field is a global attribute of its own, and the JSON document is the
global attribute `document`.

```matlab
ncdisp('scan.qa.nc')                                   % the whole layout
signal = ncread('scan.qa.nc', 'curves.roi_signal');
snr = ncreadatt('scan.qa.nc', '/', 'measurements.snr');
tr = ncreadatt('scan.qa.nc', '/', 'provenance.tr');
roi = ncreadatt('scan.qa.nc', '/', 'settings.roi_size');
doc = jsondecode(ncreadatt('scan.qa.nc', '/', 'document'));
```

```r
nc <- ncdf4::nc_open("scan.qa.nc")
signal <- ncdf4::ncvar_get(nc, "curves.roi_signal")
doc <- jsonlite::fromJSON(ncdf4::ncatt_get(nc, 0, "document")$value)
```

```python
import xarray as xr

dataset = xr.open_dataset("scan.qa.nc")
dataset["curves.roi_signal"]
dataset["curves.roi_signal"].plot()  # against the frame axis the file supplies
dataset.attrs["document"]
```

`ncdump -h scan.qa.nc` prints the same header at a shell.

Caveat on the last MATLAB line: the document spells an unresolved measurement as
the bare token `NaN`, which Python and R's JSON parsers accept and MATLAB's
`jsondecode` rejects. Arrays and attributes are unaffected, and every scalar in
the document is also an attribute, so MATLAB users never need to decode it.

A netCDF-4 file is an HDF5 file, and HDF5 takes an advisory lock on files it
opens. On an NFS or SMB share with locking disabled or broken, a reader can fail
where a plain read would work. Set `HDF5_USE_FILE_LOCKING=FALSE` in the reader's
environment to work around it. Nothing here sets it for you, since a library that
disables locking for its whole process decides that for code it knows nothing
about.

Damage is caught, but not in every form. A sweep of 408 single-byte flips over a
stored analysis file refused 153 and left 247 in slack space, where they changed
nothing a reader can see. One flip sent a variable to another variable's intact
chunk, which passes its own checksum and so reads back as the wrong image. Seven
aborted the process inside libhdf5, a C library that reads files it was not
written to distrust. The checksum makes damage to an array's own bytes loud. It
does not make the file tamper-proof.

## Versions, and older files

The file records the schema it was written under. A later build upgrades an older
layout on load, with a warning, and any field that schema lacked comes back as
*not recorded*, not as a value nothing measured. Only an analysis file from a
**newer** build than the reader is refused, because its layout cannot be known.

Analysis files written by earlier builds as compressed `.qa.npz` archives still load.
The container is recognized from the file's leading bytes, not its name, so a
directory filled before the netCDF change keeps opening. Nothing writes an `.npz`
any more.

`ARTIFACT_SCHEMA_VERSION` pins the layout of the *document* (which fields exist
and what they mean), not the envelope. The move from `.npz` to netCDF changed no
field, so it bumped no version. Bumping it would have made older builds refuse
files as "from the future" when they understand the document perfectly.

## References

- `notes/analysis_report_split.md` in this repository: why the project splits
  into a calculation half and a presentation half, and what the seam carries.
- CF Conventions 1.10: the flag vocabulary the masks use and the coordinate
  convention the axes follow.
