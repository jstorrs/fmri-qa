# The analysis file

The analysis file (`.qa.nc`) is the complete result of analyzing one series. It
contains the settings requested for the run, the origin of the data, every
scalar measurement, every curve, and the summary images together with the
geometry drawn on them. It is written by `fmri-qa --analysis-file` and by
`fmri-qa-run`, and a report is rendered from it alone. Every value is already
computed, so a reader never recomputes a metric.

Instructions for opening a file in MATLAB, R, Python or `ncdump` are given under
[Reading an analysis file in other software](#reading-an-analysis-file-in-other-software).
The remainder of this page specifies the format. The quantities that each
analysis stores are documented on the page for that analysis, and the
[list of analyses](analyses/index.md) maps names to pages.

## The container

The file is netCDF-4, written through the `netCDF4` package, which wraps the
Unidata C library used by MATLAB, R and Octave. MATLAB reads it without a
toolbox, and R requires only `ncdf4` from CRAN. Each array is stored with:

- **compression**: zlib level 4 with the byte-shuffle filter;
- **a checksum**: `fletcher32`, verified on every read, so that a flipped bit
  within the stored bytes of an array produces an error and not a plausible
  number;
- **its own dimensions**, which may have zero length: `images.phantom_hull` is
  $(0, 2)$ when the mask is too small to have an outline.

Everything is stored in the root group. `Conventions` is CF-1.10 (Eaton et al.,
2022), which the mask flags and the labeled units follow. Variable names are
dotted paths, such as `images.sfnr`, and are the names used throughout this
guide. The reasons for these choices are given in {doc}`developers`.

## Dimensions and coordinates

Every array is declared over shared, named dimensions, so that a reader can
identify the arrays that share an axis without comparing lengths. Axes of equal
size remain distinct: `image_axis`, `psf_direction` and `hull_coord` are three
different quantities of length 2, and merging them would imply a relationship
that does not exist.

Every dimension also has a coordinate variable of the same name. CF, and
therefore xarray and `ncdisp`, recognizes only such a variable as the axis.
Without it, a reader reports "dimensions without coordinates" and plots against
0…n−1.

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

Three of the label axes are stored as CF-flagged `NC_INT` and not as
`NC_STRING`. Strings are a type specific to netCDF-4 that the Octave netCDF
package and older readers handle poorly, and the flag vocabulary uses the same
terms as the masks.

Where the true values of an axis are not one-dimensional, they remain in their
own variable, and the axis refers to them through a CF `coordinates` attribute.
`frame` is an index, and the times in seconds along it are `curves.time`. The
PSF lags differ by direction and are therefore two-dimensional. This is why
xarray presents `ds["curves.roi_signal"].coords["curves.time"]` beside the frame
index.

`frame` counts along the **analyzed** series, after the initial volumes have
been trimmed. The acquired volume number is the index plus
`provenance.n_trimmed`, and `measurements.outlier_worst_frame` indexes this axis
directly.

All coordinates are derived when the file is encoded, and **none is ever read
back**. The dotted arrays and the JSON document remain the single source of
truth for `load_analysis`, so a coordinate cannot diverge from the data from
which it was derived.

## Masks as flagged bytes

netCDF-4 has no boolean type. Each mask (`images.phantom_mask`,
`images.invalid_mask`, and the four `images.ghost.*` regions) is therefore
stored as `uint8` bytes of 0 or 1 that carry the CF attributes
`flag_values = [0, 1]` and `flag_meanings = "outside inside"`. The bytes are
thereby sufficiently self-describing to be converted back to `bool` on read, and
the analysis in memory is identical in either case.

## Global attributes

### The `document` attribute

Everything that is not an array is carried in a single JSON string, the global
attribute `document`, which has six top-level keys:

| Key | Holds |
| --- | --- |
| `schema_version` | the layout this file was written under |
| `settings` | the knobs, the same values as the `settings.*` attributes |
| `provenance` | the fields listed below |
| `measurements` | every scalar, the same values as the `measurements.*` attributes |
| `curves` | the curve scalars, the same values as the `curves.*` attributes |
| `images` | the ROI box and the ghost flag, the same values as the `images.*` attributes |

### Scalars as individual attributes

**Every scalar in the document is also a global attribute of its own.** The
attribute is named for its path in the document, and a nested object is
flattened into the name: `settings.roi_size`, `measurements.snr`,
`provenance.tr`, `curves.psf.fwhm`, `images.roi.row0`. No reader therefore needs
to decode JSON. `ncdisp` lists every attribute and `ncreadatt` returns any one
of them.

A float is stored as `NC_DOUBLE`, an integer as `NC_INT`, a boolean as an
`NC_UBYTE` of 0 or 1, a string as `NC_CHAR`, and a JSON list of numbers as a
vector of its element type. `provenance.voxel_mm` is thus three doubles and
`provenance.matrix` two integers, a shape that a netCDF attribute supports and
that a reader receives intact. A list of words is stored as a single
space-separated text, as CF writes `flag_meanings`: `curves.psf.labels` reads
`PE RO`.

These attributes are a convenience for readers other than this package. The
JSON document is the single source of truth for `load_analysis`, which never
consults the attributes, so the two can disagree only if the document itself is
inconsistent.

### Settings

The settings record what was requested for the run, together with the one
quantity that the run resolved. A setting that was not given (`pe_axis_override`
unless `--pe-axis` was passed) has no attribute, by the same rule that governs a
`null` provenance field.

| Attribute | Type | Meaning |
| --- | --- | --- |
| `settings.trim_sec` | double | warm-up seconds dropped before analysis |
| `settings.detrend` | text | `poly` or `spline`, the detrending method |
| `settings.center` | text | `image` or `phantom`, where the ROI was centered |
| `settings.roi_size` | int | side of the square ROI requested, in voxels |
| `settings.pe_axis_override` | int | the phase-encode axis forced by `--pe-axis`; absent unless one was |
| `settings.detrend_order` | int | the polynomial or spline order the run resolved from its duration |

### Provenance

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

The fields from `voxel_mm` onward are acquisition metadata copied from the BIDS
sidecar and the NIfTI header. All of them are optional, and a scan without a
sidecar can still be analyzed. A sidecar field of the wrong type, such as an
`EchoTime` written as a string, is recorded as unknown, with a warning that
names it. No attempt is made to interpret it.

Text is written as `NC_CHAR`, encoded as UTF-8. Measurement strings are drawn
from closed ASCII vocabularies (`mm`/`vox`, `row`/`col`/`?`). Provenance strings
originate in file names and scanner headers, which this package cannot
constrain. The only string with no UTF-8 form is the lone surrogate that Python
substitutes for an undecodable byte in a Windows file name, and it is written as
its `\udcff` escape. That attribute is consequently lossy where the document is
not, which is preferable, for a convenience copy, to failing the save.

## NaN and absence

One distinction applies throughout the file:

- **NaN** means that *the estimator ran and could not resolve the value*. The
  attribute is present and holds a NaN, and the document writes it as the bare
  token `NaN`.
- **Absent** means that *the quantity does not apply*, or, for provenance, that
  *nothing recorded it*. There is **no attribute at all**, and the document
  writes `null`.

A netCDF attribute cannot be null, so absence is the encoding. Writing NaN in
both cases would discard a distinction that matters physically. The clipping
ceiling of a series with no ADC ceiling is absent, whereas a ghost ratio whose
region is empty is NaN. See [saturation](analyses/saturation.md) for the first
case and [ghosting](analyses/ghosting.md) for the second.

## Reading an analysis file in other software

netCDF-4 can be opened by software that most sites already have, with no need
for a package that understands NumPy's formats. Each array is a variable under
its dotted name (`curves.roi_signal`, `images.sfnr`), declared over shared named
dimensions (`frame`, `frequency`, `row`, `col`, …). Each dimension has a
coordinate variable, so an axis has values and not merely a name. Boolean masks
are flagged `uint8` bytes in the CF style. Every setting, scalar measurement and
recorded provenance field is a global attribute of its own, and the JSON
document is the global attribute `document`.

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

`ncdump -h scan.qa.nc` prints the same header in a shell.

One caveat applies to the last MATLAB line. The document writes an unresolved
measurement as the bare token `NaN`, which the JSON parsers of Python and R
accept and MATLAB's `jsondecode` rejects. Arrays and attributes are unaffected,
and every scalar in the document is also an attribute, so MATLAB users never
need to decode the document.

A netCDF-4 file is an HDF5 file, and HDF5 places an advisory lock on the files
it opens. On an NFS or SMB share on which locking is disabled or faulty, a
reader can fail where a plain read would succeed. Setting
`HDF5_USE_FILE_LOCKING=FALSE` in the environment of the reader avoids the
failure. The package does not set the variable itself, because a library that
disabled locking for its whole process would impose that decision on unrelated
code.

Corruption is detected, but not in every form. In a test of 408 single-byte
alterations to a stored analysis file, 153 were refused and 247 fell in unused
space, where they changed nothing visible to a reader. One redirected a variable
to the intact chunk of another variable, which passes its own checksum and
therefore reads back as the wrong image. Seven aborted the process inside
libhdf5, a C library that was not written to distrust its input. The checksum
ensures that damage to the bytes of an array is reported. It does not make the
file tamper-proof.

## Versions and older files

The file records the schema under which it was written. A later build upgrades
an older layout on load, with a warning, and any field that the older schema
lacked is returned as *not recorded*, not as a value that nothing measured. Only
an analysis file from a build **newer** than the reader is refused, because its
layout cannot be known.

Analysis files that earlier builds wrote as compressed `.qa.npz` archives can
still be loaded. The container is identified from the leading bytes of the file
and not from its name, so a directory populated before the change to netCDF
remains readable. No current code writes an `.npz`.

`ANALYSIS_SCHEMA_VERSION` fixes the layout of the *document* (which fields exist
and what they mean) and not the container. The change from `.npz` to netCDF
altered no field, and so the version was not incremented. Incrementing it would
have caused older builds to refuse files as originating from a later version
when they understand the document fully.

## References

- Eaton B, Gregory J, Drach B, et al. *NetCDF Climate and Forecast (CF)
  Metadata Conventions*, version 1.10. 2022.
  <https://cfconventions.org/cf-conventions/cf-conventions.html> The source of
  the flag vocabulary used by the masks and of the coordinate convention that
  the axes follow.
- `notes/analysis_report_split.md` in the repository explains why the project
  is divided into a calculation part and a presentation part, and what passes
  between them.
