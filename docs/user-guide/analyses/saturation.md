# ADC saturation

## What it is for

If the receiver gain is set too high, the analog-to-digital converter runs out
of range and the brightest voxels pile up on its top code. The reconstruction
that follows looks unremarkable — a slightly flat-topped phantom — but the
signal there is no longer proportional to anything, and every stability number
measured through those voxels is quietly wrong.

This check is a hint about the **acquisition**, not the reconstruction: what it
says is that a knob on the scanner side wants adjusting before the next run. It
answers in three states rather than two, and the third one is the reason the
check is worth its length: *not determinable*.

## Method

### Finding the rail

The clip ceiling is sequence-dependent and is not recorded anywhere in the
file, so it is inferred. A clipped magnitude image piles up on a hardware
$2^n - 1$ rail — a 12-bit ADC gives 4095 — so the series maximum is tested
against those values:

$$\text{rail} = \max_{v,t} I_{v,t} \quad\text{if}\quad
\max_{v,t} I_{v,t} = 2^n - 1 \ \text{ for some } n \in [8, 16]$$

A maximum that is *not* a $2^n - 1$ value means no clipping, and there is
nothing further to count. A maximum that is one means the run *may* be
saturated, and the pile-up on that value is then counted — a lone sample on the
rail is likely just a bright voxel, while a pile-up across a volume is real
saturation.

### Splitting at the trim boundary

The count is taken over the **full, untrimmed** series, because clipping is
worst in the high-signal warm-up volumes — and then split at the trim boundary:

- **`clip`** counts voxel·time samples on the rail in the analyzed volumes.
  These bias the metrics, so a nonzero count is flagged.
- **`clipPre`** counts samples confined to the dropped warm-up volumes. Those
  never reach the statistics, and are expected for sequences (ABCD among them)
  that deliberately acquire through the approach to steady state.

### Why the scanner's integers are required

A rail is an artifact of the receiver's ADC, so the check can only run on a
series that still carries the integers the scanner stored. Some converters
write float NIfTI and rescale as they go; that throws the rail away, and a
saturated run then looks exactly like a clean one.

So the loader records whether the file arrived as an integer type, and on a
float-stored series the whole clipping block answers `None` — *not
determinable*, printed as `?` in the table and `null` in the JSON. Reporting
"no clipping found" there would be the wrong verdict rather than a safe
default, and it would hide exactly the acquisitions this check exists to catch.
A reader that treats the absent answer as "clean" is reporting a scanner
verified against a check that never happened. Every other metric is unaffected
and still computed.

The practical consequence is a conversion requirement: give `fmri-qa`
integer-stored NIfTI (`dcm2niix` does this by default — check with `fslhd`, or
`nib.load(f).header.get_data_dtype()`), or give it DICOM and let
`fmri-qa-import` convert it with the flags that keep the integers. The
importer pins `-l o` for this reason: `-l y` "losslessly" rescales 16-bit
integers to fill the dynamic range, and the file it writes is *still* an
integer NIfTI, so the storage gate sees nothing wrong and no warning fires —
but every stored sample has been multiplied and the rail no longer sits at
$2^n - 1$. On a synthetic series clipped flat at 4095, `-l o` finds a 12-bit
rail and 7140 clipped samples where `-l y` finds none and reports the run
clean. That is the one saturation failure the storage gate cannot catch,
because the evidence it tests for is present and merely wrong.

There is no figure on this page: the check produces counts and a ceiling, not a
curve or an image.

## What it contributes to the artifact

| Name | Where it lives | Meaning |
| --- | --- | --- |
| `measurements.clipped_any` | attribute, ubyte flag | clipping anywhere in the full series, warm-up volumes included; **absent** when the check could not run |
| `measurements.clipped_kept` | attribute, ubyte flag | clipping reached the analyzed volumes, so the metrics are biased |
| `measurements.n_clipped_kept` | attribute, int | voxel·time samples on the rail in the analyzed volumes |
| `measurements.n_clipped_pre` | attribute, int | voxel·time samples on the rail in the dropped warm-up volumes |
| `measurements.clip_ceiling` | attribute, double | the inferred rail in image units; **absent** when no rail was found |
| `measurements.clip_bits` | attribute, int | $n$ such that the stored ceiling is $2^n - 1$; **absent** with the ceiling |

This block is the artifact's clearest case of *absent* rather than NaN. All six
fields are absent together when the series did not arrive as integers: the
estimator did not decline, it never ran. `clipped_any` is the field to test
first — `clip_ceiling` and `clip_bits` are also absent on a perfectly
determinable series that simply has no rail, so their absence alone says
nothing. An artifact from schema 6 or earlier always answers true or false
here, because the build that wrote it always answered; that false means "found
no rail", not "the storage was checked".

The check contributes no arrays and no coordinates.

## References

- The rail values are hardware, not protocol: $2^n - 1$ for
  $n \in [8, 16]$ covers the realistic MR receivers.
- dcm2niix's `-l` option
  ([rordenlab/dcm2niix](https://github.com/rordenlab/dcm2niix)) is what decides
  whether the evidence survives conversion.
