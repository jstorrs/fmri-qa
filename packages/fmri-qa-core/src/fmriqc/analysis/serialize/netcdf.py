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
  phantom's artifact is 134,928 B with it against 129,772 B without (+4%), a
  128x128x300 one 446,018 B against 342,658 B (+30%). Kept on regardless, and
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

Three things the layout does that a bag of arrays does not:

* **Dimensions are named and shared.** Every per-frame trace is declared over
  one `frame` dimension, both spectrum traces over `frequency`, every image over
  `row`/`col` -- so a reader that opens the file sees which arrays lie along the
  same axis instead of having to infer it from equal lengths. Two axes that
  merely happen to be the same size stay separate: `image_axis` is (row, col) in
  array order and `psf_direction` is (PE, RO) in the order the PSF curves use,
  and `hull_coord` is the hull's (x, y) *plot* order -- three different meanings
  that are all length 2, and conflating them would publish a relationship that
  is not there. Everything sits in the root group and nothing in a subgroup:
  `xr.open_dataset` sees only the root group, and Octave's group support is
  uneven, so a group would cost readers more than the tidiness is worth.
* **Boolean masks become `u1`.** netCDF-4 has no boolean type either, so each
  mask is stored as 0/1 bytes marked in CF style (`flag_values`,
  `flag_meanings`), which is what makes the bytes self-describing enough to turn
  back into `bool` on read -- the artifact in memory is unchanged either way.
* **Units and long names where they are certain.** Seconds, hertz, percent and
  dimensionless ratios are labelled; anything whose unit depends on the artifact
  (the PSF abscissas, in mm or voxels per `curves.psf.unit`) or that has no unit
  at all (raw image intensity) is left unlabelled rather than guessed at.

