"""The netCDF-4 container: the artifact's arrays as a self-describing file.

The on-disk form of a `QAArtifact`. Every array `decompose` produces becomes a
netCDF variable under its own dotted path (`curves.weisskoff.cv`,
`images.ghost.pe_ghost` -- a dot is a legal netCDF name character), and the JSON
document carrying everything that is not an array rides alongside as the global
attribute `document`.

The point of netCDF in particular is that a QA archive outlives the Python
environment that wrote it and is read at a site that may have none. A `.npz` is
a zip of `.npy` members, and the readers a site already has cannot open one
without third-party code: npy-matlab is a package somebody has to find and
install, and RcppCNPy is numeric-only. netCDF is the format those same readers
reach through their ordinary channels: MATLAB's `ncread`/`ncinfo`/`ncdisp` are
built into the base product and need no toolbox at all, R's `ncdf4` is on CRAN,
`ncdump` comes with the netCDF tools, and xarray reads one in a call. This
completes the move the `uint8` document member started: that made the document
readable by a reader that could already open the archive; this makes the archive
itself openable.

    >> ncdisp('scan.qa.nc')                        % MATLAB: the whole layout
    >> sfnr = ncread('scan.qa.nc', 'images.sfnr');
    >> snr  = ncreadatt('scan.qa.nc', '/', 'measurements.snr');
    >> tr   = ncreadatt('scan.qa.nc', '/', 'provenance.tr');
    >> roi  = ncreadatt('scan.qa.nc', '/', 'settings.roi_size');

Version 4, written through the `netCDF4` package -- the Unidata C library
itself, the one MATLAB, R and Octave are linked against, so what this writes is
what those were tested on. It is a ~10 MB wheel carrying libhdf5 and libnetcdf,
which is the price of writing the format through its reference implementation
rather than re-deriving it. netCDF-4 is HDF5 underneath, and the three things
that buys are the reasons it is version 4 and not the classic version 1:

* **Per-variable compression** (`zlib` level 4, plus the byte `shuffle` filter
  for floats, which reorders a float64's bytes so like-magnitude exponents sit
  together and deflate has something to find). Shuffle is on for what this
  container is *for* -- a real acquisition's mean and SFNR images, noisy float64
  with a distinct value in nearly every voxel, where it saves around 13%. It is
  measurably worse on the synthetic phantom the tests analyze, whose mean image
  holds a few hundred distinct values because the fixture is stored as `uint16`:
  plain deflate finds runs in those that the shuffle breaks up, and the test
  phantom's artifact is 138,250 B with it against 134,219 B without (+3%), a
  128x128x300 one 451,719 B against 346,767 B (+30%). Kept on regardless, and
  every size this package publishes was measured with it on.
* **A per-variable checksum.** `fletcher32` is stored with every array and
  verified on every read, so a flipped bit inside an array's stored bytes is an
  error and not a plausible number. The `.npz` had this incidentally -- a zip
  member carries a CRC -- and netCDF-3 would have lost it: a single corrupted
  byte in a classic file loads as a valid artifact carrying wrong data almost
  half the time.
* **Zero-length dimensions.** `images.phantom_hull` is legitimately `(0, 2)`
  when the mask is too small to have an outline, and netCDF-3 spells a
  zero-length dimension as *the* unlimited one -- a file may have exactly one,
  so an empty array there would silently restructure the file rather than store
  an empty array.

Four things the layout does that a bag of arrays does not:

* **Dimensions are named and shared.** Every per-frame trace is declared over
  one `frame` dimension, both spectrum traces over `frequency`, every image over
  `row`/`col` -- so a reader that opens the file sees which arrays lie along the
  same axis instead of having to infer it from equal lengths. Two axes that
  merely happen to be the same size stay separate: `image_axis` is (row, col) in
  array order, `psf_direction` is (PE, RO) in the order the PSF curves use --
  or (axis0, axis1) on a run where no PE axis resolved -- and `hull_coord` is
  the hull's (x, y) *plot* order: three different meanings that are all length
  2, and conflating them would publish a relationship that is not there.
  Everything sits in the root group and nothing in a subgroup:
  `xr.open_dataset` sees only the root group, and Octave's group support is
  uneven, so a group would cost readers more than the tidiness is worth.
* **Every dimension carries a coordinate variable.** A named axis says which
  arrays lie along one line; a coordinate says *where* along it, and CF spells
  that as a 1-D variable named for the dimension itself. Without them a reader
  gets "dimensions without coordinates" and plots against 0..n-1; with them
  `ds["curves.roi_signal"].plot()` draws over an axis the file supplied. Where
  the values are already an array here, the coordinate is those same values --
  `frequency` is `curves.spectrum_hz`, `roi_width` is
  `curves.weisskoff.roi_sizes`, and both arrays stay where they are. Where the
  axis is a position, the coordinate is that position: `frame` (which is what
  `measurements.outlier_worst_frame` indexes, counting from the trimmed series),
  `row`, `col`, the two PSF sample axes, and the hull's vertices. The three
  length-2 label axes name their positions with CF `flag_values`/`flag_meanings`
  on an NC_INT rather than as an NC_STRING: strings are a netCDF-4-only type
  that Octave's package and older readers handle poorly, and a flagged integer
  says the same thing in the vocabulary the masks already use. An axis whose
  real values are not one-dimensional keeps them where they are and points at
  them instead -- the seconds labelling `frame` are `curves.time`, and the PSF
  lags differ by direction, so they are 2-D -- which a CF `coordinates`
  attribute on each variable does, and which is why xarray hands a user
  `ds["curves.roi_signal"].coords["curves.time"]` beside the frame index. Like
  the `measurements.*` attributes, all of this is derived at encode time and
  **never read back**: the dotted arrays and the JSON document remain the single
  source of truth for `load_artifact`, so a coordinate cannot drift from what it
  was derived from.
* **Boolean masks become `u1`.** netCDF-4 has no boolean type either, so each
  mask is stored as 0/1 bytes marked in CF style (`flag_values`,
  `flag_meanings`), which is what makes the bytes self-describing enough to turn
  back into `bool` on read -- the artifact in memory is unchanged either way.
* **Units and long names where they are certain.** Seconds, hertz, percent and
  dimensionless ratios are labelled; anything whose unit depends on the artifact
  (the PSF abscissas, in mm or voxels per `curves.psf.unit`) or that has no unit
  at all (raw image intensity) is left unlabelled rather than guessed at.

**Every scalar the document holds is also a global attribute**, named for its
document path, with a nested object flattening into the name (`measurements.snr`,
`provenance.tr`, `settings.roi_size`, `curves.psf.fwhm`, `images.roi.row0`), so
no reader has to decode JSON at all -- `ncdisp` lists them all and `ncreadatt`
hands one over. A float is an NC_DOUBLE, an integer an NC_INT, a bool an
NC_UBYTE 0 or 1, a string NC_CHAR, and a JSON list of numbers the vector of its
element type: `provenance.voxel_mm` is three NC_DOUBLEs and `provenance.matrix`
two NC_INTs, which is a shape a netCDF attribute has and a reader gets whole. A
list of words is one space-separated NC_CHAR text, the way CF itself spells
`flag_meanings`: `curves.psf.labels` reads `PE RO`. A field the document spells
`null` gets **no attribute at all**, and that absence is the encoding: the
document distinguishes
a NaN ("the estimator could not resolve this") from a null ("the quantity does
not apply here", in provenance "nothing recorded it", and in settings "not
overridden"), an attribute cannot be null, and writing NaN for both would
collapse the distinction. So a NaN attribute means what a NaN measurement means,
and a missing one means the other thing.

Text is written as NC_CHAR, which netCDF4 encodes as a `str`'s UTF-8 bytes.
Every string outside provenance is a closed vocabulary this package fixes
("mm"/"vox", "poly"/"spline", "PE"/"RO", ...), all ASCII. Provenance strings
are not this package's to constrain -- `scan` and `source` come from file
names, `coil`, `manufacturer`, `model`, `serial` and `software` from scanner
headers -- and the one string with no UTF-8 form at all is the lone surrogate a
Windows file name with an undecodable byte becomes in Python, which rides as its
`\\udcff` escape. That attribute is lossy where the document beside it is not,
which is the trade a convenience copy should make rather than failing the save.

Because these are a convenience for a foreign reader and nothing else, `read`
never consults them, and the JSON document stays the single source of truth for
`load_artifact`, so the two can only disagree if the document does -- the
attributes are derived from its text.

`Conventions` is claimed because the mask variables follow CF's flag convention
and the labelled units are CF's. The dotted variable names do deviate from CF,
which says a name *should* be letters, digits and underscores; they are kept
because the dotted path is the artifact's own vocabulary and a reader that
learns `images.sfnr` from `ncdisp` can find it in this package's docs, which
`images_sfnr` would not give.

**No schema bump.** `ARTIFACT_SCHEMA_VERSION` pins the *document's* layout --
which fields exist, what they mean, which migration reaches them -- and not one
field changed here. What changed is the envelope the same document and the same
named arrays travel in, which is the same call the `uint8` document member was:
a container change, read by sniffing the file's leading bytes rather than by
consulting a version that lives *inside* the file and so cannot be consulted
first. Bumping the version would also be actively wrong: it would tell every
older build "this file is from the future, refuse it" about a document those
builds understand perfectly, and would make the migration chain describe a step
that changes no field.

Three costs worth stating. HDF5 takes an advisory lock on a file it opens, and
on an NFS or SMB share whose locking is disabled or broken that fails where a
plain read would have worked; the escape is the reader's,
`HDF5_USE_FILE_LOCKING=FALSE` in the environment, and this package does not set
it -- a library that quietly disables locking for its whole process decides that
for code it knows nothing about.

Damage is caught, but not by us and not in every form. A sweep of 408
single-byte flips over a stored artifact refused 153, left 247 in slack space
where they changed nothing a reader can see, sent one variable to another
variable's intact chunk -- which passes its own checksum and so reads back as
the wrong image -- and seven times aborted the process inside libhdf5, which is
a C library reading a file it was not written to distrust and is below any
exception this module could catch. The checksum makes damage to an array's own
bytes loud; it does not make the file tamper-proof.

And the document still spells an unresolved measurement as the bare token `NaN`,
which is Python's JSON dialect and not the standard's, so MATLAB's `jsondecode`
refuses it where Python and R's `jsonlite` take it -- which is now only a caveat
for reading the *document*, since every number it carries is also an attribute.

`encode` is pure -- document and arrays in, a `NetcdfContent` value out -- so
every way the layout can refuse a set of arrays is settled before a file is
touched, and `write` performs exactly one write to disk. `read` is the inverse
of both.
"""

