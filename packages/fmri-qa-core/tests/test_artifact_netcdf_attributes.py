"""What the netCDF file says about itself.

It is netCDF-4, the document rides as an ASCII global attribute, and every
measurement, provenance field, setting and scalar is also its own attribute, so
a reader that never decodes the document can answer the cheap questions.
"""

import json
import math
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
from fmriqa.analysis import ARTIFACT_SCHEMA_VERSION
from fmriqa.analysis.serialize import netcdf
from fmriqa.analysis.serialize.decompose import decompose


def test_the_file_is_netcdf4(tmp_path, artifact) -> None:
    """HDF5's signature: what a netCDF-4 file starts with, and what is sniffed.

    Also what `load_artifact` dispatches on: these bytes decide the container,
    never the file's name, since `--artifact` writes whatever name the user
    gave.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    assert saved.read_bytes()[:8] == b"\x89HDF\r\n\x1a\n"
    with netCDF4.Dataset(str(saved)) as dataset:
        assert dataset.data_model == "NETCDF4"
        # Flat: xarray's `open_dataset` sees only the root group, so everything
        # a reader needs has to be in it.
        assert not dataset.groups


def test_the_document_rides_as_an_ascii_global_attribute(tmp_path, artifact) -> None:
    """One attribute, readable as text, holding the whole non-array record.

    This is what MATLAB reads as `jsondecode(ncreadatt(f, '/', 'document'))`
    and R as `ncatt_get(f, 0, "document")`, so it has to be text a reader can
    take without being told an encoding.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        stored = dataset.getncattr("document")
    assert isinstance(stored, str) and stored.isascii()
    assert json.loads(stored)["schema_version"] == artifact.schema_version


