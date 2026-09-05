"""Directional noise smoothness: result-object algebra and the FWHM estimator.

`SmoothnessResult` conversions (voxels<->mm, PE/RO labelling, combined geomean,
PSF) are pinned against hand values; `estimate_smoothness` is checked to recover
the direction of an anisotropically smoothed noise field (larger FWHM along the
smoothed axis).
"""

import numpy as np
from scipy.ndimage import gaussian_filter1d

from fmriqc.metrics.smoothness import SmoothnessResult, estimate_smoothness


def test_smoothness_result_converts_voxels_to_mm_and_labels_axes() -> None:
    res = SmoothnessResult(
        fwhm_vox=(2.0, 4.0),
        lags=np.arange(3),
        acf=np.array([[1.0, 0.5, 0.25], [1.0, 0.8, 0.64]]),
        voxel_mm=(1.5, 1.5),
        pe_axis=1,
    )
    assert np.isclose(res.fwhm_axis(0), 3.0)  # 2.0 vox * 1.5 mm
    assert np.isclose(res.fwhm_axis(1), 6.0)  # 4.0 vox * 1.5 mm
    assert res.ro_axis == 0
    assert res.fwhm_pe is not None and res.fwhm_ro is not None
    assert np.isclose(res.fwhm_pe, 6.0)  # pe_axis=1
    assert np.isclose(res.fwhm_ro, 3.0)  # ro_axis=0
    # combined = geometric mean of the per-axis FWHM (AFNI ccomb), in mm here.
    assert np.isclose(res.fwhm_combined_vox, np.sqrt(8.0))
    assert np.isclose(res.fwhm, np.sqrt(3.0 * 6.0))
    assert np.allclose(res.displacement(0), [0.0, 1.5, 3.0])
    assert np.allclose(res.psf_empirical(1), res.acf[1] ** 2)
    assert np.isclose(res.psf_model(np.array([0.0]), 0)[0], 1.0)  # PSF peak = 1


def test_smoothness_result_without_voxel_size_reports_voxels_and_no_direction() -> None:
    res = SmoothnessResult(
        fwhm_vox=(2.0, 4.0),
        lags=np.arange(3),
        acf=np.full((2, 3), np.nan),
        voxel_mm=None,
        pe_axis=None,
    )
    assert np.isclose(res.fwhm_axis(1), 4.0)  # voxels, no mm scaling
    assert res.fwhm_pe is None and res.fwhm_ro is None and res.ro_axis is None
    assert res.fwhm_mm is None
    assert np.isclose(res.fwhm, np.sqrt(8.0))  # combined, in voxels


def test_estimate_smoothness_recovers_the_smoothed_direction() -> None:
    # White noise smoothed only along axis 0: the noise correlation length -- and
    # so the estimated FWHM -- must be larger along axis 0 than axis 1.
    rng = np.random.default_rng(0)
    noise = rng.normal(size=(24, 24, 30))
    smoothed = gaussian_filter1d(noise, sigma=2.0, axis=0)
    mask = np.ones((24, 24), dtype=bool)

    res = estimate_smoothness(smoothed, mask, voxel_mm=(1.0, 1.0), pe_axis=0)
    assert res.fwhm_vox[0] > res.fwhm_vox[1]
    assert res.fwhm_pe is not None and res.fwhm_ro is not None
    assert res.fwhm_pe > res.fwhm_ro  # pe_axis=0 is the smoothed axis
    assert res.lags[0] == 0
    assert np.allclose(res.acf[:, 0], 1.0)  # zero-lag autocorrelation is 1
