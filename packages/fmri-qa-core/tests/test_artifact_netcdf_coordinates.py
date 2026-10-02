"""The dimensions and coordinate variables of the stored file, and how a foreign
reader sees the rest of it.

CF (section 1.3) spells an axis's values as a 1-D variable named for the
dimension itself. Without one a reader is told a trace lies along `frame` but
not where along it, and xarray reports "dimensions without coordinates"; with
one, a plot has an abscissa and two artifacts have something to align on. They
are derived when the file is written and never read back -- exactly like the
`measurements.*` attributes -- so these tests read the file rather than the
package.
"""

import warnings
from dataclasses import replace

# `netCDF4` is imported here and not in each test on purpose: the "without a
# warning" tests run under `simplefilter("error")`, and importing the wheel
# raises its own Cython `RuntimeWarning`. Taking the import at module scope
# means every test enters that filter with the library already loaded, so what
# the filter can catch is what opening the artifact does and nothing else.
import netCDF4
import numpy as np
import pytest

import fmriqc as q
from fmriqc.analysis.serialize import netcdf
from fmriqc.analysis.serialize.decompose import decompose

# The CF marker the writer puts on a mask, and what tells one apart on the way
# back in. Spelled out here rather than imported, so a change to the marker has
# to be made in both places deliberately.
_FLAG_VALUES = np.array([0, 1], dtype=np.uint8)


# The axes the layout publishes, as a reader meets them. Spelled out rather
# than read back off the file, since the point is that these names are the
# contract a foreign reader is handed -- and each of them is also the name of
# the coordinate variable carrying that axis's values.
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
    """The file says which axis each array lies along, not just how long it is."""
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, lengths = _declared(saved)

    assert set(declared) == set(decompose(artifact)[1]) | _DIMENSIONS
    assert all(dimensions for dimensions in declared.values())
    assert lengths["frame"] == artifact.provenance.n_frames
    assert (lengths["row"], lengths["col"]) == artifact.images.signal.shape


def test_curves_along_one_axis_share_one_dimension(tmp_path, artifact) -> None:
    """Sharing a dimension is the file's claim that two arrays share an axis.

    A reader that opens this in xarray gets the per-frame traces aligned on
    `frame` without being told which of them belong together; a bag of
    equal-length vectors would leave it guessing.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, _ = _declared(saved)

    assert declared["curves.roi_signal"] == declared["curves.time"] == ("frame",)
    assert declared["curves.spectrum_hz"] == declared["curves.spectrum_magnitude"]
    assert declared["curves.translation"] == ("frame", "image_axis")
    assert declared["images.sfnr"] == declared["images.phantom_mask"] == ("row", "col")
    assert declared["images.ghost.pe_ghost"] == ("row", "col")
    assert declared["curves.weisskoff.cv"] == declared["curves.weisskoff.rdc"]


def test_axes_that_only_happen_to_match_stay_separate(tmp_path, artifact) -> None:
    """Three length-2 axes, three meanings: none of them is the others.

    `image_axis` is (row, col) in array order, `psf_direction` is (PE, RO) in
    the order the PSF curves use (or axis0, axis1 when no PE axis resolved),
    and `hull_coord` is the hull's (x, y) plot order. Declaring them as one
    dimension because they are all 2 long would publish a relationship that is
    not there.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, lengths = _declared(saved)

    paired = ("image_axis", "psf_direction", "hull_coord")
    assert all(lengths[axis] == 2 for axis in paired)
    assert declared["curves.translation"][1] == "image_axis"
    assert declared["curves.psf.empirical"][0] == "psf_direction"
    assert declared["images.phantom_hull"][1] == "hull_coord"
    # and the two PSF abscissas are not each other either
    assert declared["curves.psf.empirical"][1] != declared["curves.psf.model"][1]


# What each axis's coordinate holds. An axis that is a position carries the
# position as NC_INT; an axis the artifact already publishes values for carries
# those values, in the dtype the curve itself has.
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

    This is the whole claim: a reader that opens the file finds every axis
    resolved, rather than eleven dimensions it has to number itself.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
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
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)

    for axis in _INDEX_AXES:
        values, _ = axes[axis]
        assert np.array_equal(values, np.arange(len(values), dtype=np.int32)), axis


