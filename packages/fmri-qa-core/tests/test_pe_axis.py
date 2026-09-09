"""Phase-encode axis resolution and its priority chain.

The PE axis drives the ghost masks and the report's row/col labelling, and its
source order is load-bearing: the BIDS sidecar `PhaseEncodingDirection` is
authoritative and the NIfTI `dim_info` phase field is the fallback. If neither
carries one, `from_nifti` says so and leaves the axis unresolved for `run_qa` to
estimate from the ghost (see `test_pipeline.py`). These tests lock that order in
at both the helper and the `from_nifti` level.
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


def _write_scan(
    directory: Path,
    sidecar: dict,
    phase: int | None = None,
) -> Path:
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


def test_meta_pe_dir_from_sidecar_phase_encoding_direction(tmp_path) -> None:
    """`pe_dir` for a `PhaseEncodingDirection` sidecar, with no header fallback.

    `PhaseEncodingDirection` carries no row/col wording of its own, so `pe_dir`
    must come from the resolved `pe_axis` (`_pe_axis_from_sidecar` already
    turned "j" into axis 1) rather than a second, direct re-derivation from the
    sidecar in `_pe_direction` -- pinning the row/col label this sidecar shape
    produces now that that re-derivation is gone.
    """
    nifti = _write_scan(tmp_path, {"PhaseEncodingDirection": "j"}, phase=None)
    scan = q.QAScan.from_nifti(nifti)
    assert scan.pe_axis == 1
    assert scan.meta is not None
    assert scan.meta.pe_dir == "col"


def test_from_nifti_falls_back_to_header_dim_info(tmp_path) -> None:
    # No PE field in the sidecar; the header dim_info phase axis is used.
    nifti = _write_scan(tmp_path, {"FlipAngle": 77}, phase=1)
    assert q.QAScan.from_nifti(nifti).pe_axis == 1


def test_from_nifti_leaves_an_unnamed_axis_to_the_pipeline(tmp_path) -> None:
    """Neither source present: say so and stop, rather than guess here.

    The loader reads metadata; the Nyquist-ghost estimate is physics, and making
    it here would point the I/O layer at the metrics above it *and* measure a
    different image than the one analyzed. The warning names both ways out — the
    estimate `run_qa` will make, and the `--pe-axis` that skips it.
    """
    nifti = _write_scan(tmp_path, {"FlipAngle": 77}, phase=None)
    with pytest.warns(UserWarning, match="estimate it from the Nyquist ghost"):
        scan = q.QAScan.from_nifti(nifti)
    assert scan.pe_axis is None
