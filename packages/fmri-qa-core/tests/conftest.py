"""Shared fixtures for the calculation-half tests.

`write_scan` writes a tiny synthetic phantom to disk as a NIfTI + BIDS sidecar,
so the tests that need the real file-I/O path (`QAScan.from_nifti`, the CLI) get
one without each of them rebuilding the phantom.
"""

import json
from collections.abc import Callable
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

WriteScan = Callable[..., str]


@pytest.fixture
def write_scan() -> WriteScan:
    """Return a factory writing a synthetic phantom NIfTI + sidecar.

    A bright central disk with seeded temporal noise, 3 mm isotropic voxels and
    TR 2 s. The sidecar sets `PhaseEncodingDirection` so the PE axis resolves
    from metadata (no ghost-estimate fallback warning). Returns the NIfTI path.
    """

    def factory(
        directory: Path,
        name: str = "scan",
        n: int = 32,
        z: int = 3,
        t: int = 40,
        seed: int = 0,
        flip: float = 77,
    ) -> str:
        rng = np.random.default_rng(seed)
        yy, xx = np.mgrid[0:n, 0:n]
        disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
        base = np.where(disk, 1000.0, 0.0)
        noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
        data = base[:, :, None, None] + noise

        img = nib.Nifti1Image(data, affine=np.eye(4))
        img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
        nifti = directory / f"{name}.nii.gz"
        nib.save(img, str(nifti))
        (directory / f"{name}.json").write_text(
            json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": flip})
        )
        return str(nifti)

    return factory
