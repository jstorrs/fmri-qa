# Phantom localization

Every other quantity in the analysis file is measured through two geometric
objects: the phantom mask and the square summary ROI. Localization determines
both and reports whether each was placed correctly.

Either can fail without any visible symptom. A watershed that never separated
the phantom from the background still returns a mask, and an ROI placed in air
still yields an average. The analysis therefore stores a verdict together with
the geometry. A reader of a stored analysis file can then distinguish an
estimator that declined to answer (a NaN beside a valid mask) from an analysis
that measured background (a number beside a failed mask). A failed mask raises
no error. A batch reports the scan and continues, and the affected metrics
resolve to NaN.

The default configuration reproduces the FBIRN geometry (Friedman & Glover,
2006). The `--center phantom` mode and the mask verdicts described below have no
counterpart in that protocol. They were added because a mispositioned phantom
and a collapsed segmentation both produce numbers that appear ordinary.

## Slice selection

The metrics are computed on a single plane. Under `--center image`, the default
and the Glover convention, the middle slice is taken and the phantom is assumed
to be centered in the field of view (FOV). Under `--center phantom`, every slice
is segmented and the one with the largest phantom cross-section is taken. This
mode tolerates a mispositioned phantom better, but it is not the standard
protocol. A slice containing no recognizable phantom is assigned zero area, so
that a prescription extending past the phantom cannot be selected on the
strength of a segmentation of air. If no slice contains a phantom, the middle
slice is used and a warning is issued. The selected plane is recorded in the
provenance (`provenance.slice_index` of `provenance.n_slices`), without which
two analysis files of one series could not be told apart.

## Segmentation

The segmentation target is the temporal maximum-intensity projection of the
analyzed slice, $M$, the per-voxel maximum over frames. The mask is a watershed
of the Sobel edge magnitude of $M$, seeded from intensity quantiles:

$$\text{background seed} = \{v : M_v \le Q_{0.1}(M)\}, \qquad
\text{phantom seed} = \{v : M_v \ge Q_{0.9}(M)\}$$

The Sobel filter wraps at the image border instead of padding, because an image
reconstructed by FFT is periodic. The seeds are inclusive ($\le$, $\ge$). A
strict comparison would seed *nothing* whenever a tenth or more of the image
lies at the minimum, as it does with the exactly zero background of
background-suppressed or mask-multiplied reconstructions, and a watershed with
no background seed floods the entire frame as phantom.

When the two quantiles coincide, inclusive seeds overlap. Both are zero, for
example, when a small phantom occupies less than a tenth of an otherwise zero
frame. In that case the minimum seeds the background and the maximum seeds the
phantom, which are disjoint for any nonconstant image. A constant image receives
an empty mask, which fails the verdict below and raises the usual warning. The
same rule governs the three-dimensional watershed that forms the phantom core
for the [high/low flip-angle analysis](hilo.md), before hole filling, selection
of the largest component, and erosion.

Independently of the mask, any image edge that is entirely nulled is excluded
from every statistic. Some vendors null one outer row or column to encode the
phase-encode direction. Removing a voxel from all four sides would discard valid
data on the other three, so each edge is tested separately. The test compares
against the value that a *stored* zero reads back as. Because `get_fdata`
returns $\text{stored} \times \text{slope} + \text{inter}$, a nulled edge reads
as the intercept, not as 0, when `scl_inter` is nonzero.

## Validity of the segmentation

Two inexpensive tests decide whether the mask represents a phantom. The first
is the fraction of the frame that it covers,

$$f = \frac{|\text{mask}|}{|\text{frame}|}$$

which a collapsed segmentation drives to 0 or 1. The second is the contrast of
the mask interior against the background from which it was separated,

$$c = \frac{\langle M \rangle_{\text{inside}}}
{\langle M \rangle_{\text{outside}}}$$

which a partition of pure noise does not pass. Air segments at approximately
1.5–1.9, and the synthetic phantom shown below, whose background is Rayleigh
noise, scores approximately 26. An exactly zero background makes $c$ infinite. A mask that
partitions nothing, whether empty or covering the whole frame, scores 0. The
verdict is

$$\text{mask ok} \iff 0 < f < 0.95 \;\wedge\; c \ge 4$$

The verdict is determined once, at this stage, because the bounds belong to the
segmentation and a reader in another distribution cannot import that layer.
Both numbers are stored with it, so that a report can state which test a failed
mask did not meet. The same test ranks the slices under `--center phantom`. A
run therefore cannot report that no slice contains a phantom and then record the
phantom it segmented as valid.

