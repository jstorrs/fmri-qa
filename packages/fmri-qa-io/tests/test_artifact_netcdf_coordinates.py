"""The dimensions and coordinate variables of the stored file, and how a foreign
reader sees the rest of it.

CF (section 1.3) spells an axis's values as a 1-D variable named for the
dimension. Without one, xarray reports "dimensions without coordinates" and a
plot has no abscissa. With one, two artifacts can align. They are derived on
write and never read back, like the `measurements.*` attributes, so these tests
read the file instead of the package.
"""

import warnings
from dataclasses import replace

# `netCDF4` is imported here, not in each test. The "without a warning" tests
# run under `simplefilter("error")`, and importing the wheel raises its own
# Cython `RuntimeWarning`, so every test must enter that filter with the library
# already loaded. What the filter can catch is what opening the artifact does
# and nothing else.
import netCDF4
import numpy as np
import pytest

import fmriqa as q
import fmriqa_io
from fmriqa.analysis.serialize.decompose import decompose
from fmriqa_io.artifact import netcdf

# The CF marker the writer puts on a mask. Spelled out, not imported, so
# changing it means editing both places.
_FLAG_VALUES = np.array([0, 1], dtype=np.uint8)


# The axes the layout publishes. Spelled out, not read back from the file,
# because these names are the contract a foreign reader gets. Each is also the
# name of the coordinate variable carrying that axis's values.
_DIMENSIONS = {
    "frame",
    "frequency",
    "image_axis",
    "roi_width",
    "psf_direction",
    "psf_lag",
    "psf_model_sample",
    "row",
    "col",
    "hull_vertex",
    "hull_coord",
}


def _declared(path) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    """Each variable's dimensions and each dimension's length, read as netCDF."""
    with netCDF4.Dataset(str(path)) as dataset:
        declared = {name: var.dimensions for name, var in dataset.variables.items()}
        lengths = {name: len(dim) for name, dim in dataset.dimensions.items()}
    return declared, lengths


def test_every_stored_array_is_declared_over_named_dimensions(
    tmp_path, artifact
) -> None:
    """The file says which axis each array lies along, not just its length."""
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, lengths = _declared(saved)

    assert set(declared) == set(decompose(artifact)[1]) | _DIMENSIONS
    assert all(dimensions for dimensions in declared.values())
    assert lengths["frame"] == artifact.provenance.n_frames
    assert (lengths["row"], lengths["col"]) == artifact.images.signal.shape


def test_curves_along_one_axis_share_one_dimension(tmp_path, artifact) -> None:
    """Sharing a dimension is the file's claim that two arrays share an axis.

    A reader that opens this in xarray gets the per-frame traces aligned on
    `frame`. A bag of equal-length vectors would leave it guessing.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, _ = _declared(saved)

    assert declared["curves.roi_signal"] == declared["curves.time"] == ("frame",)
    assert declared["curves.spectrum_hz"] == declared["curves.spectrum_magnitude"]
    assert declared["curves.translation"] == ("frame", "image_axis")
    assert declared["images.sfnr"] == declared["images.phantom_mask"] == ("row", "col")
    assert declared["images.ghost.pe_ghost"] == ("row", "col")
    assert declared["curves.weisskoff.cv"] == declared["curves.weisskoff.rdc"]


def test_axes_that_only_happen_to_match_stay_separate(tmp_path, artifact) -> None:
    """Three length-2 axes have three meanings, so they are three dimensions.

    `image_axis` is (row, col) in array order, `psf_direction` is (PE, RO) in PSF
    curve order (or axis0, axis1 with no PE axis), and `hull_coord` is the
    hull's (x, y) plot order. One shared dimension for all three, because they
    are all 2 long, would publish a relationship that does not exist.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, lengths = _declared(saved)

    paired = ("image_axis", "psf_direction", "hull_coord")
    assert all(lengths[axis] == 2 for axis in paired)
    assert declared["curves.translation"][1] == "image_axis"
    assert declared["curves.psf.empirical"][0] == "psf_direction"
    assert declared["images.phantom_hull"][1] == "hull_coord"
    # and the two PSF abscissas are not each other either
    assert declared["curves.psf.empirical"][1] != declared["curves.psf.model"][1]


# What each axis's coordinate holds. A position axis carries the position as
# NC_INT. An axis the artifact already publishes values for carries those, in
# the curve's own dtype.
_COORDINATE_DTYPES = {
    "frame": np.int32,
    "frequency": np.float64,
    "image_axis": np.int32,
    "roi_width": np.float64,
    "psf_direction": np.int32,
    "psf_lag": np.int32,
    "psf_model_sample": np.int32,
    "row": np.int32,
    "col": np.int32,
    "hull_vertex": np.int32,
    "hull_coord": np.int32,
}

