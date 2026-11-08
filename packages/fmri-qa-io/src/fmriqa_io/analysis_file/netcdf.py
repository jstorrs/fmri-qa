r"""The netCDF-4 container: the analysis file's arrays as a self-describing file.

Every array `decompose` produces is a netCDF variable under its dotted path
(`curves.weisskoff.cv`, `images.ghost.pe_ghost`). A dot is a legal netCDF name
character. The JSON document holding everything else is the global attribute
`document`.

netCDF is used because a QA archive outlives the Python environment that wrote
it and is read at sites that may have none. A `.npz` needs third-party code in
MATLAB (npy-matlab) and R (RcppCNPy, numeric-only). netCDF opens with what those
sites already have: MATLAB's built-in `ncread`/`ncinfo`/`ncdisp` (no toolbox), R's
`ncdf4` on CRAN, `ncdump`, and xarray. This completes the `uint8` document
member's move: that made the document readable by a reader that could open the
archive, and this makes the archive openable.

    >> ncdisp('scan.qa.nc')                        % MATLAB: the whole layout
    >> sfnr = ncread('scan.qa.nc', 'images.sfnr');
    >> snr  = ncreadatt('scan.qa.nc', '/', 'measurements.snr');
    >> tr   = ncreadatt('scan.qa.nc', '/', 'provenance.tr');
    >> roi  = ncreadatt('scan.qa.nc', '/', 'settings.roi_size');

The file is netCDF-4 (HDF5 underneath), written through the `netCDF4` package,
which wraps the Unidata C library that MATLAB, R and Octave link against. The
wheel is ~10 MB (libhdf5 and libnetcdf). Version 4 over classic version 1 buys:

* **Compression**: `zlib` level 4 per variable, plus the byte `shuffle` filter
  for floats. Shuffle saves ~13% on a real acquisition's mean and SFNR images
  (noisy float64, nearly every voxel distinct). It is worse on the synthetic
  test phantom, whose `uint16`-stored mean image has only a few hundred distinct
  values: 138,250 B with shuffle against 134,219 B without (+3%), and 451,719 B
  against 346,767 B (+30%) at 128x128x300. Shuffle stays on, and every size this
  package publishes was measured with it on.
* **A checksum per variable.** `fletcher32` is verified on every read, so a
  flipped bit in an array is an error, not a plausible number. The `.npz` had
  this through its zip CRC. In netCDF-3 a single corrupted byte loads as a valid
  analysis file with wrong data almost half the time.
* **Zero-length dimensions.** `images.phantom_hull` is `(0, 2)` when the mask is
  too small to outline. netCDF-3 spells a zero-length dimension as the unlimited
  one, and a file may have only one.

Layout:

* **Named, shared dimensions.** Per-frame traces share `frame`, the spectrum
  traces `frequency`, images `row`/`col`. Equal sizes do not share an axis:
  `image_axis` is (row, col) in array order, `psf_direction` is (PE, RO) (or
  (axis0, axis1) when no PE axis resolved), and `hull_coord` is the hull's (x, y)
  plot order. Those are three different meanings that are all length 2, and
  conflating them would publish a relationship that isn't there. Everything is
  in the root group, since `xr.open_dataset` sees only the root group and
  Octave's group support is uneven.
* **A coordinate variable per dimension** (CF: a 1-D variable named for the
  dimension), so `ds["curves.roi_signal"].plot()` has an axis instead of
  0..n-1. Where an array already holds the values, the coordinate repeats them:
  `frequency` is `curves.spectrum_hz`, `roi_width` is
  `curves.weisskoff.roi_sizes`. Otherwise it is the position: `frame` (the index
  `measurements.outlier_worst_frame` uses, counting from the trimmed series),
  `row`, `col`, the PSF sample axes and the hull vertices. The three length-2
  label axes use CF `flag_values`/`flag_meanings` on an NC_INT, since NC_STRING
  is poorly handled by Octave and older readers. Where an axis's real values are
  not 1-D (the seconds along `frame` are `curves.time`; PSF lags differ by
  direction), each variable's CF `coordinates` attribute points at them, so
  xarray offers `ds["curves.roi_signal"].coords["curves.time"]`. Coordinates, like
  the `measurements.*` attributes, are derived at encode time and **never read
  back**. The arrays and the document are the only source for `load_analysis`.
* **Masks are `u1`**, since netCDF-4 has no boolean type either. CF `flag_values`
  and `flag_meanings` mark them, which is how `read` turns them back into `bool`.
* **Units and long names where certain.** Seconds, hertz, percent and
  dimensionless ratios are labeled. Anything whose unit depends on the analysis file
  (PSF abscissas, mm or voxels per `curves.psf.unit`) or has none (raw image
  intensity) is not.

**Every scalar in the document is also a global attribute**, named for its
document path with nested objects flattened (`measurements.snr`, `provenance.tr`,
`settings.roi_size`, `curves.psf.fwhm`, `images.roi.row0`), so no reader has to
decode JSON. Types: float NC_DOUBLE, integer NC_INT, bool NC_UBYTE 0/1, string
NC_CHAR, list of numbers a vector of its element type (`provenance.voxel_mm` is
three NC_DOUBLEs, `provenance.matrix` two NC_INTs), list of words one
space-separated NC_CHAR as CF spells `flag_meanings` (`curves.psf.labels` reads
`PE RO`). A `null` field gets **no attribute**. The document distinguishes NaN
("the estimator could not resolve this") from null ("does not apply"; in
provenance "nothing recorded it"; in settings "not overridden"), and an attribute
cannot be null, so writing NaN for both would merge them. A NaN attribute means
what a NaN measurement means, and a missing one means null.

Text is NC_CHAR, which netCDF4 encodes as UTF-8. Strings outside provenance are
a fixed ASCII vocabulary ("mm"/"vox", "poly"/"spline", "PE"/"RO", ...).
Provenance strings are not ours to constrain: `scan` and `source` come from file
names, and `coil`, `manufacturer`, `model`, `serial` and `software` from scanner
headers. An undecodable byte in a Windows file name becomes a lone surrogate in
Python, which has no UTF-8 form and rides as its `\udcff` escape. The attribute
is lossy there and the document is not, which is the right trade for a
convenience copy.

`read` never consults the attributes. The JSON document stays the single source
of truth for `load_analysis`. The attributes are derived from the document's
text, so the two can only disagree if the document does. `Conventions` is
claimed because the masks follow CF's flag convention and the labeled units are
CF's. The dotted variable names deviate from CF (letters, digits and
underscores), so that a reader who learns `images.sfnr` from `ncdisp` can find
it in this package's docs.

**No schema bump.** `ANALYSIS_SCHEMA_VERSION` pins the document's layout, and no
field changed; only the envelope did, as with the `uint8` member. The loader
sniffs leading bytes because the version lives inside the file. A bump would tell
older builds "this file is from the future" about a document they understand,
and add a migration step that changes no field.

Costs:

* HDF5 takes an advisory lock on open. On an NFS or SMB share with locking
  disabled or broken, that fails where a plain read would work. The reader's
  escape is `HDF5_USE_FILE_LOCKING=FALSE`. This package does not set it, since
  that would disable locking for the whole process, including code it knows
  nothing about.
* Damage is only partly caught, and not by us. Of 408 single-byte flips over a
  stored analysis file, 153 were refused and 247 landed in slack space where they
  change nothing a reader can see. One sent a variable to another variable's
  intact chunk, which passes its own checksum and reads back as the wrong image.
  Seven aborted the process inside libhdf5, below any exception this module could
  catch. The checksum makes damage to an array's own bytes loud; the file is not
  tamper-proof.
* The document spells an unresolved measurement as the bare token `NaN`, Python's
  JSON dialect, not the standard's. MATLAB's `jsondecode` refuses it where Python
  and R's `jsonlite` accept it. This matters only for the document, since every
  number in it is also an attribute.

`encode` is pure (document and arrays in, a `_NetcdfContent` out), so every
refusal happens before a file is touched, and `write` performs one write. `read`
is the inverse of both.
"""

import warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
from numpy.typing import NDArray

from fmriqa.analysis.serialize.decompose import Member
from fmriqa.exceptions import InvalidAnalysisFileError

if TYPE_CHECKING:  # the import itself is deferred; see `write`
    from netCDF4 import Dataset, Variable

# What a netCDF-4 file starts with, and so how `analysis` recognizes one. A
# netCDF-4 file is an HDF5 file and carries HDF5's own signature.
MAGIC: Final = b"\x89HDF\r\n\x1a\n"

# The full netCDF-4 data model, not `NETCDF4_CLASSIC`. The classic model would
# forbid the unsigned byte the masks are stored as, and buys nothing that
# staying in the root group with fixed dimensions does not already buy.
_FORMAT: Literal["NETCDF4"] = "NETCDF4"

# Deflate level for every array variable. This is netCDF4's own default, kept
# because the level hardly matters on this data. A QA image is mostly noise, so
# levels 1 through 9 span under half a percent of an analysis file's size. What moves
# the size is the byte shuffle and the fact that the masks are bytes.
_COMPLEVEL: Final = 4

# The global attribute carrying the JSON document. It is named for what it holds,
# not `__document__`. The npz member name was chosen to sort away from the arrays
# beside it, and a global attribute is not beside them.
_DOCUMENT = "document"

