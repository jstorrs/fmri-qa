# ADC saturation

When the receiver gain is set too high, the analog-to-digital converter (ADC)
exceeds its range and the brightest voxels accumulate at its maximum code. The
phantom appears only slightly flattened, but the signal in those voxels no
longer follows the magnetization, and every stability measure that includes them
is biased without any outward sign.

The check concerns the **acquisition**: a positive result means that a scanner
setting must be adjusted before the next run. It has three outcomes, clipped,
not clipped, and *not determinable*, and the third is the most important to
report correctly.

## Detection of the ceiling

The clipping ceiling depends on the sequence and is not recorded in the file,
so it is inferred. A clipped magnitude image accumulates at a hardware limit of
$2^n - 1$ (4095 for a 12-bit ADC), and the maximum of the series is tested
against those values:

$$\text{rail} = \max_{v,t} I_{v,t} \quad\text{if}\quad
\max_{v,t} I_{v,t} = 2^n - 1 \ \text{ for some } n \in [8, 16]$$

A maximum that is *not* of the form $2^n - 1$ indicates no clipping, and nothing
remains to be counted. A maximum of that form indicates that the run *may* be
saturated, and the samples at that value are counted. A single sample at the
ceiling is most likely a bright voxel, whereas an accumulation across a volume
indicates genuine saturation. The range $n \in [8, 16]$ reflects receiver
hardware and not any protocol, and it covers the converters found in practice.

## Partition at the trim boundary

Samples are counted over the **full, untrimmed** series, because clipping is
most severe in the high-signal volumes that precede steady state. The count is
then divided at the trim boundary:

- **`clip`** is the number of voxel·time samples at the ceiling in the analyzed
  volumes. These bias the metrics, so any nonzero count is flagged.
- **`clipPre`** is the number of samples confined to the discarded initial
  volumes. These never enter the statistics, and they are expected for sequences
  (ABCD among them) that acquire through the approach to steady state.

## The requirement for stored integers

The ceiling is a property of the receiver's ADC, so the check is valid only for
a series that still contains the integers the scanner stored. Some converters
write floating-point NIfTI and rescale the values, which removes the ceiling and
makes a saturated run indistinguishable from a clean one.

The loader therefore records whether the file arrived with an integer data type.
For a series stored as floating point, the entire clipping block is `None`
(*not determinable*), printed as `?` in the table and as `null` in the JSON.
Reporting that no clipping was found would be an incorrect verdict and not a
conservative default, since it would conceal the very acquisitions the check is
intended to detect. A consumer that reads an absent result as a clean one
certifies a scanner on the basis of a check that was never performed. Every
other metric is unaffected and is still computed.

In practice, `fmri-qa` should be given integer-stored NIfTI or DICOM. dcm2niix
(Li et al., 2016) preserves the integers by default, which can be confirmed with
`fslhd` or `nib.load(f).header.get_data_dtype()`, and `fmri-qa-import` converts
DICOM with flags that guarantee it. The importer fixes `-l o` for this reason.
The alternative, `-l y`, "losslessly" rescales 16-bit integers to fill the
dynamic range. The result is *still* an integer NIfTI, so the storage test
passes and no warning is issued, yet every stored sample has been multiplied and
the ceiling no longer lies at $2^n - 1$. On a synthetic series clipped flat at
4095, `-l o` finds a 12-bit ceiling and 7140 clipped samples, whereas `-l y`
finds none and reports the run as clean. This is the one form of saturation that
the storage test cannot detect, because the integer evidence it relies on is
present but wrong.

The check yields counts and a ceiling, and neither a curve nor an image, so
this page has no figure.

## Stored quantities

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.clipped_any` | attribute, ubyte flag | clipping anywhere in the full series, warm-up volumes included; **absent** when the check could not run |
| `measurements.clipped_kept` | attribute, ubyte flag | clipping reached the analyzed volumes, so the metrics are biased |
| `measurements.n_clipped_kept` | attribute, int | voxel·time samples on the rail in the analyzed volumes |
| `measurements.n_clipped_pre` | attribute, int | voxel·time samples on the rail in the dropped warm-up volumes |
| `measurements.clip_ceiling` | attribute, double | the inferred rail in image units; **absent** when no rail was found |
| `measurements.clip_bits` | attribute, int | $n$ such that the stored ceiling is $2^n - 1$; **absent** with the ceiling |

This block is the clearest instance in the analysis file of a field that is
*absent* and not NaN. All six fields are absent together when the series did not
arrive as integers, because the estimator never ran. `clipped_any` should be
tested first. `clip_ceiling` and `clip_bits` are also absent for a determinable
series in which no ceiling was found, so their absence alone is not informative.

The check contributes no arrays and no coordinates.

## References

- Li X, Morgan PS, Ashburner J, Smith J, Rorden C. The first step for
  neuroimaging data analysis: DICOM to NIfTI conversion. *J Neurosci Methods*
  2016;264:47–56.
  [doi:10.1016/j.jneumeth.2016.03.001](https://doi.org/10.1016/j.jneumeth.2016.03.001)
  The `-l` option of [dcm2niix](https://github.com/rordenlab/dcm2niix)
  determines whether the evidence survives conversion.
