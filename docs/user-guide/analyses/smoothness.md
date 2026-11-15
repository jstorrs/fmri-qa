# Smoothness and point spread

The Weisskoff RDC on the [stability](stability.md) page is confounded by spatial
smoothness. A smoother noise field decorrelates more slowly, so an otherwise
identical scanner obtains a larger RDC when its reconstruction applies more
filtering. This analysis therefore measures smoothness directly and separately
for each axis. The phase-encode and readout axes are filtered differently, and a
single combined figure would conceal the difference.

Two results are reported. The first is the Gaussian full width at half maximum
(FWHM) of the noise field along each in-plane axis, following AFNI's `3dFWHMx`
(Cox, 1996). The second is a directional point-spread profile, the empirical
shape of the blur as a function of lag, which shows whether the point-spread
function (PSF) is Gaussian or has the long tails that a reconstruction filter or
interpolation can introduce.

## Preparation of the noise field

The estimate is computed from the detrended fluctuations of the pipeline, the
residual field on which every other noise measurement is based, restricted to
the phantom mask. Each voxel is first standardized robustly over time:

$$\hat r_v(t) = \frac{r_v(t) - \operatorname{median}_t r_v}
{\operatorname{median}_t \lvert r_v - \operatorname{median}_t r_v \rvert}$$

This corresponds to AFNI's `-unif` option, which its `-detrend` path enforces.
Without it, a fluctuation amplitude that varies across the phantom would be
reported as a variation in *correlation*. A voxel that is constant over time has
no median absolute deviation (MAD) by which to divide and is removed from the
working mask.

## The FWHM estimate

For a white-noise field that has been smoothed, the width of the smoothing
kernel relates the variance of forward first differences along an axis to the
variance of the voxels. This is AFNI's Classic estimator,
`mri_estimate_FWHM_1dif`. Over pairs of neighbors that are *both* in the mask,

$$\mathrm{arg} = 1 - \frac{1}{2}\,
\frac{\operatorname{var}(\hat r_{i+1} - \hat r_i)}{\operatorname{var}(\hat r)},
\qquad
\sigma = \sqrt{\frac{-1}{4 \ln \mathrm{arg}}},
\qquad
\mathrm{FWHM} = \sqrt{8 \ln 2}\;\sigma$$

in voxels, and multiplied by the voxel size to give millimeters. An axis for
which $\mathrm{arg}$ falls outside $(0, 1)$, through too little correlation to
resolve or too few in-mask pairs, yields NaN and not the logarithm of a
non-positive value.

