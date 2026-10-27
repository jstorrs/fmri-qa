"""`write_phantom` and `phantom_scan` describe the same scan.

`phantom_scan` is built in memory so core's tests need no file. This pins it to
what `QAScan.from_nifti` reads back from the file.
"""

from pathlib import Path

import numpy as np
import pytest

import fmriqa
from fmriqa.testing import phantom_scan
from fmriqa_io.testing import write_phantom


@pytest.mark.parametrize(
    ("n", "z", "t", "seed", "flip"),
    [(32, 3, 40, 0, 77.0), (24, 2, 12, 5, 52.5)],
    ids=["defaults", "non-default"],
)
def test_the_file_loads_as_the_in_memory_phantom(
    tmp_path: Path, n: int, z: int, t: int, seed: int, flip: float
) -> None:
    nifti = write_phantom(tmp_path, n=n, z=z, t=t, seed=seed, flip=flip)
    loaded = fmriqa.QAScan.from_nifti(nifti)
    expected = phantom_scan(n=n, z=z, t=t, seed=seed, flip=flip)

    assert np.array_equal(loaded.data, expected.data)
    assert loaded.affine is not None
    assert expected.affine is not None
    assert np.array_equal(loaded.affine, expected.affine)
    assert loaded.tr == expected.tr
    assert loaded.pe_axis == expected.pe_axis
    assert loaded.meta == expected.meta
    assert loaded.slope == expected.slope
    assert loaded.inter == expected.inter
    assert loaded.stored_integer == expected.stored_integer


def test_the_name_picks_the_file_stem(tmp_path: Path) -> None:
    nifti = write_phantom(tmp_path, "run1")
    assert nifti == tmp_path / "run1.nii.gz"
    assert (tmp_path / "run1.json").is_file()
