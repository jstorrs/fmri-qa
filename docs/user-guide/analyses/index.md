# The analyses

Eight analyses run over a phantom series. Seven of them publish into the
[analysis file](../analysis-file.md); the eighth takes a pair of scans and
publishes nothing.

Each page covers what the analysis is for, how it works, a figure drawn by the
real pipeline on a synthetic phantom when the docs are built, and a table of
what it adds to the analysis file under its netCDF names.

| Analysis | What it measures | Publishes |
| --- | --- | --- |
| [FBIRN stability](stability.md) | signal against static and temporal noise, the drift removed, and how far the noise is from independent voxel to voxel | `snr`, `sfnr`, `rdc`, `drift_pct`, `percent_fluctuation` |
| [Phantom localization](localization.md) | where the phantom and the summary ROI are, and whether either landed correctly | `phantom_fraction`, `phantom_contrast`, `phantom_mask_ok`, `roi_inside_phantom` |
| [Nyquist ghosting](ghosting.md) | the N/2 ghost against the tissue that produced it, four ways, plus the axis it was measured on | `ghost_pct`, `ghost_top_pct`, `ro_ghost_pct`, `acr_ghost_pct`, `pe_axis`, `pe_label` |
| [ADC saturation](saturation.md) | whether the receiver clipped, split at the warm-up trim — with a third answer for "not determinable" | `clipped_any`, `clipped_kept`, `n_clipped_kept`, `n_clipped_pre`, `clip_ceiling`, `clip_bits` |
| [Outliers and spikes](outliers.md) | the bad volume and the dominant periodic artifact that averages hide | `outlier_max_pct`, `outlier_worst_frame`, `tc_outlier`, `spec_outlier` |
| [Motion and deformation](motion.md) | the translation, scale and shear gradient heating produces, and a mask-free centroid trace beside it | `max_translation`, `max_scale_pct`, `max_shear_pct`, `max_com_displacement`, `displacement_unit` |
| [Smoothness and point spread](smoothness.md) | the correlation length of the noise field per direction, and the shape of the blur | `fwhm`, `fwhm_pe`, `fwhm_ro`, `fwhm_unit` |
| [Thermal versus instability noise](hilo.md) | a flip-angle pair split into additive and multiplicative noise | nothing — stdout only |

The last column lists `measurements.*` attributes. Each page's table gives their
meanings and the variables, masks, and coordinates that analysis owns.

```{toctree}
:maxdepth: 1
:hidden:

stability
localization
ghosting
saturation
outliers
motion
smoothness
hilo
```
