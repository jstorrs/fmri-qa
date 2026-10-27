"""Verdicts the artifact publishes survive the trip through the file.

Core's `test_artifact.py` and `test_scan.py` pin what `analyze` and
`QAScan.from_nifti` put in an artifact. These check the same values read back
from disk, and that a value the reader would refuse is refused on the way in.
"""

import json
import warnings
from dataclasses import replace

import numpy as np
import pytest

import fmriqa as q
import fmriqa_io
from fmriqa.testing import synthetic_series
from fmriqa_io.testing import write_phantom


def test_a_noise_only_scan_keeps_its_failed_mask_verdict(tmp_path) -> None:
    """A failed localization stays failed through the archive."""
    noise = np.abs(np.random.default_rng(0).normal(size=(32, 32, 1, 40)))
    settings = q.AnalysisSettings(trim_sec=0, center="phantom", roi_size=3)
    with pytest.warns(UserWarning, match="no slice holds a recognizable phantom"):
        artifact = q.analyze(q.QAScan(data=noise, tr=2.0), settings)
    path = fmriqa_io.save_artifact(artifact, tmp_path / "noise.qa.nc")
    m = fmriqa_io.load_artifact(path).measurements
    assert 0.0 < m.phantom_fraction < 0.95  # the share alone would have passed
    assert m.phantom_mask_ok is False


def test_undeterminable_clipping_survives_the_archive(tmp_path) -> None:
    """ "Not determinable" round-trips as itself, not as zero counts and False."""
    scan = q.QAScan(data=synthetic_series(), tr=2.0, pe_axis=1, stored_integer=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9))
    assert artifact.measurements.clipped_any is None  # the answer before saving

    path = fmriqa_io.save_artifact(artifact, tmp_path / "undet.qa.nc")
    loaded = fmriqa_io.load_artifact(path)
    assert loaded.measurements.clipped_any is None
    assert loaded.measurements.n_clipped_kept is None


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("EchoTime", "0.03", "te"),  # a number written as text
        ("FlipAngle", True, "flip_angle"),  # JSON true is not an angle
        ("SliceThickness", [3.0], "slice_thickness"),
        ("MagneticFieldStrength", float("nan"), "field_strength"),
        ("Manufacturer", {"name": "Acme"}, "manufacturer"),
        ("SeriesDescription", ["qa"], "series"),
    ],
)
def test_a_malformed_sidecar_field_reads_back_as_unknown(
    tmp_path, key: str, value: object, field: str
) -> None:
    """What a scan with a dropped sidecar field produces is valid reader input."""
    nifti = write_phantom(tmp_path, n=16, z=2, t=12)
    sidecar = tmp_path / "scan.json"
    sidecar.write_text(json.dumps({"PhaseEncodingDirection": "j", key: value}))
    with pytest.warns(UserWarning, match=f"sidecar {key} .* recording it as unknown"):
        scan = q.QAScan.from_nifti(nifti)
    assert scan.meta is not None
    assert getattr(scan.meta, field) is None  # dropped before it reaches the file
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        artifact = q.analyze(scan, q.AnalysisSettings(trim_sec=0, roi_size=3))
    path = fmriqa_io.save_artifact(artifact, tmp_path / "qa.nc")
    assert getattr(fmriqa_io.load_artifact(path).provenance, field) is None


def test_a_bool_in_a_float_field_is_kept_for_the_archive_to_refuse(
    tmp_path, artifact
) -> None:
    """`True` is an int to Python but not a measurement; it is not made 1.0."""
    measurements = replace(artifact.measurements, snr=True)
    assert measurements.snr is True
    with pytest.raises(q.InvalidArtifactError, match=r"measurements\.snr"):
        fmriqa_io.save_artifact(
            replace(artifact, measurements=measurements), tmp_path / "qa.nc"
        )
