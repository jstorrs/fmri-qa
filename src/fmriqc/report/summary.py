"""Format-agnostic scan-level text: the acquisition/provenance metadata lines.

The strings a report shows about a scan, derived from a `QAResult` with no
dependency on any output format: the `_*_line` helpers return the acquisition /
provenance / device strings, `_appendix_rows` the packet provenance table, and
`package_version` the running version. The per-metric vocabulary (tile labels
and value formatting) lives in `content`. A format driver (see `formats`)
decides how to lay these out.
"""

from collections.abc import Iterable
from importlib.metadata import PackageNotFoundError, version

import fmriqc as q


def package_version() -> str:
    """The installed `fmri-qa` version, or "unknown" from a bare source tree."""
    try:
        return version("fmri-qa")
    except PackageNotFoundError:
        return "unknown"


def _appendix_rows(
    items: Iterable[tuple[str, q.QAResult]],
) -> list[tuple[str, str]]:
    """(scan title, provenance text) rows for the packet appendix.

    Joins the device and scanner/coil/software/time lines; scans without a
    sidecar contribute a placeholder so every scan is accounted for.
    """
    rows = []
    for title, result in items:
        parts = [_device_line(result.meta), _provenance_line(result.meta)]
        detail = "   ·   ".join(p for p in parts if p) or "no sidecar metadata"
        rows.append((title, detail))
    return rows


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
