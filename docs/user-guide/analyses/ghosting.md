# Nyquist ghosting

EPI traverses k-space in alternating directions. A mismatch between the even and
odd echo trains, whether from eddy currents, gradient delays, or an inadequate
phase-correction scan, produces a copy of the phantom displaced by half a field
of view along the phase-encode axis. This Nyquist, or N/2, ghost is among the
most sensitive routine indicators of EPI calibration.

A single region-mean ratio conflates two distinct cases: a ghost that is bright
but small, and an apparent ghost that is only background. The package therefore
reports four quantities: the FBIRN region-mean percent ghost (Friedman & Glover,
2006), a localized variant computed from the brightest tenth of the ghost
region, the same measurement along the readout axis as a baseline, and a
difference of the two directions in the manner of the ACR and AAPM.

## The phase-encode axis

Every ghost statistic is defined relative to an axis, so the axis is resolved
first, from the most authoritative source available:

1. the BIDS sidecar fields `PhaseEncodingDirection`, `PhaseEncodingAxis` and
   `InPlanePhaseEncodingDirectionDICOM`, in that order, each consulted only
   when the preceding field is absent;
2. the `dim_info` phase field of the NIfTI header;
3. an estimate from the data, used only when both of the above are missing.
   Ghost masks are constructed for both in-plane axes, and the axis with the
   brighter ghost region is selected, because a shift along the true axis lands
   on ghost signal and a shift along the other lands on background. Only finite
   ratios are considered, and a single measurable axis is selected outright.
   Equal finite ratios (two zeros included), or the absence of any measurable
   axis, leave the estimate unresolved. No tolerance is applied for near-ties.

The first phase-encoding field present in the sidecar must be valid. A malformed
value (an empty string, null, a boolean, a number, or any string other than
`i`, `i-`, `j`, `j-`, `k` or `k-`) raises an input error that names the field,
even when a weaker source could have supplied the axis. A valid authoritative
field takes precedence over the weaker sources.

The `--pe-axis` option overrides all three sources. Polarity is discarded. The
metrics are computed on a single plane, so the direction must lie in that plane
(NIfTI axis `0`/`i` or `1`/`j`), and a through-plane (`2`/`k`) acquisition
raises an input error. When no axis can be resolved, all four ghost measurements
are NaN and the region masks are absent from the analysis file.

## Region-matched masks

Let $P$ denote the phantom mask, $a$ a candidate axis, and
$S = \lfloor N_a / 2 \rfloor$ a shift of half the field of view along it. The
ghost region is the phantom shifted circularly by $S$ and eroded, with the
dilated phantom and any nulled image edge removed:

$$G_a = \operatorname{erode}_\rho(\operatorname{roll}_a(P, S))
\;\cap\; \overline{\operatorname{dilate}_\rho(P)}
\;\cap\; V$$

where $\rho = 3$ voxels is the radius of erosion and dilation and $V$ is the
mask of valid data. The matching signal region is the same region shifted
*back*:

$$\Sigma_a = \operatorname{roll}_a(G_a, -S)$$

so that each ghost patch is compared with the part of the phantom that produced
it. Where the phantom and its ghost overlap they cannot be separated, and that
zone is excluded from both regions. The masks are constructed once per in-plane
axis, and every ratio is derived from them. The four measurements are
consequently consistent with one another, and a report that draws the regions
draws exactly what was measured.

## Measures

With $\bar S_v$ the signal (temporal mean) image, the region-mean ratio along
an axis is

$$g_a = \frac{\langle \bar S \rangle_{G_a}}{\langle \bar S \rangle_{\Sigma_a}}$$

Writing $p$ for the phase-encode axis and $r$ for the readout axis, the four
reported percentages are

$$\text{ghost \%} = 100\,g_p, \qquad
\text{RO \%} = 100\,g_r, \qquad
\text{ACRg \%} = 100\,\lvert g_p - g_r \rvert$$

$$\text{ghT \%} = 100\,
\frac{\operatorname{mean}\big(\text{top } 10\% \text{ of } \bar S|_{G_p}\big)}
{\langle \bar S \rangle_{\Sigma_p}}$$

**ghost %** is the FBIRN percent ghost. **ghT %** is its localized counterpart,
taken from Greve's `fmriqa_ghostiness` in the BXH/XCEDE tools. Its numerator is
the mean of the brightest tenth of the ghost voxels (at least one voxel), so it
is never smaller than the region mean, and it reveals a bright, concentrated
ghost that the region mean dilutes. **RO %** is the same measurement along the
readout axis. No N/2 ghost falls there, so it serves as a background baseline on
the same scale.

**ACRg %** adapts the percent-signal-ghosting measure of the ACR and AAPM
(American College of Radiology, 2015; Jackson et al., 2010), which subtracts a
background estimate from the phase-encode ghost and normalizes by the signal, to
region-matched space. Each direction has its own matched denominator, so
subtracting the readout ratio cancels the background without the ACR assumption
of a single signal level. For a uniform phantom the denominators coincide and
the measure reduces to the classical form.

A ratio is NaN when its region is empty, which occurs when the phantom spans the
field of view along that axis or the segmentation has collapsed. This is
distinct from a low ratio, and the distinction matters when the axis estimate
compares these values.

The band width $\rho$ and the top fraction are defaults that depend on the
acquisition and should be verified for each protocol.

## Example

```{eval-rst}
.. plot::
   :caption: The region-matched signal and ghost masks for both axes, over the signal image.
   :filename-prefix: ghosting-regions

   import matplotlib.pyplot as plt

   import phantom

   analysis = phantom.analysis()
   images = analysis.images
   measurements = analysis.measurements
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

The signal region is outlined in blue and the ghost region matched to it in red.
The synthetic phantom fills about 0.8 of the field of view, as the FBIRN phantom
does, so it overlaps its own ghost. The ghost regions are the parts of the
shifted phantom that fall outside the overlap, and the signal regions are the
parts of the phantom that produce them.
The synthetic phantom contains no true N/2 ghost. Both directions therefore
measure the background floor, and the ACR difference is close to zero, as it is
for a well-calibrated acquisition.

## Stored quantities

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

The four masks are present together or not at all. When no phase-encode axis is
resolved, there are no ghost regions and `images.has_ghost` is 0. The four
percentages are then NaN, whereas `measurements.pe_axis` is *absent*: the lack
of an axis is not a value that an estimator failed to resolve, because the
quantity does not exist for that run. `pe_label` is always present and reads
`?` when no source named a direction.

## References

- American College of Radiology. *Magnetic Resonance Imaging Quality Control
  Manual.* Reston, VA: ACR; 2015.
- Friedman L, Glover GH. Report on a multicenter fMRI quality assurance
  protocol. *J Magn Reson Imaging* 2006;23:827–839.
  [doi:10.1002/jmri.20583](https://doi.org/10.1002/jmri.20583)
- Greve DN. `fmriqa_ghostiness`, in the BXH/XCEDE tools. The source of the
  localized top-10% ghost and of the readout direction as a background
  baseline.
- Jackson EF, Bronskill MJ, Drost DJ, et al. *Acceptance Testing and Quality
  Assurance Procedures for Magnetic Resonance Imaging Facilities.* AAPM Report
  No. 100. College Park, MD: American Association of Physicists in Medicine;
  2010.
