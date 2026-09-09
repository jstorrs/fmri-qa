"""Phase-encode axis resolution and its priority chain.

The PE axis drives the ghost masks and the report's row/col labelling, and its
source order is load-bearing: the BIDS sidecar is authoritative -- dcm2niix's
`PhaseEncodingDirection` and `PhaseEncodingAxis` ahead of the raw DICOM row/col
tag -- and the NIfTI `dim_info` phase field is the fallback. If neither
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
        # What dcm2niix writes when it resolved the axis but not the polarity.
        ({"PhaseEncodingAxis": "i"}, 0),
        ({"PhaseEncodingAxis": "j"}, 1),
        ({"PhaseEncodingAxis": "k"}, 2),
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
        {"PhaseEncodingAxis": "junk"},
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


def test_the_axis_dcm2niix_derived_wins_over_the_raw_dicom_tag() -> None:
    """`PhaseEncodingAxis` outranks `InPlanePhaseEncodingDirectionDICOM`.

    Both name an axis, but not in the same terms. The DICOM tag is (0018,1312)
    verbatim, in DICOM's row/col *image* frame, and reaching an array axis from
    it needs the row = i mapping `PE_ROWCOL` records having verified on one
    vendor and one orientation. `PhaseEncodingAxis` is dcm2niix's conclusion,
    already in NIfTI array letters, with no mapping of ours in between -- so it
    is the one to believe when they disagree.
    """
    sidecar = {
        "PhaseEncodingAxis": "i",  # axis 0
        "InPlanePhaseEncodingDirectionDICOM": "COL",  # axis 1
    }
    assert _pe_axis_from_sidecar(sidecar) == 0


def test_a_stated_polarity_wins_over_an_axis_alone() -> None:
    """The stronger of dcm2niix's two answers is still tried first.

    They cannot disagree about the axis in practice; the order is what makes
    that a fact about the code rather than about dcm2niix.
    """
    sidecar = {"PhaseEncodingDirection": "j-", "PhaseEncodingAxis": "i"}
    assert _pe_axis_from_sidecar(sidecar) == 1


def test_a_malformed_axis_is_named_by_the_field_it_came_from() -> None:
    """Two fields share one parser, so the error has to say which one failed."""
    with pytest.raises(q.InvalidScanError) as excinfo:
        _pe_axis_from_sidecar({"PhaseEncodingAxis": "sideways"})

    assert excinfo.value.field == "PhaseEncodingAxis"


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
    can only come from the resolved `pe_axis` -- `_pe_axis_from_sidecar` already
    turned "j" into axis 1, and `_pe_direction` names that axis rather than
    re-deriving anything from the sidecar.
    """
    nifti = _write_scan(tmp_path, {"PhaseEncodingDirection": "j"}, phase=None)
    scan = q.QAScan.from_nifti(nifti)
    assert scan.pe_axis == 1
    assert scan.meta is not None
    assert scan.meta.pe_dir == "col"


def test_from_nifti_reads_an_axis_only_sidecar(tmp_path) -> None:
    """The shape `fmri-qa-import` produces for a series with no vendor polarity.

    Before `PhaseEncodingAxis` was read, such a series fell through to the
    header's `dim_info` -- here deliberately stamped with the wrong axis, so the
    test fails if the fall-through comes back.
    """
    nifti = _write_scan(tmp_path, {"PhaseEncodingAxis": "j"}, phase=0)

    assert q.QAScan.from_nifti(nifti).pe_axis == 1


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


def test_pe_dir_names_the_axis_that_was_resolved_not_the_dicom_word(
    tmp_path,
) -> None:
    """A contradicting DICOM tag no longer overrides the direction word.

    `_pe_axis_from_sidecar` prefers dcm2niix's `PhaseEncodingAxis` (axis 0) over
    `InPlanePhaseEncodingDirectionDICOM` (col, axis 1). `_pe_direction` used to
    read that tag's wording directly, so the scan came back naming axis 0 and
    calling it "col" -- and the report showed a direction that was not the axis
    the ghost masks were built on. The word follows the axis now.
    """
    nifti = _write_scan(
        tmp_path,
        {"PhaseEncodingAxis": "i", "InPlanePhaseEncodingDirectionDICOM": "COL"},
    )
    scan = q.QAScan.from_nifti(nifti)

    assert scan.pe_axis == 0
    assert scan.meta is not None
    assert scan.meta.pe_dir == "row"


def test_a_through_plane_axis_leaves_the_direction_unnamed(tmp_path) -> None:
    """`k` is a well-formed answer to a question this pipeline does not ask.

    The single-slice pipeline cannot measure on the through-plane axis, so
    `run_qa` estimates one from the ghost instead -- and a row/col word taken
    from the sidecar's DICOM tag here would name neither the sidecar's axis nor
    the estimated one. None lets the label fall through to the axis actually
    used (see `analysis.build._pe_label`).
    """
    nifti = _write_scan(
        tmp_path,
        {"PhaseEncodingDirection": "k", "InPlanePhaseEncodingDirectionDICOM": "ROW"},
    )
    scan = q.QAScan.from_nifti(nifti)

    assert scan.pe_axis == 2
    assert scan.meta is not None
    assert scan.meta.pe_dir is None
