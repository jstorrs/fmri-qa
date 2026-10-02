"""Shared fixtures for the calculation-half tests.

`synthetic_series` builds the tiny phantom every test measures against, and
`write_scan` writes one to disk as a NIfTI + BIDS sidecar, so the tests that need
the real file-I/O path (`QAScan.from_nifti`, the CLI) get one without each of
them rebuilding the phantom. `artifact` runs the whole pipeline over that
phantom once per session, for the artifact and CLI tests that need a finished
analysis rather than a scan.
"""

import dataclasses
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import netCDF4
import nibabel as nib
import numpy as np
import pytest

import fmriqc as q
from fmriqc.analysis.serialize import netcdf

WriteScan = Callable[..., str]
MakeScan = Callable[..., "q.QAScan"]

# Background noise floor, as a fraction of phantom signal. Real magnitude images
# have a Rician air background; an exactly-constant one is what makes the
# intensity quantiles seeding `segment_phantom` degenerate, so the fixtures give
# the background a floor and exercise the segmentation rather than a failure path.
BACKGROUND_SCALE = 8.0
PHANTOM_SIGNAL = 1000.0


def synthetic_series(n: int = 32, z: int = 3, t: int = 40, seed: int = 0) -> np.ndarray:
    """A bright central disk over a noisy background: (n, n, z, t), float64.

    The disk carries seeded temporal noise (the fluctuation the stability metrics
    measure); the background carries a static magnitude floor (see
    `BACKGROUND_SCALE`) so the phantom is separable from it.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    base = np.where(disk, PHANTOM_SIGNAL, 0.0)
    floor = np.abs(rng.normal(scale=BACKGROUND_SCALE, size=(n, n, z, t)))
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    return np.asarray(base[:, :, None, None] + noise + floor, dtype=np.float64)


@pytest.fixture
def make_scan() -> MakeScan:
    """Return a factory building an in-memory `QAScan` over `synthetic_series`.

    The in-code counterpart of `write_scan`, for the tests that exercise the pure
    pipeline and need no file on disk. `pe_axis=1` is passed explicitly so the
    ghost-estimate fallback (and its warning) stays out of the way.
    """

    def factory(seed: int = 0, n: int = 32, z: int = 3, t: int = 40) -> q.QAScan:
        data = synthetic_series(n=n, z=z, t=t, seed=seed)
        return q.QAScan(data=data, tr=2.0, pe_axis=1)

    return factory


def _write_phantom(
    directory: Path,
    name: str = "scan",
    n: int = 32,
    z: int = 3,
    t: int = 40,
    seed: int = 0,
    flip: float = 77,
) -> str:
    """Write a synthetic phantom NIfTI + sidecar; return the NIfTI path.

    A bright central disk with seeded temporal noise, 3 mm isotropic voxels and
    TR 2 s. The sidecar sets `PhaseEncodingDirection` so the PE axis resolves
    from metadata (no ghost-estimate fallback warning).

    The background carries a Rician-like noise floor, as a real magnitude image
    does. That matters: on an *exactly* constant background the intensity
    quantiles that seed `segment_phantom` degenerate, so a zero-background
    fixture would exercise a failure path instead of the segmentation.

    Stored as `uint16`, as a properly converted acquisition is: the ADC rail the
    saturation check looks for is an integer artifact, so a float image is one
    the check declines to answer for (see `metrics.saturation`). Writing the
    shared phantom as floats would put every file-based test on that declined
    path and attach a storage warning to each. `PHANTOM_SIGNAL` is 1000, well
    inside `uint16`, so nibabel stores these values directly rather than
    rescaling them onto the type's own maximum -- which would be a `2**16 - 1`
    rail, and would have the fixture report clipping it does not have.
    """
    data = synthetic_series(n=n, z=z, t=t, seed=seed)

    img = nib.Nifti1Image(data.astype(np.uint16), affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    img.header.set_xyzt_units("mm", "sec")
    nifti = directory / f"{name}.nii.gz"
    nib.save(img, str(nifti))
    (directory / f"{name}.json").write_text(
        json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": flip})
    )
    return str(nifti)


def _arrays(obj: object) -> Iterator[np.ndarray]:
    """Every ndarray reachable through dataclass fields of `obj`."""
    if isinstance(obj, np.ndarray):
        yield obj
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _arrays(getattr(obj, f.name))


@pytest.fixture
def write_scan() -> WriteScan:
    """Return `_write_phantom`: write a synthetic phantom NIfTI + sidecar.

    Function-scoped factory so each test writes into its own `tmp_path`.
    """
    return _write_phantom


@pytest.fixture(scope="session")
def artifact(tmp_path_factory: pytest.TempPathFactory) -> q.QAArtifact:
    """An artifact from the synthetic phantom, at a small ROI.

    Built once per session and shared: the artifact is a frozen dataclass whose
    arrays are read-only, so no test can change it for another. The assertion
    below checks that premise rather than assuming it.
    """
    nifti = _write_phantom(tmp_path_factory.mktemp("artifact"))
    scan = q.QAScan.from_nifti(nifti)
    settings = q.AnalysisSettings(roi_size=9)
    result = q.analyze(scan, settings, name="scan.nii.gz", source="scan.nii.gz")
    assert not any(a.flags.writeable for a in _arrays(result)), (
        "shared artifact has a writeable array"
    )
    return result


@pytest.fixture
def read_netcdf() -> Callable[[Path], tuple[dict, dict[str, np.ndarray]]]:
    """Return a reader of a stored artifact that drives `netCDF4` directly.

    Tests that corrupt or inspect a stored artifact read it back through a plain
    netCDF reader rather than the package's own `netcdf` module: reading the file
    that way is itself the claim this container was chosen for.
    """

    def read(path: Path) -> tuple[dict, dict[str, np.ndarray]]:
        """The document and every array of a stored artifact, read with netCDF4 alone.

        The coordinate variables are skipped -- a variable named for a dimension is
        that axis, derived on the way out and not part of what the artifact
        carries -- so what this returns is what `decompose` produced.
        """
        with netCDF4.Dataset(str(path)) as dataset:
            dataset.set_auto_mask(False)
            document = json.loads(dataset.getncattr("document"))
            arrays = {
                name: (
                    np.asarray(variable[...] != 0)
                    if "flag_values" in variable.ncattrs()
                    else np.asarray(variable[...])
                )
                for name, variable in dataset.variables.items()
                if name not in dataset.dimensions
            }
        return document, arrays

    return read


@pytest.fixture
def encode() -> Callable[[dict, dict[str, np.ndarray]], bytes]:
    """Return `netcdf.encode` as `save_artifact` calls it: text and its parse."""

    def run(document: dict, arrays: dict[str, np.ndarray]) -> bytes:
        text = json.dumps(document)
        return netcdf.encode(text, json.loads(text), arrays)

    return run
