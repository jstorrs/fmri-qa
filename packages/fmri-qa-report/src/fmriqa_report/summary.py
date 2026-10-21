"""Format-agnostic scan-level text: the acquisition/provenance metadata lines.

The strings a report shows about a scan, derived from a `QAArtifact` with no
dependency on any output format. The `*_line` helpers return the acquisition,
provenance and device strings, and `package_version` the renderer version.
Tile labels and value formatting live in `content`; a format driver (see
`formats`) lays everything out.
"""

import math
from importlib.metadata import PackageNotFoundError, version

from fmriqa.analysis import Provenance, QAArtifact

# The separator between fields on a metadata line.
_SEP = "   ·   "


def package_version() -> str:
    """Read the installed `fmri-qa-report` version; "unknown" from a source tree."""
    try:
        return version("fmri-qa-report")
    except PackageNotFoundError:
        return "unknown"


def acquisition_line(artifact: QAArtifact) -> str:
    """Build the sequence/geometry metadata string, omitting absent fields."""
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
    if prov.slice_index is not None:
        # The stored 0-based index, so it matches the artifact and JSON record.
        total = f"/{prov.n_slices}" if prov.n_slices is not None else ""
        parts.append(f"slice index {prov.slice_index}{total}")
    parts.append(f"{prov.n_frames} frames")
    parts.append(f"PE {m.pe_label}")
    detrend = f"detrend {settings.detrend}"
    if settings.detrend_order is not None:
        unit = "deg" if settings.detrend == "poly" else "knots"
        detrend += f" ({unit} {settings.detrend_order})"
    parts.append(detrend)
    return _SEP.join(parts)


def acquisition_notes(artifact: QAArtifact) -> str:
    """Clipping and localization notes, separate from acquisition metadata."""
    return _SEP.join(
        note
        for note in (_clipping_note(artifact), _localization_note(artifact))
        if note
    )


def _localization_note(artifact: QAArtifact) -> str:
    """Build the phantom/ROI localization warning for the notes; empty if fine.

    Both failures make every mask-based number meaningless while leaving it
    looking like an ordinary measurement. So they are called out in capitals
    next to the metrics they invalidate, instead of being left for a reader to
    infer from a NaN. The verdict comes from the artifact (`phantom_mask_ok`); the
    bounds belong to the segmentation in the calculation half, which isn't
    importable from here.

    A verdict of `None` means the artifact was migrated from a schema that
    predates the check. It is reported quietly, since nothing is known to be
    wrong, but the page must not imply the checks ran and passed.
    """
    m = artifact.measurements
    notes = []
    if m.phantom_mask_ok is False:
        # Show both numbers so the reader sees which failed: a collapse shows in
        # the share, a segmentation of noise in the contrast. Artifacts that
        # predate the contrast don't have it.
        why = f"{100 * m.phantom_fraction:.0f}% of frame"
        if not math.isnan(m.phantom_contrast):
            why += f", {m.phantom_contrast:.3g}× contrast"
        notes.append(f"BAD PHANTOM MASK ({why})")
    if m.roi_inside_phantom is False:
        notes.append("ROI NOT INSIDE PHANTOM")
    if not notes and None in (m.phantom_mask_ok, m.roi_inside_phantom):
        notes.append("localization not recorded")
    return _SEP.join(notes)


def _clipping_note(artifact: QAArtifact) -> str:
    """Build the ADC-saturation warning for the notes block; empty if none.

    Clipping inside the analyzed data biases every metric and is called out in
    capitals. Clipping confined to the dropped warm-up volumes is expected on
    some scanners and is reported quietly.

    A `clipped_any` of None means the series wasn't integer samples, so the rail
    test couldn't run. It gets its own line, since silence would read as "no
    clipping found".
    """
    m = artifact.measurements
    if m.clipped_any is None:
        return "clip not determinable (non-integer storage)"
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


def provenance_line(prov: Provenance) -> str:
    """Build the scanner/coil/software/time string; empty without a sidecar."""
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


def device_line(prov: Provenance) -> str:
    """Build the manufacturer, model and field-strength title text; empty if none."""
    dev = " ".join(x for x in (prov.manufacturer, prov.model) if x)
    if prov.field_strength is not None:
        dev = f"{dev}{_SEP}{prov.field_strength:g}T".strip(" ·")
    return dev
