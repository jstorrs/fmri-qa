"""Decoding a scan from bytes gives the scan loading the file gives.

`scan_from_bytes` is what a browser calls with the bytes of a dropped file, and
`load_scan` reads the files and calls it. These pin that the two agree on every
field, and that the decoder's own refusals and warnings name the `name` and
`sidecar_name` it was handed, since there may be no file to name.
"""

import gzip
import json
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

import fmriqa as q
from fmriqa_io import load_scan, scan_from_bytes
from fmriqa_io.decode import parse_sidecar
from fmriqa_io.testing import write_phantom


def _assert_same_scan(a: q.QAScan, b: q.QAScan) -> None:
    """Every `QAScan` field of `a` equals `b`'s."""
    assert np.array_equal(a.data, b.data)
    assert a.affine is not None
    assert b.affine is not None
    assert np.array_equal(a.affine, b.affine)
    assert (a.tr, a.pe_axis, a.meta) == (b.tr, b.pe_axis, b.meta)
    assert (a.slope, a.inter, a.stored_integer) == (b.slope, b.inter, b.stored_integer)


def _image(
    dtype: type = np.uint16,
    *,
    shape: tuple[int, ...] = (8, 8, 2, 6),
    time_unit: str = "sec",
    pixdim_t: float = 2.0,
    phase: int | None = 1,
    image_type: type[nib.Nifti1Image] = nib.Nifti1Image,
) -> nib.Nifti1Image:
    """A small NIfTI image in memory, 3 mm voxels."""
    data = np.arange(np.prod(shape), dtype=dtype).reshape(shape)
    img = image_type(data, affine=np.diag([3.0, 3.0, 3.0, 1.0]))
    if len(shape) == 4:
        img.header.set_zooms((3.0, 3.0, 3.0, pixdim_t))
    img.header.set_xyzt_units(xyz="mm", t=time_unit)
    if phase is not None:
        img.header.set_dim_info(freq=None, phase=phase, slice=None)
    return img


@pytest.mark.parametrize("suffix", [".nii", ".nii.gz"])
@pytest.mark.parametrize("with_sidecar", [True, False])
def test_bytes_decode_to_the_scan_the_file_loads(
    tmp_path: Path, suffix: str, with_sidecar: bool
) -> None:
    nifti = write_phantom(tmp_path, n=16, z=2, t=8)
    if suffix == ".nii":
        plain = tmp_path / "scan.nii"
        plain.write_bytes(gzip.decompress(nifti.read_bytes()))
        nifti.unlink()
        nifti = plain
    sidecar_file = tmp_path / "scan.json"
    sidecar = sidecar_file.read_bytes() if with_sidecar else None
    if not with_sidecar:
        sidecar_file.unlink()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the missing-sidecar warning, both ways
        loaded = load_scan(nifti)
        decoded = scan_from_bytes(nifti.read_bytes(), sidecar)

    _assert_same_scan(decoded, loaded)


def test_gzipped_and_raw_bytes_decode_to_the_same_scan(tmp_path: Path) -> None:
    nifti = write_phantom(tmp_path, n=16, z=2, t=8)
    compressed = nifti.read_bytes()
    sidecar = (tmp_path / "scan.json").read_bytes()
    _assert_same_scan(
        scan_from_bytes(compressed, sidecar),
        scan_from_bytes(gzip.decompress(compressed), sidecar),
    )


def test_a_nifti2_image_is_accepted() -> None:
    sidecar = b'{"PhaseEncodingDirection": "j"}'
    one = scan_from_bytes(_image().to_bytes(), sidecar)
    two = scan_from_bytes(_image(image_type=nib.Nifti2Image).to_bytes(), sidecar)
    _assert_same_scan(two, one)


def test_a_big_endian_header_is_accepted() -> None:
    img = _image()
    swapped = nib.Nifti1Image(
        img.get_fdata().astype(">u2"), img.affine, img.header.as_byteswapped(">")
    )
    assert swapped.to_bytes()[:4] == (348).to_bytes(4, "big")
    scan = scan_from_bytes(swapped.to_bytes(), b'{"PhaseEncodingDirection": "j"}')
    assert np.array_equal(scan.data, img.get_fdata())


@pytest.mark.parametrize(
    "data", [b"", b"not a nifti", gzip.compress(b"not a nifti either")]
)
def test_bytes_that_are_not_a_nifti_are_refused_by_name(data: bytes) -> None:
    with pytest.raises(q.InvalidScanError, match="NIfTI") as info:
        scan_from_bytes(data, name="dropped.nii.gz")
    assert info.value.value == "dropped.nii.gz"


def _corrupt_crc(compressed: bytes) -> bytes:
    """Flip a bit of the gzip trailer's CRC-32, leaving the deflate data whole."""
    crc = len(compressed) - 8
    return compressed[:crc] + bytes([compressed[crc] ^ 1]) + compressed[crc + 1 :]


