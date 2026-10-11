"""A warning names the caller's line, not a line inside the package.

`fmriqc.warn.warn` skips every frame in the package, so the ROI warning must
land on the test's own call through both `run_qa` and `analyze`.
"""

import json
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np

import fmriqc as q

_ROI_TOO_BIG = 31  # does not fit the phantom of the 32-voxel conftest scan


def _caught(record: list[warnings.WarningMessage], text: str) -> str:
    """The one recorded warning whose message holds `text`, by filename."""
    matching = [w for w in record if text in str(w.message)]
    assert len(matching) == 1, [str(w.message) for w in record]
    return matching[0].filename


def test_a_warning_names_the_callers_line_through_from_nifti(tmp_path: Path) -> None:
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
        q.QAScan.from_nifti(nifti)
    assert _caught(record, "sidecar EchoTime") == __file__


def test_a_warning_names_the_callers_line_through_run_qa(
    tmp_path: Path, write_scan
) -> None:
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        q.run_qa(scan, q.AnalysisSettings(roi_size=_ROI_TOO_BIG))
    assert _caught(record, "not fully inside the phantom") == __file__


def test_a_warning_names_the_callers_line_through_analyze(
    tmp_path: Path, write_scan
) -> None:
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        q.analyze(scan, q.AnalysisSettings(roi_size=_ROI_TOO_BIG))
    assert _caught(record, "not fully inside the phantom") == __file__
