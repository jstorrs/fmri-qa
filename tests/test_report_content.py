"""The per-metric catalog: tiles and characterization share one source."""

import json

import nibabel as nib
import numpy as np

import fmriqc as q
from fmriqc.report import content


def _result(tmp_path):
    n, z, t = 32, 3, 40
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    data = (
        np.where(disk, 1000.0, 0.0)[:, :, None, None]
        + rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    )
    img = nib.Nifti1Image(data, affine=np.eye(4))
    img.header.set_zooms((3.0, 3.0, 3.0, 2.0))
    path = tmp_path / "scan.nii.gz"
    nib.save(img, str(path))
    (tmp_path / "scan.json").write_text(json.dumps({"PhaseEncodingDirection": "j"}))
    return q.run_qa(q.QAScan.from_nifti(str(path)), roi_size=9)


def test_tiles_and_characterization_share_labels_and_values(tmp_path) -> None:
    m = _result(tmp_path).metrics
    tiles = content.metric_tiles(m)
    rows = content.characterization_rows(m)
    # Same metrics, same order, same formatted values -- one catalog drives both.
    assert [label for label, _ in tiles] == [doc.label for doc, _ in rows]
    assert [value for _, value in tiles] == [value for _, value in rows]


def test_every_metric_doc_is_documented(tmp_path) -> None:
    m = _result(tmp_path).metrics
    for doc in content.METRIC_DOCS:
        assert doc.label and doc.definition and doc.method
        assert doc.fmt(m)  # the formatter returns a non-empty string
