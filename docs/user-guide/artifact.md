# The analysis artifact

One `.qa.nc` file is the whole published result of analyzing one series:
the settings the run was asked for, where the data came from, every scalar
measurement, every curve, and the summary images with the geometry drawn on
them. It is what the calculation half produces and the only thing the report
half accepts, and it is fully resolved — a consumer never recomputes a metric.

This page documents the file. What each analysis puts *into* it is on that
analysis's own page; the [analysis index](analyses/index.md) maps names to
pages.

## The container

The file is netCDF-4, written through the `netCDF4` package — the Unidata C
library itself, the one MATLAB, R and Octave are linked against, so what is
written is what those readers were tested on.

netCDF rather than a NumPy archive because a QA archive outlives the Python
environment that wrote it and is read at a site that may have none. MATLAB's
`ncread`, `ncinfo`, `ncdisp` and `ncreadatt` are in the base product and need
no toolbox; R's `ncdf4` is on CRAN; `ncdump` ships with the netCDF tools;
xarray opens one in a call. A `.npz`, by contrast, needs npy-matlab (a package
somebody has to find and install) and offers R only numeric arrays.

Version 4 rather than the classic version 1 buys three things this layout
needs:

- **Per-variable compression** — zlib level 4 with the byte shuffle filter,
  which reorders a float64's bytes so like-magnitude exponents sit together.
- **A per-variable checksum** — `fletcher32`, stored with every array and
  verified on every read, so a flipped bit inside an array's stored bytes is an
  error rather than a plausible number.
- **Zero-length dimensions** — `images.phantom_hull` is legitimately $(0, 2)$
  when the mask is too small to have an outline, and netCDF-3 spells a
  zero-length dimension as *the* unlimited one, of which a file may have
  exactly one.

Everything sits in the root group: `xr.open_dataset` sees only the root group
and Octave's group support is uneven, so a subgroup would cost readers more
than the tidiness is worth. `Conventions` is claimed as CF-1.10, which the mask
flags and the labeled units follow. The dotted variable names do deviate from
CF's recommendation of letters, digits and underscores; they are kept because
the dotted path is the artifact's own vocabulary, and a reader who learns
`images.sfnr` from `ncdisp` can look it up in these pages, which `images_sfnr`
would not give.

## Dimensions and coordinates

Every array is declared over shared, named dimensions, so a reader sees which
arrays lie along the same axis instead of inferring it from equal lengths. Two
axes that merely happen to be the same size stay separate — `image_axis`,
`psf_direction` and `hull_coord` are three different length-2 meanings, and
conflating them would publish a relationship that is not there.

Every dimension also carries a coordinate variable of its own, named for the
dimension, which is the only spelling CF — and so xarray, and so `ncdisp` —
reads as the axis itself. Without them a reader gets "dimensions without
coordinates" and plots against 0…n−1.

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

Three of the label axes are stored as CF-flagged `NC_INT` rather than as
`NC_STRING`: strings are a netCDF-4-only type that Octave's netCDF package and
older readers handle poorly, and the flag vocabulary says the same thing in the
terms the masks already use.

Where an axis's real values cannot *be* its coordinate — because they are not
one-dimensional — they stay where they are and the axis points at them with a
CF `coordinates` attribute. `frame` is an index and the seconds along it are
`curves.time`; the PSF lags differ by direction and so are 2-D. That is what
makes xarray hand a reader `ds["curves.roi_signal"].coords["curves.time"]`
beside the frame index.

`frame` counts along the **analyzed** series, after the warm-up trim: the
acquired volume number is the index plus `provenance.n_trimmed`, and
`measurements.outlier_worst_frame` indexes this axis directly.

All of the coordinates are derived at encode time and **none is ever read
back**. The dotted arrays and the JSON document remain the single source of
truth for `load_artifact`, so a coordinate cannot drift from what it was
derived from.

## Masks are flagged bytes

netCDF-4 has no boolean type, so each mask (`images.phantom_mask`,
`images.invalid_mask`, and the four `images.ghost.*` regions) is stored as
`uint8` 0/1 bytes carrying CF's `flag_values = [0, 1]` and
`flag_meanings = "outside inside"`. That is what makes the bytes
self-describing enough to be turned back into `bool` on read; the artifact in
memory is unchanged either way.

## Global attributes

### `document`

The whole of everything that is not an array rides as one JSON string in the
global attribute `document`, with six top-level keys:

| Key | Holds |
| --- | --- |
| `schema_version` | the layout this file was written under |
| `settings` | the knobs, the same values as the `settings.*` attributes |
| `provenance` | the fields listed below |
| `measurements` | every scalar, the same values as the `measurements.*` attributes |
| `curves` | the curve scalars, the same values as the `curves.*` attributes |
| `images` | the ROI box and the ghost flag, the same values as the `images.*` attributes |

### Every scalar, as an attribute

**Every scalar the document holds is also a global attribute of its own**,
named for its document path, with a nested object flattening into the name —
`settings.roi_size`, `measurements.snr`, `provenance.tr`, `curves.psf.fwhm`,
`images.roi.row0` — so no reader has to decode JSON at all. `ncdisp` lists them
all and `ncreadatt` hands one over.

