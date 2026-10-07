# Outliers and spikes

## What it is for

The FBIRN summaries on the [stability](stability.md) page are averages, and an
average is exactly the wrong instrument for a transient: one badly corrupted
volume in a three-hundred-volume run barely moves the SD it is folded into.
This analysis is the complementary one — three unitless indicators that stand
up when *something happened*, rather than when everything is slightly worse.

Two of them look for a single bad volume, from two directions: the share of
phantom voxels that are statistical outliers in each frame, and the peak of the
ROI-mean residual against its own robust spread. The third looks for a
*periodic* artifact — vibration, a bad interleave, physiological-like pickup —
as a single dominant line in the residual spectrum.

## Method

### The per-frame outlier fraction

This follows AFNI's `3dToutcount`, over the phantom mask, on the pipeline's
detrended residuals $r_v(t)$. (`3dToutcount` detrends first as well;
`afni_proc.py` recommends detrending before outlier classification. Its fit is
L1 where this package's is L2, a minor difference for a stable phantom.)

For each masked voxel the implemented threshold scale is taken from the
median absolute residual,

$$\sigma_v = \sqrt{\tfrac{\pi}{2}}\; \operatorname{median}_t
\lvert r_v(t) \rvert$$

A frame counts as an outlier for that voxel when

$$\lvert r_v(t) \rvert > \alpha\,\sigma_v, \qquad
\alpha = Q^{-1}\!\left(\frac{q_{\text{thr}}}{N}\right)$$

with $Q^{-1}$ the normal upper-tail quantile, $N$ the number of analyzed
frames, and $q_{\text{thr}} = 0.001$ by default. The parameter tunes the
threshold through $q_{\text{thr}}/N$; increasing the run length raises the
threshold for a fixed residual scale. It is not an expected per-frame outlier
fraction. A constant voxel ($\operatorname{MAD} = 0$) never flags.

The published trace is the share of masked voxels flagged at each frame,

$$\text{outlier fraction}(t) = \frac{1}{|P|}
\sum_{v \in P} \mathbb{1}\big[\lvert r_v(t)\rvert > \alpha \sigma_v\big]$$

so a peak identifies a frame with an elevated share of flagged voxels. The
scalar `outl %` is the worst frame's fraction as a percentage, and the index
of that frame is published beside it — counted
from the *analyzed* series, so adding `provenance.n_trimmed` gives the acquired
volume number. An empty mask gives an all-NaN trace rather than a division by
zero.

### The two spike scores

Both come from cran-fmriqa and both are the same kernel — a peak against a
robust spread — applied to the ROI-mean residual $\bar r(t)$ and to its
spectrum. The denominator is R's `mad()`, the SD-consistent robust spread:

$$\operatorname{mad}(x) = 1.4826 \operatorname{median}_i
\lvert x_i - \operatorname{median}(x) \rvert$$

$$\text{tcOut} = \frac{\max_t \lvert \bar r(t) \rvert}
{\operatorname{mad}(\bar r)}, \qquad
\text{spcOut} = \frac{\max_f \lvert \mathcal{F}\{\bar r\}(f) \rvert}
{\operatorname{mad}\big(\lvert \mathcal{F}\{\bar r\} \rvert\big)}$$

with the DC bin dropped from the magnitude spectrum before either the peak or
the spread is taken — the same DC-dropped spectrum the artifact publishes and
the [stability](stability.md) page plots. Both are unitless and both are
peak-over-spread, so a clean, stationary phantom sits near the level a Gaussian
would give (a few) and a transient stands well above it. **tcOut** is large
when a single volume spikes; **spcOut** is large when one narrow frequency
dominates. Either is NaN for an empty series or one with no spread at all.

## What it looks like

```{eval-rst}
.. plot::
   :caption: Per-frame outlier-voxel fraction, with the worst frame marked.
   :filename-prefix: outliers-fraction

   import matplotlib.pyplot as plt

   import phantom

   artifact = phantom.artifact()
   curves = artifact.curves
   measurements = artifact.measurements

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

The phantom has no injected transient. The marker identifies the frame with
the largest measured fraction; the plot supplies no calibrated chance baseline.

## What it contributes to the artifact

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.outlier_max_pct` | attribute, double | worst frame's outlier-voxel percentage |
| `measurements.outlier_worst_frame` | attribute, int | index of that frame, counting along the `frame` axis |
| `measurements.tc_outlier` | attribute, double | temporal spike score, peak over robust spread |
| `measurements.spec_outlier` | attribute, double | spectral spike score, on the DC-dropped residual spectrum |
| `curves.outlier_fraction` | variable `(frame)`, 1 | fraction (not percent) of masked voxels flagged in each frame |
| `curves.outlier_qthr` | attribute, double | threshold tuning parameter, used as $q_{\text{thr}}/N$ in the normal upper-tail quantile |

The threshold parameter is a scalar, so it is an attribute rather than a variable.
The two spike scores are computed on the residual and spectrum
the [stability](stability.md) page publishes; this analysis adds no second copy
of either.

All four measurements are NaN-able and none is ever absent: a NaN means the
estimator could not resolve the value (an empty mask, a constant series), never
that the quantity does not apply.

## References

- AFNI `3dToutcount` — the per-voxel MAD threshold, the $q_{\text{thr}}/N$
  tail probability, and the per-frame fraction.
- AFNI `afni_proc.py` — detrend before classifying outliers.
- cran-fmriqa — the MAD-normalized temporal and spectral spike scores.
