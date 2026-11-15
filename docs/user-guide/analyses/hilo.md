# Thermal versus instability noise (high/low flip)

The other analyses treat noise as a single quantity, but it has two components.
**Thermal** noise is additive and electronic in origin (coil, preamplifier,
sample), and its variance is independent of the signal. **Instability** noise is
multiplicative (drift, gradient heating, fluctuations resembling physiological
noise, or anything else that modulates the signal), and its variance scales with
the square of the signal. A poor SFNR indicates that a problem exists.
Separating the two components indicates whether it lies in the receive chain or
in the stability of the system.

The high/low flip-angle method of Greve et al. (2011) achieves the separation
with two acquisitions that differ only in flip angle. Two signal levels and two
variances provide two equations in two unknowns. The method is a **pair-level**
diagnostic with its own command, `fmri-qa-hilo`, because it takes two scans and
reports quantities different from those of the per-scan table.

## The noise model

Let $\mu_H$ and $\mu_L$ denote the mean signals of the high- and low-flip runs,
$\sigma^2_H$ and $\sigma^2_L$ their variances, and let

$$M = \left(\frac{\mu_H}{\mu_L}\right)^2$$

be the squared signal ratio. The thermal variance is common to both runs,
whereas the instability variance scales with the square of the signal and hence
with $M$:

$$\sigma^2_H = \sigma^2_{\text{th}} + M\,\sigma^2_{\text{inst},0},
\qquad
\sigma^2_L = \sigma^2_{\text{th}} + \sigma^2_{\text{inst},0}$$

These equations have the solution

$$\sigma^2_{\text{th}} = \frac{M\,\sigma^2_L - \sigma^2_H}{M - 1},
\qquad
\sigma^2_{\text{inst}} = \sigma^2_H - \sigma^2_{\text{th}}$$

Measurement noise can drive $\sigma^2_{\text{inst}}$ negative, which is
unphysical. In that case the separation falls back to
$\sigma^2_{\text{th}} = \sigma^2_L$ and
$\sigma^2_{\text{inst}} = \sigma^2_H - \sigma^2_L$, and the result records that
the fallback was applied. The figures of merit are the functional SNR (FSNR)
with respect to each component and the fraction of the high-flip variance that
is due to instability:

$$\mathrm{FSNR}_{\text{th}} = \frac{\mu_H}{\sqrt{\sigma^2_{\text{th}}}},
\qquad
\mathrm{FSNR}_{\text{inst}} = \frac{\mu_H}{\sqrt{\sigma^2_{\text{inst}}}},
\qquad
\text{instability fraction} = \frac{\sigma^2_{\text{inst}}}{\sigma^2_H}$$

A high $\mathrm{FSNR}_{\text{inst}}$, that is, an instability variance that is
small relative to the high-flip variance, indicates a stable scanner.

## Estimation of the means and variances

Each scan is trimmed and detrended as in the main pipeline (`--trim-sec` and
`--detrend` have the same meaning as in the main command) and reduced to two
whole-volume maps: the temporal mean, and the temporal standard deviation of the
detrended residual. $\mu$ is the mean of the first map over the phantom core,
and $\sigma^2$ is the *square* of the core mean of the second.

The core is the eroded interior of the phantom **common to both runs**. Each run
is segmented with the watershed used in-plane by the
[localization](localization.md) analysis. The largest connected component is
retained and its holes are filled, and `--erode` layers of voxels (5 by default,
matching `3dAutomask -q -erode 5`) are removed to exclude edge and
partial-volume voxels. The two masks are then intersected, so that both means
cover the same voxels, as the ratio $M$ requires.

The two scans must agree in array geometry, frame count, affine, voxel size, TR,
and, where recorded, TE. A mismatch is rejected before either scan is processed,
so that acquisitions sampled differently are never pooled by array index. The
loader converts voxel sizes and the world coordinates of the affine, translation
included, to millimeters, so that scans recorded in meters, millimeters, and
microns can be paired. An unknown spatial unit is assumed to be millimeters, and
one warning is issued for each scan loaded. A caller that constructs a `QAScan`
directly must supply its affine in millimeters.

The high-flip scan is given first. A warning is issued if the recorded flip
angles indicate the opposite order.

## Example output

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

The analysis reduces a pair of runs to ten scalars, so there is no figure.

## Relation to the analysis file

`fmri-qa-hilo` writes no analysis file. It has no `--analysis-file` option, it
produces a `HiLoResult` and not a `QAAnalysis`, and none of the quantities above
appears in a `.qa.nc` file. Its output is the text table shown above, on stdout.

The omission is deliberate. The analysis file describes **one analyzed series**:
its provenance names one scan, one source, one TR, and one frame count. A
high/low result describes a *pair*, and that layout has no place for two scans,
two flip angles, and two variances. For the same reason the result is excluded
from the per-scan batch table, where a pair-level number would either be
repeated on both rows or belong to neither.

A consumer that requires these numbers in a database can parse the standard
output of the command, or call `fmriqa.run_hilo` and read the `HiLoResult`
directly.

## References

- Greve DN, Mueller BA, Liu T, et al. A novel method for quantifying scanner
  instability in fMRI. *Magn Reson Med* 2011;65:1053–1061.
  [doi:10.1002/mrm.22691](https://doi.org/10.1002/mrm.22691)
  The implementation follows the BXH `fmriqa` tools, and
  `notes/bxh-fmriqa-hilo.md` in the repository gives the derivation step by
  step.
- Cox RW. AFNI: software for analysis and visualization of functional magnetic
  resonance neuroimages. *Comput Biomed Res* 1996;29:162–173.
  [doi:10.1006/cbmr.1996.0014](https://doi.org/10.1006/cbmr.1996.0014)
  `3dAutomask -q -erode 5` defines the core mask over which the statistics are
  pooled.