def test_the_cheap_attributes_answer_without_decoding_the_document(
    tmp_path, artifact
) -> None:
    """A reader that never touches JSON can still tell what the file is."""
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        attributes = {name: dataset.getncattr(name) for name in dataset.ncattrs()}
    assert attributes["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert attributes["Conventions"] == "CF-1.10"
    assert "fmri-qa" in attributes["title"]
    assert attributes["source"].startswith("fmri-qa-core ")


# How each JSON scalar is published as an attribute. `bool` comes before `int`
# because a Python bool is an int, and a verdict stored as a number would make
# the reader guess, which the flagged masks avoid.
_ATTRIBUTE_DTYPES = ((bool, np.uint8), (int, np.int32), (float, np.float64))


def _section_attributes(path, section: str) -> dict[str, object]:
    """Every `<section>.*` global attribute of a stored artifact, by field name."""
    with netCDF4.Dataset(str(path)) as dataset:
        return {
            name.removeprefix(f"{section}."): dataset.getncattr(name)
            for name in dataset.ncattrs()
            if name.startswith(f"{section}.")
        }


def test_every_resolved_measurement_is_published_as_its_own_attribute(
    tmp_path, artifact, read_netcdf
) -> None:
    """`ncreadatt(f, '/', 'measurements.snr')`: a number without a JSON parser.

    The attribute is the document's own value in the netCDF type that holds it,
    including NaN, which means the estimator could not resolve the value.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = read_netcdf(saved)
    measured = document["measurements"]
    published = _section_attributes(saved, "measurements")

    assert set(published) == {k for k, v in measured.items() if v is not None}
    for name, value in measured.items():
        if value is None:
            continue
        stored = published[name]
        if isinstance(value, str):
            assert stored == value, name
            continue
        # `getncattr` is typed as returning anything at all, so the numeric
        # attributes are named as arrays before their dtype is asked about.
        number = np.asarray(stored)
        expected = next(d for kind, d in _ATTRIBUTE_DTYPES if isinstance(value, kind))
        assert number.dtype == expected, name
        assert number == value or (np.isnan(number) and np.isnan(value)), name


def test_a_measurement_the_document_calls_null_has_no_attribute(
    tmp_path, artifact, read_netcdf
) -> None:
    """Absence means "does not apply", since NaN already means more.

    The clipping check runs on the fixture, so `clip_ceiling` is null because
    the series has no rail, not because nothing looked. An attribute cannot be
    null, and NaN would say the estimator tried and failed.
    """
    # A failed motion fit, the usual source of a NaN measurement.
    failed = replace(artifact.measurements, max_translation=math.nan)
    saved = q.save_artifact(
        replace(artifact, measurements=failed), tmp_path / "scan.qa.nc"
    )
    document, _ = read_netcdf(saved)
    published = _section_attributes(saved, "measurements")

    assert document["measurements"]["clip_ceiling"] is None
    assert "clip_ceiling" not in published
    # and the distinction it protects: a NaN measurement *is* published
    assert np.isnan(document["measurements"]["max_translation"])
    assert np.isnan(np.asarray(published["max_translation"]))


def test_save_refuses_a_measurement_no_attribute_can_hold(tmp_path, artifact) -> None:
    """An integer past NC_INT is refused rather than published wrapped around."""
    counts = replace(artifact.measurements, n_clipped_pre=2**31, clipped_any=True)
    with pytest.raises(q.InvalidArtifactError, match="netCDF integer"):
        q.save_artifact(replace(artifact, measurements=counts), tmp_path / "qa.nc")
    assert not (tmp_path / "qa.nc").exists()


def test_encode_refuses_an_empty_list(artifact, encode) -> None:
    """An attribute is a *typed* vector, and an empty list names no type."""
    document, arrays = decompose(artifact)
    document["provenance"]["voxel_mm"] = []
    with pytest.raises(ValueError, match="voxel_mm is an empty list"):
        encode(document, arrays)


def test_encode_refuses_a_value_no_attribute_can_hold(artifact, encode) -> None:
    """A list of objects: a JSON shape with no attribute form at all.

    A nested object flattens into the name, and a list of ints, floats or strings
    becomes a vector or a line of words. An object inside a list has nowhere to
    go. `validate_document` refuses it before `save_artifact` gets here, so this
    fallthrough covers `encode` called directly.
    """
    document, arrays = decompose(artifact)
    document["measurements"]["snr"] = [{"value": 1.0}]
    with pytest.raises(ValueError, match="no attribute can hold"):
        encode(document, arrays)


def test_every_recorded_provenance_field_is_published_as_its_own_attribute(
    tmp_path, artifact, read_netcdf
) -> None:
    """`ncreadatt(f, '/', 'provenance.tr')`: the run's own record, un-decoded.

    The measurements' rule applied to where the series came from, with one new
    shape: a JSON list is a vector attribute of its element type, so `voxel_mm`
    is three doubles and `matrix` two integers, each read in one call.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = read_netcdf(saved)
    recorded = document["provenance"]
    published = _section_attributes(saved, "provenance")

    assert set(published) == {k for k, v in recorded.items() if v is not None}
    for name, value in recorded.items():
        if value is None:
            continue
        stored = published[name]
        if isinstance(value, str):
            assert stored == value, name
            continue
        # `getncattr` is typed as returning anything at all, so the numeric
        # attributes are named as arrays before their dtype is asked about.
        number = np.asarray(stored)
        element = value[0] if isinstance(value, list) else value
        expected = next(d for kind, d in _ATTRIBUTE_DTYPES if isinstance(element, kind))
        assert number.dtype == expected, name
        shape = (len(value),) if isinstance(value, list) else ()
        assert number.shape == shape, name
        assert np.array_equal(number, value), name

    assert np.asarray(published["voxel_mm"]).shape == (3,)
    assert np.asarray(published["matrix"]).shape == (2,)


def test_a_provenance_field_the_document_calls_null_has_no_attribute(
    tmp_path, artifact, read_netcdf
) -> None:
    """Absence means "not recorded", as it does for a measurement.

    The phantom's sidecar gives a flip angle but no echo time, and nothing names
    a coil. An attribute cannot say "nobody wrote this down", and a zero would
    mean something else.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = read_netcdf(saved)
    published = _section_attributes(saved, "provenance")

    assert document["provenance"]["te"] is None
    assert document["provenance"]["coil"] is None
    assert not {"te", "coil"} & set(published)
    assert published["flip_angle"] == document["provenance"]["flip_angle"]


def test_every_setting_is_published_as_its_own_attribute(
    tmp_path, artifact, read_netcdf
) -> None:
    """`ncreadatt(f, '/', 'settings.roi_size')`: what the run was asked for.

    The measurements' rule applied to the settings: a float is a double, an
    integer an NC_INT, method names are text, and an override nobody gave
    (`pe_axis_override` is None unless `--pe-axis` was passed) is no attribute
    at all, not a number that would read as an axis.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = read_netcdf(saved)
    asked = document["settings"]
    published = _section_attributes(saved, "settings")

    assert set(published) == {k for k, v in asked.items() if v is not None}
    assert asked["pe_axis_override"] is None
    assert "pe_axis_override" not in published
    assert published["detrend"] == asked["detrend"]
    assert published["center"] == asked["center"]
    for name in ("trim_sec", "roi_size", "detrend_order"):
        number = np.asarray(published[name])
        expected = next(
            d for kind, d in _ATTRIBUTE_DTYPES if isinstance(asked[name], kind)
        )
        assert number.dtype == expected, name
        assert number == asked[name], name


def test_provenance_text_is_published_as_the_scanner_supplied_it(
    tmp_path, artifact
) -> None:
    """Unlike a measurement, this text is not this package's to constrain.

    A scan name comes from a file system and a manufacturer from a scanner header,
    so neither is a closed vocabulary that could be held to ASCII. netCDF4
    writes a `str` attribute as UTF-8 NC_CHAR and a reader gets it back
    unchanged.
    """
    prov = replace(
        artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz", manufacturer="Siemens™"
    )
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.qa.nc")
    published = _section_attributes(saved, "provenance")
    with netCDF4.Dataset(str(saved)) as dataset:
        # The document beside the convenience attributes still rides as ASCII.
        assert dataset.getncattr("document").isascii()

    assert published["scan"] == "sujet_créé_Ω_頭部.nii.gz"
    assert published["manufacturer"] == "Siemens™"
    assert q.load_artifact(saved).provenance == prov


def test_a_lone_surrogate_name_is_published_escaped_rather_than_refused(
    tmp_path, artifact
) -> None:
    """The one string with no UTF-8 form: a lossy attribute beats no file.

    A Windows file name with an undecodable byte reaches Python as an unpaired
    surrogate, which `str.encode` cannot render. The convenience attribute
    carries the escape instead of failing the save, and the document beside it
    spells the name correctly for `load_artifact` to read.
    """
    name = "bad_\udcff_name.nii.gz"
    prov = replace(artifact.provenance, scan=name)
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "s.qa.nc")

    assert _section_attributes(saved, "provenance")["scan"] == "bad_\\udcff_name.nii.gz"
    assert q.load_artifact(saved).provenance.scan == name