Each fluctuation frame is estimated independently, and the frames are combined
by their geometric mean (AFNI's `-geom`), the convention AFNI adopts for
scale-like quantities. The axes are labeled by direction: `fwPE` along the
phase-encode axis and `fwRO` along the readout axis. A combined value, the
geometric mean of the two directions (AFNI's `ccomb`), is also stored. It is the
only value that remains when no phase-encode axis has been resolved, in which
case the two directional fields are absent and the axes are named `axis0` and
`axis1` in place of `PE` and `RO`.

## The point-spread profiles

The noise field is white noise convolved with a point-spread function, so its
normalized spatial autocorrelation is the autocorrelation of the PSF. For a
Gaussian PSF this equals the square of the PSF, so the square of the measured
autocorrelation at each lag gives the empirical point-spread profile:

$$\mathrm{PSF}_{\text{emp}}(d) = \rho(d)^2, \qquad
\rho(d) = \frac{\langle (\hat r_{i+d} - \bar{\hat r})
(\hat r_i - \bar{\hat r}) \rangle}{\operatorname{var}(\hat r)}$$

evaluated over in-mask neighbor pairs for lags $d = 0 \dots 10$ voxels, or fewer
if the image is smaller. For comparison, the analysis samples the Gaussian
implied by the measured FWHM,

$$\mathrm{PSF}_{\text{model}}(x) = \exp\!\left(-\frac{x^2}{2\sigma^2}\right),
\qquad \sigma = \frac{\mathrm{FWHM}}{\sqrt{8 \ln 2}}$$

on a grid of 100 points spanning a plotting range that the *analysis* selects,
so that a report draws the intended curve without deriving it again. A narrower
curve indicates a sharper direction. Empirical points that depart from the
Gaussian indicate a non-Gaussian, typically long-tailed, point spread. This
construction follows from the Gaussian random-field model that the FWHM estimate
already assumes.

The lag abscissas are lengths in the unit of the FWHM, so they differ between
the two directions whenever the voxel is anisotropic. For this reason they are
stored as a full two-dimensional array and not as a shared axis.

## Example

```{eval-rst}
.. plot::
   :caption: Empirical point-spread points over the Gaussian implied by the measured FWHM, per direction.
   :filename-prefix: smoothness-psf

   import matplotlib.pyplot as plt

   import phantom

   analysis = phantom.analysis()
   psf = analysis.curves.psf

   fig, axes = plt.subplots(figsize=(5.8, 4.0), layout="constrained")
   for index, label in enumerate(psf.labels):
       color = f"C{index}"
       axes.plot(
           psf.model_x[index],
           psf.model[index],
           "-",
           color=color,
           lw=1.3,
           label=f"{label} Gaussian, FWHM {psf.fwhm[index]:.2f} {psf.unit}",
       )
       axes.plot(
           psf.displacement[index],
           psf.empirical[index],
           "o",
           ms=4,
           color=color,
           label=f"{label} measured",
       )
   axes.set_xlim(0, psf.xmax)
   axes.set_xlabel(f"displacement ({psf.unit})")
   axes.set_ylabel("point spread (normalized)")
   axes.legend(fontsize="small")
```

The synthetic phantom is blurred isotropically, so its two directions nearly
coincide. In a real acquisition they separate to the extent that the
reconstruction filters the two axes differently.

## Stored quantities

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.fwhm` | attribute, double | combined (AFNI `ccomb`) FWHM of the noise field, in `fwhm_unit` |
| `measurements.fwhm_pe` | attribute, double | FWHM along the phase-encode axis; **absent** when no phase-encode axis resolved |
| `measurements.fwhm_ro` | attribute, double | FWHM along the readout axis; absent under the same condition |
| `measurements.fwhm_unit` | attribute, text | `mm` when the voxel size is known, else `vox`; governs all three above |
| `curves.psf.displacement` | variable `(psf_direction, psf_lag)` | the lag each empirical point was sampled at, in `fwhm_unit` |
| `curves.psf.empirical` | variable `(psf_direction, psf_lag)`, 1 | the measured point-spread profile |
| `curves.psf.model_x` | variable `(psf_direction, psf_model_sample)` | the abscissa the model curve is sampled on |
| `curves.psf.model` | variable `(psf_direction, psf_model_sample)`, 1 | the Gaussian implied by the measured FWHM |
| `psf_direction` | coordinate, flags | the two directions, phase-encode first; the names are the document's, since they are `PE`/`RO` on most runs and `axis0`/`axis1` when no axis resolved |
| `psf_lag` | coordinate, index | sample along the empirical profile |
| `psf_model_sample` | coordinate, index | sample along the model curve |
| `curves.psf.labels` | attribute, text | the two direction names, phase-encode first, as one line: `PE RO`, or `axis0 axis1` when no axis resolved |
| `curves.psf.fwhm` | attribute, double[2] | the per-direction FWHM the model curves are drawn from, in `curves.psf.unit` |
| `curves.psf.unit` | attribute, text | `mm` or `vox`: the unit of both abscissas and of `curves.psf.fwhm` |
| `curves.psf.xmax` | attribute, double | the plotting range the analysis chose, so a plot draws the curve it meant |

The two PSF abscissas carry no `units` attribute, because the unit depends on
the header of the analyzed scan (millimeters or voxels). `curves.psf.unit`
records it.

`measurements.fwhm` is NaN when the estimator could not resolve the smoothness
at all. `fwhm_pe` and `fwhm_ro` are *absent*, and not NaN, only when no
phase-encode axis was resolved, because the phase-encode and readout directions
are then undefined. The metrics table prints `?` for them and the JSON record
gives `null`. The arrays are still stored, under the `axis0` and `axis1` labels.

## References

- Cox RW. AFNI: software for analysis and visualization of functional magnetic
  resonance neuroimages. *Comput Biomed Res* 1996;29:162–173.
  [doi:10.1006/cbmr.1996.0014](https://doi.org/10.1006/cbmr.1996.0014)
  `3dFWHMx` supplies the Classic first-difference estimator, the `-unif`
  standardization, the `-geom` aggregation across frames, and the `ccomb`
  combined value. See also `notes/3dFWHMx_algorithms.md` in the repository.
