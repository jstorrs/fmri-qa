"""Decode NIfTI bytes and read the header fields the scan needs.

`image_from_bytes` turns the bytes of a single-file NIfTI-1 or NIfTI-2 image,
gzipped or not, into a nibabel image without touching a file, and `image_data`
reads its samples. Both refuse damaged bytes as an `InvalidScanError` naming the
scan. The other helpers read one header field each, in the units the pipeline
expects.
"""

import gzip
import struct
import zlib

import nibabel as nib
from nibabel.filebasedimages import ImageFileError
from nibabel.spatialimages import HeaderDataError
from nibabel.wrapstruct import WrapStructError

from fmriqa.exceptions import InvalidScanError
from fmriqa.types import FloatArray
from fmriqa.warn import warn

__all__ = [
    "TIME_UNIT_SECONDS",
    "image_data",
    "image_from_bytes",
    "pe_axis_from_header",
    "spatial_scale_mm",
    "tr_from_header",
]

# The gzip magic number. A `.nii.gz` is a gzipped `.nii`, and nibabel's
# `from_bytes` reads only the uncompressed form.
_GZIP_MAGIC = b"\x1f\x8b"

# `sizeof_hdr`, the header's first int32, names the format: 348 for NIfTI-1,
# 540 for NIfTI-2. It is in the file's byte order, so both orders are tried.
_IMAGE_BY_HEADER_SIZE: dict[int, type[nib.Nifti1Image]] = {
    348: nib.Nifti1Image,
    540: nib.Nifti2Image,
}

# Where each format keeps its magic, and the magic of a pair's `.hdr`, which
# holds no samples (`n+1`/`n+2` mark a single file).
_PAIR_MAGIC: dict[int, tuple[slice, bytes]] = {
    348: (slice(344, 348), b"ni1\x00"),
    540: (slice(4, 8), b"ni2\x00"),
}

# What damaged bytes raise on the way through gzip and nibabel: a truncated or
# corrupt gzip stream (`BadGzipFile` is an `OSError`), a header of the wrong
# size or contents, or fewer samples than the header promises.
_DECODE_ERRORS = (
    OSError,
    EOFError,
    zlib.error,
    ValueError,
    HeaderDataError,
    WrapStructError,
    ImageFileError,
)

# NIfTI `xyzt_units` time codes, as nibabel spells them, in seconds. An unknown
# unit is read as seconds, which is what an unlabeled pixdim has always meant in
# practice.
TIME_UNIT_SECONDS: dict[str, float] = {"sec": 1.0, "msec": 1e-3, "usec": 1e-6}

# NIfTI `xyzt_units` spatial codes, as nibabel spells them, in millimeters.
_SPATIAL_UNIT_MM: dict[str, float] = {
    "meter": 1000.0,
    "mm": 1.0,
    "micron": 0.001,
    "unknown": 1.0,
}


def image_from_bytes(data: bytes, *, name: str) -> nib.Nifti1Image:
    """Decode a single-file NIfTI-1 or NIfTI-2 image, gzipped or not.

    `name` identifies the bytes in an error, since there may be no file.

    The whole gzip stream is checked, so a `.nii.gz` with a bad checksum or cut
    short is refused rather than loaded.

    Raises
    ------
    InvalidScanError
        If the bytes are not a single-file NIfTI-1 or NIfTI-2 image, or are
        damaged.
    """
    try:
        if data.startswith(_GZIP_MAGIC):
            data = gzip.decompress(data)
        size = _header_size(data)
        if size is None:
            raise InvalidScanError(
                "NIfTI", name, "not a single-file NIfTI-1 or NIfTI-2 image"
            )
        where, pair_magic = _PAIR_MAGIC[size]
        if data[where] == pair_magic:
            raise InvalidScanError(
                "NIfTI",
                name,
                "is the header of a NIfTI pair (.hdr/.img), which is not "
                "supported; convert it to a single-file .nii or .nii.gz",
            )
        return _IMAGE_BY_HEADER_SIZE[size].from_bytes(data)
    except InvalidScanError:
        raise
    except _DECODE_ERRORS as e:
        raise InvalidScanError("NIfTI", name, f"could not be decoded: {e}") from e


def image_data(img: nib.Nifti1Image, *, name: str) -> FloatArray:
    """Read the image's samples, scaled, as float64.

    Raises
    ------
    InvalidScanError
        If the bytes hold fewer samples than the header promises.
    """
    try:
        return img.get_fdata()
    except _DECODE_ERRORS as e:
        raise InvalidScanError("NIfTI", name, f"could not be decoded: {e}") from e


def _header_size(data: bytes) -> int | None:
    """Return the `sizeof_hdr` the bytes declare, or None if not a NIfTI one."""
    if len(data) < 4:
        return None
    for order in ("<", ">"):
        (size,) = struct.unpack(f"{order}i", data[:4])
        if size in _IMAGE_BY_HEADER_SIZE:
            return int(size)
    return None


def pe_axis_from_header(header: nib.Nifti1Header) -> int | None:
    """Read the PE axis from NIfTI `dim_info`, or None if unset or invalid.

    `dim_info` carries no polarity, which we don't need for ghost placement.
    """
    phase = header.get_dim_info()[1]
    return int(phase) if phase in (0, 1, 2) else None


def tr_from_header(header: nib.Nifti1Header) -> float:
    """Read pixdim[4] in seconds, converted by the header's declared time unit.

    pixdim[4] is a bare number. Its unit is in the header's `xyzt_units` field,
    and scanners do write milliseconds there. Read at face value, a 2 s TR
    arrives as 2000, and every duration-derived choice goes quietly wrong: the
    warm-up trim drops no volumes and the detrend fit picks an absurd order,
    while the metrics still look like numbers. So the header value is always
    converted by its declared unit.
    """
    unit = str(header.get_xyzt_units()[1])
    return float(header.get_zooms()[3]) * TIME_UNIT_SECONDS.get(unit, 1.0)


def spatial_scale_mm(unit: str) -> float:
    """Resolve the header's spatial unit once for voxel sizes and the affine."""
    if unit == "unknown":
        warn(
            "NIfTI spatial unit is unknown; assuming millimeters for voxel sizes "
            "and affine",
        )
    return _SPATIAL_UNIT_MM[unit]