import json
import warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
from numpy.typing import NDArray

from ...exceptions import InvalidArtifactError
from .decompose import Member

if TYPE_CHECKING:  # the import itself is deferred; see `write`
    from netCDF4 import Dataset, Variable

# What a netCDF-4 file starts with, and so how `serialize` recognizes one: a
# netCDF-4 file *is* an HDF5 file and carries HDF5's own signature.
MAGIC: Final = b"\x89HDF\r\n\x1a\n"

# The full netCDF-4 data model, not `NETCDF4_CLASSIC`: the classic model would
# forbid the unsigned byte the masks are stored as, and buys nothing here that
# staying in the root group with fixed dimensions does not already buy.
_FORMAT: Literal["NETCDF4"] = "NETCDF4"

# Deflate level for every array variable: netCDF4's own default, kept because
# the level hardly matters on this data. A QA image is mostly noise, so levels 1
# through 9 span under half a percent of an artifact's size -- what moves the
# size here is the byte shuffle and the fact that the masks are bytes.
_COMPLEVEL: Final = 4

# The global attribute carrying the JSON document. Named for what it holds and
# not `__document__`: the npz member name was a name chosen to sort away from
# the arrays beside it, and a global attribute is not beside them.
_DOCUMENT = "document"

# The rest of the global attributes, for a reader that never decodes the JSON.
_CONVENTIONS = "CF-1.10"
_TITLE = "fmri-qa phantom fMRI quality-assurance artifact"

