# Smoothness and point spread

## What it is for

The Weisskoff RDC on the [stability](stability.md) page is confounded by spatial
smoothness. A smoother noise field decorrelates more slowly, so an otherwise
identical scanner scores a larger RDC if its reconstruction filters more. So
this page measures smoothness directly, per axis: the phase-encode and readout
axes are filtered differently, and one combined number would hide that.

It publishes two things. One is the Gaussian FWHM of the noise field along each
in-plane axis, following AFNI's `3dFWHMx`. The other is a directional
point-spread profile, the empirical shape of the blur at each lag. It shows
whether the point spread is Gaussian or has the long tails a reconstruction
filter or interpolation can leave.

## Method

### Preparing the noise field

The estimate runs on the pipeline's detrended fluctuations (the residual field
every other noise measurement uses), restricted to the phantom mask. Each voxel
is first robustly standardized over time:

$$\hat r_v(t) = \frac{r_v(t) - \operatorname{median}_t r_v}
{\operatorname{median}_t \lvert r_v - \operatorname{median}_t r_v \rvert}$$

This is AFNI's `-unif`, which its `-detrend` path forces on. Without it, raw
fluctuation amplitude that varies across the phantom would be reported as
varying *correlation*. A voxel constant over time has no MAD to divide by and is
dropped from the working mask.

### The Classic FWHM

For a smoothed white-noise field, the smoothing kernel width ties the variance
of forward first differences along an axis to the voxel variance. This is AFNI's
Classic `mri_estimate_FWHM_1dif` estimator. Over neighbor pairs that are *both*
in the mask,

$$\mathrm{arg} = 1 - \frac{1}{2}\,
\frac{\operatorname{var}(\hat r_{i+1} - \hat r_i)}{\operatorname{var}(\hat r)},
\qquad
\sigma = \sqrt{\frac{-1}{4 \ln \mathrm{arg}}},
\qquad
\mathrm{FWHM} = \sqrt{8 \ln 2}\;\sigma$$

in voxels, multiplied by the voxel size for millimeters. An axis whose
$\mathrm{arg}$ leaves $(0, 1)$ (too little correlation to resolve, or too few
in-mask pairs) gives NaN, not the logarithm of a non-positive value.

Each fluctuation frame is estimated independently and the frames are combined
by geometric mean (AFNI's `-geom`), as AFNI does for scale-like quantities. The
axes are labeled by direction: `fwPE` along phase-encode, `fwRO` along readout.
A combined figure (AFNI's `ccomb`, the geometric mean of the two directions) is
published too. It is the one number left when no phase-encode axis resolved, in
which case the two directional fields are absent and the axes are named
`axis0`/`axis1` instead of `PE`/`RO`.

### The point-spread curves

The noise field is a point-spread function convolved with white noise, so its
normalized spatial autocorrelation is the autocorrelation of the PSF. For a
Gaussian PSF that equals the PSF squared, so squaring the measured
autocorrelation at each lag gives the empirical point-spread profile:

$$\mathrm{PSF}_{\text{emp}}(d) = \rho(d)^2, \qquad
\rho(d) = \frac{\langle (\hat r_{i+d} - \bar{\hat r})
(\hat r_i - \bar{\hat r}) \rangle}{\operatorname{var}(\hat r)}$$

taken over in-mask neighbor pairs, for lags $d = 0 \dots 10$ voxels (truncated
to the image if it is smaller). Against it the analysis samples the Gaussian the
measured FWHM implies,

$$\mathrm{PSF}_{\text{model}}(x) = \exp\!\left(-\frac{x^2}{2\sigma^2}\right),
\qquad \sigma = \frac{\mathrm{FWHM}}{\sqrt{8 \ln 2}}$$

on a grid of 100 points over a plotting range the *analysis* chooses, so a
report draws the intended curve and does not re-derive it. A narrower curve is a
sharper direction. Empirical points that fall off the Gaussian flag a
non-Gaussian, typically long-tailed, point spread.

The lag abscissas are lengths in the FWHM's unit, so they differ between the two
directions whenever the voxel is anisotropic. That is why they are stored as a
full 2-D array, not a shared axis.

## What it looks like

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

The synthetic phantom is smoothed isotropically in k-space, so its two
directions nearly coincide. On a real acquisition they separate by however much
the reconstruction filters the two axes differently.

## What it contributes to the analysis file

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
the analysis file's header (millimeters or voxels), and `curves.psf.unit` records it.

`measurements.fwhm` is NaN when the estimator could not resolve smoothness at
all. `fwhm_pe` and `fwhm_ro` go *absent* rather than NaN only when no
phase-encode axis resolved, because "along PE" and "along RO" do not exist then. The metrics table
prints `?` for them and the JSON record spells them `null`. The arrays are still
published, under the `axis0`/`axis1` labels.

## References

- AFNI `3dFWHMx`. The Classic first-difference estimator, `-unif`
  standardization, `-geom` aggregation across frames, and the `ccomb` combined
  figure. See also `notes/3dFWHMx_algorithms.md` in this repository.
- The point-spread construction (squaring the measured autocorrelation) follows
  from the Gaussian random-field model the FWHM estimate already assumes.
