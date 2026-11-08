"""A warning core raises on io's behalf still names the caller's line.

Loading an old analysis migrates it, and loading a scan reads its sidecar
through core's rules; `fmriqa.warn` reports both. The call passes through
`fmriqa_io` on the way, so its frames must be skipped as well as core's for the
warning to land on the line that loaded the file.
"""

import json
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np

import fmriqa_io

_V1 = Path(__file__).parent / "fixtures" / "schema_v1.qa.npz"


def test_a_migration_warning_names_the_callers_line() -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fmriqa_io.load_analysis(_V1)
    assert record, "loading a v1 analysis should warn that it was migrated"
    assert {w.filename for w in record} == {__file__}


def test_a_warning_names_the_callers_line_through_load_scan(tmp_path: Path) -> None:
    img = nib.Nifti1Image(np.ones((8, 8, 2, 6), dtype=np.uint16), affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    img.header.set_xyzt_units(xyz="mm")
    nifti = tmp_path / "scan.nii.gz"
    nib.save(img, str(nifti))
    (tmp_path / "scan.json").write_text(
        json.dumps({"RepetitionTime": 2.0, "EchoTime": "thirty"})
    )
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fmriqa_io.load_scan(nifti)
    matching = [w for w in record if "sidecar EchoTime" in str(w.message)]
    assert len(matching) == 1, [str(w.message) for w in record]
    assert matching[0].filename == __file__