# The range NC_INT holds, which every integer measurement has to fit.
_INT32 = np.iinfo(np.int32)

# An attribute value in the forms this layout writes: text, the numeric scalars
# a measurement (or `schema_version`) becomes, the vectors a provenance list
# becomes, and the `u1` pair marking a mask.
type _AttributeValue = (
    str
    | np.int32
    | np.float64
    | np.uint8
    | NDArray[np.uint8]
    | NDArray[np.int32]
    | NDArray[np.float64]
)


# What marks a `u1` variable as a boolean mask, in CF's flag vocabulary, and
# what `read` looks for to turn one back into `bool`.
_FLAG_VALUES = "flag_values"


def _mask_attributes() -> dict[str, _AttributeValue]:
    """The CF flag markers for one mask, built fresh for each.

    A function rather than a module constant because the value is a mutable
    array: one shared instance would be handed to every mask in the file, and a
    caller that edited one would be editing all of them.
    """
    return {
        _FLAG_VALUES: np.array([0, 1], dtype=np.uint8),
        "flag_meanings": "outside inside",
    }


@dataclass(frozen=True, slots=True)
class _Layout:
    """How one array is declared: its axes, and what a reader should be told.

    `units` is omitted where the unit is not a fact about the layout -- an
    artifact's PSF abscissas are mm or voxels depending on what its header gave
    -- or where there is no unit to state, as for raw image intensity.
    """

    dimensions: tuple[str, ...]
    long_name: str
    units: str | None = None


# The declared layout, one entry per array `decompose` produces. Written out
# rather than derived, for the same reason `decompose` spells out its own
# mapping: the dimensions a variable is declared over are the published claim
# about which arrays share an axis, so adding a field should be a deliberate
# edit here and `encode` refuses an array this table does not describe.
_LAYOUT: dict[str, _Layout] = {
    # Per-frame traces, all along the analyzed series' `frame` axis.
    "curves.time": _Layout(("frame",), "time of the analyzed frame", "s"),
    "curves.roi_signal": _Layout(("frame",), "ROI-mean raw signal"),
    "curves.roi_trend": _Layout(("frame",), "fitted low-frequency trend"),
    "curves.roi_residual": _Layout(("frame",), "detrended ROI residual"),
    "curves.outlier_fraction": _Layout(
        ("frame",), "fraction of outlier voxels in the frame", "1"
    ),
    "curves.shear_pct": _Layout(("frame",), "fitted in-plane shear", "percent"),
    "curves.translation": _Layout(
        ("frame", "image_axis"), "fitted in-plane translation, in voxels"
    ),
    "curves.scale_pct": _Layout(
        ("frame", "image_axis"), "fitted in-plane scale change", "percent"
    ),
    "curves.com_deviation": _Layout(
        ("frame", "image_axis"), "centroid deviation from the series mean, in voxels"
    ),
    # The residual spectrum, on its own abscissa: DC is dropped, so this is not
    # a slice of the frame axis and must not share its dimension.
    "curves.spectrum_hz": _Layout(
        ("frequency",), "residual spectrum frequency, DC dropped", "Hz"
    ),
    "curves.spectrum_magnitude": _Layout(("frequency",), "residual spectrum magnitude"),
    # The Weisskoff curves, over the sampled ROI widths.
    "curves.weisskoff.roi_sizes": _Layout(
        ("roi_width",), "ROI width sampled, in voxels"
    ),
    "curves.weisskoff.cv": _Layout(
        ("roi_width",), "measured ROI-averaged coefficient of variation", "1"
    ),
    "curves.weisskoff.cv_ideal": _Layout(
        ("roi_width",), "uncorrelated-noise reference coefficient of variation", "1"
    ),
    "curves.weisskoff.rdc": _Layout(
        ("roi_width",), "radius of decorrelation at this ROI width", "1"
    ),
    # The point-spread curves: two directions (phase-encode first), sampled on
    # two different abscissas -- the measured lags and the model's own grid.
    "curves.psf.displacement": _Layout(
        ("psf_direction", "psf_lag"), "lag the empirical PSF was sampled at"
    ),
    "curves.psf.empirical": _Layout(
        ("psf_direction", "psf_lag"), "measured point-spread profile", "1"
    ),
    "curves.psf.model_x": _Layout(
        ("psf_direction", "psf_model_sample"), "lag the model PSF was sampled at"
    ),
    "curves.psf.model": _Layout(
        ("psf_direction", "psf_model_sample"),
        "Gaussian PSF implied by the measured FWHM",
        "1",
    ),
    # The summary images and the geometry drawn on them, all in the plane.
    "images.signal": _Layout(("row", "col"), "temporal mean image"),
    "images.sfnr": _Layout(
        ("row", "col"), "signal-to-fluctuation-noise ratio image", "1"
    ),
    "images.fluctuation_noise": _Layout(
        ("row", "col"), "temporal RMS of the detrended residuals"
    ),
    "images.static_noise": _Layout(("row", "col"), "odd/even difference image"),
    "images.phantom_mask": _Layout(("row", "col"), "phantom segmentation"),
    "images.invalid_mask": _Layout(
        ("row", "col"), "zeroed image edge, excluded from every statistic"
    ),
    "images.phantom_hull": _Layout(
        ("hull_vertex", "hull_coord"),
        "closed convex outline of the phantom, in (x=col, y=row) order",
    ),
    "images.ghost.pe_signal": _Layout(
        ("row", "col"), "phase-encode signal region the ghost ratio is measured against"
    ),
    "images.ghost.pe_ghost": _Layout(("row", "col"), "phase-encode ghost region"),
    "images.ghost.ro_signal": _Layout(
        ("row", "col"), "readout signal region, the ghost baseline"
    ),
    "images.ghost.ro_ghost": _Layout(("row", "col"), "readout ghost region"),
}