**Every scalar measurement is also a global attribute**, named for its document
path (`measurements.snr`, `measurements.ghost_pct`), so no reader has to decode
JSON to get a number -- `ncdisp` lists them all and `ncreadatt` hands one over.
A float is an NC_DOUBLE, an integer an NC_INT, a bool an NC_UBYTE 0 or 1, a
closed-set string NC_CHAR. A measurement the document spells `null` gets **no
attribute at all**, and that absence is the encoding: the document distinguishes
a NaN ("the estimator could not resolve this") from a null ("the quantity does
not apply here"), an attribute cannot be null, and writing NaN for both would
collapse the distinction. So a NaN attribute means what a NaN measurement means,
and a missing one means the other thing. These attributes are a convenience for
a foreign reader and nothing else: `read` never consults them, and the JSON
document stays the single source of truth for `load_artifact`, so the two can
only disagree if the document does -- the attributes are derived from its text.

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
from collections.abc import Mapping
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

# What each scalar measurement's own global attribute is called: the document
# path it came from, so `measurements.snr` in the file is `measurements.snr` in
# the document and in this package's vocabulary.
_MEASUREMENTS = "measurements"

# The rest of the global attributes, for a reader that never decodes the JSON.
_CONVENTIONS = "CF-1.10"
_TITLE = "fmri-qa phantom fMRI quality-assurance artifact"

# The range NC_INT holds, which every integer measurement has to fit.
_INT32 = np.iinfo(np.int32)

# An attribute value in the forms this layout writes: text, the numeric scalars
# a measurement (or `schema_version`) becomes, and the `u1` pair marking a mask.
type _AttributeValue = str | np.int32 | np.float64 | np.uint8 | NDArray[np.uint8]

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
    one dimension at two lengths, a measurement no attribute can hold -- on the
    near side of opening a file, so a refusal cannot leave a partly written one
    behind.
    """

    dimensions: dict[str, int]
    variables: dict[str, _Variable]
    attributes: dict[str, _AttributeValue]


def encode(document: dict[str, Any], arrays: Mapping[str, Member]) -> NetcdfContent:
    """Lay out an artifact's document and arrays as a netCDF-4 file.

    Raises:
        ValueError: If an array is not one this layout declares, disagrees with
            its declared rank, or claims a dimension another array has already
            fixed at a different length; or if a scalar measurement is of a kind
            no netCDF attribute can hold.
    """
    dimensions: dict[str, int] = {}
    variables: dict[str, _Variable] = {}
    for name, array in arrays.items():
        variables[name] = _variable(name, array, dimensions)
    return NetcdfContent(
        dimensions=dimensions,
        variables=variables,
        attributes=_global_attributes(document),
    )


def _global_attributes(document: dict[str, Any]) -> dict[str, _AttributeValue]:
    """The whole file's attributes: the JSON document, plus what it says.

    The document is the artifact's own record, unchanged from the `.npz` layout
    and still the only one `read` consults. Beside it ride two conveniences for
    a reader that never decodes JSON: a cheap header, so it can tell what the
    file is and refuse a version it does not know, and every scalar measurement
    as an attribute of its own.
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
    # The measurement attributes are read back out of the text rather than taken
    # from `document` itself, so they are by construction the same values the
    # document publishes: the in-memory document still holds numpy scalars where
    # the file holds plain numbers, and a second encoding of those would be a
    # second chance to disagree with the first.
    stored = json.loads(text)
    core_version = str(document["provenance"].get("core_version") or "")
    return {
        "Conventions": _CONVENTIONS,
        "title": _TITLE,
        "source": f"fmri-qa-core {core_version}".rstrip(),
        # The same number the document carries, hoisted out so a reader can
        # check it without JSON.
        "schema_version": np.int32(document["schema_version"]),
        **_measurement_attributes(stored.get(_MEASUREMENTS) or {}),
        _DOCUMENT: text,
    }


def _measurement_attributes(
    measurements: dict[str, Any],
) -> dict[str, _AttributeValue]:
    """Every resolved scalar measurement as its own global attribute.

    A `null` measurement is skipped rather than written as anything: see the
    module docstring -- absence is how "the quantity does not apply" is spelled,
    because NaN already means "the estimator could not resolve it".
    """
    attributes: dict[str, _AttributeValue] = {}
    for name, value in measurements.items():
        if value is None:
            continue
        attribute = f"{_MEASUREMENTS}.{name}"
        attributes[attribute] = _attribute(attribute, value)
    return attributes


def _attribute(name: str, value: Any) -> _AttributeValue:
    """One JSON scalar as the netCDF attribute that holds it.

    Bools are tested before ints because `bool` *is* an `int` in Python, and a
    verdict published as a number a reader has to know is a verdict would be
    exactly the kind of guessing the flagged masks avoid.

    Raises:
        ValueError: If the value is an integer outside NC_INT, a string that is
            not ASCII, or of a kind no attribute can hold.
    """
    if isinstance(value, bool):
        return np.uint8(value)
    if isinstance(value, int):
        if not _INT32.min <= value <= _INT32.max:
            raise ValueError(f"{name} is {value}, which does not fit a netCDF integer")
        return np.int32(value)
    if isinstance(value, float):
        return np.float64(value)
    if isinstance(value, str):
        # The three string measurements are closed vocabularies ("mm"/"vox",
        # "row"/"col"/"?"), so this cannot fire on an artifact this build
        # produces; it fires on a hand-edited document, where refusing beats
        # writing bytes a reader would have to guess an encoding for.
        if not value.isascii():
            raise ValueError(f"{name} is not ASCII: {value!r}")
        return value
    raise ValueError(f"{name} is a {type(value).__name__}, which no attribute can hold")


def _variable(name: str, array: Member, dimensions: dict[str, int]) -> _Variable:
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
    return _Variable(_stored(name, array), layout.dimensions, attributes)


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
    on the synthetic phantom and what it is expected to save on a real one.
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
        for name, variable in content.variables.items():
            _write_variable(dataset, name, variable)


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
    however the bytes were stored. The scalar measurements published as global
    attributes are deliberately *not* read: the document is the one record this
    package reads back, and reading both would be two answers to one question.

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
