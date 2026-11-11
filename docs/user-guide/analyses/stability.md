# FBIRN stability

## What it is for

This is the core of the Glover/FBIRN phantom protocol (Friedman & Glover, 2006)
and the reason the rest of the package exists. A stationary phantom emits a
constant signal, so anything that changes in the measured time course comes from
the scanner. Four scalars say how much changes and on what time scale: SNR
against the static spatial noise, SFNR against the temporal fluctuation noise,
and the percentages of the mean signal due to drift and to residual fluctuation.
A fifth, the Weisskoff radius of decorrelation, says how far the noise is from
independent voxel to voxel, which decides whether averaging over an ROI buys
precision.

Every number is measured over one fixed square ROI on one slice, so it is
comparable across sessions only if the localization is (see
[phantom localization](localization.md)). The trim and detrending below are
shared by every analysis. The outlier, smoothness and spike analyses read the
residual field this detrending produces.

## Method

### The preprocessing every analysis shares

The first volumes of an EPI run are not at steady state. Longitudinal
magnetization is still approaching equilibrium, so the signal decays steeply
through them. They are dropped before anything is measured:

$$n_{\text{trim}} = \max\!\left(\operatorname{round}\!\left(
\frac{t_{\text{trim}}}{\mathrm{TR}}\right),\, 0\right)$$

with $t_{\text{trim}}$ the `--trim-sec` setting (5 s by default). Every frame
index in the analysis file counts from the *trimmed* series. Add `provenance.n_trimmed`
for the acquired volume number.

One slice is then selected (the middle slice under `--center image`) and each
voxel's time course is detrended. The default fit is a Legendre polynomial of
degree

$$d = \operatorname{round}\!\left(\frac{N\,\mathrm{TR}}{200\ \mathrm{s}}\right)$$

so fit complexity follows run *duration*, not frame count: a 200 s run gets one
degree of freedom of drift, a 600 s run three. `--detrend spline` instead fits a
least-squares B-spline of degree 2 with
$\operatorname{round}(N\,\mathrm{TR}/256\ \mathrm{s}) - 1$ interior knots. The
resolved order is published with the settings, because only the pipeline knows
it. A fit with at least as many coefficients as frames is refused. It would
leave no residual for the noise metrics, and the run would score as a perfectly
stable scanner.

Writing $I_v(t)$ for the voxel time series, the fit gives a trend $T_v(t)$ and a
residual (the *fluctuation*) $r_v(t) = I_v(t) - T_v(t)$. Two derived images
follow, both published:

$$\bar S_v = \frac{1}{N}\sum_t I_v(t), \qquad
\sigma_v = \sqrt{\frac{1}{N}\sum_t r_v(t)^2}$$

the temporal mean (the *signal* image) and the temporal RMS of the residual (the
*fluctuation noise* image). Detrending commutes with the spatial mean, so
ROI-averaging the per-voxel fluctuations equals detrending the ROI-mean time
course, and the ROI curves here agree with the per-voxel images by construction.

### SNR

The FBIRN SNR measures the signal against the *static spatial* noise, estimated
from a difference image that cancels the phantom: the sum of the odd frames
minus the sum of the even frames.

$$D_v = \sum_{t \text{ odd}} I_v(t) \;-\; \sum_{t \text{ even}} I_v(t), \qquad
\mathrm{SNR} = \frac{\bar S_{\mathrm{ROI}}}
{\sqrt{\operatorname{var}_{\mathrm{ROI}}(D)\,/\,N}}$$

where $\bar S_{\mathrm{ROI}}$ is the ROI mean of the signal image and
$\operatorname{var}_{\mathrm{ROI}}(D)$ the variance of $D$ across the ROI's
voxels. The difference uses an *even* number of frames, dropping a trailing
frame if needed. With an odd count the two subsets differ by a whole frame, so
$D$ carries signal and the phantom's spatial shading, not noise, dominates the
variance. The signal still averages the full series. SNR is NaN for a series too
short to hold one odd/even pair, and when $D$ has no variance across the ROI.

### SFNR

SFNR measures the same signal against the *temporal fluctuation* noise, voxel
by voxel, and averages the ratio over the ROI $R$:

$$\mathrm{SFNR} = \frac{1}{|R|}\sum_{v \in R} \frac{\bar S_v}{\sigma_v}$$

It is NaN if any ROI voxel has no fluctuation noise, since an average is only as
well defined as its voxels. (The per-voxel SFNR *image* is drawn, not reduced.
It floors the divisor so a noiseless voxel renders instead of blanking the map.)

### Drift and fluctuation

Both are percentages of the ROI mean signal, from the fitted trend and the
residual respectively:

$$\text{drift \%} = 100\,\frac{\max_t \bar T(t) - \min_t \bar T(t)}
{\bar S_{\mathrm{ROI}}}, \qquad
\text{fluctuation \%} = 100\,\frac{\operatorname{rms}_t\, \bar r(t)}
{\bar S_{\mathrm{ROI}}}$$

with $\bar T$ and $\bar r$ the ROI-mean trend and residual. The fluctuation is
an RMS about zero, since detrending has already removed the residual's mean.
Both are NaN when the ROI mean signal is zero, with no division warning.

### The Weisskoff curve and the RDC

Averaging $k \times k$ voxels should cut the coefficient of variation by a
factor of $k$ if the noise is independent from voxel to voxel. It never quite
does, and the shortfall is the Weisskoff measurement (Weisskoff, 1996). For each
width $k = 1 \dots K$ (with $K$ the full ROI side), two coefficients of
variation are formed on the concentric $k \times k$ ROI $R_k$:

$$\mathrm{CV}(k) = \frac{\operatorname{rms}_t\,\bar r_{R_k}(t)}{\bar S_{R_k}},
\qquad
\mathrm{CV}_1(k) = \frac{\sqrt{\langle \sigma_v^2 \rangle_{v \in R_k}}}
{\bar S_{R_k}}$$

$\mathrm{CV}$ is the measured variation of the ROI-mean time course.
$\mathrm{CV}_1$ is the single-voxel variation pooled over the same ROI. The
uncorrelated-noise reference line is $\mathrm{CV}_1(K)/k$, what $\mathrm{CV}$
would be if averaging paid in full. The ratio of the two at each width is the
decorrelation factor, and the reported scalar is that ratio at the full ROI:

$$\mathrm{RDC} = \frac{\mathrm{CV}_1(K)}{\mathrm{CV}(K)}$$

read as the width of an ROI over which the noise is effectively independent. A
perfect scanner gives $\mathrm{RDC} = K$ and a real one gives less. Spatial
smoothness confounds the RDC, since smoother noise decorrelates more slowly, so
the [smoothness](smoothness.md) analysis reports an explicit FWHM beside it.

## What it looks like

The ROI time course, the trend removed from it, and the spectrum of what was
left. The spectrum is stored with DC dropped, so it starts at the first nonzero
bin and a plot needs no windowing of its own.

```{eval-rst}
.. plot::
   :caption: ROI-mean signal with its fitted trend, the detrended residual, and the residual spectrum, for the synthetic phantom.
   :filename-prefix: stability-roi-series

   import matplotlib.pyplot as plt

   import phantom

   curves = phantom.analysis().curves

   fig, (signal, residual, spectrum) = plt.subplots(
       3, 1, figsize=(6.6, 6.4), layout="constrained"
   )

   signal.plot(curves.time, curves.roi_signal, lw=0.8, label="ROI mean")
   signal.plot(curves.time, curves.roi_trend, lw=1.6, label="fitted trend")
   signal.set_ylabel("signal (a.u.)")
   signal.set_xlabel("time (s)")
   signal.legend(loc="upper right", fontsize="small")

   residual.plot(curves.time, curves.roi_residual, lw=0.8, color="C3")
   residual.axhline(0.0, lw=0.6, color="0.5")
   residual.set_ylabel("residual (a.u.)")
   residual.set_xlabel("time (s)")

   spectrum.plot(curves.spectrum_hz, curves.spectrum_magnitude, lw=0.9, color="C2")
   spectrum.set_ylabel("magnitude (a.u.)")
   spectrum.set_xlabel("frequency (Hz)")
```

The synthetic phantom's signal drifts linearly by 1% over the run, so the
fitted trend is a straight line and `drift_pct` reads about 1.

The Weisskoff plot, against the line the noise would follow if it were
independent voxel to voxel. The gap at the right-hand end is the RDC.

```{eval-rst}
.. plot::
   :caption: Measured ROI-averaged coefficient of variation against the uncorrelated-noise reference.
   :filename-prefix: stability-weisskoff

   import matplotlib.pyplot as plt

   import phantom

   analysis = phantom.analysis()
   weisskoff = analysis.curves.weisskoff

   fig, axes = plt.subplots(figsize=(5.2, 4.0), layout="constrained")
   axes.loglog(weisskoff.roi_sizes, 100 * weisskoff.cv, "o-", ms=4, label="measured")
   axes.loglog(
       weisskoff.roi_sizes, 100 * weisskoff.cv_ideal, "--", label="uncorrelated noise"
   )
   axes.set_xlabel("ROI width (voxels)")
   axes.set_ylabel("coefficient of variation (%)")
   axes.set_title(f"RDC = {analysis.measurements.rdc:.1f} voxels")
   axes.legend(fontsize="small")
   axes.grid(True, which="both", lw=0.3, alpha=0.5)
```