# The rest of the global attributes, for a reader that never decodes the JSON.
_CONVENTIONS = "CF-1.10"
_TITLE = "fmri-qa phantom fMRI quality-assurance analysis file"

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
    """Build the CF flag markers for one mask, fresh for each.

    This is a function, not a module constant, because the value is a mutable
    array. One shared instance would go to every mask in the file, and a caller
    that edited one would edit all of them.
    """
    return {
        _FLAG_VALUES: np.array([0, 1], dtype=np.uint8),
        "flag_meanings": "outside inside",
    }


@dataclass(frozen=True, slots=True)
class _Layout:
    """How one array is declared: its axes and what a reader should be told.

    `units` is omitted where the unit is not a fact about the layout (an
    analysis file's PSF abscissas are mm or voxels depending on what its header gave)
    or where there is no unit to state, as for raw image intensity.
    """

    dimensions: tuple[str, ...]
    long_name: str
    units: str | None = None


# The declared layout, one entry per array `decompose` produces. It is written
# out, not derived, for the same reason `decompose` spells out its own mapping.
# The dimensions a variable is declared over are the published claim about which
# arrays share an axis, so adding a field should be a deliberate edit here, and
# `encode` refuses an array this table does not describe.
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
    # The residual spectrum, on its own abscissa. DC is dropped, so this is not
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
    # two different abscissas, the measured lags and the model's own grid.
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

    This is the index a reader would otherwise have to invent. It is published
    so that two analysis files align on it and a plot has an abscissa. `comment` is
    where an index that means more than its own position says so.
    """

    long_name: str
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class _Values:
    """An axis labeled by an array the analysis file already publishes.

    That array stays where it is under its own dotted name. The coordinate is
    the same numbers again under the dimension's name, which is the only
    spelling CF (and so xarray and `ncdisp`) reads as the axis itself. A file
    that does not carry `source` gets no coordinate for this axis, not an
    invented one.
    """

    source: str
    long_name: str
    units: str | None = None


@dataclass(frozen=True, slots=True)
class _Labels:
    """A short axis whose positions are named, as CF flags on an NC_INT.

    Not an NC_STRING variable, which Octave's package and older readers handle
    poorly; the flag vocabulary matches what the masks use.

    `meanings` is either the names as one space-separated string, or a path into
    the document to this analysis file's list of names. The PSF directions need the
    second form: they are PE and RO, or axis0 and axis1 when no PE axis resolved,
    and a coordinate that said "PE RO" regardless would publish a claim the
    document contradicts.
    """

    long_name: str
    meanings: str | tuple[str, ...]


# One coordinate variable per dimension the table above declares, written out
# in the same explicit style and for the same reason. Which values a reader is
# handed for an axis is a published claim, so an axis that reaches `encode`
# without an entry here is refused, not left unlabeled. Every one is derived at
# encode time and none is ever read back (see the module docstring).
_COORDINATES: dict[str, _Index | _Values | _Labels] = {
    "frame": _Index(
        "index of the analyzed frame",
        comment=(
            "0-based index into the analyzed series, which is what every frame "
            "index in this analysis file counts along: "
            "measurements.outlier_worst_frame "
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
# `curves.time`. The two PSF sample axes are indices because the lags differ by
# direction and so are 2-D. CF calls these auxiliary coordinates, and a
# variable names its own in a `coordinates` attribute. That is what makes
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
class _NetcdfContent:
    """A whole netCDF-4 file, as a value: dimensions, variables, attributes.

    `encode` produces it and `write` pours it into a file. The split keeps
    every way the layout can refuse an analysis file before any file is opened, so a
    refusal cannot leave a partly written one behind. Those refusals are an
    array it does not declare, a rank that disagrees with the declaration, two
    arrays claiming one dimension at two lengths, an axis with no coordinate
    declared for it, and a measurement or provenance field no attribute can
    hold.

    `variables` are the analysis file's own arrays. `coordinates` are the axes
    derived from them, kept apart because they are stored differently and
    nothing reads them back.
    """

    dimensions: dict[str, int]
    variables: dict[str, _Variable]
    coordinates: dict[str, _Variable]
    attributes: dict[str, _AttributeValue]


def encode(
    text: str, stored: dict[str, Any], arrays: Mapping[str, Member]
) -> _NetcdfContent:
    """Lay out an analysis file's document and arrays as a netCDF-4 file.

    `text` is the document's JSON, stored verbatim, and `stored` is that same
    text parsed back: the caller round-trips once and hands over both.

    Raises
    ------
    ValueError
        If an array is not one this layout declares, disagrees with its declared
        rank, or claims a dimension another array has already fixed at a
        different length; if an axis has no declared coordinate; or if a
        measurement or provenance field is of a kind no netCDF attribute can
        hold.
    """
    # Only the auxiliary coordinates this file actually carries. A `coordinates`
    # attribute naming a variable that is not here would send a reader looking
    # for an axis nothing can supply.
    auxiliary = {
        axis: source for axis, source in _AUXILIARY.items() if source in arrays
    }
    dimensions: dict[str, int] = {}
    variables: dict[str, _Variable] = {}
    for name, array in arrays.items():
        variables[name] = _variable(name, array, dimensions, auxiliary)
    return _NetcdfContent(
        dimensions=dimensions,
        variables=variables,
        coordinates=_coordinates(dimensions, arrays, stored),
        attributes=_global_attributes(text, stored),
    )


def _coordinates(
    dimensions: dict[str, int], arrays: Mapping[str, Member], document: dict[str, Any]
) -> dict[str, _Variable]:
    """Build one coordinate variable per axis from the arrays and document.

    An axis whose values live in an array this file does not carry gets no
    coordinate, not an invented one. `encode` takes whatever arrays it is
    handed, and a made-up abscissa would be worse than none.

    Raises
    ------
    ValueError
        If an axis has no coordinate declared for it.
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
    """Build one axis's coordinate variable, or None if its values are not here."""
    if isinstance(declared, _Values):
        return _value_coordinate(axis, declared, arrays)
    if isinstance(declared, _Labels):
        return _label_coordinate(axis, length, declared, document)
    return _index_coordinate(axis, length, declared)