@dataclass(frozen=True, slots=True)
class _Index:
    """An axis whose coordinate is the position along it: 0..n-1, as NC_INT.

    The index a reader would otherwise have had to invent, published so that
    two artifacts align on it and a plot has an abscissa. `comment` is where an
    index that means something beyond its own position says what.
    """

    long_name: str
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class _Values:
    """An axis labelled by an array the artifact already publishes.

    That array stays exactly where it is under its own dotted name; the
    coordinate is the same numbers again under the dimension's name, which is
    the only spelling CF -- and so xarray, and so `ncdisp` -- reads as the axis
    itself. A file that does not carry `source` gets no coordinate for this
    axis rather than an invented one.
    """

    source: str
    long_name: str
    units: str | None = None


@dataclass(frozen=True, slots=True)
class _Labels:
    """A short axis whose positions are named, as CF flags on an NC_INT.

    Not an NC_STRING variable: strings are a netCDF-4-only type that Octave's
    netCDF package and older readers handle poorly, and the flag vocabulary
    says the same thing in the terms this file already uses for the masks.

    `meanings` is either the names themselves, fixed by this layout as one
    space-separated string, or a path into the document to the list of strings
    that names the positions for *this* artifact. The PSF directions are the
    case for the second: they are PE and RO on most runs and axis0 and axis1
    when no phase-encode axis resolved, and a coordinate that said "PE RO"
    regardless would publish a claim the document contradicts.
    """

    long_name: str
    meanings: str | tuple[str, ...]


# One coordinate variable per dimension the table above declares, written out
# in the same explicit style and for the same reason: which values a reader is
# handed for an axis is a published claim, so an axis that reaches `encode`
# without an entry here is refused rather than left unlabelled. Every one is
# derived at encode time and none is ever read back -- see the module
# docstring.
_COORDINATES: dict[str, _Index | _Values | _Labels] = {
    "frame": _Index(
        "index of the analyzed frame",
        comment=(
            "0-based index into the analyzed series, which is what every frame "
            "index in this artifact counts along: measurements.outlier_worst_frame "
            "indexes this axis directly, and the acquired volume number is this "
            "index plus provenance.n_trimmed, the warm-up volumes the run dropped."
        ),
    ),
    "frequency": _Values(
        "curves.spectrum_hz", "residual spectrum frequency, DC dropped", "Hz"
    ),
    "roi_width": _Values("curves.weisskoff.roi_sizes", "ROI width sampled, in voxels"),
    "row": _Index("image row, in array index order"),
    "col": _Index("image column, in array index order"),
    "psf_lag": _Index("sample along the empirical point-spread profile"),
    "psf_model_sample": _Index("sample along the model point-spread curve"),
    "hull_vertex": _Index("vertex of the closed phantom outline"),
    "image_axis": _Labels("in-plane image axis, in array order", "row col"),
    "psf_direction": _Labels(
        "point-spread direction, phase-encode first", ("curves", "psf", "labels")
    ),
    "hull_coord": _Labels("hull vertex coordinate, in plot order", "x y"),
}

