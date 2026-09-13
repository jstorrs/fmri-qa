# Thermal versus instability noise (high/low flip)

## What it is for

Every other page here measures noise as one quantity. It is really two, and
they have different causes and different fixes. **Thermal** noise is additive
and electronic — the coil, the preamplifier, the sample — and its variance does
not depend on how much signal there is. **Instability** noise is
multiplicative — drift, gradient heating, physiological-like fluctuation,
anything that modulates the signal — and its variance scales with the signal
squared. A run with poor SFNR tells you something is wrong; separating the two
tells you whether to look at the receive chain or at the stability of the
system.

Doug Greve's high/low flip-angle method gets the separation from two
acquisitions that differ *only* in flip angle: two signal levels, two variances,
two equations, two unknowns. This is a **pair-level** diagnostic and it has its
own command, `fmri-qa-hilo`, because it takes two scans and reports a different
set of numbers than the per-scan table.

## Method

### The algebra

Write $\mu_H, \mu_L$ for the mean signal of the high- and low-flip runs and
$\sigma^2_H, \sigma^2_L$ for their variances, and let

$$M = \left(\frac{\mu_H}{\mu_L}\right)^2$$

be the squared signal ratio. Thermal variance is common to both runs;
instability variance scales with signal squared, hence with $M$:

$$\sigma^2_H = \sigma^2_{\text{th}} + M\,\sigma^2_{\text{inst},0},
\qquad
\sigma^2_L = \sigma^2_{\text{th}} + \sigma^2_{\text{inst},0}$$

which solve to

$$\sigma^2_{\text{th}} = \frac{M\,\sigma^2_L - \sigma^2_H}{M - 1},
\qquad
\sigma^2_{\text{inst}} = \sigma^2_H - \sigma^2_{\text{th}}$$

Measurement noise can drive $\sigma^2_{\text{inst}}$ negative, which is
unphysical; the separation then falls back to
$\sigma^2_{\text{th}} = \sigma^2_L$ and
$\sigma^2_{\text{inst}} = \sigma^2_H - \sigma^2_L$, and the result records that
it did. The reported figures of merit are functional SNRs against each
component, plus the share of the high-flip variance the instability accounts
for:

$$\mathrm{FSNR}_{\text{th}} = \frac{\mu_H}{\sqrt{\sigma^2_{\text{th}}}},
\qquad
\mathrm{FSNR}_{\text{inst}} = \frac{\mu_H}{\sqrt{\sigma^2_{\text{inst}}}},
\qquad
\text{instability fraction} = \frac{\sigma^2_{\text{inst}}}{\sigma^2_H}$$

A high $\mathrm{FSNR}_{\text{inst}}$ — a small instability variance relative to
the high-flip variance — is a stable scanner.

### What the statistics are pooled over

Each scan is trimmed and detrended exactly as the main pipeline does
(`--trim-sec` and `--detrend` mirror the main command), and reduced to two
whole-volume maps: the temporal mean, and the temporal SD of the detrended
residual. $\mu$ is the core mean of the first map; $\sigma^2$ is the *square*
of the core mean of the second.

The core is the **shared** eroded phantom interior: each run's volume is
segmented with the same watershed used in-plane, the largest connected
component is kept with its interior holes filled, `--erode` voxel layers (5 by
default, matching `3dAutomask -q -erode 5`) are peeled off to exclude edge and
partial-volume voxels, and the two masks are intersected. Both means therefore
cover identical voxels, which is the precondition for the ratio $M$ meaning
what the algebra assumes it means.

The pair must match in array geometry, frame count, affine, voxel size, TR, and
TE where recorded; an incompatibility is rejected before either scan is
processed, so differently sampled acquisitions cannot be pooled by array index.
Pass the high-flip scan first — a warning fires if the recorded flip angles say
otherwise.

## What it looks like

```console
$ uv run fmri-qa-hilo HIGH_flip.nii.gz LOW_flip.nii.gz
# hi/lo flip-angle thermal/instability noise separation (Greve)
# high = FBIRN_QA_fMRI_flip77_14.nii.gz (flip 77)
# low  = FBIRN_QA_fMRI_flip10_15.nii.gz (flip 10)
# core voxels = 20502
ThermalFSNR                639.6224
InstabilityFSNR           3083.9969
MeanHigh                  1023.3249
MeanLow                    184.3902
VarHigh                      2.6697
VarLow                       2.5632
ThermalVar                   2.5596
InstabilityVar               0.1101
M                           30.8000
InstabilityFraction          0.0412
```

There is no figure: the analysis reduces a pair of runs to ten scalars and
publishes no curve or image.

## What it contributes to the artifact

**Nothing.** `fmri-qa-hilo` writes no artifact at all. It has no `--artifact`
flag, it produces a `HiLoResult` rather than a `QAArtifact`, and none of the
quantities above appears anywhere in a `.qa.nc` file — no measurement, no
variable, no coordinate, no provenance field. Its output is the text table
above, on stdout.

That is deliberate rather than pending. The artifact describes **one analyzed
series**: its provenance names one scan, one source, one TR, one frame count.
A hi/lo result is a statement about a *pair*, and the fields that would have to
carry it (two scans, two flip angles, two variances) have no home in a layout
built around a single acquisition. Keeping it out also keeps it out of the
per-scan batch table, where a pair-level number would have to be repeated
against both rows or attached to neither.

A consumer that wants these numbers in a database should parse the command's
stdout, or call `fmriqc.run_hilo` and read the `HiLoResult` directly.

## References

- Greve DN — the high/low flip-angle separation, as implemented in bxh's
  `fmriqa` tooling. See `notes/bxh-fmriqa-hilo.md` in this repository for the
  derivation this follows step by step.
- AFNI `3dAutomask -q -erode 5` — the core mask the statistics are pooled over.
