# Phantom motion and deformation

## What it is for

A phantom on a scanner bed does not move. What *does* happen over a long run is
that the gradient coils heat, their calibration drifts, and the image the
scanner reconstructs slowly stretches and slides — which looks like motion in
the reconstructed series without anything having been displaced. Measuring that
is the point: a slow monotonic strain ramp is the thermal-drift signature, and
a sudden step is something knocked, dropped, or mis-triggered.

Two independent estimators are published, one expensive and one cheap. The
first registers every frame to the run's temporal mean under a deformation
model built for a rigid phantom. The second tracks the intensity centroid of
the whole slice, which needs no mask and no registration at all. Agreement
between them is reassuring; disagreement usually means the registration is
looking at something the centroid is not.

Both are **diagnostics only**. The analyzed series is never resampled from the
fit, so the FBIRN metrics stay measured on the acquired data.

## Method

### The registration model

This is AFNI `3dvolreg`'s per-volume registration with the model tailored to a
phantom. A stationary phantom cannot rotate, so the rotation degrees of freedom
are dropped; what gradient heating does produce is a translation plus a scaling
and shear. Each frame is aligned to the temporal-mean image under a 2-D affine
restricted to translation and *symmetric* strain — five parameters, no
rotation:

$$W(\mathbf{x}) = \mathbf{c} + U(\mathbf{x} - \mathbf{c}) + \mathbf{t},
\qquad
U = \begin{bmatrix} 1 + s_r & h \\ h & 1 + s_c \end{bmatrix},
\qquad
\mathbf{t} = \begin{bmatrix} d_r \\ d_c \end{bmatrix}$$

$U$ is symmetric, which is exactly what excludes rotation: a general $2\times2$
matrix carries an antisymmetric part, and that part *is* the rotation. The
strain is pivoted at the phantom centroid $\mathbf{c}$ so that translation and
deformation stay separable — pivot anywhere else and a pure scaling shows up as
a translation too.

The fit is forward-additive Lucas-Kanade over the phantom mask: each step warps
the frame by the current parameters, forms the steepest-descent images from the
warped frame's gradients,

$$\nabla W \cdot \frac{\partial W}{\partial \mathbf{p}} =
\big[\,g_r,\ g_c,\ g_r \tilde r,\ g_c \tilde c,\
g_r \tilde c + g_c \tilde r\,\big]$$

(with $\tilde r, \tilde c$ the centered coordinates), and solves the linearized
least-squares problem for the additive update. The warp Jacobian is linear in
the centered coordinates and independent of the parameters, so the additive
scheme is exact up to the image interpolation. At most 12 iterations are
allowed and convergence is declared when the largest parameter update falls
below $10^{-4}$ (voxels for translation, fraction for strain) — phantom drift
is sub-voxel, so a handful of Gauss-Newton steps is enough.

The published scalars are the peaks over frames:

$$\text{motn} = \max_t \lVert \mathbf{t}(t) \rVert, \qquad
\text{scl \%} = \max_{t,a} 100\,\lvert s_a(t) \rvert, \qquad
\text{shr \%} = \max_t 100\,\lvert h(t) \rvert$$

with the translation magnitude in millimetres when the in-plane voxel size is
known and in voxels when it is not.

Each fit must be identifiable, finite, and converged. A frame that is
rank-deficient, non-finite, or out of iterations is published as an all-NaN
row rather than as a partial fit, a warning names how many frames failed, and
the run's *peak* motion measurements are NaN — a peak over an incomplete series
would be a smaller number presented as a larger claim.

### The centroid trace

The second estimator is bxh `fmriqa_volmeasures`' center of mass: the
intensity-weighted first moment of the whole slice, computed *circularly*.
An MRI image is periodic under FFT reconstruction, so the moment is taken
through the unit circle,

$$\theta_a(t) = \frac{2\pi}{N_a}\,\mathbf{x}_a, \qquad
\bar\theta_a(t) = \operatorname{atan2}\!\big(
\langle \sin\theta_a \rangle_{I},\ \langle \cos\theta_a \rangle_{I}\big),
\qquad
\text{COM}_a(t) = \frac{N_a}{2\pi}\,\bar\theta_a(t) \bmod N_a$$

which is what lets a phantom sitting against a wrapped image edge yield its
true centroid instead of aliasing to mid-FOV. The circular mean has a second
useful property: a uniform background and the 180-degree Nyquist ghost
self-cancel on the periodic grid, so this needs no phantom mask at all — only
genuinely missing data (a vendor-nulled edge) is healed first. The reference is
the circular mean of the per-frame centroids, and the published deviation is
wrapped into $(-N_a/2,\, N_a/2]$ so a centroid that crosses the periodic
boundary reads as a small displacement rather than a full-FOV jump.

