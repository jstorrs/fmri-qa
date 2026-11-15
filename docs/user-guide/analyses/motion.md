# Phantom motion and deformation

A phantom resting on the scanner bed does not move. Over a long run, however,
the gradient coils heat and their calibration drifts, and the reconstructed
image stretches and shifts as though the phantom had moved. A slow, monotonic
increase in strain is the signature of thermal drift. An abrupt step indicates
that something was disturbed, dropped, or mistriggered.

Two independent estimators are reported. The more costly one registers every
frame to the temporal mean under a deformation model designed for a rigid
phantom. The simpler one tracks the intensity centroid of the whole slice and
requires neither a mask nor a registration. Disagreement between them usually
means that the registration is responding to a feature to which the centroid is
insensitive.

Both are **diagnostic only**. The analyzed series is never resampled from the
fit, so the FBIRN metrics remain measurements of the acquired data.

## Registration

The registration follows the per-volume scheme of AFNI's `3dvolreg` (Cox, 1996),
with a deformation model adapted to a phantom. A stationary phantom cannot
rotate, so rotation is omitted, whereas gradient heating produces translation
together with scaling and shear. Each frame is aligned to the temporal-mean
image under a two-dimensional affine transformation restricted to translation
and *symmetric* strain, which has five parameters:

$$W(\mathbf{x}) = \mathbf{c} + U(\mathbf{x} - \mathbf{c}) + \mathbf{t},
\qquad
U = \begin{bmatrix} 1 + s_r & h \\ h & 1 + s_c \end{bmatrix},
\qquad
\mathbf{t} = \begin{bmatrix} d_r \\ d_c \end{bmatrix}$$

The symmetry of $U$ is what excludes rotation, since the rotation is the
antisymmetric part of a general $2\times2$ matrix. The strain is applied about
the phantom centroid $\mathbf{c}$ so that translation and deformation remain
separable. About any other point, a pure scaling would also appear as a
translation.

The parameters are estimated by the forward-additive Lucas-Kanade algorithm
(Baker & Matthews, 2004) over the phantom mask. Each iteration warps the frame
by the current parameters, forms the steepest-descent images from the gradients
of the warped frame,

$$\nabla W \cdot \frac{\partial W}{\partial \mathbf{p}} =
\big[\,g_r,\ g_c,\ g_r \tilde r,\ g_c \tilde c,\
g_r \tilde c + g_c \tilde r\,\big]$$

where $\tilde r$ and $\tilde c$ are the centered coordinates, and solves the
linearized least-squares problem for the additive update. The Jacobian of the
warp is linear in the centered coordinates and independent of the parameters, so
the additive scheme is exact up to image interpolation. Iteration stops after 12
steps, or when the largest parameter update falls below $10^{-4}$ (in voxels for
translation and as a fraction for strain). Phantom drift is smaller than a
voxel, so a few steps suffice.

The reported scalars are the maxima over frames:

$$\text{motn} = \max_t \lVert \mathbf{t}(t) \rVert, \qquad
\text{scl \%} = \max_{t,a} 100\,\lvert s_a(t) \rvert, \qquad
\text{shr \%} = \max_t 100\,\lvert h(t) \rvert$$

The translation magnitude is in millimeters when the in-plane voxel size is
known and in voxels otherwise.

Each fit must be identifiable, finite, and converged. A frame whose fit is
rank-deficient, non-finite, or not converged within the iteration limit is
stored as a row of NaN values in place of a partial fit, and a warning states
the number of failed frames. The *peak* motion measurements are then NaN, since
a maximum over an incomplete series would understate the true maximum.

## The centroid trace

The second estimator is the center of mass of `fmriqa_volmeasures` in the
BXH/XCEDE tools: the intensity-weighted first moment of the whole slice,
computed *circularly*. Because an image reconstructed by FFT is periodic, the
moment is evaluated on the unit circle,

$$\theta_a(t) = \frac{2\pi}{N_a}\,\mathbf{x}_a, \qquad
\bar\theta_a(t) = \operatorname{atan2}\!\big(
\langle \sin\theta_a \rangle_{I},\ \langle \cos\theta_a \rangle_{I}\big),
\qquad
\text{COM}_a(t) = \frac{N_a}{2\pi}\,\bar\theta_a(t) \bmod N_a$$

so that a phantom lying across a wrapped image edge receives its true centroid
and is not aliased to the middle of the field of view. On the periodic grid the
circular mean also cancels a uniform background and the Nyquist ghost, which is
displaced by 180 degrees, so no phantom mask is required. Only missing data (an
edge nulled by the vendor) are filled beforehand. The reference is the circular
mean of the per-frame centroids. The stored deviation is wrapped into
$(-N_a/2,\, N_a/2]$, so that a centroid crossing the periodic boundary registers
as a small displacement and not as a jump of a full field of view.

The centroid along an axis is defined only when the norm of the sine and cosine
resultant exceeds $10^{-12}$ times the total positive intensity above the
pedestal. This relative tolerance rejects cancellation roundoff at any
brightness, so a uniform positive frame has no centroid. An unresolved
coordinate is NaN and is excluded from the temporal reference of its axis, while
the other coordinate may still be resolved. The reference applies the same
tolerance, relative to the number of resolved coordinates on each axis. It is
NaN when no coordinate is resolved or when the unit vectors cancel, as they do
for balanced antipodal centroids.

`com` is the peak magnitude of this deviation, in the same unit as the
translation from the registration. A first-moment measure is insensitive to any
deformation that preserves the centroid, so it complements the registration and
does not replace it. Each magnitude requires both centroid coordinates and both
reference axes. The peak disregards missing magnitudes and is NaN when no
complete displacement exists, including when a reference axis is ambiguous.

## Example

```{eval-rst}
.. plot::
   :caption: Per-frame translation, scale, shear, and centroid deviation for the synthetic phantom.
   :filename-prefix: motion-traces

   import matplotlib.pyplot as plt

   import phantom

   analysis = phantom.analysis()
   curves = analysis.curves
   unit = analysis.measurements.displacement_unit

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

The traces are stored in voxels. The *peak* measurements are converted to
millimeters when the header supplies a voxel size, and
`measurements.displacement_unit` records which unit applies.

The synthetic phantom does not move, so the traces represent the noise floor of
the registration: translations of at most a few thousandths of a voxel, and
scale and shear of a few hundredths of a percent.

## Stored quantities

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
converge. The failed frames appear as rows of NaN values in
`curves.translation`, `curves.scale_pct` and `curves.shear_pct`, from which a
consumer can determine which frames were lost and how many. The centroid trace
involves no fit that could fail. A NaN there means only that the coordinate, or
its temporal reference, has no resolved circular direction.

## References

- Baker S, Matthews I. Lucas-Kanade 20 years on: a unifying framework. *Int J
  Comput Vis* 2004;56:221–255.
  [doi:10.1023/B:VISI.0000011205.11775.fd](https://doi.org/10.1023/B:VISI.0000011205.11775.fd)
- Cox RW. AFNI: software for analysis and visualization of functional magnetic
  resonance neuroimages. *Comput Biomed Res* 1996;29:162–173.
  [doi:10.1006/cbmr.1996.0014](https://doi.org/10.1006/cbmr.1996.0014)
  `3dvolreg` registers each volume to a reference volume. The present method
  removes the rotation and adds strain.
- Greve DN. `fmriqa_volmeasures`, in the BXH/XCEDE tools. The source of the
  circular center-of-mass trace.
