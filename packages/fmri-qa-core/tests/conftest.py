"""Shared fixtures for the calculation-half tests.

The phantom every test measures against is `fmriqa.testing.synthetic_series`.
`write_scan` writes one to disk as a NIfTI + BIDS sidecar for tests that need
real file I/O. `artifact` runs the whole pipeline over the phantom once per
session.
"""

import dataclasses
import json
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import netCDF4
import nibabel as nib
import numpy as np
import pytest

import fmriqa as q
from fmriqa.analysis.serialize import netcdf
from fmriqa.testing import phantom_scan, synthetic_series

WriteScan = Callable[..., str]
MakeScan = Callable[..., "q.QAScan"]


@pytest.fixture
def make_scan() -> MakeScan:
    """Return a factory building an in-memory `QAScan` over `synthetic_series`.

    The in-code counterpart of `write_scan`. `pe_axis=1` is passed explicitly to
    skip the ghost-estimate fallback and its warning.
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
    TR 2 s. The sidecar sets `PhaseEncodingDirection`, so no ghost-estimate
    fallback warning fires.

    The background has a Rician-like noise floor, as a real magnitude image
    does. A constant background would make the quantiles that seed
    `segment_phantom` degenerate.

    Stored as `uint16`, like a properly converted acquisition. The saturation
    check needs integer data (see `metrics.saturation`), and floats would add a
    storage warning to every file-based test. `PHANTOM_SIGNAL` is 1000, so
    nibabel stores the values directly. Rescaling them onto the type's maximum
    would create a false `2**16 - 1` rail.
    """
    # Mirrors `fmriqa_io.testing.write_phantom`. Goes away when the file-based
    # tests move to fmri-qa-io.
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
def artifact() -> q.QAArtifact:
    """An artifact from the synthetic phantom, at a small ROI.

    Built once per session and shared. The artifact is frozen with read-only
    arrays, so no test can change it for another. The assertion below checks
    that.
    """
    scan = phantom_scan()
    settings = q.AnalysisSettings(roi_size=9)
    result = q.analyze(scan, settings, name="scan.nii.gz", source="scan.nii.gz")
    assert not any(a.flags.writeable for a in _arrays(result)), (
        "shared artifact has a writeable array"
    )
    return result


@pytest.fixture
def read_netcdf() -> Callable[[Path], tuple[dict, dict[str, np.ndarray]]]:
    """Return a reader of a stored artifact that drives `netCDF4` directly.

    Tests that corrupt or inspect a stored artifact use plain netCDF instead of
    the package's `netcdf` module, since readability that way is why this
    container was chosen.
    """

    def read(path: Path) -> tuple[dict, dict[str, np.ndarray]]:
        """The document and every array of a stored artifact, read with netCDF4 alone.

        Coordinate variables are skipped. They are derived on the way out, so the
        result is what `decompose` produced.
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


# Mirrors `fmriqa_io.testing.fake_dcm2niix_script`. Goes away when the import
# session tests move to fmri-qa-io.
@pytest.fixture
def fake_dcm2niix(tmp_path):
    """Build a stub dcm2niix that writes the outputs a test asks for.

    For each stem, writes a NIfTI containing the stem, plus `<stem>.json` where
    a sidecar was given, into the directory named by `-o`. Prints dcm2niix's real
    banner line for the version parser.
    """

    def build(
        outputs, returncode=0, name="dcm2niix", *, suffix=".nii.gz", companions=None
    ):
        script = tmp_path / name
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            f"outputs = {outputs!r}\n"
            f"companions = {companions or {}!r}\n"
            f"suffix = {suffix!r}\n"
            "args = sys.argv[1:]\n"
            "out = Path(args[args.index('-o') + 1])\n"
            'print("Chris Rorden\'s dcm2niiX version v1.0.20260724 (JP2:OpenJPEG)")\n'
            "for stem, sidecar in outputs.items():\n"
            "    (out / f'{stem}{suffix}').write_bytes(stem.encode())\n"
            "    if sidecar is not None:\n"
            "        (out / f'{stem}.json').write_text(json.dumps(sidecar))\n"
            "for filename, content in companions.items():\n"
            "    (out / filename).write_bytes(content)\n"
            f"sys.exit({returncode})\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    return build