def test_a_value_axis_is_the_curve_it_labels(tmp_path, artifact) -> None:
    """Two axes have real values already, and the coordinate is those values.

    The curves stay exactly where they are under their own dotted names: the
    coordinate is a second spelling of the same numbers, because the dimension's
    name is the only one CF reads as the axis.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)
    _, arrays = decompose(artifact)

    assert np.array_equal(axes["frequency"][0], arrays["curves.spectrum_hz"])
    assert np.array_equal(axes["roi_width"][0], arrays["curves.weisskoff.roi_sizes"])
    assert axes["frequency"][1]["units"] == "Hz"
    # and the curves themselves are still there to be read under their own names
    assert {"curves.spectrum_hz", "curves.weisskoff.roi_sizes"} <= set(arrays)


def test_the_frame_axis_counts_the_way_the_artifact_counts(tmp_path, artifact) -> None:
    """Frame 0 is the first *analyzed* volume, not the first acquired one.

    Every frame index in the artifact counts from the trimmed series (see
    `Provenance`), so `measurements.outlier_worst_frame` indexes this
    coordinate directly and the acquired volume number is the index plus
    `provenance.n_trimmed`. A reader that took the coordinate for an
    acquisition number would be wrong by the warm-up, so the offset is named in
    the coordinate's own comment rather than left to be inferred.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    frame, attributes = _axes(saved)["frame"]

    assert np.array_equal(frame, np.arange(artifact.provenance.n_frames))
    assert artifact.provenance.n_trimmed  # the fixture really does drop warm-up
    worst = artifact.measurements.outlier_worst_frame
    assert frame[worst] == worst
    assert int(np.argmax(artifact.curves.outlier_fraction)) == worst
    # `getncattr` is typed as returning anything at all, so the comment is
    # named as text before it is searched.
    assert "n_trimmed" in str(attributes["comment"])


def test_a_named_axis_carries_its_labels_as_flags(tmp_path, artifact) -> None:
    """(row, col), (PE, RO) and (x, y) are named as flagged ints, not strings.

    NC_STRING is a netCDF-4-only type that Octave's netCDF package and older
    readers handle poorly, and the flag vocabulary already says exactly this
    much for the masks -- so the three length-2 axes use it too.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)

    for axis, meanings in _LABEL_AXES.items():
        values, attributes = axes[axis]
        flags = np.asarray(attributes["flag_values"])
        assert np.array_equal(values, [0, 1]), axis
        assert np.array_equal(flags, [0, 1]), axis
        assert flags.dtype == np.int32, axis
        assert attributes["flag_meanings"] == meanings, axis


def test_every_per_frame_variable_points_at_the_time_axis(tmp_path, artifact) -> None:
    """The frame index is one answer; the seconds are the other, and both ride.

    `curves.time` cannot be the `frame` coordinate -- a coordinate variable is
    named for its dimension -- so it is named as an auxiliary coordinate
    instead, which is what makes xarray hand a reader
    `ds["curves.roi_signal"].coords["curves.time"]`. The two PSF sample axes
    work the same way, and their lags are 2-D on top of that.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
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
    and chunk-index metadata whatever it holds, which for these would be most
    of what they add: the eleven axes grow the phantom's artifact by 3,322 B
    stored plain, against 27,265 B filtered. The checksum is not missed,
    because nothing reads them back -- `load_artifact` rebuilds the artifact
    from the arrays and the document.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
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
    """Derived on the way out, and not a word of them on the way back in.

    The dotted arrays and the JSON document stay the single source of truth, so
    `compose` is handed exactly what `decompose` produced -- an axis it has no
    field for never reaches it, and a coordinate cannot become a second answer
    to a question the document already answers.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    _, arrays = netcdf.read(saved)

    assert set(arrays) == set(decompose(artifact)[1])
    assert not set(arrays) & _DIMENSIONS
    loaded = q.load_artifact(saved)
    assert np.array_equal(loaded.curves.time, artifact.curves.time)
    assert np.array_equal(loaded.curves.spectrum_hz, artifact.curves.spectrum_hz)
    assert np.array_equal(loaded.images.phantom_hull, artifact.images.phantom_hull)


def test_an_artifact_without_ghost_regions_still_carries_every_axis(
    tmp_path, artifact
) -> None:
    """The one optional section owns no axis, so nothing is lost when it is.

    `images.ghost` is the only part of an artifact that can be absent, and its
    four masks lie along `row`/`col` like every other image -- so a ghost-less
    artifact declares the same eleven axes and resolves all eleven. The rest of
    the `replace` is what "no PE axis resolved" means elsewhere in the artifact:
    the ghost regions, `pe_axis`, `pe_label`, `fwhm_pe`/`fwhm_ro`, and the PSF
    labels go together.
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
    saved = q.save_artifact(without, tmp_path / "ng.qa.nc")
    declared, _ = _declared(saved)

    assert q.load_artifact(saved).images.ghost is None
    assert not [name for name in declared if name.startswith("images.ghost.")]
    axes = _axes(saved)
    assert set(axes) == _DIMENSIONS
    # The direction labels are this artifact's, not a fixed vocabulary: a file
    # that said "PE RO" here would contradict its own document.
    _, attributes = axes["psf_direction"]
    assert attributes["flag_meanings"] == "axis0 axis1"