# Where an axis's real values live when they cannot be the axis's own
# coordinate variable. `frame` is an index and the seconds along it are
# `curves.time`; the two PSF sample axes are indices because the lags differ by
# direction and so are 2-D. CF calls these auxiliary coordinates, and a
# variable names its own in a `coordinates` attribute -- which is what makes
# xarray hand a reader the seconds beside the index.
_AUXILIARY: dict[str, str] = {
    "frame": "curves.time",
    "psf_lag": "curves.psf.displacement",
    "psf_model_sample": "curves.psf.model_x",
}


@dataclass(frozen=True, slots=True)
class _Variable:
    """One netCDF variable: the stored array, its axes, and its attributes."""

    data: NDArray[Any]
    dimensions: tuple[str, ...]
    attributes: dict[str, _AttributeValue]


@dataclass(frozen=True, slots=True)
class NetcdfContent:
    """A whole netCDF-4 file, as a value: dimensions, variables, attributes.

    What `encode` produces and `write` pours into a file. Splitting the two is
    what keeps every way the layout can refuse an artifact -- an array it does
    not declare, a rank that disagrees with the declaration, two arrays claiming
    one dimension at two lengths, an axis with no coordinate declared for it, a
    measurement or provenance field no attribute can hold -- on the near side of
    opening a file, so a refusal cannot leave a partly written one behind.

    `variables` are the artifact's own arrays; `coordinates` are the axes
    derived from them, kept apart because they are stored differently and
    because nothing reads them back.
    """

    dimensions: dict[str, int]
    variables: dict[str, _Variable]
    coordinates: dict[str, _Variable]
    attributes: dict[str, _AttributeValue]


def encode(document: dict[str, Any], arrays: Mapping[str, Member]) -> NetcdfContent:
    """Lay out an artifact's document and arrays as a netCDF-4 file.

    Raises:
        ValueError: If an array is not one this layout declares, disagrees with
            its declared rank, or claims a dimension another array has already
            fixed at a different length; if an axis has no declared coordinate;
            or if a measurement or provenance field is of a kind no netCDF
            attribute can hold.
    """
    # Only the auxiliary coordinates this file actually carries: a `coordinates`
    # attribute naming a variable that is not here would send a reader looking
    # for an axis nothing can supply.
    auxiliary = {
        axis: source for axis, source in _AUXILIARY.items() if source in arrays
    }
    dimensions: dict[str, int] = {}
    variables: dict[str, _Variable] = {}
    for name, array in arrays.items():
        variables[name] = _variable(name, array, dimensions, auxiliary)
    return NetcdfContent(
        dimensions=dimensions,
        variables=variables,
        coordinates=_coordinates(dimensions, arrays, document),
        attributes=_global_attributes(document),
    )


def _coordinates(
    dimensions: dict[str, int], arrays: Mapping[str, Member], document: dict[str, Any]
) -> dict[str, _Variable]:
    """One coordinate variable per axis, derived from the arrays and document.

    An axis whose values live in an array this file does not carry gets no
    coordinate rather than an invented one -- `encode` takes whatever arrays it
    is handed, and a made-up abscissa would be worse than none.

    Raises:
        ValueError: If an axis has no coordinate declared for it.
    """
    coordinates: dict[str, _Variable] = {}
    for axis, length in dimensions.items():
        declared = _COORDINATES.get(axis)
        if declared is None:
            raise ValueError(f"the {axis} axis has no coordinate this layout declares")
        coordinate = _coordinate(axis, length, declared, arrays, document)
        if coordinate is not None:
            coordinates[axis] = coordinate
    return coordinates


def _coordinate(
    axis: str,
    length: int,
    declared: _Index | _Values | _Labels,
    arrays: Mapping[str, Member],
    document: dict[str, Any],
) -> _Variable | None:
    """One axis's coordinate variable, or None when its values are not here."""
    if isinstance(declared, _Values):
        return _value_coordinate(axis, declared, arrays)
    if isinstance(declared, _Labels):
        return _label_coordinate(axis, length, declared, document)
    return _index_coordinate(axis, length, declared)


def _value_coordinate(
    axis: str, declared: _Values, arrays: Mapping[str, Member]
) -> _Variable | None:
    """An axis carrying the values of the curve that already measures it."""
    source = arrays.get(declared.source)
    if source is None:
        return None
    attributes: dict[str, _AttributeValue] = {"long_name": declared.long_name}
    if declared.units is not None:
        attributes["units"] = declared.units
    return _Variable(np.asarray(source), (axis,), attributes)


def _label_coordinate(
    axis: str, length: int, declared: _Labels, document: dict[str, Any]
) -> _Variable:
    """An axis whose positions are named, as CF flags on the position itself."""
    positions = np.arange(length, dtype=np.int32)
    return _Variable(
        positions,
        (axis,),
        {
            "long_name": declared.long_name,
            _FLAG_VALUES: positions,
            "flag_meanings": " ".join(_label_meanings(declared, document)),
        },
    )


def _label_meanings(declared: _Labels, document: dict[str, Any]) -> list[str]:
    """The names of a labelled axis's positions, fixed or from the document."""
    if isinstance(declared.meanings, str):
        return declared.meanings.split()
    labels: Any = document
    for key in declared.meanings:
        labels = labels[key]
    return [str(label) for label in labels]


