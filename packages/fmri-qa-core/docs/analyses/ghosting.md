# Nyquist ghosting

## What it is for

EPI reads k-space in alternating directions, and any mismatch between the even
and odd echo trains — eddy currents, gradient delays, a poor phase-correction
scan — puts a copy of the phantom half a field of view away along the
phase-encode axis. That copy is the Nyquist, or N/2, ghost, and its brightness
relative to the phantom is one of the most sensitive routine checks of EPI
calibration on a scanner.

The package reports four numbers rather than one, because a single region-mean
ratio hides two different things: a ghost that is bright but small, and a
"ghost" that is really just background. The four are the fBIRN region-mean
percent ghost, its localized top-10% companion, the same measurement taken
along the readout axis as a background baseline, and the ACR/AAPM-style
difference of the two directions.

## Method

### Resolving the phase-encode axis

Every ghost statistic is defined relative to an axis, so the axis is resolved
first, from the most authoritative source available:

1. the BIDS sidecar's `PhaseEncodingDirection`, or failing that
   `InPlanePhaseEncodingDirectionDICOM`;
2. the NIfTI header's `dim_info` phase field;
3. only if both are missing, an estimate from the data — the ghost masks are
   built for both in-plane axes and the axis whose ghost region is brighter
   wins, since rolling along the true axis lands the region on real ghost
   signal and rolling along the wrong one lands it on background. Only finite
   ratios participate: a single measurable axis wins, but exactly equal finite
   ratios (including two zeros), or no measurable axes, leave the estimate
   unresolved. Any strictly larger finite ratio wins; no near-tie tolerance is
   applied.

`--pe-axis` overrides all three. Polarity is not needed and is dropped. The
metrics work on one plane, so the phase-encode direction must be in-plane
(NIfTI axis `0`/`i` or `1`/`j`); a through-plane (`2`/`k`) acquisition is
rejected with an input error rather than analyzed on the wrong plane. When no
axis resolves at all, there is no ghost result: all four ghost measurements are
NaN and the region masks are absent from the artifact entirely.

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

so each ghost patch is compared against the exact tissue that produced it,
and the zone where phantom and ghost are superimposed — where the two cannot be
separated — is excluded from both. The masks are built once per in-plane axis
and every ratio is taken from them, so no two members of the family can
disagree, and a report drawing the regions is drawing what was measured.

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

**ghost %** is the fBIRN percent ghost. **ghT %** is its localized companion
(Greve's `fmriqa_ghostiness` in bxh), narrowing the numerator to the brightest
tenth of the ghost voxels — at least one voxel is always averaged, so it can
only be greater than or equal to the region mean, and a bright concentrated
ghost that the region mean dilutes still shows. **RO %** is the identical
measurement along the readout axis, where no N/2 ghost lands: it is a genuine
background-relative-to-signal baseline on the same scale. **ACRg %** is the
ACR/AAPM percent-signal-ghosting idea — subtract a background estimate from the
phase-encode ghost and normalize by the signal — expressed in region-matched
space. Because each direction carries its own matched denominator, subtracting
the readout ratio cancels the background exactly as ACR intends, without ACR's
single-signal assumption; for a uniform phantom the two denominators coincide
and it reduces to the classic form.

A ratio is NaN when the region it needed came back empty — the phantom spans
the field of view along that axis, or the segmentation collapsed — which is not
the same as a low ratio, and the difference matters when the axis estimate is
reading these values to pick a winner.

The band width $\rho$ and the top fraction are acquisition-dependent defaults
and are worth verifying per protocol.

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

Blue is the signal region, red the ghost region it is matched to. The synthetic
phantom has no real N/2 ghost, so both directions measure the background floor
and the ACR difference between them is near zero — which is what a
well-calibrated acquisition looks like.

## What it contributes to the artifact

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.ghost_pct` | attribute, double | fBIRN region-mean percent ghost along the phase-encode axis |
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

The four masks are present as a group or not at all: a run with no resolved
phase-encode axis has no ghost regions, and `images.has_ghost` is 0. `measurements.pe_axis` is the one
measurement that is *absent* rather than NaN when it does not apply, because
"no axis" is not a number the estimator failed to resolve — it is a quantity
that does not exist for that run. The four percentages are NaN in the same
situation. `pe_label` is always present, and reads `?` when nothing named a
direction.

## References

- Friedman L, Glover GH. J Magn Reson Imaging 2006;23:827–839 — the
  region-matched percent ghost.
- Greve DN, bxh/XCEDE `fmriqa_ghostiness` — the top-10% localized ghost, and
  the readout direction as a background baseline.
- ACR MRI Quality Control Manual / AAPM Report 100 — percent-signal ghosting,
  $\lvert \text{ghost}_{\text{PE}} - \text{ghost}_{\text{freq}} \rvert /
  \text{signal}$.
