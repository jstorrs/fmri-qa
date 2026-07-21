"""Format-agnostic report content: the metric tiles and the metadata text lines.

The numbers and strings a report header shows, derived from a `QAResult` with no
dependency on any output format — `_metric_tiles` returns (label, value) pairs
and the `_*_line` helpers return the acquisition / provenance / device strings.
A format driver (see `formats`) decides how to lay them out.
"""

import fmriqc as q


def _fwhm_label(s: q.SmoothnessResult) -> str:
    """Combined FWHM tile text: mm when the voxel size is known, else voxels."""
    unit = "mm" if s.voxel_mm is not None else "vox"
    return f"{s.fwhm:.2f}{unit}"


def _metric_tiles(m: q.QAMetrics) -> list[tuple[str, str]]:
    """(label, value) pairs for the header metric tiles, in display order."""
    return [
        ("SNR", f"{m.snr:.1f}"),
        ("SFNR", f"{m.sfnr:.1f}"),
        ("RDC", f"{m.rdc:.2f}"),
        ("ghost", f"{m.ghost_pct:.2f}%"),
        ("ghostT", f"{m.ghost_top_pct:.2f}%"),
        ("RO", f"{m.ro_ghost_pct:.2f}%"),
        ("ACRg", f"{m.acr_ghost_pct:.2f}%"),
        ("drift", f"{m.drift_pct:.3f}%"),
        ("fluct", f"{m.percent_fluctuation:.3f}%"),
        ("outl", f"{100.0 * m.outliers.max_fraction:.2f}%"),
        ("tcOut", f"{m.spikes.tc_outlier:.1f}"),
        ("spec", f"{m.spikes.spec_outlier:.1f}"),
        ("motn", f"{m.motion.max_translation:.2f}"),
        ("com", f"{m.center_of_mass.max_displacement:.2f}"),
        ("fwhm", _fwhm_label(m.smoothness)),
    ]


def _acquisition_line(result: q.QAResult) -> str:
    """The sequence/geometry metadata string. Sidecar-only fields are omitted."""
    images, m, meta = result.images, result.metrics, result.meta
    parts = [f"TR {images.tr:.3g}s"]
    if meta and meta.te is not None:
        parts.append(f"TE {meta.te * 1000:.0f}ms")
    if meta and meta.flip_angle is not None:
        parts.append(f"flip {meta.flip_angle:g}°")
    if meta:
        vr, vc, spacing = meta.voxel_mm
        parts.append(f"{vr:.3g}×{vc:.3g}mm")
        thk = meta.slice_thickness if meta.slice_thickness is not None else spacing
        parts.append(f"{thk:g}mm slice")
        parts.append(f"{meta.matrix[0]}×{meta.matrix[1]} px")
    parts.append(f"{images.center_slice.shape[-1]} frames")
    if meta and meta.pe_dir:
        pe = meta.pe_dir
    elif m.pe_axis is not None:
        pe = q.PE_ROWCOL.get(m.pe_axis, "?")
    else:
        pe = "?"
    parts.append(f"PE {pe}")
    detrend = f"detrend {images.detrend_method}"
    if images.detrend_order is not None:
        unit = "deg" if images.detrend_method == "poly" else "knots"
        detrend += f" ({unit} {images.detrend_order})"
    parts.append(detrend)
    sat = m.saturation
    if sat.clipped_kept:  # clipping in the analyzed data -- biases the metrics
        txt = f"CLIP {sat.n_clipped_kept} in analyzed data"
        if sat.n_clipped_pre:
            txt += f" (+{sat.n_clipped_pre} pre-SS)"
        parts.append(f"{txt} @ {sat.ceiling:.0f} ({sat.bits}-bit)")
    elif sat.clipped:  # confined to dropped warm-up volumes -- doesn't reach stats
        parts.append(
            f"clip {sat.n_clipped_pre} pre-SS only @ {sat.ceiling:.0f} ({sat.bits}-bit)"
        )
    return "   ·   ".join(parts)


def _provenance_line(meta: q.ScanMeta | None) -> str:
    """The scanner/coil/software/time string; empty without a sidecar."""
    if meta is None:
        return ""
    parts = []
    if meta.serial:
        parts.append(f"SN {meta.serial}")
    if meta.coil:
        parts.append(f"coil {meta.coil}")
    if meta.software:
        parts.append(meta.software)
    if meta.datetime:
        parts.append(meta.datetime)
    return "   ·   ".join(parts)


def _device_line(meta: q.ScanMeta | None) -> str:
    """Manufacturer/model/field-strength for the title row; empty if unknown."""
    if meta is None:
        return ""
    dev = " ".join(x for x in (meta.manufacturer, meta.model) if x)
    if meta.field_strength is not None:
        dev = f"{dev}   ·   {meta.field_strength:g}T".strip(" ·")
    return dev
