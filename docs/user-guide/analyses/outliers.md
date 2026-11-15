# Outliers and spikes

The FBIRN summaries on the [stability](stability.md) page are averages, and an
average is poorly suited to detecting a transient: a single badly corrupted
volume in a run of three hundred scarcely changes the standard deviation into
which it is absorbed. This analysis adds three dimensionless indicators that
respond to an isolated event and not to a uniform degradation.

Two of them detect a single corrupted volume: the fraction of phantom voxels
that are outliers in each frame, and the peak of the ROI-mean residual relative
to its own robust spread. The third detects a *periodic* artifact (vibration, a
faulty interleave, or pickup resembling physiological noise) as a single
dominant line in the spectrum of the residual.

## The per-frame outlier fraction

The outlier fraction follows AFNI's `3dToutcount` (Cox, 1996). It is evaluated
over the phantom mask, on the detrended residuals $r_v(t)$ of the pipeline.
`3dToutcount` likewise detrends first, and `afni_proc.py` recommends detrending
before outliers are classified. The AFNI fit is L1 where this package's is L2, a
minor difference for a stable phantom.

For each masked voxel, the threshold scale is derived from the median absolute
residual,

$$\sigma_v = \sqrt{\tfrac{\pi}{2}}\; \operatorname{median}_t
\lvert r_v(t) \rvert$$

A frame is counted as an outlier for that voxel when

$$\lvert r_v(t) \rvert > \alpha\,\sigma_v, \qquad
\alpha = Q^{-1}\!\left(\frac{q_{\text{thr}}}{N}\right)$$

where $Q^{-1}$ is the upper-tail quantile function of the normal distribution,
$N$ is the number of analyzed frames, and $q_{\text{thr}} = 0.001$ by default.
The threshold depends on $q_{\text{thr}}/N$, so a longer run raises it for a
fixed residual scale. $q_{\text{thr}}$ should not be read as an expected
per-frame outlier fraction. A voxel that is constant in time
($\operatorname{MAD} = 0$) is never flagged.

The stored trace is the fraction of masked voxels flagged at each frame,

$$\text{outlier fraction}(t) = \frac{1}{|P|}
\sum_{v \in P} \mathbb{1}\big[\lvert r_v(t)\rvert > \alpha \sigma_v\big]$$

so that a peak identifies a frame with an elevated fraction of flagged voxels.
The scalar `outl %` is the fraction in the worst frame, expressed as a
percentage, and the index of that frame is stored with it. The index refers to
the *analyzed* series, and the acquired volume number is obtained by adding
`provenance.n_trimmed`. An empty mask yields a trace of NaN values and no
division by zero.

## The spike scores

Both spike scores derive from the R package `fmriqa` (referred to here as
cran-fmriqa). They apply one kernel, a peak divided by a robust spread, to the
ROI-mean residual $\bar r(t)$ and to its spectrum. The denominator is R's
`mad()`, the median absolute deviation (MAD) scaled for consistency with the
standard deviation of a normal distribution:

$$\operatorname{mad}(x) = 1.4826 \operatorname{median}_i
\lvert x_i - \operatorname{median}(x) \rvert$$

$$\text{tcOut} = \frac{\max_t \lvert \bar r(t) \rvert}
{\operatorname{mad}(\bar r)}, \qquad
\text{spcOut} = \frac{\max_f \lvert \mathcal{F}\{\bar r\}(f) \rvert}
{\operatorname{mad}\big(\lvert \mathcal{F}\{\bar r\} \rvert\big)}$$

The DC term is removed from the magnitude spectrum before either the peak or
the spread is taken, as it is in the spectrum that the analysis file stores and
the [stability](stability.md) page plots. Both scores are dimensionless ratios
of a peak to a spread. A clean, stationary phantom therefore scores at the level
expected of Gaussian noise (a few units), and a transient stands well above it.
**tcOut** is large when a single volume spikes, and **spcOut** is large when a
single narrow frequency dominates. Either is NaN for an empty series or for one
with no spread.

## Example

```{eval-rst}
.. plot::
   :caption: Per-frame outlier-voxel fraction, with the worst frame marked.
   :filename-prefix: outliers-fraction

   import matplotlib.pyplot as plt

   import phantom

   analysis = phantom.analysis()
   curves = analysis.curves
   measurements = analysis.measurements

   fig, axes = plt.subplots(figsize=(6.6, 3.2), layout="constrained")
   axes.plot(curves.time, 100 * curves.outlier_fraction, lw=0.9)
   worst = measurements.outlier_worst_frame
   axes.plot(
       curves.time[worst],
       100 * curves.outlier_fraction[worst],
       "o",
       ms=6,
       mfc="none",
       color="C3",
       label=f"worst frame ({worst})",
   )
   axes.set_xlabel("time (s)")
   axes.set_ylabel("outlier voxels (%)")
   axes.legend(fontsize="small")
```

The synthetic phantom contains no injected transient. The marker identifies the
frame with the largest measured fraction, and the plot provides no calibrated
baseline for chance.

## Stored quantities

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.outlier_max_pct` | attribute, double | worst frame's outlier-voxel percentage |
| `measurements.outlier_worst_frame` | attribute, int | index of that frame, counting along the `frame` axis |
| `measurements.tc_outlier` | attribute, double | temporal spike score, peak over robust spread |
| `measurements.spec_outlier` | attribute, double | spectral spike score, on the DC-dropped residual spectrum |
| `curves.outlier_fraction` | variable `(frame)`, 1 | fraction (not percent) of masked voxels flagged in each frame |
| `curves.outlier_qthr` | attribute, double | threshold tuning parameter, used as $q_{\text{thr}}/N$ in the normal upper-tail quantile |

The threshold parameter is a scalar and is therefore stored as an attribute. The
two spike scores are computed from the residual and the spectrum stored by the
[stability](stability.md) analysis, so this analysis stores no second copy of
either.

All four measurements may be NaN, and none is ever absent. NaN indicates that
the estimator could not resolve the value (an empty mask, a constant series),
never that the quantity does not apply.

## References

- Cox RW. AFNI: software for analysis and visualization of functional magnetic
  resonance neuroimages. *Comput Biomed Res* 1996;29:162–173.
  [doi:10.1006/cbmr.1996.0014](https://doi.org/10.1006/cbmr.1996.0014)
  `3dToutcount` supplies the per-voxel MAD threshold, the $q_{\text{thr}}/N$
  tail probability and the per-frame fraction, and `afni_proc.py` the
  recommendation to detrend before classifying outliers.
- cran-fmriqa, the R package `fmriqa`. The source of the MAD-normalized
  temporal and spectral spike scores.
