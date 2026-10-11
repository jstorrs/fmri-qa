# Phantom localization

## What it is for

Every other number in the artifact is measured through two pieces of geometry:
the phantom mask, and the square summary ROI. Localization is how those two are
found, and — just as important — how the run says whether they landed where
they must.

Both can fail *quietly*. A watershed that never separated phantom from
background still returns a mask; an ROI sitting in air still yields an average.
So the analysis publishes not only the geometry but a verdict on it, which is
what lets a reader of a stored artifact tell "the estimator declined" (a NaN
beside a good mask) from "the analysis was measuring background" (a number
beside a failed one). Nothing is raised on a bad mask: a batch reports the scan
and keeps going, and the affected metrics resolve to NaN on their own.

## Method

### Choosing the slice

The metrics are computed on a single plane of the volume. `--center image`
(the default, and the Glover convention) takes the geometric middle slice and
assumes the phantom is centered in the FOV. `--center phantom` instead
segments every slice and takes the one with the largest phantom
cross-section — more robust to a mispositioned phantom, but not the standard
protocol. A slice holding no recognizable phantom scores zero area, so a
prescription that runs off the end of the phantom cannot win on the strength of
a segmentation of its own air; if no slice holds one, the middle slice is used
and a warning says so. The chosen plane is recorded in provenance
(`provenance.slice_index` of `provenance.n_slices`), without which two
artifacts of one series cannot be told apart.

### Segmenting the phantom

The segmentation target is the time-MIP of the analyzed slice, $M$ — the
per-voxel maximum over frames, the most permissive image of where signal ever
was. The mask is a watershed of the Sobel edge magnitude of $M$, seeded from
the intensity quantiles:

$$\text{background seed} = \{v : M_v \le Q_{0.1}(M)\}, \qquad
\text{phantom seed} = \{v : M_v \ge Q_{0.9}(M)\}$$

The Sobel filter wraps rather than pads at the image border, because an MRI
image is periodic under FFT reconstruction. The seeds are inclusive ($\le$,
$\ge$) rather than strict: a strict comparison seeds *nothing* whenever a tenth
or more of the image sits exactly on the minimum — an exactly-zero background,
which background-suppressed and mask-multiplied reconstructions do produce —
and a watershed with no background seed floods the whole frame as phantom.

If the two quantiles coincide, inclusive seeds would overlap — for example,
both quantiles are zero when a small phantom fills less than a tenth of an
otherwise zero frame. In that case, the minimum intensity seeds background
and the maximum seeds phantom instead. These classes are disjoint whenever
the image is nonconstant. A constant image has no distinct classes and returns
an empty mask, which fails the segmentation verdict below and retains the
usual warning. The same rule applies to the 3-D watershed used to form the
hi/lo phantom core before filling holes, keeping the largest connected
component, and eroding its boundary.

Separately, any image edge that is entirely nulled is excluded from every
statistic. Some vendors null one outer row or column to encode the
phase-encode direction; a nulled border carries no signal, but blanket-trimming
one voxel on all four sides would discard valid data on the other three, so
each edge is tested on its own. The test compares against the value a *stored*
zero reads back as — `get_fdata` returns $\text{stored} \times
\text{slope} + \text{inter}$, so under a nonzero `scl_inter` a nulled edge
reads as exactly the intercept, not as 0.

### Judging the segmentation

Two cheap tests decide whether that mask *is* a phantom. The first is the share
of the frame it covers,

$$f = \frac{|\text{mask}|}{|\text{frame}|}$$

which a collapse drives to 0 or to 1. The second is how far the mask's interior
stands above the background it was cut from,

$$c = \frac{\langle M \rangle_{\text{inside}}}
{\langle M \rangle_{\text{outside}}}$$

which a partition of pure noise never passes: air segments at about 1.5–1.9, a
faint phantom at about 10, an ordinary one at about 160. An exactly-zero
background makes $c$ infinite (any signal at all is contrast enough); a mask
that partitions nothing — empty, or the whole frame — scores 0. The verdict is

$$\text{mask ok} \iff 0 < f < 0.95 \;\wedge\; c \ge 4$$

and it is settled here, once, rather than left to each consumer: the bounds
live with the segmentation, and a reader in another distribution cannot import
that layer. Both numbers are published beside the verdict so a report can say
*which* test a bad mask failed. The same test is what ranks slices under
`--center phantom`, so a run cannot report "no slice holds a phantom" and then
record the phantom it segmented anyway as good.

### Placing the ROI

The summary ROI is a square of side `--roi-size` (21 voxels by default, the
FBIRN size). Its center is the image-matrix center under `--center image`, and
the phantom's own center under `--center phantom` — the latter taken as the
mask voxel farthest from any background, i.e. the maximum of the Euclidean
distance transform of the mask, which is the most interior point rather than
the centroid of a possibly ragged segmentation. The side is clamped to the
image bounds and the center shifted if needed to keep the box on-image; the
*requested* side is what the settings publish, and the box the artifact carries
is the one actually used.

Whether the box also lies wholly inside the phantom is a separate question,
answered by a separate field: an out-of-bounds box counts as not fitting, so
the empty selection it would produce cannot pass vacuously.

### The outline

For drawing, the mask's convex hull is materialized as a closed polygon in plot
order — $(x=\text{col}, y=\text{row})$, not array order — so a renderer needs no
computational geometry of its own. A mask too small or too collinear to enclose
an area yields an empty $(0, 2)$ outline rather than an error.

## What it looks like

```{eval-rst}
.. plot::
   :caption: The phantom mask, its convex outline, and the summary ROI over the signal image.
   :filename-prefix: localization-geometry

   import matplotlib.pyplot as plt

   import phantom

   artifact = phantom.artifact()
   images = artifact.images
   measurements = artifact.measurements
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

Blue is the segmentation, orange its convex outline, red the summary ROI every
scalar on the [stability](stability.md) page is averaged over.

## What it contributes to the artifact

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

The summary ROI is not an array, so it is four attributes rather than a
variable: half-open bounds in array order, indexing the `row` and `col` axes.

The two verdicts follow the artifact's absent-versus-NaN rule in its sharper
form. `analyze` always answers them, so an absent verdict can only come from an
artifact written before the field existed; it means *not recorded*, which is
neither a pass nor a failure, and a reader that treats it as either is drawing a
conclusion the data does not support. `phantom_fraction` and
`phantom_contrast` are NaN on those same artifacts.

## References

- Friedman L, Glover GH. J Magn Reson Imaging 2006;23:827–839 — the 21×21 ROI
  at the image center on the middle slice, which `--center image` reproduces.
- The `--center phantom` mode and the mask verdicts have no protocol behind
  them; they exist because a mispositioned phantom and a collapsed segmentation
  both produce numbers that look ordinary.
