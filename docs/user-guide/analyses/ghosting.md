# Nyquist ghosting

## What it is for

EPI reads k-space in alternating directions. A mismatch between the even and odd
echo trains (eddy currents, gradient delays, a poor phase-correction scan) puts
a copy of the phantom half a field of view away along the phase-encode axis.
This Nyquist, or N/2, ghost is one of the most sensitive routine checks of EPI
calibration.

A single region-mean ratio hides two different things: a ghost that is bright but
small, and a "ghost" that is really just background. So the package reports four
numbers: the FBIRN region-mean percent ghost, its localized top-10% companion,
the same measurement along the readout axis as a baseline, and the ACR/AAPM-style
difference of the two directions.

## Method

### Resolving the phase-encode axis

Every ghost statistic is defined relative to an axis, so the axis is resolved
first, from the best source available:

1. the BIDS sidecar's `PhaseEncodingDirection`, then `PhaseEncodingAxis`, then
   `InPlanePhaseEncodingDirectionDICOM`, moving on only when a field is absent;
2. the NIfTI header's `dim_info` phase field;
3. only if both are missing, an estimate from the data. Ghost masks are built
   for both in-plane axes and the axis with the brighter ghost region wins,
   because rolling along the true axis lands on ghost signal and the wrong axis
   lands on background. Only finite ratios count. One measurable axis wins.
   Equal finite ratios (including two zeros) or no measurable axis leave the
   estimate unresolved. There is no near-tie tolerance.

The first sidecar phase-encoding field present must be valid. A malformed value
raises an input error naming the field, including an empty string, null, boolean,
number, or any string outside `i`/`i-`/`j`/`j-`/`k`/`k-`. The error is raised
even if a weaker source could supply the axis. A valid authoritative field takes
precedence over the weaker ones.

`--pe-axis` overrides all three. Polarity is dropped. The metrics work on one
plane, so the direction must be in-plane (NIfTI axis `0`/`i` or `1`/`j`). A
through-plane (`2`/`k`) acquisition raises an input error. When no axis
resolves, all four ghost measurements are NaN and the region masks are absent
from the artifact.

### The region-matched masks

Write $P$ for the phantom mask, $a$ for a candidate axis, and $S$ for a roll of
half the field of view along it, $S = \lfloor N_a / 2 \rfloor$. The ghost
region is the phantom rolled by $S$, eroded, with the dilated phantom and any
nulled image edge removed:

$$G_a = \operatorname{erode}_\rho(\operatorname{roll}_a(P, S))
\;\cap\; \overline{\operatorname{dilate}_\rho(P)}
\;\cap\; V$$

with $\rho = 3$ voxels the erosion/dilation radius and $V$ the valid-data mask.
The matching signal region is that same region rolled *back*:

$$\Sigma_a = \operatorname{roll}_a(G_a, -S)$$

so each ghost patch is compared against the tissue that produced it. Where
phantom and ghost overlap they cannot be separated, so that zone is excluded
from both. The masks are built once per in-plane axis and every ratio comes from
them. No two members of the family can disagree, and a report that draws the
regions draws what was measured.

### The four measurements

With $\bar S_v$ the signal (temporal mean) image, the region-mean ratio along
an axis is

$$g_a = \frac{\langle \bar S \rangle_{G_a}}{\langle \bar S \rangle_{\Sigma_a}}$$

and the four published percentages are, writing $p$ for the phase-encode axis
and $r$ for the readout axis:

$$\text{ghost \%} = 100\,g_p, \qquad
\text{RO \%} = 100\,g_r, \qquad
\text{ACRg \%} = 100\,\lvert g_p - g_r \rvert$$

$$\text{ghT \%} = 100\,
\frac{\operatorname{mean}\big(\text{top } 10\% \text{ of } \bar S|_{G_p}\big)}
{\langle \bar S \rangle_{\Sigma_p}}$$