The four summary images the protocol is read from: the signal, the per-voxel
SFNR, the fluctuation noise, and the static (odd/even difference) noise.

```{eval-rst}
.. plot::
   :caption: The four FBIRN summary images of the synthetic phantom.
   :filename-prefix: stability-images

   import matplotlib.pyplot as plt

   import phantom

   images = phantom.analysis().images

   panels = [
       ("signal", images.signal, "a.u."),
       ("SFNR", images.sfnr, "1"),
       ("fluctuation noise", images.fluctuation_noise, "a.u."),
       ("static noise", images.static_noise, "a.u."),
   ]

   fig, axes = plt.subplots(2, 2, figsize=(6.4, 6.0), layout="constrained")
   for panel, (title, data, unit) in zip(axes.flat, panels, strict=True):
       shown = panel.imshow(data, cmap="gray")
       panel.set_title(f"{title} ({unit})", fontsize="small")
       panel.set_xlabel("col (voxels)", fontsize="x-small")
       panel.set_ylabel("row (voxels)", fontsize="x-small")
       panel.tick_params(labelsize="x-small")
       fig.colorbar(shown, ax=panel, shrink=0.82)
```

## What it contributes to the analysis file

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.snr` | attribute, double | FBIRN SNR over the summary ROI; NaN if it could not be resolved |
| `measurements.sfnr` | attribute, double | FBIRN SFNR over the summary ROI; NaN if any ROI voxel has no temporal noise |
| `measurements.rdc` | attribute, double | Weisskoff radius of decorrelation at the full ROI, in voxels |
| `measurements.drift_pct` | attribute, double | peak-to-peak of the ROI-mean trend, as a percentage of the ROI mean signal |
| `measurements.percent_fluctuation` | attribute, double | RMS of the ROI-mean residual, as a percentage of the ROI mean signal |
| `curves.time` | variable `(frame)`, s | seconds of the analyzed frame; the CF auxiliary coordinate every per-frame trace names |
| `curves.roi_signal` | variable `(frame)` | ROI-mean raw signal |
| `curves.roi_trend` | variable `(frame)` | the fitted low-frequency trend that was removed |
| `curves.roi_residual` | variable `(frame)` | ROI-mean detrended residual |
| `curves.spectrum_hz` | variable `(frequency)`, Hz | residual-spectrum frequencies, DC dropped |
| `curves.spectrum_magnitude` | variable `(frequency)` | residual-spectrum magnitude |
| `curves.weisskoff.roi_sizes` | variable `(roi_width)`, voxels | the ROI widths sampled, 1 to the full ROI side |
| `curves.weisskoff.cv` | variable `(roi_width)` | measured ROI-averaged coefficient of variation |
| `curves.weisskoff.cv_ideal` | variable `(roi_width)` | the uncorrelated-noise reference, $\mathrm{CV}_1(K)/k$ |
| `curves.weisskoff.rdc` | variable `(roi_width)` | decorrelation factor at each width; its last value is `measurements.rdc` |
| `images.signal` | variable `(row, col)` | temporal mean image |
| `images.sfnr` | variable `(row, col)` | per-voxel SFNR, zero outside the phantom mask |
| `images.fluctuation_noise` | variable `(row, col)` | temporal RMS of the detrended residuals |
| `images.static_noise` | variable `(row, col)` | the odd/even difference image SNR is measured from |
| `frame` | coordinate, index | 0-based index into the analyzed series |
| `frequency` | coordinate, Hz | the spectrum abscissa, the same values as `curves.spectrum_hz` |
| `roi_width` | coordinate, voxels | the Weisskoff abscissa, the same values as `curves.weisskoff.roi_sizes` |
| `row` | coordinate, index | image row, in array-index order |
| `col` | coordinate, index | image column, in array-index order |

Any of the five measurements can be NaN. NaN always means the estimator ran and
could not resolve the value, never that the quantity does not apply, and none is
ever absent. The settings that produced them (`trim_sec`, `detrend`, the
resolved `detrend_order`, `roi_size`, `center`) ride in the JSON document's
`settings` section; see [the analysis file](../analysis-file.md).

## References

- Friedman L, Glover GH. *Report on a multicenter fMRI quality assurance
  protocol.* J Magn Reson Imaging 2006;23:827–839. (the FBIRN protocol: SNR,
  SFNR, drift, fluctuation, the four summary images)
- Weisskoff RM. *Simple measurement of scanner stability for fMRI of BOLD
  contrast at 1.5 T.* Magn Reson Med 1996;36:643–645. (the ROI-size curve and
  the radius of decorrelation)
- AFNI `afni_proc.py` recommends detrending before any noise statistic is
  classified, so every other analysis reads the residual field defined here.
