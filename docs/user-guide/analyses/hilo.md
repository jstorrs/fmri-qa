# Thermal versus instability noise (high/low flip)

## What it is for

Every other page here measures noise as one quantity. It is really two.
**Thermal** noise is additive and electronic (coil, preamplifier, sample), and
its variance does not depend on the signal. **Instability** noise is
multiplicative (drift, gradient heating, physiological-like fluctuation,
anything that modulates the signal), and its variance scales with the signal
squared. Poor SFNR says something is wrong. Separating the two says whether to
look at the receive chain or at system stability.

Doug Greve's high/low flip-angle method does this with two acquisitions that
differ only in flip angle: two signal levels, two variances, two equations, two
unknowns. It is a **pair-level** diagnostic with its own command,
`fmri-qa-hilo`, because it takes two scans and reports different numbers than
the per-scan table.

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
unphysical. The separation then falls back to $\sigma^2_{\text{th}} =
\sigma^2_L$ and $\sigma^2_{\text{inst}} = \sigma^2_H - \sigma^2_L$, and the
result records the fallback. The figures of merit are functional SNRs against
each component, plus the share of the high-flip variance due to instability:

$$\mathrm{FSNR}_{\text{th}} = \frac{\mu_H}{\sqrt{\sigma^2_{\text{th}}}},
\qquad
\mathrm{FSNR}_{\text{inst}} = \frac{\mu_H}{\sqrt{\sigma^2_{\text{inst}}}},
\qquad
\text{instability fraction} = \frac{\sigma^2_{\text{inst}}}{\sigma^2_H}$$

A high $\mathrm{FSNR}_{\text{inst}}$ (a small instability variance relative to
the high-flip variance) means a stable scanner.

### What the statistics are pooled over

Each scan is trimmed and detrended as in the main pipeline (`--trim-sec` and
`--detrend` mirror the main command) and reduced to two whole-volume maps: the
temporal mean and the temporal SD of the detrended residual. $\mu$ is the core
mean of the first. $\sigma^2$ is the *square* of the core mean of the second.

The core is the **shared** eroded phantom interior. Each run is segmented with
the same watershed used in-plane, the largest connected component is kept with
its holes filled, and `--erode` voxel layers (5 by default, matching
`3dAutomask -q -erode 5`) are peeled off to drop edge and partial-volume
voxels. The two masks are intersected, so both means cover the same voxels, as
the ratio $M$ requires.

The pair must match in array geometry, frame count, affine, voxel size, TR, and
TE where recorded. A mismatch is rejected before either scan is processed, so
differently sampled acquisitions are never pooled by array index. The loader
converts voxel sizes and affine world coordinates (including translation) to
millimeters, so meters, millimeters, and microns can be paired. An unknown
spatial unit is assumed to be millimeters, with one warning per loaded scan.
Callers constructing `QAScan` directly must supply its affine in millimeters.

Pass the high-flip scan first. A warning fires if the recorded flip angles say
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

There is no figure. The analysis reduces a pair of runs to ten scalars.

## What it contributes to the analysis file

**Nothing.** `fmri-qa-hilo` writes no analysis file. It has no `--analysis-file` flag,
it produces a `HiLoResult` instead of a `QAAnalysis`, and none of the
quantities above appears in a `.qa.nc` file. Its output is the text table above,
on stdout.

This is by design. The analysis file describes **one analyzed series**: its
provenance names one scan, one source, one TR, one frame count. A hi/lo result
describes a *pair*, and two scans, two flip angles, and two variances have no
home in that layout. It also stays out of the per-scan batch table, where a
pair-level number would repeat on both rows or attach to neither.

A consumer that wants these numbers in a database should parse the command's
stdout, or call `fmriqa.run_hilo` and read the `HiLoResult` directly.

## References

- Greve DN. The high/low flip-angle separation, as implemented in the
  bxh `fmriqa` tools. See `notes/bxh-fmriqa-hilo.md` in this repository for the
  derivation this follows step by step.
- AFNI `3dAutomask -q -erode 5`. The core mask the statistics are pooled over.