An axis has a defined centroid only when its sine/cosine resultant norm exceeds
$10^{-12}$ times the total positive above-pedestal intensity. This relative
numerical tolerance rejects cancellation roundoff regardless of brightness:
a uniform positive frame has no centroid even when it has nonzero total
intensity. An unresolved coordinate is NaN and does not enter that axis's
temporal reference; the other coordinate can still resolve. The reference uses
the same tolerance relative to the number of resolved coordinates on each axis.
It is NaN when none resolve or their unit vectors cancel, as with balanced
antipodal centroids.

`com` is the peak of that deviation's magnitude, in the same unit as the
registration's translation. It is a first-moment measure, so it is blind to any
deformation that preserves the centroid — which is exactly why it is published
beside the registration rather than instead of it. Each magnitude requires both
centroid coordinates and both reference axes to resolve. The peak ignores
missing magnitudes and is NaN when no complete displacement is available,
including when an axis of the temporal reference is ambiguous.

## What it looks like

```{eval-rst}
.. plot::
   :caption: Per-frame translation, scale, shear, and centroid deviation for the synthetic phantom.
   :filename-prefix: motion-traces

   import matplotlib.pyplot as plt

   import phantom

   artifact = phantom.artifact()
   curves = artifact.curves
   unit = artifact.measurements.displacement_unit

   fig, axes = plt.subplots(4, 1, figsize=(6.6, 7.4), layout="constrained", sharex=True)

   axes[0].plot(curves.time, curves.translation[:, 0], lw=0.9, label="axis 0 (row)")
   axes[0].plot(curves.time, curves.translation[:, 1], lw=0.9, label="axis 1 (col)")
   axes[0].set_ylabel("translation (voxels)")

   axes[1].plot(curves.time, curves.scale_pct[:, 0], lw=0.9, label="axis 0 (row)")
   axes[1].plot(curves.time, curves.scale_pct[:, 1], lw=0.9, label="axis 1 (col)")
   axes[1].set_ylabel("scale (%)")

   axes[2].plot(curves.time, curves.shear_pct, lw=0.9, color="C2")
   axes[2].set_ylabel("shear (%)")

   axes[3].plot(curves.time, curves.com_deviation[:, 0], lw=0.9, label="axis 0 (row)")
   axes[3].plot(curves.time, curves.com_deviation[:, 1], lw=0.9, label="axis 1 (col)")
   axes[3].set_ylabel("centroid (voxels)")
   axes[3].set_xlabel("time (s)")

   for panel in axes:
       panel.axhline(0.0, lw=0.6, color="0.6")
   axes[0].legend(fontsize="small", ncols=2)
   axes[0].set_title(
       f"peak translation and centroid shift are reported in {unit}",
       fontsize="small",
   )
```

The traces are stored in voxels; the *peak* measurements are converted to
millimetres when the header gave a voxel size, which is what
`measurements.displacement_unit` records.

## What it contributes to the artifact

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.max_translation` | attribute, double | peak per-frame translation magnitude, in `displacement_unit` |
| `measurements.max_scale_pct` | attribute, double | peak per-frame fractional scaling, as a percentage |
| `measurements.max_shear_pct` | attribute, double | peak per-frame symmetric shear, as a percentage |
| `measurements.max_com_displacement` | attribute, double | peak per-frame centroid deviation, in `displacement_unit` |
| `measurements.displacement_unit` | attribute, text | `mm` when the in-plane voxel size is known, else `vox`; governs both peaks above |
| `curves.translation` | variable `(frame, image_axis)`, voxels | fitted in-plane translation per frame |
| `curves.scale_pct` | variable `(frame, image_axis)`, percent | fitted fractional scaling per frame and axis |
| `curves.shear_pct` | variable `(frame)`, percent | fitted symmetric shear per frame |
| `curves.com_deviation` | variable `(frame, image_axis)`, voxels | centroid deviation from the series mean |
| `image_axis` | coordinate, flags `row col` | the in-plane array axis, for the two-column traces |

The three registration measurements are NaN whenever *any* frame failed to
converge, and the failed frames are all-NaN rows in `curves.translation`,
`curves.scale_pct` and `curves.shear_pct` — so a consumer can tell which frames
were lost, and how many, without recomputing anything. The centroid trace is
independent of that failure: it has no fit to fail, and a NaN there means only
that the coordinate or its temporal reference has no resolved circular direction.

One unit caveat survives migration. Schema 5 and earlier always published these
two peaks in voxels regardless of whether the voxel size was known, so a
migrated artifact can carry `displacement_unit` of `vox` beside a
`measurements.fwhm_unit` of `mm`. On anything this build writes the two agree.

## References

- AFNI `3dvolreg` — per-volume registration to a reference volume, which this
  follows with the rotation removed and strain added.
- Greve DN, bxh/XCEDE `fmriqa_volmeasures` — the circular center-of-mass trace.
- Baker S, Matthews I. *Lucas-Kanade 20 years on: a unifying framework.* Int J
  Comput Vis 2004;56:221–255 — the forward-additive formulation used here.