def _index_coordinate(axis: str, length: int, declared: _Index) -> _Variable:
    """An axis carrying the position along it, 0..n-1."""
    attributes: dict[str, _AttributeValue] = {"long_name": declared.long_name}
    if declared.comment is not None:
        attributes["comment"] = declared.comment
    return _Variable(np.arange(length, dtype=np.int32), (axis,), attributes)


def _global_attributes(document: dict[str, Any]) -> dict[str, _AttributeValue]:
    """The whole file's attributes: the JSON document, plus what it says.

    The document is the artifact's own record, unchanged from the `.npz` layout
    and still the only one `read` consults. Beside it ride two conveniences for
    a reader that never decodes JSON: a cheap header, so it can tell what the
    file is and refuse a version it does not know, and every scalar the
    document holds as an attribute of its own.

    `source` is CF's own name for what produced a file, so it keeps that
    spelling and is derived from `provenance.core_version` -- which is a
    different attribute under a different name, carrying the bare version.
    """
    # `json.dumps` defaults to ensure_ascii=True, and that default is
    # load-bearing here rather than incidental. A netCDF text attribute written
    # as NC_CHAR is bytes, and a consumer takes it as characters without being
    # told an encoding -- MATLAB's `ncreadatt` and R's `ncatt_get` both do.
    # Escaping every non-ASCII character to `\uXXXX` is what makes those the
    # right characters, whatever a scanner or a file name put in the document --
    # including the lone surrogate a Windows file name with an undecodable byte
    # becomes in Python, which has no UTF-8 form at all.
    text = json.dumps(document)
    # The section attributes are read back out of the text rather than taken
    # from `document` itself, so they are by construction the same values the
    # document publishes: the in-memory document still holds numpy scalars and
    # tuples where the file holds plain numbers and JSON lists, and a second
    # encoding of those would be a second chance to disagree with the first.
    stored = json.loads(text)
    return {
        "Conventions": _CONVENTIONS,
        "title": _TITLE,
        "source": f"fmri-qa-core {document['provenance']['core_version']}".rstrip(),
        # The same number the document carries, hoisted out so a reader can
        # check it without JSON.
        "schema_version": np.int32(document["schema_version"]),
        # Ordered so that `ncdisp` lists the short attributes before the long
        # blob: the header, then what the run was asked for, what it measured
        # and what it measured it on, then the document.
        **_section_attributes("settings", stored),
        **_section_attributes("measurements", stored),
        **_section_attributes("provenance", stored),
        **_section_attributes("curves", stored),
        **_section_attributes("images", stored),
        _DOCUMENT: text,
    }


def _section_attributes(
    section: str, document: dict[str, Any]
) -> dict[str, _AttributeValue]:
    """Every recorded field of one document section, as an attribute apiece.

    Each attribute is named for the document path its value came from, so
    `measurements.snr` in the file is `measurements.snr` in the document and in
    this package's vocabulary. One encoder serves every section, so the
    kind-to-type table is stated once and `measurements.snr`, `provenance.tr`
    and `settings.trim_sec` are NC_DOUBLEs for the same reason. A nested object
    -- the `psf` block of `curves`, the `roi` box of `images` -- flattens into
    the name, so its fields are attributes under their full document path
    (`curves.psf.fwhm`, `images.roi.row0`).

    A `null` field is skipped rather than written as anything: see the module
    docstring -- absence is how "the quantity does not apply", "nothing
    recorded it" and "not overridden" are spelled, because NaN already means
    "the estimator could not resolve it".
    """
    return {
        path: _attribute(path, value)
        for path, value in _leaves(section, document[section])
    }