**ghost %** is the FBIRN percent ghost. **ghT %** is its localized companion
(Greve's `fmriqa_ghostiness` in bxh). Its numerator is the mean of the brightest
tenth of the ghost voxels (at least one voxel), so it is never below the region
mean, and a bright concentrated ghost that the region mean dilutes still shows.
**RO %** is the same measurement along the readout axis, where no N/2 ghost
lands, so it is a background baseline on the same scale. **ACRg %** follows the
ACR/AAPM percent-signal-ghosting idea (subtract a background estimate from the
phase-encode ghost, normalize by the signal) in region-matched space. Each
direction has its own matched denominator, so subtracting the readout ratio
cancels the background without ACR's single-signal assumption. For a uniform
phantom the denominators coincide and it reduces to the classic form.

A ratio is NaN when its region is empty (the phantom spans the field of view
along that axis, or the segmentation collapsed). That differs from a low ratio,
which matters when the axis estimate uses these values to pick a winner.

The band width $\rho$ and the top fraction are acquisition-dependent defaults.
Verify them per protocol.

## What it looks like

```{eval-rst}
.. plot::
   :caption: The region-matched signal and ghost masks for both axes, over the signal image.
   :filename-prefix: ghosting-regions

   import matplotlib.pyplot as plt

   import phantom

   artifact = phantom.artifact()
   images = artifact.images
   measurements = artifact.measurements
   regions = images.ghost

   pairs = [
       ("phase encode", regions.pe_signal, regions.pe_ghost),
       ("readout", regions.ro_signal, regions.ro_ghost),
   ]

   fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.8), layout="constrained")
   for panel, (title, signal, ghost) in zip(axes, pairs, strict=True):
       panel.imshow(images.signal, cmap="gray")
       panel.contour(signal, levels=[0.5], colors="C0", linewidths=1.1)
       panel.contour(ghost, levels=[0.5], colors="C3", linewidths=1.1)
       panel.set_title(title, fontsize="small")
       panel.set_xlabel("col (voxels)", fontsize="small")
       panel.set_ylabel("row (voxels)", fontsize="small")

   fig.suptitle(
       f"ghost {measurements.ghost_pct:.2f}%   "
       f"ghT {measurements.ghost_top_pct:.2f}%   "
       f"RO {measurements.ro_ghost_pct:.2f}%   "
       f"ACRg {measurements.acr_ghost_pct:.3f}%",
       fontsize="small",
   )
```

Blue is the signal region, red the ghost region matched to it. The synthetic
phantom has no real N/2 ghost, so both directions measure the background floor
and the ACR difference is near zero, as in a well-calibrated acquisition.

## What it contributes to the artifact

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.ghost_pct` | attribute, double | FBIRN region-mean percent ghost along the phase-encode axis |
| `measurements.ghost_top_pct` | attribute, double | localized percent ghost over the brightest 10% of ghost voxels |
| `measurements.ro_ghost_pct` | attribute, double | the same region-matched percent ghost along the readout axis |
| `measurements.acr_ghost_pct` | attribute, double | ACR/AAPM percent-signal-ghosting: the absolute difference between the phase-encode and readout percent ghosts |
| `measurements.pe_axis` | attribute, int | the array axis the ghost was measured on (0 or 1); **absent** when none resolved |
| `measurements.pe_label` | attribute, text | the direction as it should be displayed: `row`, `col`, or `?` |
| `images.ghost.pe_signal` | variable `(row, col)`, mask | phase-encode signal region the ratio is measured against |
| `images.ghost.pe_ghost` | variable `(row, col)`, mask | phase-encode ghost region |
| `images.ghost.ro_signal` | variable `(row, col)`, mask | readout signal region, the baseline's denominator |
| `images.ghost.ro_ghost` | variable `(row, col)`, mask | readout ghost region |
| `images.has_ghost` | attribute, ubyte flag | whether the four masks above are present |

The four masks are present together or not at all. With no resolved
phase-encode axis there are no ghost regions and `images.has_ghost` is 0. The
four percentages are NaN, and `measurements.pe_axis` is *absent* rather than
NaN. "No axis" is not a value the estimator failed to resolve. The quantity does
not exist for that run. `pe_label` is always
present and reads `?` when nothing named a direction.

## References

- Friedman L, Glover GH. J Magn Reson Imaging 2006;23:827–839. The
  region-matched percent ghost.
- Greve DN, bxh/XCEDE `fmriqa_ghostiness`. The top-10% localized ghost, and
  the readout direction as a background baseline.
- ACR MRI Quality Control Manual / AAPM Report 100. Percent-signal ghosting,
  $\lvert \text{ghost}_{\text{PE}} - \text{ghost}_{\text{freq}} \rvert /
  \text{signal}$.
