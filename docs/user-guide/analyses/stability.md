# FBIRN stability

The stability analysis implements the core of the Glover/FBIRN phantom protocol
(Friedman & Glover, 2006), around which the rest of the package is organized. A
stationary phantom emits a constant signal, so any variation in the measured
time course originates in the scanner. Four scalar measures characterize the
size and time scale of that variation: the signal-to-noise ratio (SNR), taken
against the static spatial noise; the signal-to-fluctuation-noise ratio (SFNR),
taken against the temporal fluctuation noise; and the percentages of the mean
signal attributable to drift and to residual fluctuation. A fifth, the radius of
decorrelation (RDC; Weisskoff, 1996), expresses how far the noise departs from
voxel-to-voxel independence, and therefore how much precision is gained by
averaging over a region of interest (ROI).

All five are measured over a single fixed square ROI on a single slice. They are
therefore comparable across sessions only when the localization is comparable
(see [phantom localization](localization.md)). The trimming and detrending
described under [Preprocessing](#preprocessing) are common to every analysis,
and the outlier, smoothness and spike analyses operate on the residual field
that this detrending produces.

## Preprocessing

### Removal of the approach to steady state

The first volumes of an echo-planar imaging (EPI) run are acquired before the
longitudinal magnetization has reached steady state, and the signal decays
steeply across them. These volumes are discarded before any measurement is
made:

$$n_{\text{trim}} = \max\!\left(\operatorname{round}\!\left(
\frac{t_{\text{trim}}}{\mathrm{TR}}\right),\, 0\right)$$

where $t_{\text{trim}}$ is the `--trim-sec` setting (5 s by default). Every
frame index in the analysis file refers to the *trimmed* series. The acquired
volume number is obtained by adding `provenance.n_trimmed`.

### Detrending

One slice is then selected (the middle slice under `--center image`), and the
time course of each voxel is detrended. Detrending precedes every noise
statistic, as AFNI's `afni_proc.py` recommends (Cox, 1996). The default model is
a Legendre polynomial of degree

$$d = \operatorname{round}\!\left(\frac{N\,\mathrm{TR}}{200\ \mathrm{s}}\right)$$

so that the complexity of the fit follows the *duration* of the run and not its
frame count: a 200 s run is allowed one degree of freedom for drift, and a 600 s
run three. The alternative, `--detrend spline`, fits a least-squares B-spline of
degree 2 with $\operatorname{round}(N\,\mathrm{TR}/256\ \mathrm{s}) - 1$
interior knots. The resolved order is known only to the pipeline, so it is
recorded with the settings. A fit with at least as many coefficients as frames
is refused, because it would leave no residual for the noise measures and the
run would be scored as a perfectly stable scanner.

Let $I_v(t)$ denote the time series of voxel $v$. The fit yields a trend
$T_v(t)$ and a residual, termed the *fluctuation*, $r_v(t) = I_v(t) - T_v(t)$.
Two derived images are stored:

$$\bar S_v = \frac{1}{N}\sum_t I_v(t), \qquad
\sigma_v = \sqrt{\frac{1}{N}\sum_t r_v(t)^2}$$

These are the temporal mean (the *signal* image) and the temporal
root-mean-square (RMS) of the residual (the *fluctuation noise* image).
Detrending commutes with spatial averaging, so the ROI average of the per-voxel
fluctuations equals the detrended ROI-mean time course, and the ROI curves
reported here agree with the per-voxel images by construction.

## Measures

### Signal-to-noise ratio

The FBIRN SNR relates the signal to the *static spatial* noise. That noise is
estimated from a difference image in which the phantom cancels, namely the sum
of the odd frames minus the sum of the even frames:

$$D_v = \sum_{t \text{ odd}} I_v(t) \;-\; \sum_{t \text{ even}} I_v(t), \qquad
\mathrm{SNR} = \frac{\bar S_{\mathrm{ROI}}}
{\sqrt{\operatorname{var}_{\mathrm{ROI}}(D)\,/\,N}}$$

where $\bar S_{\mathrm{ROI}}$ is the ROI mean of the signal image and
$\operatorname{var}_{\mathrm{ROI}}(D)$ is the variance of $D$ across the voxels
of the ROI. The difference is formed from an *even* number of frames, and a
trailing frame is dropped when necessary. With an odd count the two subsets
would differ by a whole frame, $D$ would retain signal, and the spatial shading
of the phantom would dominate the variance in place of noise. The signal term
still averages the full series. The SNR is NaN for a series too short to contain
one odd/even pair, and when $D$ has no variance across the ROI.

### Signal-to-fluctuation-noise ratio

The SFNR relates the same signal to the *temporal fluctuation* noise. The ratio
is formed voxel by voxel and averaged over the ROI $R$:

$$\mathrm{SFNR} = \frac{1}{|R|}\sum_{v \in R} \frac{\bar S_v}{\sigma_v}$$

It is NaN if any ROI voxel has zero fluctuation noise, because the average is
defined only when every term is. The per-voxel SFNR *image* is treated
differently. It is displayed and never reduced to a scalar, so its divisor is
floored and a noiseless voxel is rendered instead of leaving a gap in the map.

### Drift and fluctuation

Both quantities are expressed as percentages of the ROI mean signal. Drift is
derived from the fitted trend and fluctuation from the residual:

$$\text{drift \%} = 100\,\frac{\max_t \bar T(t) - \min_t \bar T(t)}
{\bar S_{\mathrm{ROI}}}, \qquad
\text{fluctuation \%} = 100\,\frac{\operatorname{rms}_t\, \bar r(t)}
{\bar S_{\mathrm{ROI}}}$$

where $\bar T$ and $\bar r$ are the ROI-mean trend and residual. The fluctuation
is an RMS about zero, since detrending has already removed the mean of the
residual. Both are NaN when the ROI mean signal is zero, and no division warning
is raised.

### The Weisskoff analysis and the radius of decorrelation

If the noise were independent from voxel to voxel, averaging over $k \times k$
voxels would reduce the coefficient of variation by a factor of $k$. In practice
the reduction is smaller, and the Weisskoff analysis measures the shortfall
(Weisskoff, 1996). For each width $k = 1 \dots K$, where $K$ is the full side of
the ROI, the coefficient of variation of the ROI-mean time course is formed on
the concentric $k \times k$ ROI $R_k$:

$$\mathrm{CV}(k) = \frac{\operatorname{rms}_t\,\bar r_{R_k}(t)}{\bar S_{R_k}}$$

In the conventional presentation (Friedman & Glover, 2006), $\mathrm{CV}(k)$ is
plotted against $k$ on logarithmic axes together with a theoretical line of
slope $-1$ anchored at the single-voxel value, $\mathrm{CV}(1)/k$. The RDC is
read graphically: a horizontal line is drawn from the measured value at the
largest ROI to the theoretical line, and the intercept is projected onto the
abscissa.

#### Departure from the conventional calculation

The conventional anchor is the coefficient of variation of one voxel, the
central $1 \times 1$ ROI. That value represents the larger ROIs only if the
phantom image is uniform. Under intensity non-uniformity, the signal, and with
it the per-voxel coefficient of variation, varies across the ROI. The central
voxel is then not representative of the voxels being averaged, and the
comparison of ROIs of different sizes against a line through $\mathrm{CV}(1)$
confounds the spatial correlation of the noise, which the analysis is intended
to measure, with the non-uniformity of the image. The anchor is also a
single-voxel estimate and carries the sampling variability of one voxel.

This package therefore replaces the single-voxel anchor with the single-voxel
coefficient of variation *pooled over the ROI*:

$$\mathrm{CV}_1(k) = \frac{\sqrt{\langle \sigma_v^2 \rangle_{v \in R_k}}}
{\bar S_{R_k}}$$

The choice follows from the quantity that the reference line is meant to
represent. If the noise is independent between voxels, the variance of the
ROI mean is $\langle \sigma_v^2 \rangle / k^2$, so that

$$\mathrm{CV}(k) = \frac{\mathrm{CV}_1(k)}{k}$$

holds *exactly*, whatever the spatial distribution of signal and noise within
the ROI. $\mathrm{CV}_1(k)/k$ is thus the value that the measured
$\mathrm{CV}(k)$ would take under independence for the same voxels, and any
excess of the measurement over it is attributable to correlation alone.

Two results follow. First, the theoretical line of the Weisskoff plot is
anchored at the largest ROI, as $\mathrm{CV}_1(K)/k$, and the reported scalar is

$$\mathrm{RDC} = \frac{\mathrm{CV}_1(K)}{\mathrm{CV}(K)}$$

Because the graphical construction projects the measurement at the largest ROI
onto the theoretical line, the intercept of this line is exactly the reported
RDC. With the conventional anchor, the graphical and the computed values agree
only for a uniform phantom.

Second, the same ratio can be evaluated at every ROI width and not only at the
largest:

$$\mathrm{RDC}(k) = \frac{\mathrm{CV}_1(k)}{\mathrm{CV}(k)}$$

with numerator and denominator taken over the same voxels, so that
non-uniformity cancels at each width separately. Plotted against $k$ on linear
axes, the ideal is the identity line $\mathrm{RDC}(k) = k$, which independent
noise would follow without limit. Noise that contains a component common to the
whole ROI follows the identity at small widths and then levels off, and the
plateau gives the radius of decorrelation directly. The saturation that must be inferred from a small divergence between
two curves on the logarithmic Weisskoff plot appears here as an evident
plateau. The scalar RDC is the last point of this curve.

The RDC is interpreted as the width of an ROI over which the noise is
effectively independent. An ideal scanner gives $\mathrm{RDC} = K$, and a real
one gives less. Spatial smoothness confounds the RDC, because smoother noise
decorrelates more slowly. The [smoothness](smoothness.md) analysis therefore
reports an explicit full width at half maximum (FWHM) alongside it.

## Example

The first figure shows the ROI time course, the trend removed from it, and the
spectrum of the residual, all computed from the synthetic phantom. The spectrum
is stored without its DC term, so it begins at the first nonzero frequency and
can be plotted without further windowing. The signal of the synthetic phantom
drifts linearly by 1% over the run, so the fitted trend is a straight line and
`drift_pct` reads approximately 1.

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

The Weisskoff curve is plotted against the line the noise would follow if it
were independent from voxel to voxel, anchored at the pooled single-voxel value
$\mathrm{CV}_1(K)$ as described above. The reported RDC is the width at which
that line reaches the measured value at the largest ROI.

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

The decorrelation factor evaluated at every ROI width is plotted against the
identity line that independent noise would follow. The synthetic phantom
carries a gain fluctuation of 0.1% that is common to the whole image, as the
instability of a scanner is. Averaging cannot reduce that component, so the
curve leaves the identity at small widths and levels off. The level of the
plateau, marked by the horizontal line, is the radius of decorrelation. The
vertical axis is limited to the range of the measured curve, and the identity
line continues beyond it.

```{eval-rst}
.. plot::
   :caption: Decorrelation factor at each ROI width against the identity line for uncorrelated noise.
   :filename-prefix: stability-rdc

   import matplotlib.pyplot as plt

   import phantom

   weisskoff = phantom.analysis().curves.weisskoff

   fig, axes = plt.subplots(figsize=(5.2, 4.0), layout="constrained")
   axes.plot(weisskoff.roi_sizes, weisskoff.rdc, "o-", ms=4, label="measured")
   axes.plot(
       weisskoff.roi_sizes, weisskoff.roi_sizes, "--", label="uncorrelated noise"
   )
   axes.axhline(weisskoff.rdc[-1], lw=0.8, ls=":", color="0.4")
   axes.set_ylim(0, 1.5 * weisskoff.rdc.max())
   axes.set_xlabel("ROI width (voxels)")
   axes.set_ylabel("RDC (voxels)")
   axes.legend(fontsize="small", loc="lower right")
   axes.grid(True, lw=0.3, alpha=0.5)
```

The protocol is read from four summary images: the signal, the per-voxel SFNR,
the fluctuation noise, and the static (odd/even difference) noise.

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

## Stored quantities

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

Any of the five measurements may be NaN, and none is ever absent. NaN indicates
that the estimator ran and could not resolve the value, never that the quantity
does not apply. The settings that produced the measurements (`trim_sec`,
`detrend`, the resolved `detrend_order`, `roi_size` and `center`) are recorded
in the `settings` section of the JSON document (see
[the analysis file](../analysis-file.md)).

## References

- Cox RW. AFNI: software for analysis and visualization of functional magnetic
  resonance neuroimages. *Comput Biomed Res* 1996;29:162–173.
  [doi:10.1006/cbmr.1996.0014](https://doi.org/10.1006/cbmr.1996.0014)
- Friedman L, Glover GH. Report on a multicenter fMRI quality assurance
  protocol. *J Magn Reson Imaging* 2006;23:827–839.
  [doi:10.1002/jmri.20583](https://doi.org/10.1002/jmri.20583)
- Weisskoff RM. Simple measurement of scanner stability for functional NMR
  imaging of activation in the brain. *Magn Reson Med* 1996;36:643–645.
  [doi:10.1002/mrm.1910360422](https://doi.org/10.1002/mrm.1910360422)