def _leaves(prefix: str, mapping: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Every recorded value under `mapping`, by its dotted path from `prefix`.

    A nested object yields its own leaves under its key rather than itself, and
    a `null` yields nothing: see `_section_attributes`.
    """
    for name, value in mapping.items():
        path = f"{prefix}.{name}"
        if value is None:
            continue
        if isinstance(value, dict):
            yield from _leaves(path, value)
        else:
            yield path, value


def _attribute(name: str, value: Any) -> _AttributeValue:
    """One JSON value, already validated, as the netCDF attribute that holds it.

    Bools are matched before ints because `bool` *is* an `int` in Python, and a
    verdict published as a number a reader has to know is a verdict would be
    exactly the kind of guessing the flagged masks avoid.

    A list of numbers is the vector of its element type: `provenance.voxel_mm`
    is three NC_DOUBLEs and `provenance.matrix` two NC_INTs, which is a shape a
    netCDF attribute has natively and a reader gets in one call. A list of
    strings has no vector form -- that would be NC_STRING, the netCDF-4-only
    type the label axes already avoid -- so it is one space-separated NC_CHAR
    text, the way CF itself spells `flag_meanings`: `curves.psf.labels` reads
    `PE RO`.

    Raises:
        ValueError: If an integer is outside NC_INT, or the value is of a kind
            no attribute can hold.
    """
    match value:
        case bool():
            return np.uint8(value)
        case int():
            return _nc_int(name, value)
        case float():
            return np.float64(value)
        case str():
            return _escaped(value)
        case []:
            raise ValueError(f"{name} is an empty list, which names no attribute type")
        case list() if all(type(element) is int for element in value):
            return np.array([_nc_int(name, element) for element in value])
        case list() if all(type(element) is float for element in value):
            return np.array(value, dtype=np.float64)
        case list() if all(type(element) is str for element in value):
            return _escaped(" ".join(value))
    raise ValueError(f"{name} is a {type(value).__name__}, which no attribute can hold")


def _nc_int(name: str, value: int) -> np.int32:
    """An integer as NC_INT, refused rather than wrapped around if it does not fit.

    Validation bounds counts below but not above, so a count past NC_INT is a
    valid artifact this layout cannot publish faithfully.
    """
    if not _INT32.min <= value <= _INT32.max:
        raise ValueError(f"{name} is {value}, which does not fit a netCDF integer")
    return np.int32(value)


def _escaped(text: str) -> str:
    """One string as the NC_CHAR text a reader is handed.

    netCDF4 writes a `str` attribute as the UTF-8 bytes of NC_CHAR, and ASCII
    and any other encodable text pass through unchanged. The one string with no
    UTF-8 form -- the lone surrogate an undecodable byte in a Windows file name
    becomes in Python -- is escaped rather than allowed to fail the save; the
    document beside it still spells the name exactly, and that is what
    `load_artifact` reads.
    """
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _variable(
    name: str,
    array: Member,
    dimensions: dict[str, int],
    auxiliary: dict[str, str],
) -> _Variable:
    """One array as a netCDF variable, registering the axes it lies along.

    `dimensions` is extended in place with any axis this array is the first to
    fix, and checked against it for any axis already fixed -- so two variables
    declared over one dimension must agree on its length or neither is written.
    """
    layout = _LAYOUT.get(name)
    if layout is None:
        raise ValueError(f"{name} is not an array this artifact layout declares")
    if array.ndim != len(layout.dimensions):
        raise ValueError(
            f"{name} has rank {array.ndim}, but the layout declares it over "
            f"{layout.dimensions}"
        )
    for axis, length in zip(layout.dimensions, array.shape, strict=True):
        _fix_dimension(axis, int(length), name, dimensions)
    attributes: dict[str, _AttributeValue] = {"long_name": layout.long_name}
    if layout.units is not None:
        attributes["units"] = layout.units
    if array.dtype == np.bool_:
        attributes |= _mask_attributes()
    labelled = _labelling(name, layout.dimensions, auxiliary)
    if labelled:
        attributes["coordinates"] = labelled
    return _Variable(_stored(name, array), layout.dimensions, attributes)


def _labelling(
    name: str, dimensions: tuple[str, ...], auxiliary: dict[str, str]
) -> str:
    """The arrays that label this variable's axes, as CF names it them.

    A variable never names itself: `curves.time` *is* the seconds along the
    frame axis, and an array pointing at itself would be a claim about a
    relationship rather than one.
    """
    return " ".join(
        auxiliary[axis]
        for axis in dimensions
        if axis in auxiliary and auxiliary[axis] != name
    )


def _stored(name: str, array: Member) -> NDArray[Any]:
    """The array in the dtype the file holds it as.

    Masks become 0/1 `u1`, because netCDF has no boolean type; a measured array
    keeps its own float64. Any other dtype is refused rather than silently
    narrowed -- a QA number quietly stored at half its precision is the kind of
    loss a file format is supposed to make impossible.
    """
    if array.dtype == np.bool_:
        return array.astype(np.uint8)
    if array.dtype == np.float64:
        return array
    raise ValueError(f"{name} has dtype {array.dtype}, which this layout cannot store")


def _fix_dimension(
    axis: str, length: int, name: str, dimensions: dict[str, int]
) -> None:
    """Record one axis's length, or fail if it is already fixed differently."""
    fixed = dimensions.setdefault(axis, length)
    if fixed != length:
        raise ValueError(
            f"{name} makes the {axis} dimension {length}, but another array "
            f"already fixed it at {fixed}"
        )


def write(content: NetcdfContent, path: Path) -> None:
    """Write `content` to `path` as a netCDF-4 file, and close it.

    Exactly one file is written and the handle is closed before this returns, so
    a caller can fsync and rename the result -- which is how `save_artifact`
    makes the write atomic, and which Windows refuses to do to an open file.

    Every array variable is deflated and carries a `fletcher32` checksum, so a
    corrupted array fails to read rather than reading as wrong numbers. The
    float ones are shuffled first; see the module docstring for what that costs
    on the synthetic phantom and what it is expected to save on a real one. The
    coordinate variables get none of that, and are written first so `ncdisp`
    lists the axes before the arrays along them.
    """
    # Deferred: importing netCDF4 loads libhdf5 and libnetcdf, and the pipeline
    # defers `scipy.spatial` for the same reason -- a bare `--version` or
    # `--help` should not pay for a writer.
    import netCDF4

    with (
        netCDF4.Dataset(path, "w", format=_FORMAT) as dataset,
        warnings.catch_warnings(),
    ):
        # netCDF4 1.7.4 reshapes the incoming array by assigning to `.shape`
        # whenever it has more than one dimension (it compares the wanted shape,
        # a list, against `data.shape`, a tuple, so they never match), and NumPy
        # 2.5 deprecated setting `.shape`. There is no way to hand it an array
        # it will not reshape, and the warning names a line in a Cython module a
        # caller cannot act on, so it is dropped here rather than at every
        # caller of `save_artifact`.
        warnings.filterwarnings(
            "ignore",
            message="Setting the shape on a NumPy array",
            category=DeprecationWarning,
        )
        dataset.setncatts(content.attributes)
        for axis, length in content.dimensions.items():
            dataset.createDimension(axis, length)
        for axis, coordinate in content.coordinates.items():
            _write_coordinate(dataset, axis, coordinate)
        for name, variable in content.variables.items():
            _write_variable(dataset, name, variable)


def _write_coordinate(dataset: "Dataset", axis: str, coordinate: _Variable) -> None:
    """Create one coordinate variable and fill it, with every filter left off.

    A coordinate is a few hundred bytes of ascending numbers, and a filtered
    variable costs HDF5 a fixed couple of kilobytes of filter pipeline and
    chunk-index metadata whatever it holds: eleven of them deflated and
    checksummed grow the test phantom's artifact by 27,265 B, against 3,322 B
    stored contiguously and plain -- 20% of the file for the axes, or 2.5%.
    The checksum is not missed, because these are the one part of the file
    nothing reads back: `read` skips them and rebuilds the artifact from the
    arrays and the document, so damage to an axis cannot reach a loaded
    artifact the way damage to an array could.

    An empty axis -- `hull_vertex` when the phantom is too small to outline --
    is left chunked, because HDF5 has no contiguous layout for a dataset with
    no elements and refuses to create one. There is nothing to store either
    way, so the only thing the fallback costs is the chunk index.
    """
    stored = dataset.createVariable(
        axis,
        coordinate.data.dtype.name,
        coordinate.dimensions,
        contiguous=coordinate.data.size > 0,
    )
    stored.setncatts(coordinate.attributes)
    stored[...] = coordinate.data


def _write_variable(dataset: "Dataset", name: str, variable: _Variable) -> None:
    """Create one compressed, checksummed variable and fill it."""
    stored = dataset.createVariable(
        name,
        # By name ("float64", "uint8"), which is how netCDF spells a type too.
        variable.data.dtype.name,
        variable.dimensions,
        zlib=True,
        complevel=_COMPLEVEL,
        # The byte shuffle is for the float arrays; a single-byte mask has
        # nothing to interleave, so it could only cost time there.
        shuffle=variable.data.dtype.itemsize > 1,
        fletcher32=True,
    )
    stored.setncatts(variable.attributes)
    stored[...] = variable.data


def read(path: Path) -> tuple[str, dict[str, NDArray[Any]]]:
    """The JSON document's text and every stored array, from a netCDF artifact.

    Masks come back as `bool`, so what a caller receives is what was written
    however the bytes were stored. The measurements and provenance fields
    published as global attributes are deliberately *not* read -- they are
    derived at encode time, and a provenance string with no UTF-8 form is lossy
    there where the document is not -- and neither are the coordinate variables:
    the document and the dotted arrays are the one record this package reads
    back, and reading a derived copy too would be two answers to one question.

    Raises:
        InvalidArtifactError: If the file is not readable as netCDF-4, carries
            no `document` attribute, or carries one that is not text.
    """
    # Deferred for the same reason as in `write`.
    import netCDF4

    try:
        with netCDF4.Dataset(path, "r") as dataset:
            # Plain ndarrays, not masked ones: netCDF4 masks `_FillValue` and
            # out-of-range values by default, which would hand a caller a
            # MaskedArray whose fill value is indistinguishable from a measured
            # one. Nothing here writes a fill value or a scale factor, so both
            # conversions can only misrepresent what was stored.
            dataset.set_auto_mask(False)
            dataset.set_auto_scale(False)
            text = _document_text(dataset, path)
            arrays = {
                name: _restored(variable)
                for name, variable in dataset.variables.items()
                # A variable named for a dimension is that axis's coordinate
                # (CF 1.3), which this module derived on the way out and
                # `compose` has no field for. Skipped by that rule rather than
                # by a list of names, so an axis added to the layout is
                # excluded by the same reasoning that included it.
                if name not in dataset.dimensions
            }
    except InvalidArtifactError:
        raise
    except Exception as exc:
        # Broad on purpose, and only around the library calls: netCDF4 answers a
        # malformed file with an `OSError` carrying HDF5's error text, but a
        # fuzzed one also reaches `RuntimeError`, `IndexError` and `MemoryError`
        # through the same call. Enumerating a C library's failure modes is a
        # list that is wrong the next time it is rebuilt, and every one of them
        # means the same thing here.
        raise InvalidArtifactError(path, f"unreadable netCDF file: {exc}") from exc
    return text, arrays


def _document_text(dataset: "Dataset", path: Path) -> str:
    """The JSON document carried by the file's `document` attribute."""
    if _DOCUMENT not in dataset.ncattrs():
        raise InvalidArtifactError(path, "not an fmriqc artifact archive")
    text = dataset.getncattr(_DOCUMENT)
    if not isinstance(text, str):
        raise InvalidArtifactError(path, f"the {_DOCUMENT} attribute is not text")
    return text


def _restored(variable: "Variable[Any]") -> NDArray[Any]:
    """One stored variable as the array that was written.

    A variable carrying the CF flag markers `_mask_attributes` writes is a
    boolean mask stored as 0/1 bytes, and comes back `bool`; everything else is
    handed over as stored, for `compose` to narrow.
    """
    data: NDArray[Any] = np.asarray(variable[...])
    if _FLAG_VALUES in variable.ncattrs():
        return np.asarray(data != 0, dtype=np.bool_)
    return data
