"""Phase-encode axis resolution and its priority chain.

The PE axis drives the ghost masks and the report's row/col labelling, and its
source order is load-bearing: the BIDS sidecar `PhaseEncodingDirection` is
authoritative, the NIfTI `dim_info` phase field is the fallback, and only if
both are absent does `from_nifti` estimate the axis from the ghost. These tests
lock that order in at both the helper and the `from_nifti` level.
"""

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

import fmriqc as q
from fmriqc.load.pe_axis import _pe_axis_from_header, _pe_axis_from_sidecar


@pytest.mark.parametrize(
    ("sidecar", "expected"),
    [
        ({"PhaseEncodingDirection": "i"}, 0),
        ({"PhaseEncodingDirection": "j"}, 1),
        ({"PhaseEncodingDirection": "k"}, 2),
        ({"PhaseEncodingDirection": "j-"}, 1),  # polarity is dropped
        ({"InPlanePhaseEncodingDirectionDICOM": "ROW"}, 0),
        ({"InPlanePhaseEncodingDirectionDICOM": "COL"}, 1),
        ({"InPlanePhaseEncodingDirectionDICOM": "col"}, 1),  # case-insensitive
        ({}, None),  # no PE field
        ({"PhaseEncodingDirection": ""}, None),  # empty string is not a direction
    ],
)
def test_pe_axis_from_sidecar(sidecar: dict, expected: int | None) -> None:
    assert _pe_axis_from_sidecar(sidecar) == expected


@pytest.mark.parametrize(
    "sidecar",
    [
        {"PhaseEncodingDirection": "junk"},
        {"PhaseEncodingDirection": "j+"},
        {"InPlanePhaseEncodingDirectionDICOM": "diagonal"},
    ],
)
def test_pe_axis_from_sidecar_rejects_malformed_values(sidecar: dict) -> None:
    with pytest.raises(q.InvalidScanError):
        _pe_axis_from_sidecar(sidecar)


def test_sidecar_bids_direction_wins_over_dicom() -> None:
    # PhaseEncodingDirection is checked before the DICOM row/col fallback.
    sidecar = {
        "PhaseEncodingDirection": "i",  # axis 0
        "InPlanePhaseEncodingDirectionDICOM": "COL",  # axis 1
    }
    assert _pe_axis_from_sidecar(sidecar) == 0


def test_pe_axis_from_header_reads_dim_info_phase() -> None:
    header = nib.Nifti1Header()
    header.set_dim_info(freq=0, phase=1, slice=2)
    assert _pe_axis_from_header(header) == 1


def test_pe_axis_from_header_none_when_unset() -> None:
    assert _pe_axis_from_header(nib.Nifti1Header()) is None


def _write_scan(directory: Path, sidecar: dict, phase: int | None = None) -> Path:
    """Write a minimal NIfTI + sidecar; optionally stamp a dim_info phase axis."""
    data = np.ones((8, 8, 2, 6), dtype=np.float32)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    if phase is not None:
        img.header.set_dim_info(freq=None, phase=phase, slice=None)
    nifti = directory / "scan.nii.gz"
    nib.save(img, str(nifti))
    (directory / "scan.json").write_text(json.dumps(sidecar))
    return nifti


def test_from_nifti_prefers_sidecar_over_header(tmp_path) -> None:
    # Sidecar says j (axis 1); header dim_info says phase axis 0. Sidecar wins.
    nifti = _write_scan(tmp_path, {"PhaseEncodingDirection": "j"}, phase=0)
    assert q.QAScan.from_nifti(nifti).pe_axis == 1


def test_from_nifti_falls_back_to_header_dim_info(tmp_path) -> None:
    # No PE field in the sidecar; the header dim_info phase axis is used.
    nifti = _write_scan(tmp_path, {"FlipAngle": 77}, phase=1)
    assert q.QAScan.from_nifti(nifti).pe_axis == 1


def test_from_nifti_falls_back_to_ghost_estimate_with_warning(tmp_path) -> None:
    # Neither source present: estimate from the ghost, warning that it did so.
    nifti = _write_scan(tmp_path, {"FlipAngle": 77}, phase=None)
    with pytest.warns(UserWarning, match="ghost estimate"):
        scan = q.QAScan.from_nifti(nifti)
    assert scan.pe_axis in (0, 1)


def test_from_nifti_no_estimate_leaves_axis_none(tmp_path) -> None:
    nifti = _write_scan(tmp_path, {"FlipAngle": 77}, phase=None)
    with pytest.warns(UserWarning, match="no phase-encode axis"):
        scan = q.QAScan.from_nifti(nifti, estimate_pe=False)
    assert scan.pe_axis is None
