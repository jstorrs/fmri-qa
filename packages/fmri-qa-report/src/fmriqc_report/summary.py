"""Format-agnostic scan-level text: the acquisition/provenance metadata lines.

The strings a report shows about a scan, derived from a `QAArtifact` with no
dependency on any output format: the `_*_line` helpers return the acquisition /
provenance / device strings, `_appendix_rows` the packet provenance table, and
`package_version` the running renderer version. The per-metric vocabulary (tile
labels and value formatting) lives in `content`. A format driver (see `formats`)
decides how to lay these out.
"""

from collections.abc import Iterable
from importlib.metadata import PackageNotFoundError, version

from fmriqc.analysis import Provenance, QAArtifact

# The separator between fields on a metadata line.
_SEP = "   ·   "


def package_version() -> str:
    """The installed `fmri-qa-report` version, or "unknown" from a source tree."""
    try:
        return version("fmri-qa-report")
    except PackageNotFoundError:
        return "unknown"


def _appendix_rows(
    items: Iterable[tuple[str, QAArtifact]],
) -> list[tuple[str, str]]:
    """(scan title, provenance text) rows for the packet appendix.

    Joins the device and scanner/coil/software/time lines with the version of
    the package that computed the artifact; a scan without a sidecar still
    contributes its computed-by line, so every scan is accounted for.
    """
    rows = []
    for title, artifact in items:
        prov = artifact.provenance
        parts = [_device_line(prov), _provenance_line(prov)]
        if prov.core_version:
            parts.append(f"computed by fmri-qa-core {prov.core_version}")
        detail = _SEP.join(p for p in parts if p) or "no sidecar metadata"
        rows.append((title, detail))
    return rows


def _acquisition_line(artifact: QAArtifact) -> str:
    """The sequence/geometry metadata string. Sidecar-only fields are omitted."""
    prov, m, settings = artifact.provenance, artifact.measurements, artifact.settings
    parts = [f"TR {prov.tr:.3g}s"]
    if prov.te is not None:
        parts.append(f"TE {prov.te * 1000:.0f}ms")
    if prov.flip_angle is not None:
        parts.append(f"flip {prov.flip_angle:g}°")
    if prov.voxel_mm is not None:
        vr, vc, spacing = prov.voxel_mm
        parts.append(f"{vr:.3g}×{vc:.3g}mm")
        thk = prov.slice_thickness if prov.slice_thickness is not None else spacing
        parts.append(f"{thk:g}mm slice")
    if prov.matrix is not None:
        parts.append(f"{prov.matrix[0]}×{prov.matrix[1]} px")
    parts.append(f"{prov.n_frames} frames")
    parts.append(f"PE {m.pe_label}")
    detrend = f"detrend {settings.detrend}"
    if settings.detrend_order is not None:
        unit = "deg" if settings.detrend == "poly" else "knots"
        detrend += f" ({unit} {settings.detrend_order})"
    parts.append(detrend)
    if clip := _clipping_note(artifact):
        parts.append(clip)
    if localization := _localization_note(artifact):
        parts.append(localization)
    return _SEP.join(parts)


def _localization_note(artifact: QAArtifact) -> str:
    """The phantom/ROI localization warning for the acquisition line; empty if fine.

    Both failures make every mask-based number on the page meaningless while
    leaving it looking like an ordinary measurement, so they are called out in
    capitals next to the metrics they invalidate rather than left for a reader to
    infer from a NaN.

    The verdict on the mask is the artifact's (`phantom_mask_ok`), not this
    module's: the bounds belong to the segmentation, which lives in the
    calculation half and is not importable from here.

    A verdict of `None` — an artifact migrated from a schema written before the
    check existed — is reported quietly rather than in capitals: nothing is known
    to be wrong, but the page must not imply the checks were made and passed.
    """
    m = artifact.measurements
    notes = []
    if m.phantom_mask_ok is False:
        notes.append(f"BAD PHANTOM MASK ({100 * m.phantom_fraction:.0f}% of frame)")
    if m.roi_inside_phantom is False:
        notes.append("ROI NOT INSIDE PHANTOM")
    if not notes and None in (m.phantom_mask_ok, m.roi_inside_phantom):
        notes.append("localization not recorded")
    return _SEP.join(notes)


def _clipping_note(artifact: QAArtifact) -> str:
    """The ADC-saturation warning for the acquisition line; empty if none.

    Clipping inside the analyzed data biases every metric and is called out in
    capitals; clipping confined to the dropped warm-up volumes is expected on
    some scanners and is reported quietly, apart from the biasing kind.
    """
    m = artifact.measurements
    if not m.clipped_any or m.clip_ceiling is None:
        return ""
    rail = f"{m.clip_ceiling:.0f}"
    if m.clip_bits is not None:
        rail += f" ({m.clip_bits}-bit)"
    if not m.clipped_kept:
        return f"clip {m.n_clipped_pre} pre-SS only @ {rail}"
    text = f"CLIP {m.n_clipped_kept} in analyzed data"
    if m.n_clipped_pre:
        text += f" (+{m.n_clipped_pre} pre-SS)"
    return f"{text} @ {rail}"


def _provenance_line(prov: Provenance) -> str:
    """The scanner/coil/software/time string; empty without a sidecar."""
    parts = []
    if prov.serial:
        parts.append(f"SN {prov.serial}")
    if prov.coil:
        parts.append(f"coil {prov.coil}")
    if prov.software:
        parts.append(prov.software)
    if prov.datetime:
        parts.append(prov.datetime)
    return _SEP.join(parts)


def _device_line(prov: Provenance) -> str:
    """Manufacturer/model/field-strength for the title row; empty if unknown."""
    dev = " ".join(x for x in (prov.manufacturer, prov.model) if x)
    if prov.field_strength is not None:
        dev = f"{dev}{_SEP}{prov.field_strength:g}T".strip(" ·")
    return dev