A float is an `NC_DOUBLE`, an integer an `NC_INT`, a bool an `NC_UBYTE` 0 or 1,
a string `NC_CHAR`, and a JSON list of numbers the vector of its element type:
`provenance.voxel_mm` is three doubles and `provenance.matrix` two ints, which
is a shape a netCDF attribute has and a reader gets whole. A list of words is
one space-separated text, the way CF spells `flag_meanings`: `curves.psf.labels`
reads `PE RO`.

These attributes are a convenience for a foreign reader and nothing else. The
JSON document stays the single source of truth for `load_artifact`, which never
consults them — so the two can only disagree if the document does.

### The settings

What the run was asked for, and the one thing it resolved. A setting that was
not given — `pe_axis_override` unless `--pe-axis` was passed — has no
attribute, by the same rule as a `null` provenance field.

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
sidecar and the NIfTI header, and every one of those is optional: a scan
without a sidecar still analyzes. A sidecar field of the wrong type (an
`EchoTime` written as a string, say) is recorded as unknown with a warning
naming it, rather than guessed at.

Text is written as `NC_CHAR`, UTF-8 encoded. A measurement's strings are closed
vocabularies this package fixes (`mm`/`vox`, `row`/`col`/`?`), all ASCII.
Provenance strings are not this package's to constrain — they come from file
names and scanner headers — and the one string with no UTF-8 form at all is the
lone surrogate a Windows file name with an undecodable byte becomes in Python.
It rides as its `\udcff` escape; that attribute is lossy where the document
beside it is not, which is the trade a convenience copy should make rather than
failing the save.

## NaN, and absent

The distinction runs through the whole file and is worth stating once:

- **NaN** means *the estimator ran and could not resolve the value*. The
  attribute is present and holds a NaN; the document spells it with the bare
  token `NaN`.
- **Absent** means *the quantity does not apply here* — and, in provenance,
  *nothing recorded it*. There is **no attribute at all**, and the document
  spells it `null`.

A netCDF attribute cannot be null, so absence *is* the encoding, and writing
NaN for both would collapse a distinction a physicist reads. The clipping
ceiling of a series with no ADC rail is absent; a ghost ratio whose region came
back empty is NaN. See [saturation](analyses/saturation.md) for the clearest
case of the first and [ghosting](analyses/ghosting.md) for the second.

## Reading an artifact elsewhere

netCDF-4 is the format the readers a site already has can open without going
looking for a package that understands NumPy's. Each array is a variable under
the dotted name the library gives it (`curves.roi_signal`, `images.sfnr`),
declared over shared named dimensions (`frame`, `frequency`, `row`, `col`, …),
each of which carries a coordinate variable of its own so an axis has values
and not only a name; boolean masks are flagged `uint8` bytes in CF style; every
setting, scalar measurement and recorded provenance field is a global attribute
of its own; and the JSON document is the global attribute `document`.

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

One caveat on that last MATLAB line: the document spells an unresolved
measurement as the bare token `NaN`, which Python and R's JSON parsers accept
and MATLAB's `jsondecode` rejects. It only affects decoding the *document* —
the arrays and the attributes are unaffected, and every scalar in the document
is also an attribute, so a MATLAB user never needs to decode it.

A netCDF-4 file is an HDF5 file, and HDF5 takes an advisory lock on a file it
opens. On an NFS or SMB share with locking disabled or broken, a reader can
fail where a plain read would have worked; `HDF5_USE_FILE_LOCKING=FALSE` in
that reader's environment is the escape. Nothing here sets it for you — a
library that quietly disables locking for its whole process is deciding that
for code it knows nothing about.

Damage is caught, but not in every form. A sweep of 408 single-byte flips over
a stored artifact refused 153, left 247 in slack space where they changed
nothing a reader can see, sent one variable to another variable's intact
chunk — which passes its own checksum and so reads back as the wrong image —
and seven times aborted the process inside libhdf5, which is a C library
reading a file it was not written to distrust. The checksum makes damage to an
array's own bytes loud; it does not make the file tamper-proof.

## Versions, and older files

The file records the schema it was written under, and a later build reads it:
an older layout is migrated forward on load, with a warning, and any field that
schema did not carry comes back as *not recorded* rather than as a value
nothing measured. Only an artifact from a **newer** build than the one reading
it is refused, since its layout cannot be known.

Artifacts written by earlier builds as compressed `.qa.npz` archives still
load. The container is recognized from the file's leading bytes rather than
from its name, so a directory filled before the netCDF change keeps opening.
Nothing writes an `.npz` any more.

`ARTIFACT_SCHEMA_VERSION` pins the *document's* layout — which fields exist and
what they mean — and not the envelope. The move from `.npz` to netCDF changed
no field and so bumped no version: bumping it would have told every older build
"this file is from the future, refuse it" about a document those builds
understand perfectly.

## References

- `notes/analysis_report_split.md` in this repository — why the project splits
  into a calculation half and a presentation half, and what the seam carries.
- CF Conventions 1.10 — the flag vocabulary the masks use and the coordinate
  convention the axes follow.
