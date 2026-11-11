"""Helpers for tests, docs and spikes that need real file IO.

`write_phantom` writes the synthetic phantom to disk as a NIfTI + BIDS sidecar,
the file counterpart of `fmriqa.testing.phantom_scan`: `load_scan` reads it
back as that scan. `fake_dcm2niix_script`
writes a stub converter. Import this module as `fmriqa_io.testing`. It is not
part of the `fmriqa_io` public surface.
"""

import json
import stat
from collections.abc import Mapping
from pathlib import Path

import nibabel as nib
import numpy as np

from fmriqa.testing import TR_SEC, VOXEL_MM, synthetic_series

__all__ = ["fake_dcm2niix_script", "write_phantom"]


def write_phantom(
    directory: Path,
    name: str = "scan",
    *,
    n: int = 32,
    z: int = 3,
    t: int = 40,
    seed: int = 0,
    flip: float = 77.0,
    smoothing: float = 0.0,
    ghost: float = 0.0,
    drift: float = 0.0,
) -> Path:
    """Write a synthetic phantom NIfTI + sidecar; return the NIfTI path.

    The disk of `fmriqa.testing.synthetic_series`, rendered from k-space with
    seeded noise, 3 mm isotropic voxels and TR 2 s. The sidecar sets
    `PhaseEncodingDirection`, so no ghost-estimate fallback warning fires.

    The background is Rayleigh noise, as a real magnitude image's is. A
    constant background would make the quantiles that seed `segment_phantom`
    degenerate.

    Stored as `uint16`, like a properly converted acquisition. The saturation
    check needs integer data (see `metrics.saturation`), and floats would add a
    storage warning to every file-based test. `PHANTOM_SIGNAL` is 1000, so
    nibabel stores the values directly. Rescaling them onto the type's maximum
    would create a false `2**16 - 1` rail.

    `smoothing` blurs the series in-plane, `ghost` adds an N/2 ghost along the
    phase-encode axis and `drift` a linear signal drift (see
    `synthetic_series`). The docs use `smoothing`. `fmriqa.testing.phantom_scan`
    describes only the unblurred phantom with neither.
    """
    data = synthetic_series(
        n=n, z=z, t=t, seed=seed, smoothing=smoothing, ghost=ghost, drift=drift
    )

    img = nib.Nifti1Image(data.astype(np.uint16), affine=np.eye(4))
    img.header.set_zooms((VOXEL_MM, VOXEL_MM, VOXEL_MM, TR_SEC))
    img.header.set_xyzt_units("mm", "sec")
    nifti = directory / f"{name}.nii.gz"
    nib.save(img, str(nifti))
    (directory / f"{name}.json").write_text(
        json.dumps({"PhaseEncodingDirection": "j", "FlipAngle": flip})
    )
    return nifti


def fake_dcm2niix_script(
    directory: Path,
    outputs: Mapping[str, Mapping[str, object] | None],
    returncode: int = 0,
    name: str = "dcm2niix",
    *,
    suffix: str = ".nii.gz",
    companions: Mapping[str, bytes] | None = None,
) -> Path:
    """Write a stub dcm2niix into `directory`; return the executable's path.

    For each stem in `outputs`, the stub writes a NIfTI containing the stem, plus
    `<stem>.json` where a sidecar was given, into the directory named by `-o`.
    `companions` maps extra file names to their bytes. The stub prints dcm2niix's
    real banner line for the version parser and exits with `returncode`.
    """
    script = directory / name
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        f"outputs = {dict(outputs)!r}\n"
        f"companions = {dict(companions or {})!r}\n"
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
