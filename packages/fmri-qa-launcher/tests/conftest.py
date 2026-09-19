"""Shared fixtures for the launcher tests.

`prepared_series` builds an analyzable synthetic phantom NIfTI + BIDS sidecar
pair with nibabel -- the same recipe as `fmri-qa-core/tests/conftest.py`'s
`write_scan` and `fmri-qa-report/tests/conftest.py`'s `_phantom`. This is a
*third* copy of it rather than a shared import: a package's `tests/` directory
is not itself importable by another package's tests (there is no shared
test-support distribution in this workspace), and the alternative -- reaching
into a sibling package's `tests/` with a path hack -- would tie this package's
test collection to another package's internal layout. Three small, literal
copies are the plainer failure mode.

`stub_dcm2niix` stands in for the real converter. `fmri-qa-core`'s own
`fake_dcm2niix` (`test_convert.py`) writes NIfTI files that do not load --
enough to test naming and staging, not enough to run `analyze` over. This one
copies an already-analyzable `prepared_series` pair into the `-o` directory
under dcm2niix-style stems instead, so `import_dicom`'s real staging, naming
(`names="qa"`) and filing all run for real, and the series that comes out the
other end is one `run_session` can actually analyze.
"""

import json
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

# Mirrors `fmri-qa-core/tests/conftest.py::BACKGROUND_SCALE`/`PHANTOM_SIGNAL`.
_BACKGROUND_SCALE = 8.0
_PHANTOM_SIGNAL = 1000.0

PreparedSeries = Callable[..., tuple[Path, dict[str, object]]]
StubDcm2niix = Callable[..., Path]


def _synthetic_series(
    n: int = 32, z: int = 3, t: int = 40, seed: int = 0
) -> np.ndarray:
    """A bright central disk over a noisy background: (n, n, z, t), float64."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    base = np.where(disk, _PHANTOM_SIGNAL, 0.0)
    floor = np.abs(rng.normal(scale=_BACKGROUND_SCALE, size=(n, n, z, t)))
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    return np.asarray(base[:, :, None, None] + noise + floor, dtype=np.float64)


@pytest.fixture
def prepared_series(tmp_path: Path) -> PreparedSeries:
    """Return a factory writing one analyzable phantom NIfTI + sidecar pair.

    Each call gets its own subdirectory (so the NIfTI can be freely renamed
    into a stub converter's output without colliding), and returns the NIfTI
    path plus the sidecar dict as written beside it -- a caller layers on
    whatever `SeriesNumber`/`SeriesDescription`/acquisition fields `naming`
    needs before handing it to `stub_dcm2niix`.
    """
    counter = iter(range(10_000))

    def factory(
        name: str = "scan", t: int = 40, seed: int = 0, flip: float = 77.0
    ) -> tuple[Path, dict[str, object]]:
        directory = tmp_path / f"prepared-{next(counter)}"
        directory.mkdir()
        data = _synthetic_series(t=t, seed=seed)
        img = nib.Nifti1Image(data.astype(np.uint16), affine=np.eye(4))
        img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
        img.header.set_xyzt_units("mm", "sec")
        nifti_path = directory / f"{name}.nii.gz"
        nib.save(img, str(nifti_path))
        sidecar: dict[str, object] = {
            "PhaseEncodingDirection": "j",
            "FlipAngle": flip,
        }
        (directory / f"{name}.json").write_text(json.dumps(sidecar))
        return nifti_path, sidecar

    return factory


@pytest.fixture
def stub_dcm2niix(tmp_path: Path) -> StubDcm2niix:
    """Return a factory building a stub dcm2niix from `{stem: (nifti, sidecar)}`.

    `nifti`/`sidecar` are what `prepared_series` returns, `sidecar` merged with
    whatever naming fields (`SeriesNumber`, `AcquisitionDateTime`,
    `SeriesDescription`, ...) the caller adds. The script parses only what
    `dcm2niix.build_args` actually passes -- the `-o DIR` this test cares
    about -- and otherwise ignores its arguments, the same restraint
    `fmri-qa-core`'s `fake_dcm2niix` shows.
    """

    def build(series: dict[str, tuple[Path, dict[str, object]]]) -> Path:
        script = tmp_path / "stub-dcm2niix"
        payload = {
            stem: (str(nifti), sidecar) for stem, (nifti, sidecar) in series.items()
        }
        script.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import shutil\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"series = {payload!r}\n"
            "args = sys.argv[1:]\n"
            "out = Path(args[args.index('-o') + 1])\n"
            'print("Chris Rorden\'s dcm2niiX version v1.0.20260724 (JP2:OpenJPEG)")\n'
            "for stem, (nifti, sidecar) in series.items():\n"
            "    shutil.copy(nifti, out / f'{stem}.nii.gz')\n"
            "    (out / f'{stem}.json').write_text(json.dumps(sidecar))\n"
            "sys.exit(0)\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    return build


@pytest.fixture
def dicom_dir(tmp_path: Path) -> Path:
    """A dummy non-empty directory standing in for a real DICOM source.

    `stub_dcm2niix` never reads it -- only `import_dicom`'s own `source.is_dir()`
    guard looks at it -- so its content does not matter, only that it exists.
    """
    directory = tmp_path / "dicom"
    directory.mkdir()
    (directory / "IM001").write_bytes(b"not a real DICOM file")
    return directory