def test_save_refuses_a_provenance_integer_no_attribute_can_hold(
    tmp_path, artifact
) -> None:
    """The NC_INT bound the measurements are held to, over a reachable field.

    `n_trimmed` is only required to be non-negative, so a valid artifact can carry
    a count past NC_INT. Publishing it wrapped around would give a reader a
    wrong number with no reason to distrust it.
    """
    prov = replace(artifact.provenance, n_trimmed=2**31)
    with pytest.raises(q.InvalidArtifactError, match="netCDF integer"):
        q.save_artifact(replace(artifact, provenance=prov), tmp_path / "qa.nc")
    assert not (tmp_path / "qa.nc").exists()


def test_a_whole_number_setting_is_published_as_a_double(tmp_path, artifact) -> None:
    """`trim_sec=5` is a float field given an int: NC_DOUBLE, not NC_INT."""
    settings = q.AnalysisSettings(trim_sec=5, roi_size=9)
    saved = q.save_artifact(
        replace(artifact, settings=settings), tmp_path / "scan.qa.nc"
    )
    trim = np.asarray(_section_attributes(saved, "settings")["trim_sec"])
    assert trim.dtype == np.float64
    assert trim == 5.0


def test_a_voxel_size_mixing_ints_and_floats_saves_as_doubles(
    tmp_path, artifact
) -> None:
    """`(3.0, 3, 3.0)` is one vector of doubles, not a list of two kinds."""
    prov = replace(artifact.provenance, voxel_mm=(3.0, 3, 3.0))
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "v.qa.nc")
    voxel = np.asarray(_section_attributes(saved, "provenance")["voxel_mm"])
    assert voxel.dtype == np.float64
    assert voxel.shape == (3,)
    assert q.load_artifact(saved).provenance.voxel_mm == (3.0, 3.0, 3.0)


def test_every_curve_and_image_scalar_is_published_as_its_own_attribute(
    tmp_path, artifact, read_netcdf
) -> None:
    """The last of the document: nothing in it now needs JSON to read.

    These two sections nest (the `psf` block, the `roi` box), and the nest
    flattens into the name: `curves.psf.fwhm` is a two-double vector and
    `images.roi.row0` an integer. The one new shape is a list of words:
    `curves.psf.labels` is one text, `PE RO`, spelled as CF spells
    `flag_meanings`.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = read_netcdf(saved)

    for section in ("curves", "images"):
        recorded = dict(netcdf._leaves(section, document[section]))
        published = _section_attributes(saved, section)
        assert set(published) == {
            name.removeprefix(f"{section}.") for name in recorded
        }, section
        for path, value in recorded.items():
            stored = published[path.removeprefix(f"{section}.")]
            if isinstance(value, list) and isinstance(value[0], str):
                assert stored == " ".join(value), path
                continue
            if isinstance(value, str):
                assert stored == value, path
                continue
            number = np.asarray(stored)
            element = value[0] if isinstance(value, list) else value
            expected = next(
                d for kind, d in _ATTRIBUTE_DTYPES if isinstance(element, kind)
            )
            assert number.dtype == expected, path
            assert np.array_equal(number, value), path

    assert _section_attributes(saved, "curves")["psf.labels"] == "PE RO"
    assert np.asarray(_section_attributes(saved, "images")["has_ghost"]) == 1