def _value_coordinate(
    axis: str, declared: _Values, arrays: Mapping[str, Member]
) -> _Variable | None:
    """Build an axis from the values of the curve that already measures it."""
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
    """Build an axis of named positions, as CF flags on the position itself."""
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
    """Resolve a labeled axis's position names, fixed or from the document."""
    if isinstance(declared.meanings, str):
        return declared.meanings.split()
    labels: Any = document
    for key in declared.meanings:
        labels = labels[key]
    return [str(label) for label in labels]


def _index_coordinate(axis: str, length: int, declared: _Index) -> _Variable:
    """Build an axis carrying the position along it, 0..n-1."""
    attributes: dict[str, _AttributeValue] = {"long_name": declared.long_name}
    if declared.comment is not None:
        attributes["comment"] = declared.comment
    return _Variable(np.arange(length, dtype=np.int32), (axis,), attributes)


def _global_attributes(text: str, stored: dict[str, Any]) -> dict[str, _AttributeValue]:
    """Build the whole file's attributes: the JSON document, plus what it says.

    The document is the analysis file's own record, unchanged from the `.npz` layout
    and still the only one `read` consults. Beside it are two conveniences for a
    reader that never decodes JSON: a cheap header, so it can tell what the file
    is and refuse a version it does not know, and every scalar the document
    holds as an attribute of its own.

    `source` is CF's own name for what produced a file, so it keeps that
    spelling. It is derived from `provenance.core_version`, which is a separate
    attribute carrying the bare version.
    """
    # Every attribute but the document is read out of `stored`, the parsed
    # text, not the in-memory document, so they are the same values the
    # document publishes. The in-memory document still holds numpy scalars and
    # tuples where the file holds plain numbers and JSON lists, and a second
    # encoding of those would be a second chance to disagree with the first.
    # The text itself uses `json.dumps`'s default `ensure_ascii=True`, and that
    # matters. A netCDF text attribute is bytes, and a consumer takes it as
    # characters without being told an encoding (MATLAB's `ncreadatt` and R's
    # `ncatt_get` both do). Escaping every non-ASCII character to `\uXXXX`
    # makes those the right characters, including the lone surrogate an
    # undecodable Windows file name becomes in Python, which has no UTF-8 form.
    return {
        "Conventions": _CONVENTIONS,
        "title": _TITLE,
        "source": f"fmri-qa-core {stored['provenance']['core_version']}".rstrip(),
        # The same number the document carries, so a reader can check it
        # without JSON.
        "schema_version": np.int32(stored["schema_version"]),
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
    """Convert every recorded field of one document section to an attribute.

    Each attribute is named for its document path. One encoder serves every
    section, so the kind-to-type table is stated once. A nested object (the
    `psf` block of `curves`, the `roi` box of `images`) flattens into the name
    (`curves.psf.fwhm`, `images.roi.row0`).

    A `null` field is skipped (see the module docstring).
    """
    return {
        path: _attribute(path, value)
        for path, value in _leaves(section, document[section])
    }


def _leaves(prefix: str, mapping: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield every recorded value under `mapping`, by dotted path from `prefix`.

    A nested object yields its own leaves under its key, not itself, and a
    `null` yields nothing (see `_section_attributes`).
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
    """Convert one validated JSON value to the netCDF attribute that holds it.

    Bools are matched before ints because `bool` is an `int` in Python. A bool
    is not published as an int, because a verdict should not be a number the
    reader has to know is a verdict.

    A list of numbers is the vector of its element type, and a list of strings is
    one space-separated NC_CHAR (no NC_STRING; see the module docstring).

    Raises
    ------
    ValueError
        If an integer is outside NC_INT, or the value is of a kind no attribute
        can hold.
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
    """Convert an integer to NC_INT, refusing rather than wrapping on overflow.

    Validation bounds counts below but not above, so a count past NC_INT is a
    valid analysis file that this layout cannot publish faithfully.
    """
    if not _INT32.min <= value <= _INT32.max:
        raise ValueError(f"{name} is {value}, which does not fit a netCDF integer")
    return np.int32(value)


def _escaped(text: str) -> str:
    """Convert one string to the NC_CHAR text a reader is handed.

    netCDF4 writes a `str` attribute as the UTF-8 bytes of NC_CHAR, and ASCII
    and any other encodable text pass through unchanged. The one string with no
    UTF-8 form, the lone surrogate an undecodable byte in a Windows file name
    becomes in Python, is escaped instead of failing the save. The document
    beside it still spells the name exactly, and `load_analysis` reads that.
    """
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _variable(
    name: str,
    array: Member,
    dimensions: dict[str, int],
    auxiliary: dict[str, str],
) -> _Variable:
    """Convert one array to a netCDF variable, registering the axes it lies along.

    `dimensions` is extended in place with any axis this array is the first to
    fix, and checked against it for any axis already fixed. So two variables
    declared over one dimension must agree on its length, or neither is written.
    """
    layout = _LAYOUT.get(name)
    if layout is None:
        raise ValueError(f"{name} is not an array this analysis file layout declares")
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
    """Name the arrays that label this variable's axes, space-separated.

    A variable never names itself. `curves.time` is the seconds along the frame
    axis, and an array pointing at itself would say nothing.
    """
    return " ".join(
        auxiliary[axis]
        for axis in dimensions
        if axis in auxiliary and auxiliary[axis] != name
    )


def _stored(name: str, array: Member) -> NDArray[Any]:
    """Convert an array to the dtype the file holds it as.

    Masks become 0/1 `u1`, because netCDF has no boolean type. A measured array
    keeps its own float64. Any other dtype is refused, not silently narrowed,
    because a file format should not quietly store a QA number at half its
    precision.
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


def write(content: _NetcdfContent, path: Path) -> None:
    """Write `content` to `path` as a netCDF-4 file and close it.

    Exactly one file is written. The handle is closed before this returns, so a
    caller can fsync and rename the result (how `save_analysis` is atomic;
    Windows will not rename an open file).

    Array variables are deflated with a `fletcher32` checksum, and the float ones
    are shuffled first (see the module docstring for the cost and saving).
    Coordinates get no filters and are written first so `ncdisp` lists axes
    before the arrays along them.
    """
    # Imported here because netCDF4 loads libhdf5 and libnetcdf, and a bare
    # `--version` or `--help` should not pay for a writer. The pipeline defers
    # `scipy.spatial` for the same reason.
    import netCDF4

    with (
        netCDF4.Dataset(path, "w", format=_FORMAT) as dataset,
        warnings.catch_warnings(),
    ):
        # netCDF4 1.7.4 reshapes the incoming array by assigning to `.shape`
        # whenever it has more than one dimension (it compares the wanted shape,
        # a list, against `data.shape`, a tuple, so they never match), and NumPy
        # 2.5 deprecated setting `.shape`. There is no way to hand it an array
        # it will not reshape. The warning names a line in a Cython module that
        # a caller cannot act on, so it is dropped here, not at every caller of
        # `save_analysis`.
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

    A filtered variable costs HDF5 a fixed couple of kilobytes of filter and
    chunk-index metadata whatever it holds. Eleven coordinates deflated and
    checksummed add 27,265 B to the test phantom's analysis file (20%), against 3,322 B
    (2.5%) stored contiguously and plain. The checksum is not missed, because
    `read` skips coordinates, so damage to an axis cannot reach a loaded analysis file.

    An empty axis (`hull_vertex` for a mask too small to outline) stays chunked,
    since HDF5 has no contiguous layout for a dataset with no elements and
    netCDF refuses to create one. There is nothing to store either way, so the
    fallback costs only the chunk index.
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
        # By name ("float64", "uint8"), which is also how netCDF spells a type.
        variable.data.dtype.name,
        variable.dimensions,
        zlib=True,
        complevel=_COMPLEVEL,
        # The byte shuffle is for the float arrays. A single-byte mask has
        # nothing to interleave, so shuffling it would only cost time.
        shuffle=variable.data.dtype.itemsize > 1,
        fletcher32=True,
    )
    stored.setncatts(variable.attributes)
    stored[...] = variable.data


def read(path: Path) -> tuple[str, dict[str, NDArray[Any]]]:
    """Read the JSON text and every stored array from a netCDF analysis file.

    Masks come back as `bool`. The global attributes and coordinate variables
    are derived copies and are not read (a provenance string with no UTF-8 form
    is lossy in the attributes). The document and the dotted arrays are the one
    record read back.

    Raises
    ------
    InvalidAnalysisFileError
        If the file is not readable as netCDF-4, carries no `document`
        attribute, or carries one that is not text.
    """
    # Imported here for the same reason as in `write`.
    import netCDF4

    try:
        with netCDF4.Dataset(path, "r") as dataset:
            # Plain ndarrays, not masked ones. netCDF4 masks `_FillValue` and
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
                # `compose` has no field for. It is skipped by that rule, not
                # by a list of names, so an axis added to the layout is
                # excluded by the same reasoning that included it.
                if name not in dataset.dimensions
            }
    except InvalidAnalysisFileError:
        raise
    except Exception as exc:
        # Broad on purpose, and only around the library calls. netCDF4 answers a
        # malformed file with an `OSError` carrying HDF5's error text, but a
        # fuzzed one also reaches `RuntimeError`, `IndexError` and `MemoryError`
        # through the same call. A list of a C library's failure modes goes
        # stale the next time it is rebuilt, and every one of them means the
        # same thing here.
        raise InvalidAnalysisFileError(path, f"unreadable netCDF file: {exc}") from exc
    return text, arrays


def _document_text(dataset: "Dataset", path: Path) -> str:
    """Read the JSON document carried by the file's `document` attribute."""
    if _DOCUMENT not in dataset.ncattrs():
        raise InvalidAnalysisFileError(path, "not an fmri-qa analysis file")
    text = dataset.getncattr(_DOCUMENT)
    if not isinstance(text, str):
        raise InvalidAnalysisFileError(path, f"the {_DOCUMENT} attribute is not text")
    return text


def _restored(variable: "Variable[Any]") -> NDArray[Any]:
    """Restore one stored variable to the array that was written.

    A variable carrying the CF flag markers `_mask_attributes` writes is a
    boolean mask stored as 0/1 bytes, and comes back `bool`. Everything else is
    handed over as stored, for `compose` to narrow.
    """
    data: NDArray[Any] = np.asarray(variable[...])
    if _FLAG_VALUES in variable.ncattrs():
        return np.asarray(data != 0, dtype=np.bool_)
    return data