# The axes whose coordinate is the index along them, and the three length-2
# axes whose two positions are named instead.
_INDEX_AXES = ("frame", "row", "col", "psf_lag", "psf_model_sample", "hull_vertex")
_LABEL_AXES = {"image_axis": "row col", "psf_direction": "PE RO", "hull_coord": "x y"}


def _axes(path) -> dict[str, tuple[np.ndarray, dict[str, object]]]:
    """Each dimension's own coordinate variable: its values and its attributes."""
    with netCDF4.Dataset(str(path)) as dataset:
        dataset.set_auto_mask(False)
        return {
            axis: (
                np.asarray(dataset[axis][...]),
                {
                    name: dataset[axis].getncattr(name)
                    for name in dataset[axis].ncattrs()
                },
            )
            for axis in dataset.dimensions
        }


def test_every_dimension_carries_a_coordinate_variable(tmp_path, artifact) -> None:
    """One 1-D variable per axis, named for it and as long as it is.

    A reader finds every axis resolved, not eleven dimensions to number itself.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    _, lengths = _declared(saved)
    axes = _axes(saved)
    with netCDF4.Dataset(str(saved)) as dataset:
        declared = {
            axis: (dataset[axis].dimensions, dataset[axis].dtype)
            for axis in dataset.dimensions
        }

    assert set(declared) == _DIMENSIONS
    for axis, (dimensions, dtype) in declared.items():
        assert dimensions == (axis,), axis
        assert dtype == _COORDINATE_DTYPES[axis], axis
    assert {axis: len(values) for axis, (values, _) in axes.items()} == lengths
    assert all("long_name" in attributes for _, attributes in axes.values())


def test_an_index_axis_counts_from_zero(tmp_path, artifact) -> None:
    """Where the axis is a position, the coordinate is that position."""
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)

    for axis in _INDEX_AXES:
        values, _ = axes[axis]
        assert np.array_equal(values, np.arange(len(values), dtype=np.int32)), axis


def test_a_value_axis_is_the_curve_it_labels(tmp_path, artifact) -> None:
    """Two axes have real values already, and the coordinate is those values.

    The curves stay under their own dotted names. The coordinate is a second
    spelling, because the dimension's name is the only one CF reads as the axis.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)
    _, arrays = decompose(artifact)

    assert np.array_equal(axes["frequency"][0], arrays["curves.spectrum_hz"])
    assert np.array_equal(axes["roi_width"][0], arrays["curves.weisskoff.roi_sizes"])
    assert axes["frequency"][1]["units"] == "Hz"
    # and the curves themselves are still there to be read under their own names
    assert {"curves.spectrum_hz", "curves.weisskoff.roi_sizes"} <= set(arrays)


def test_the_frame_axis_counts_the_way_the_artifact_counts(tmp_path, artifact) -> None:
    """Frame 0 is the first *analyzed* volume, not the first acquired one.

    Every frame index counts from the trimmed series (see `Provenance`), so
    `measurements.outlier_worst_frame` indexes this coordinate directly. The
    acquired volume number is the index plus `provenance.n_trimmed`, so the
    coordinate's comment names the offset.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    frame, attributes = _axes(saved)["frame"]

    assert np.array_equal(frame, np.arange(artifact.provenance.n_frames))
    assert artifact.provenance.n_trimmed  # the fixture really does drop warm-up
    worst = artifact.measurements.outlier_worst_frame
    assert frame[worst] == worst
    assert int(np.argmax(artifact.curves.outlier_fraction)) == worst
    # `getncattr` is typed as returning anything, so narrow to text first.
    assert "n_trimmed" in str(attributes["comment"])


def test_a_named_axis_carries_its_labels_as_flags(tmp_path, artifact) -> None:
    """(row, col), (PE, RO) and (x, y) are named as flagged ints, not strings.

    NC_STRING is netCDF-4-only and handled poorly by Octave's netCDF package and
    older readers. The flag vocabulary already avoids it for masks, so these
    axes do too.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)

    for axis, meanings in _LABEL_AXES.items():
        values, attributes = axes[axis]
        flags = np.asarray(attributes["flag_values"])
        assert np.array_equal(values, [0, 1]), axis
        assert np.array_equal(flags, [0, 1]), axis
        assert flags.dtype == np.int32, axis
        assert attributes["flag_meanings"] == meanings, axis


