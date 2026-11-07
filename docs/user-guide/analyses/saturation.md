# ADC saturation

## What it is for

If the receiver gain is set too high, the analog-to-digital converter runs out
of range and the brightest voxels pile up on its top code. The phantom looks
slightly flat-topped, but the signal there no longer tracks anything, and every
stability number measured through those voxels is quietly wrong.

This check points at the **acquisition**: a scanner-side setting needs adjusting
before the next run. It answers in three states, and the third matters most:
*not determinable*.

## Method

### Finding the rail

The clip ceiling depends on the sequence and is not recorded in the file, so it
is inferred. A clipped magnitude image piles up on a hardware $2^n - 1$ rail (a
12-bit ADC gives 4095), so the series maximum is tested against those values:

$$\text{rail} = \max_{v,t} I_{v,t} \quad\text{if}\quad
\max_{v,t} I_{v,t} = 2^n - 1 \ \text{ for some } n \in [8, 16]$$

A maximum that is *not* a $2^n - 1$ value means no clipping, and there is
nothing to count. A maximum that is one means the run *may* be saturated, and
the pile-up on that value is counted. One sample on the rail is probably a
bright voxel. A pile-up across a volume is real saturation.

### Splitting at the trim boundary

The count is taken over the **full, untrimmed** series, because clipping is
worst in the high-signal warm-up volumes. It is then split at the trim
boundary:

- **`clip`** counts voxel·time samples on the rail in the analyzed volumes.
  These bias the metrics, so a nonzero count is flagged.
- **`clipPre`** counts samples confined to the dropped warm-up volumes. Those
  never reach the statistics. They are expected for sequences (ABCD among them)
  that acquire through the approach to steady state.

### Why the scanner's integers are required

A rail is an artifact of the receiver's ADC, so the check only works on a
series that still holds the integers the scanner stored. Some converters write
float NIfTI and rescale, which discards the rail and makes a saturated run look
clean.

The loader therefore records whether the file arrived as an integer type. For a
float-stored series the whole clipping block answers `None` (*not
determinable*), printed as `?` in the table and `null` in the JSON. Reporting
"no clipping found" there would be the wrong verdict, not a safe default. It
would hide exactly the acquisitions this check exists to catch. A reader who
treats "absent" as "clean" reports a scanner as verified by a check that never
happened. Every other metric is unaffected and still computed.

In practice, give `fmri-qa` integer-stored NIfTI (`dcm2niix` does this by
default; check with `fslhd` or `nib.load(f).header.get_data_dtype()`), or give
it DICOM and let `fmri-qa-import` convert it with flags that keep the integers.
The importer pins `-l o` for this reason. `-l y` "losslessly" rescales 16-bit
integers to fill the dynamic range. The file is *still* an integer NIfTI, so the
storage gate sees nothing wrong and no warning fires, but every stored sample
has been multiplied and the rail no longer sits at $2^n - 1$. On a synthetic
series clipped flat at 4095, `-l o` finds a 12-bit rail and 7140 clipped samples,
and `-l y` finds none and reports the run clean. This is the one saturation
failure the storage gate cannot catch, because the integer evidence it tests for
is present but wrong.

There is no figure: the check produces counts and a ceiling, not a curve or an
image.

## What it contributes to the analysis file

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.clipped_any` | attribute, ubyte flag | clipping anywhere in the full series, warm-up volumes included; **absent** when the check could not run |
| `measurements.clipped_kept` | attribute, ubyte flag | clipping reached the analyzed volumes, so the metrics are biased |
| `measurements.n_clipped_kept` | attribute, int | voxel·time samples on the rail in the analyzed volumes |
| `measurements.n_clipped_pre` | attribute, int | voxel·time samples on the rail in the dropped warm-up volumes |
| `measurements.clip_ceiling` | attribute, double | the inferred rail in image units; **absent** when no rail was found |
| `measurements.clip_bits` | attribute, int | $n$ such that the stored ceiling is $2^n - 1$; **absent** with the ceiling |

This block is the analysis file's clearest case of *absent* rather than NaN. All six
fields are absent together when the series did not arrive as integers, because
the estimator never ran. Test `clipped_any` first. `clip_ceiling` and
`clip_bits` are also absent on a determinable series with no rail, so their
absence alone says nothing.

The check contributes no arrays and no coordinates.

## References

- The rail values come from hardware, not protocol: $2^n - 1$ for
  $n \in [8, 16]$ covers realistic MR receivers.
- dcm2niix's `-l` option
  ([rordenlab/dcm2niix](https://github.com/rordenlab/dcm2niix)) decides whether
  the evidence survives conversion.