def test_encode_omits_an_axis_whose_values_are_not_stored(artifact, encode) -> None:
    """A coordinate is derived or left out; it is never invented.

    `encode` takes whatever arrays it is handed, and an axis whose values live
    in an array that is not among them gets no coordinate rather than a made-up
    one -- and nothing points at a label the file does not carry either.
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

    The failure the test above rules out, seen from the other side: an axis
    added to the variable layout and forgotten here is refused by name rather
    than written as a dimension a reader cannot resolve.
    """
    document, arrays = decompose(artifact)
    monkeypatch.delitem(netcdf._COORDINATES, "frame")
    with pytest.raises(ValueError, match="frame axis has no coordinate"):
        encode(document, arrays)


def test_every_axis_the_layout_uses_has_a_coordinate_declared() -> None:
    """Two hand-written tables, one contract: an axis needs an entry in both.

    The dimensions a variable is declared over and the values a reader is
    handed for them are both published claims, so neither table is derived from
    the other and adding an axis to one without the other is caught here rather
    than by a reader.
    """
    used = {axis for layout in netcdf._LAYOUT.values() for axis in layout.dimensions}
    assert used == set(netcdf._COORDINATES) == _DIMENSIONS


def test_masks_are_stored_as_cf_flagged_bytes(tmp_path, artifact) -> None:
    """netCDF has no boolean, so a mask is 0/1 bytes that say what they mean.

    The flags are what makes the file self-describing enough to reconstruct a
    `bool` array from it -- and what a reader with no fmriqc knowledge reads to
    learn that 1 is inside the phantom.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        dataset.set_auto_mask(False)
        mask = dataset["images.phantom_mask"]
        stored = np.asarray(mask[...])
        attributes = {name: mask.getncattr(name) for name in mask.ncattrs()}

    assert stored.dtype == np.uint8
    assert set(np.unique(stored)) <= {0, 1}
    assert np.array_equal(attributes["flag_values"], _FLAG_VALUES)
    assert attributes["flag_meanings"] == "outside inside"
    assert q.load_artifact(saved).images.phantom_mask.dtype == np.bool_


def test_the_units_a_reader_is_told_are_the_ones_that_are_certain(
    tmp_path, artifact
) -> None:
    """Seconds, hertz and percent are labelled; a unit the file cannot know is not.

    The PSF abscissas are mm or voxels depending on what the header gave, so
    they carry a long name and no `units` rather than a guess.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
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

    The coordinate variables are deliberately excluded and covered by
    `test_the_coordinates_are_stored_plain`: they are a few hundred bytes of
    ascending numbers, and a filter pipeline costs more metadata than they hold
    data.

    The checksum is the one the zip container gave the `.npz` for free and
    netCDF-3 would have dropped: without it a flipped byte in an image reads
    back as a plausible number.

    What is asserted about `shuffle` is that the filter is *on* for the floats
    and off for the byte masks, not that it makes this file smaller -- on this
    fixture it does not. The phantom is stored as `uint16`, so its mean image
    holds only a few hundred distinct float64 values and plain deflate finds
    runs the shuffle breaks up: 138,250 B with the filter against 134,219 B
    without. Shuffle is kept on for the acquisitions the container is for,
    whose mean and SFNR images are noisy float64 with a distinct value in
    nearly every voxel, where it saves around 13%.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
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

    netCDF4 masks `_FillValue` and out-of-range values unless told not to, and
    a `MaskedArray` reaching `compose` would make a fill value indistinguishable
    from a measurement. Byte order is the same kind of claim one level down: an
    artifact written on one machine and read on another must arrive as numbers
    this machine can compute with directly.
    """
    loaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))
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

    Written as a file that is nearly all array -- one variable of incompressible
    noise, whose chunk is much the largest thing in it -- so that the byte
    flipped in the middle of it is inside that chunk whatever HDF5 does with
    the metadata around it. The rest is HDF5's fixed overhead, the stored
    document and its attributes, and the `row`/`col` axes the one variable
    declares -- a few tens of kilobytes, so the array is made large enough to
    dwarf them.
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
    error, a JSON parse or a shape check happened to raise; one type means "this
    file is not a readable artifact" and nothing else escapes. The offsets are
    landmarks rather than a random sweep, so the test says the same thing on
    every run: the signature, the superblock behind it, the text of the stored
    document, and the tail where the last chunk lies.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    whole = saved.read_bytes()
    document_at = whole.find(b'"schema_version"')
    assert document_at > 0  # the document is stored as plain text, so this finds it
    path = tmp_path / "damaged.nc"

    for offset in (0, 64, document_at + 8, len(whole) - 4096, len(whole) - 1):
        damaged = bytearray(whole)
        damaged[offset] ^= 0xFF
        path.write_bytes(bytes(damaged))
        try:
            loaded = q.load_artifact(path)
        except q.InvalidArtifactError:
            continue
        # A flip that lands in slack space changes nothing a reader can see.
        assert np.array_equal(loaded.images.sfnr, artifact.images.sfnr), offset


def test_an_artifact_with_no_hull_round_trips(tmp_path, artifact) -> None:
    """A phantom too small to outline stores an empty array, and reads back one.

    `_convex_hull` yields `(0, 2)` for a mask with no area (see
    `analysis/build.py`), which netCDF-3 could not have stored at all: a
    zero-length dimension there is *the* unlimited one, of which a file may
    have one. netCDF-4 has ordinary zero-length dimensions.
    """
    images = replace(artifact.images, phantom_hull=np.zeros((0, 2)))
    saved = q.save_artifact(replace(artifact, images=images), tmp_path / "flat.qa.nc")
    loaded = q.load_artifact(saved)

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
    saved = str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))
    # Imported here, before the filter, and not at the top of the module: what
    # is asserted is that *opening the file* warns about nothing, and importing
    # either library under `error` raises the netCDF4 wheel's own Cython
    # `RuntimeWarning` -- a defect in the wheel that no artifact can fix, and
    # one a test of the file must not be able to trip over.
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

    A vector attribute arrives as an array and text as a `str` -- so
    `ds.attrs["provenance.voxel_mm"]` is a voxel size to compute with rather
    than something to parse, and a non-ASCII scan name written as UTF-8 NC_CHAR
    is the same string on the way back out.
    """
    prov = replace(artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz")
    saved = str(q.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.nc"))
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

    Without them `xr.open_dataset` reports "dimensions without coordinates" and
    a plot runs against 0..n-1. With them every axis is an index xarray can
    select and align on, `curves.time` rides along as a second label on the
    per-frame traces, and `ds["curves.roi_signal"].plot()` draws against
    seconds without the caller supplying anything.
    """
    saved = str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))
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

    The headline claim of this container is that a reader which has never heard
    of fmriqc opens the file, finds the axes named, and can turn the flagged
    bytes back into a mask on its own.
    """
    saved = str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))

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