def test_every_per_frame_variable_points_at_the_time_axis(tmp_path, artifact) -> None:
    """Both the frame index and the seconds are published.

    `curves.time` cannot be the `frame` coordinate, since a coordinate variable is
    named for its dimension. It is an auxiliary coordinate instead, so xarray
    gives `ds["curves.roi_signal"].coords["curves.time"]`. The two PSF sample
    axes work the same way, and their lags are also 2-D.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, _ = _declared(saved)
    with netCDF4.Dataset(str(saved)) as dataset:
        labelled = {
            name: dataset[name].getncattr("coordinates")
            for name in declared
            if "coordinates" in dataset[name].ncattrs()
        }

    per_frame = {
        name
        for name, dimensions in declared.items()
        if dimensions[:1] == ("frame",) and name not in _DIMENSIONS
    }
    assert len(per_frame) > 1
    for name in per_frame - {"curves.time"}:
        assert labelled[name] == "curves.time", name
    # An array never names itself as its own label.
    assert "curves.time" not in labelled
    assert labelled["curves.psf.empirical"] == "curves.psf.displacement"
    assert labelled["curves.psf.model"] == "curves.psf.model_x"
    assert "curves.psf.displacement" not in labelled


def test_the_coordinates_are_stored_plain(tmp_path, artifact) -> None:
    """No filters and no chunking on eleven short vectors of ascending numbers.

    A deflated, checksummed variable costs HDF5 a couple of kilobytes of filter
    and chunk-index metadata whatever it holds. The eleven axes add 3,322 B to
    the phantom's artifact stored plain, against 27,265 B filtered. The checksum
    is not needed because nothing reads them back; `load_artifact` rebuilds the
    artifact from the arrays and the document.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        stored = {
            axis: (dataset[axis].filters(), dataset[axis].chunking())
            for axis in dataset.dimensions
        }

    assert set(stored) == _DIMENSIONS
    for axis, (filters, chunking) in stored.items():
        assert not any(filters.values()), (axis, filters)
        assert chunking == "contiguous", axis


