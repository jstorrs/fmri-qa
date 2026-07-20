# High/Low Flip Angle fMRI QA Analysis

This document describes the high/low flip angle QA method for separating thermal noise from instability noise in fMRI scanner quality assurance, as developed by Doug Greve (MGH).

## Overview

MRI signal variance has two primary sources:
1. **Thermal noise** - inherent electronic/physical noise in the scanner
2. **Instability noise** - scanner drift, gradient heating, physiological noise, etc.

By acquiring two phantom scans at different flip angles, these noise sources can be mathematically separated. The key insight is that thermal noise scales with signal intensity, while instability noise scales with the square of signal intensity.

## Inputs

- **High flip angle scan**: 4D phantom image (e.g., agar phantom) acquired at high flip angle
- **Low flip angle scan**: 4D phantom image of same phantom at low flip angle
- Both scans should have the same acquisition parameters except flip angle

## Processing Pipeline

For each input scan (high and low), perform the following steps:

### 1. Convert to NIfTI

```bash
bxh2analyze --overwrite -b -s -v --nii --nosform <input.bxh> <output_prefix>
```

### 2. Select Timepoints (Optional)

If only a subset of timepoints should be analyzed:

```bash
3dcalc -a '<input.nii>[<timepoint_selector>]' -expr 'a*1' -prefix <output_select.nii>
```

Timepoint selector format: `[0..10,15..20]` or `[5..$]` for timepoint 5 to end.

### 3. Detrend

Remove low-frequency drift with 2nd-order polynomial detrending:

```bash
3dDetrend -polort 2 -prefix <output_detrend.nii> <input_select.nii>
```

### 4. Compute Temporal Mean

```bash
3dTstat -mean -prefix <output_mean.nii> <input_select.nii>
```

### 5. Create Eroded Mask

Generate a mask of the phantom core, eroded by 5 voxels to exclude edge effects:

```bash
3dAutomask -q -erode 5 -prefix <output_mask.nii> <input_mean.nii>
```

### 6. Compute Temporal Standard Deviation

Compute stddev of the detrended data:

```bash
3dTstat -stdev -prefix <output_stddev.nii> <input_detrend.nii>
```

### 7. Extract ROI Statistics

Get mean signal and standard deviation within the mask:

```bash
3dROIstats -mask <mask.nii> <mean.nii>
3dROIstats -mask <mask.nii> <stddev.nii>
```

## Calculations

After processing both scans, extract these values:
- `MeanHigh` - mean signal intensity from high flip angle scan
- `MeanLow` - mean signal intensity from low flip angle scan
- `VarHigh` - variance from high flip angle scan (stddev²)
- `VarLow` - variance from low flip angle scan (stddev²)

### Noise Separation Formula

The flip angle ratio squared:
```
M = (MeanHigh / MeanLow)²
```

Thermal variance (scales linearly with signal):
```
ThermalVar = ((M × VarLow) - VarHigh) / (M - 1)
```

Instability variance (scales quadratically with signal):
```
InstabilityVar = VarHigh - ThermalVar
```

### Edge Case Handling

If `InstabilityVar < 0` (can occur due to noise), fall back to:
```
ThermalVar = VarLow
InstabilityVar = VarHigh - VarLow
```

### FSNR Metrics

Functional Signal-to-Noise Ratio for each noise component:
```
ThermalFSNR = MeanHigh / sqrt(ThermalVar)
InstabilityFSNR = MeanHigh / sqrt(InstabilityVar)
```

## Output Metrics

| Metric | Description |
|--------|-------------|
| `ThermalFSNR` | Signal-to-noise ratio for thermal noise component |
| `InstabilityFSNR` | Signal-to-noise ratio for instability noise component |
| `MeanHigh` | Mean signal in high flip angle scan (within mask) |
| `MeanLow` | Mean signal in low flip angle scan (within mask) |
| `VarHigh` | Temporal variance in high flip angle scan |
| `VarLow` | Temporal variance in low flip angle scan |
| `ThermalVar` | Separated thermal variance component |
| `InstabilityVar` | Separated instability variance component |
| `M` | (MeanHigh/MeanLow)² - the squared signal ratio |
| `NumVoxels` | Number of voxels in the eroded mask |

## Mathematical Background

The method exploits the different scaling behavior of noise sources with flip angle:

- **Thermal noise**: Variance is constant regardless of signal level (additive noise)
- **Instability noise**: Variance scales with signal² (multiplicative noise)

For two flip angles with signal ratio `r = MeanHigh/MeanLow`:
- High scan: `VarHigh = ThermalVar + r² × InstabilityVar₀`
- Low scan: `VarLow = ThermalVar + InstabilityVar₀`

Solving these equations yields the separation formulas above.

## References

- Greve DN, et al. "Accurate and robust brain image alignment using boundary-based registration." NeuroImage. 2009.
- FBIRN stability phantom protocols