## ROI placement

The summary ROI is a square of side `--roi-size` (21 voxels by default, the
FBIRN size). It is centered on the image matrix under `--center image` and on
the phantom under `--center phantom`. The phantom center is defined as the mask
voxel farthest from any background, that is, the maximum of the Euclidean
distance transform, which is less sensitive to a ragged boundary than a
centroid. The side is clamped to the image bounds, and the center is shifted as
needed to keep the box within the image. The settings record the *requested*
side, and the analysis file records the box actually used.

Whether the box lies wholly inside the phantom is a separate field. A box that
extends outside the image is counted as not fitting, so that its empty selection
cannot pass vacuously.

For display, the convex hull of the mask is stored as a closed polygon in plot
order, $(x=\text{col}, y=\text{row})$, and not in array order, so that a
renderer requires no geometry code. A mask too small or too nearly collinear to
enclose an area yields an empty $(0, 2)$ outline and no error.

## Example

```{eval-rst}
.. plot::
   :caption: The phantom mask, its convex outline, and the summary ROI over the signal image.
   :filename-prefix: localization-geometry

   import matplotlib.pyplot as plt

   import phantom

   analysis = phantom.analysis()
   images = analysis.images
   measurements = analysis.measurements
   box = images.roi

   fig, axes = plt.subplots(figsize=(5.4, 5.2), layout="constrained")
   axes.imshow(images.signal, cmap="gray")
   axes.contour(images.phantom_mask, levels=[0.5], colors="C0", linewidths=1.2)
   axes.plot(
       images.phantom_hull[:, 0], images.phantom_hull[:, 1], "-", color="C1", lw=1.2
   )
   axes.add_patch(
       plt.Rectangle(
           (box.col0 - 0.5, box.row0 - 0.5),
           box.col1 - box.col0,
           box.row1 - box.row0,
           fill=False,
           edgecolor="C3",
           lw=1.4,
       )
   )
   axes.set_xlabel("col (voxels)")
   axes.set_ylabel("row (voxels)")
   axes.set_title(
       f"mask {100 * measurements.phantom_fraction:.1f}% of frame, "
       f"contrast {measurements.phantom_contrast:.0f}x",
       fontsize="small",
   )
```

The segmentation is drawn in blue, its convex outline in orange, and in red the
summary ROI over which every scalar on the [stability](stability.md) page is
averaged.

## Stored quantities

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.phantom_fraction` | attribute, double | share of the frame the mask covers, in [0, 1] |
| `measurements.phantom_contrast` | attribute, double | mask interior over background; infinite over an exactly-zero background |
| `measurements.phantom_mask_ok` | attribute, ubyte flag | the verdict on the two numbers above |
| `measurements.roi_inside_phantom` | attribute, ubyte flag | whether the summary ROI lies wholly within the mask |
| `images.phantom_mask` | variable `(row, col)`, mask | the phantom segmentation, stored as CF-flagged 0/1 bytes |
| `images.invalid_mask` | variable `(row, col)`, mask | the zeroed image edge, excluded from every statistic |
| `images.phantom_hull` | variable `(hull_vertex, hull_coord)` | closed convex outline of the mask, in (x, y) plot order |
| `hull_vertex` | coordinate, index | vertex of the closed outline; length 0 when the mask has no area |
| `hull_coord` | coordinate, flags `x y` | which outline coordinate, in plot order |
| `images.roi.row0` | attribute, int | first row of the summary ROI, inclusive |
| `images.roi.row1` | attribute, int | last row of the summary ROI, exclusive |
| `images.roi.col0` | attribute, int | first column of the summary ROI, inclusive |
| `images.roi.col1` | attribute, int | last column of the summary ROI, exclusive |

The summary ROI is not an array, so it is stored as four attributes: half-open
bounds in array order that index the `row` and `col` axes.

`analyze` always sets the two verdicts. An absent verdict can therefore arise
only from an analysis file written before the field existed, and it means *not
recorded*, which is neither a pass nor a failure. Treating it as either draws a
conclusion that the data do not support. `phantom_fraction` and
`phantom_contrast` are NaN in such files.

## References

- Friedman L, Glover GH. Report on a multicenter fMRI quality assurance
  protocol. *J Magn Reson Imaging* 2006;23:827–839.
  [doi:10.1002/jmri.20583](https://doi.org/10.1002/jmri.20583)