def test_the_reader_ignores_the_coordinate_variables(tmp_path, artifact) -> None:
    """Coordinates are derived on the way out and ignored on the way in.

    The dotted arrays and JSON document stay the single source of truth, so
    `compose` receives what `decompose` produced and a coordinate cannot become
    a second answer.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    _, arrays = netcdf.read(saved)

    assert set(arrays) == set(decompose(artifact)[1])
    assert not set(arrays) & _DIMENSIONS
    loaded = fmriqa_io.load_artifact(saved)
    assert np.array_equal(loaded.curves.time, artifact.curves.time)
    assert np.array_equal(loaded.curves.spectrum_hz, artifact.curves.spectrum_hz)
    assert np.array_equal(loaded.images.phantom_hull, artifact.images.phantom_hull)


def test_an_artifact_without_ghost_regions_still_carries_every_axis(
    tmp_path, artifact
) -> None:
    """The one optional section owns no axis, so omitting it loses none.

    `images.ghost` is the only part of an artifact that can be absent. Its four
    masks lie along `row`/`col` like every other image, so a ghost-less artifact
    still declares and resolves all eleven axes. The rest of the `replace` is
    what "no PE axis resolved" means elsewhere: the ghost regions, `pe_axis`,
    `pe_label`, `fwhm_pe`/`fwhm_ro` and the PSF labels go together.
    """
    without = replace(
        artifact,
        images=replace(artifact.images, ghost=None),
        measurements=replace(
            artifact.measurements,
            pe_axis=None,
            pe_label="?",
            fwhm_pe=None,
            fwhm_ro=None,
        ),
        curves=replace(
            artifact.curves,
            psf=replace(artifact.curves.psf, labels=("axis0", "axis1")),
        ),
    )
    saved = fmriqa_io.save_artifact(without, tmp_path / "ng.qa.nc")
    declared, _ = _declared(saved)

    assert fmriqa_io.load_artifact(saved).images.ghost is None
    assert not [name for name in declared if name.startswith("images.ghost.")]
    axes = _axes(saved)
    assert set(axes) == _DIMENSIONS
    # The direction labels belong to this artifact. "PE RO" here would contradict
    # its own document.
    _, attributes = axes["psf_direction"]
    assert attributes["flag_meanings"] == "axis0 axis1"


def test_encode_omits_an_axis_whose_values_are_not_stored(artifact, encode) -> None:
    """A coordinate is derived or left out, never invented.

    `encode` takes whatever arrays it is handed. An axis whose values are in an
    array that is not among them gets no coordinate, and nothing points at a
    label the file lacks.
    """
    document, arrays = decompose(artifact)
    without = {
        k: v
        for k, v in arrays.items()
        if k not in ("curves.spectrum_hz", "curves.time")
    }
    content = encode(document, without)

    assert {"frequency", "frame"} <= set(content.dimensions)
    assert "frequency" not in content.coordinates
    assert "frame" in content.coordinates  # an index needs nothing but a length
    assert "coordinates" not in content.variables["curves.roi_signal"].attributes


def test_encode_refuses_an_axis_with_no_coordinate_declared(
    artifact, monkeypatch, encode
) -> None:
    """An axis the coordinate table has never heard of stops the write.

    The other side of the test above: an axis added to the variable layout and
    forgotten here is refused by name, not written as an unresolvable dimension.
    """
    document, arrays = decompose(artifact)
    monkeypatch.delitem(netcdf._COORDINATES, "frame")
    with pytest.raises(ValueError, match="frame axis has no coordinate"):
        encode(document, arrays)


def test_every_axis_the_layout_uses_has_a_coordinate_declared() -> None:
    """Two hand-written tables, one contract: an axis needs an entry in both.

    The dimensions a variable is declared over and the values a reader gets for
    them are both published claims. Neither table is derived from the other, so
    a mismatch is caught here, not by a reader.
    """
    used = {axis for layout in netcdf._LAYOUT.values() for axis in layout.dimensions}
    assert used == set(netcdf._COORDINATES) == _DIMENSIONS


def test_masks_are_stored_as_cf_flagged_bytes(tmp_path, artifact) -> None:
    """netCDF has no boolean, so a mask is 0/1 bytes that say what they mean.

    The flags let a reader with no fmriqa knowledge rebuild a `bool` array and
    learn that 1 is inside the phantom.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        dataset.set_auto_mask(False)
        mask = dataset["images.phantom_mask"]
        stored = np.asarray(mask[...])
        attributes = {name: mask.getncattr(name) for name in mask.ncattrs()}

    assert stored.dtype == np.uint8
    assert set(np.unique(stored)) <= {0, 1}
    assert np.array_equal(attributes["flag_values"], _FLAG_VALUES)
    assert attributes["flag_meanings"] == "outside inside"
    assert fmriqa_io.load_artifact(saved).images.phantom_mask.dtype == np.bool_


def test_the_units_a_reader_is_told_are_the_ones_that_are_certain(
    tmp_path, artifact
) -> None:
    """Seconds, hertz and percent are labeled; a unit the file cannot know is not.

    The PSF abscissas are mm or voxels depending on what the header gave, so
    they carry a long name and no `units` rather than a guess.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        attributes = {
            name: set(variable.ncattrs())
            for name, variable in dataset.variables.items()
        }
        units = {
            name: dataset[name].getncattr("units")
            for name in ("curves.time", "curves.spectrum_hz", "curves.shear_pct")
        }

    assert units == {
        "curves.time": "s",
        "curves.spectrum_hz": "Hz",
        "curves.shear_pct": "percent",
    }
    assert "units" not in attributes["curves.psf.displacement"]
    assert all("long_name" in value for value in attributes.values())


def test_every_array_is_compressed_and_checksummed(tmp_path, artifact) -> None:
    """Deflate and a Fletcher-32 checksum on every array, floats shuffled.

    The coordinate variables are excluded (see
    `test_the_coordinates_are_stored_plain`). They are a few hundred bytes, and a
    filter pipeline costs more metadata than they hold.

    The checksum is the one the zip container gave the `.npz` for free and
    netCDF-3 would have dropped. Without it, a flipped byte in an image reads
    back as a plausible number.

    The test asserts that `shuffle` is on for the floats and off for the byte
    masks, not that it shrinks this file, because it does not here. The phantom
    is stored as `uint16`, so its mean image has only a few hundred distinct
    float64 values and plain deflate finds runs the shuffle breaks up: 138,250 B
    with the filter against 134,219 B without. Shuffle stays on for real
    acquisitions, whose noisy float64 mean and SFNR images have a distinct value
    in nearly every voxel, where it saves around 13%.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        filters = {
            name: (variable.filters(), variable.dtype)
            for name, variable in dataset.variables.items()
            if name not in dataset.dimensions
        }

    assert filters  # a layout with no variables would pass every claim below
    for name, (applied, dtype) in filters.items():
        assert applied["zlib"] and applied["complevel"] == 4, name
        assert applied["fletcher32"], name
        assert applied["shuffle"] == (dtype != np.uint8), name