@pytest.mark.parametrize(
    "damage",
    [
        lambda nii: nii[: len(nii) // 2],  # samples cut short
        lambda nii: nii[:200],  # header cut short
        lambda nii: gzip.compress(nii)[:300],  # gzip stream cut short
        lambda nii: _corrupt_crc(gzip.compress(nii)),
        lambda nii: gzip.compress(nii) + b"junk",
    ],
    ids=["truncated-nii", "truncated-header", "truncated-gz", "bad-crc", "trailing"],
)
def test_damaged_bytes_are_refused_by_name(damage) -> None:
    nifti = damage(_image().to_bytes())
    with pytest.raises(q.InvalidScanError, match="could not be decoded") as info:
        scan_from_bytes(nifti, b"{}", name="dropped.nii.gz")
    assert info.value.value == "dropped.nii.gz"


@pytest.mark.parametrize("pair_type", [nib.Nifti1Pair, nib.Nifti2Pair])
def test_the_header_of_a_nifti_pair_is_refused_by_name(pair_type) -> None:
    pair = pair_type(np.ones((8, 8, 2, 6), dtype=np.uint16), np.eye(4))
    with pytest.raises(q.InvalidScanError, match=r"NIfTI pair \(\.hdr/\.img\)") as info:
        scan_from_bytes(pair.header.binaryblock, b"{}", name="scan.hdr")
    assert info.value.value == "scan.hdr"


def test_a_three_dimensional_image_is_refused() -> None:
    nifti = _image(shape=(8, 8, 2)).to_bytes()
    with pytest.raises(q.InvalidScanError, match="data shape") as info:
        scan_from_bytes(nifti, b"{}", name="dropped.nii")
    assert info.value.value == (8, 8, 2)


def test_the_sidecar_is_read_from_bytes() -> None:
    sidecar = json.dumps({"PhaseEncodingAxis": "i", "FlipAngle": 52.5}).encode()
    scan = scan_from_bytes(_image(phase=None).to_bytes(), sidecar)
    assert scan.pe_axis == 0
    assert scan.meta is not None
    assert scan.meta.flip_angle == 52.5


@pytest.mark.parametrize(
    ("sidecar", "match"),
    [
        (b"{not json at all", "could not be parsed"),
        (b"[1, 2, 3]", "JSON object"),
        (b'{"FlipAngle": "\xff\xfe"}', "could not be parsed"),  # not UTF-8
    ],
    ids=["malformed", "not-an-object", "not-utf-8"],
)
def test_an_unreadable_sidecar_is_refused_by_name(sidecar: bytes, match: str) -> None:
    with pytest.raises(q.InvalidScanError, match=match) as info:
        scan_from_bytes(_image().to_bytes(), sidecar, sidecar_name="dropped.json")
    assert info.value.field == "BIDS JSON sidecar"
    assert info.value.value == "dropped.json"


def test_parse_sidecar_accepts_text_and_bytes_alike() -> None:
    text = '{"EchoTime": 0.03}'
    assert parse_sidecar(text, source="s") == parse_sidecar(text.encode(), source="s")


def test_a_missing_sidecar_warns_by_name() -> None:
    with pytest.warns(UserWarning, match=r"^dropped\.nii: no BIDS JSON sidecar"):
        scan = scan_from_bytes(_image().to_bytes(), name="dropped.nii")
    assert scan.meta is not None
    assert scan.meta.flip_angle is None


def test_float_storage_warns_by_name() -> None:
    nifti = _image(np.float32).to_bytes()
    with pytest.warns(UserWarning, match=r"^dropped\.nii: stored as float32"):
        scan = scan_from_bytes(nifti, b"{}", name="dropped.nii")
    assert scan.stored_integer is False


def test_no_phase_encode_axis_warns_by_name() -> None:
    nifti = _image(phase=None).to_bytes()
    with pytest.warns(UserWarning, match=r"^dropped\.nii: no phase-encode axis"):
        scan = scan_from_bytes(nifti, b"{}", name="dropped.nii")
    assert scan.pe_axis is None


def test_a_millisecond_header_tr_is_converted_to_seconds() -> None:
    nifti = _image(time_unit="msec", pixdim_t=2500.0).to_bytes()
    assert scan_from_bytes(nifti, b"{}").tr == pytest.approx(2.5)


def test_header_scaling_is_kept() -> None:
    img = _image(np.int16)
    img.header.set_slope_inter(2.0, 10.0)
    scan = scan_from_bytes(img.to_bytes(), b"{}")
    assert (scan.slope, scan.inter) == (2.0, 10.0)
    assert np.array_equal(scan.data, np.asarray(img.dataobj) * 2 + 10)
    assert scan.stored_integer is True