def test_loaded_arrays_are_plain_native_endian_ndarrays(tmp_path, artifact) -> None:
    """What a caller gets is an ordinary array, not a masked or byte-swapped one.

    netCDF4 masks `_FillValue` and out-of-range values unless told not to, and a
    `MaskedArray` reaching `compose` would make a fill value look like a
    measurement. Byte order matters the same way: an artifact written on one
    machine must arrive as numbers another can compute with directly.
    """
    loaded = fmriqa_io.load_artifact(
        fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    )
    for array in (
        loaded.images.signal,
        loaded.images.phantom_mask,
        loaded.curves.time,
        loaded.curves.translation,
    ):
        assert type(array) is np.ndarray
        assert not isinstance(array, np.ma.MaskedArray)
        assert array.dtype.byteorder in ("=", "|")


def test_a_flipped_byte_inside_an_array_is_refused(tmp_path, artifact, encode) -> None:
    """A corrupted array fails to read rather than reading as wrong numbers.

    The file is nearly all array: one variable of incompressible noise, whose
    chunk is by far the largest thing in it, so the byte flipped in the middle
    lands inside that chunk whatever HDF5 does with the metadata. The rest is a
    few tens of kilobytes of fixed overhead, the document and its attributes,
    and the `row`/`col` axes, so the array is made large enough to dwarf it.
    """
    noise = np.random.default_rng(0).standard_normal((256, 256))
    document, _ = decompose(artifact)
    content = encode(document, {"images.signal": noise})
    path = tmp_path / "noise.nc"
    netcdf.write(content, path)
    raw = bytearray(path.read_bytes())
    assert len(raw) < noise.nbytes * 1.6  # the array really is most of the file

    raw[len(raw) // 2] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(q.InvalidArtifactError):
        netcdf.read(path)


def test_a_flipped_byte_anywhere_is_refused_or_harmless(tmp_path, artifact) -> None:
    """However a stored artifact is damaged, `load_artifact` is what answers.

    A reader of a QA archive must not have to catch whichever exception an HDF5
    error, a JSON parse or a shape check raised. One type means "this file is
    not a readable artifact", and nothing else escapes. The offsets are
    landmarks, not a random sweep, so the test is the same on every run: the
    signature, the superblock behind it, the stored document text, and the tail
    where the last chunk lies.
    """
    saved = fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc")
    whole = saved.read_bytes()
    document_at = whole.find(b'"schema_version"')
    assert document_at > 0  # the document is stored as plain text, so this finds it
    path = tmp_path / "damaged.nc"

    for offset in (0, 64, document_at + 8, len(whole) - 4096, len(whole) - 1):
        damaged = bytearray(whole)
        damaged[offset] ^= 0xFF
        path.write_bytes(bytes(damaged))
        try:
            loaded = fmriqa_io.load_artifact(path)
        except q.InvalidArtifactError:
            continue
        # A flip that lands in slack space changes nothing a reader can see.
        assert np.array_equal(loaded.images.sfnr, artifact.images.sfnr), offset


def test_an_artifact_with_no_hull_round_trips(tmp_path, artifact) -> None:
    """A phantom too small to outline stores an empty array, and reads back one.

    `_convex_hull` yields `(0, 2)` for a mask with no area (see
    `analysis/build.py`). netCDF-3 could not store that, since a zero-length
    dimension there is the unlimited one and a file may have only one. netCDF-4
    has ordinary zero-length dimensions.
    """
    images = replace(artifact.images, phantom_hull=np.zeros((0, 2)))
    saved = fmriqa_io.save_artifact(
        replace(artifact, images=images), tmp_path / "flat.qa.nc"
    )
    loaded = fmriqa_io.load_artifact(saved)

    assert loaded.images.phantom_hull.shape == (0, 2)
    _, lengths = _declared(saved)
    assert lengths["hull_vertex"] == 0
    assert np.array_equal(loaded.images.signal, artifact.images.signal)
    # and the axis still carries a coordinate variable, of no length
    with netCDF4.Dataset(str(saved)) as dataset:
        vertex = dataset["hull_vertex"]
        assert vertex.dimensions == ("hull_vertex",)
        assert np.asarray(vertex[...]).shape == (0,)


def test_xarray_opens_the_artifact_without_a_warning(tmp_path, artifact) -> None:
    """`xr.open_dataset` is the one-line path a notebook takes to an artifact."""
    saved = str(fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc"))
    # Imported here, before the filter. Importing either library under `error`
    # raises the netCDF4 wheel's own Cython `RuntimeWarning`, which no artifact
    # can fix and a test of the file must not trip on.
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with xr.open_dataset(saved) as dataset:
            dimensions = set(dataset.sizes)
            variables = set(dataset.data_vars)
            attributes = dict(dataset.attrs)
            sfnr = dataset["images.sfnr"].to_numpy()
            time = dataset["curves.time"]

    assert dimensions == _DIMENSIONS
    assert {"curves.weisskoff.cv", "images.ghost.pe_ghost"} <= variables
    assert attributes["schema_version"] == artifact.schema_version
    assert attributes["measurements.snr"] == artifact.measurements.snr
    assert np.allclose(sfnr, artifact.images.sfnr, equal_nan=True)
    # The dotted name survives, and so does the axis the trace lies along.
    assert time.dims == ("frame",)
    assert time.attrs["units"] == "s"


def test_xarray_hands_over_the_provenance_attributes(tmp_path, artifact) -> None:
    """What a notebook gets for free: the run's record, typed, without JSON.

    A vector attribute arrives as an array and text as a `str`, so
    `ds.attrs["provenance.voxel_mm"]` is a voxel size to compute with, and a
    non-ASCII scan name written as UTF-8 NC_CHAR comes back unchanged.
    """
    prov = replace(artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz")
    saved = str(
        fmriqa_io.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.nc")
    )
    # Imported before the filter, for the reason the test above gives.
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with xr.open_dataset(saved) as dataset:
            attributes = dict(dataset.attrs)

    assert isinstance(attributes["provenance.tr"], float)
    assert attributes["provenance.tr"] == prov.tr
    voxel = np.asarray(attributes["provenance.voxel_mm"])
    assert voxel.shape == (3,)
    assert np.array_equal(voxel, prov.voxel_mm)
    assert attributes["provenance.scan"] == "sujet_créé_Ω_頭部.nii.gz"


def test_xarray_resolves_every_axis_as_a_coordinate(tmp_path, artifact) -> None:
    """What the coordinate variables buy a notebook, in the library that uses them.

    Without them, `xr.open_dataset` reports "dimensions without coordinates" and
    a plot runs against 0..n-1. With them, every axis is an index xarray can
    select and align on, `curves.time` rides along as a second label on the
    per-frame traces, and `ds["curves.roi_signal"].plot()` draws against seconds.
    """
    saved = str(fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc"))
    # Imported before the filter, for the reason the test above gives.
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with xr.open_dataset(saved) as dataset:
            coordinates = set(dataset.coords)
            indexes = set(dataset.indexes)
            frame = dataset["frame"].to_numpy()
            trace = dataset["curves.roi_signal"]
            seconds = trace.coords["curves.time"].to_numpy()
            labelled = dataset["image_axis"].attrs["flag_meanings"]

    assert coordinates > _DIMENSIONS  # every axis, and `curves.time` besides
    assert "curves.time" in coordinates
    assert indexes == _DIMENSIONS  # each one selectable and alignable
    assert np.array_equal(frame, np.arange(artifact.provenance.n_frames))
    assert trace.dims == ("frame",)
    assert np.array_equal(seconds, artifact.curves.time)
    assert labelled == "row col"


def test_the_unidata_library_opens_the_artifact_without_a_warning(
    tmp_path, artifact
) -> None:
    """The C library itself: what `ncdump`, MATLAB and R read through.

    The container's main claim: a reader that has never heard of fmriqa can open
    the file, find the axes named, and turn the flagged bytes back into a mask.
    """
    saved = str(fmriqa_io.save_artifact(artifact, tmp_path / "scan.qa.nc"))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with netCDF4.Dataset(saved) as dataset:
            assert dataset.data_model == "NETCDF4"
            assert set(dataset.dimensions) == _DIMENSIONS
            mask = dataset["images.phantom_mask"]
            document = dataset.getncattr("document")
            snr = dataset.getncattr("measurements.snr")
            flags = np.asarray(mask.flag_values)
            stored = np.asarray(mask[:])

    assert '"schema_version"' in document
    assert snr == artifact.measurements.snr
    assert np.array_equal(flags, [0, 1])
    assert np.array_equal(stored != 0, artifact.images.phantom_mask)
