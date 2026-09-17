"""Shared type vocabulary: array dtypes, Literals, the sidecar, and the ROI size.

The type primitives every layer speaks in — the three numpy array aliases,
the `Literal` sets whose values are passed and published as options, and the
`Sidecar` mapping type. Kept central (not scattered to the operation modules)
precisely because they are the cross-cutting vocabulary: nearly every module
annotates against them, and a closed option set defined once is a set that
can't drift. The one constant here is here for the same reason: `FBIRN_ROI_SIZE`
is spoken by the layer that resolves an ROI and by the artifact that records
the one a run asked for, and the artifact may not import the prep layer to
learn it.

`readout_axis` is the one function, and it is here rather than in an operation
module because it is the sole *operation on* a closed set defined here: the
other in-plane axis is only meaningful for a `PeAxis`, and the three layers that
ask for it (ghost, smoothness, artifact) already speak this vocabulary and would
otherwise each spell `1 - pe_axis` and lose the type.

The frozen dataclass *value objects* used to live here too; they now sit with
the operation that produces them (`ls` the package): `QAImages` in
`prep.images`, `PhantomGeometry`/`ROI` in `prep.geometry`, `ScanMeta` in
`load.metadata`, each metric's `*Result` in its `metrics.*` module, and the
aggregate `QAMetrics`/`QAResult` in `pipeline`.
"""

from collections.abc import Mapping
from typing import Literal, get_args

import numpy as np
from numpy.typing import NDArray

# Array aliases. numpy's generic `NDArray` needs a dtype parameter under strict
# typing; naming the three element kinds the pipeline actually uses keeps the
# annotations honest (signal is float64 end to end -- nibabel `get_fdata`
# returns float64 -- masks are bool, index/size arrays are int) and lets dtype
# flow through arithmetic instead of decaying to Any.
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
IntArray = NDArray[np.intp]

# A sidecar value, as `json.load` hands it over: the sidecar is written by an
# external tool, so nothing here assumes a field has the type it usually has.
Sidecar = Mapping[str, object]

# Closed sets of option strings, modeled as Literal so a bad value is a type
# error at the call site (see style/architecture.md). The runtime tuple each CLI
# and validator uses is derived from the Literal, so the set is defined once.
DetrendMethod = Literal["poly", "spline"]
DETREND_METHODS: tuple[DetrendMethod, ...] = get_args(DetrendMethod)

# ROI localization mode. "image": middle slice + image-center ROI (Glover).
# "phantom": largest-cross-section slice + detected phantom-center ROI.
RoiCenter = Literal["image", "phantom"]
ROI_CENTER_MODES: tuple[RoiCenter, ...] = get_args(RoiCenter)

# Unit a reported length carries: millimetres when the header gave a voxel size,
# voxels when it did not. Published on `Measurements.fwhm_unit` and
# `PsfCurves.unit`, so it is a closed set a reader can switch on.
LengthUnit = Literal["mm", "vox"]
LENGTH_UNITS: tuple[LengthUnit, ...] = get_args(LengthUnit)

# Phase-encode direction as *displayed*: the two DICOM in-plane words, or "?"
# when no axis resolved. "?" is a real answer, not a missing one -- see
# `analysis.artifact.Measurements`.
PeLabel = Literal["row", "col", "?"]
PE_LABELS: tuple[PeLabel, ...] = get_args(PeLabel)

# The phase-encode axis, as a *resolved, in-plane* NIfTI voxel-array index. The
# single-slice pipeline measures the Nyquist ghost by rolling the phantom half
# the FOV along one in-plane axis, so 0 and 1 are the only axes any of it is
# defined on -- which makes this a closed set like the option strings above, and
# it is modeled the same way rather than as a bare `int` each layer re-checks
# against `(0, 1)` on its own.
#
# It is deliberately narrower than what the *loader* can read: a BIDS sidecar
# may name the through-plane axis (`k`), so `QAScan.pe_axis` stays a plain
# `int | None` and `load.pe_axis.in_plane` is the one place that narrows one to
# the other. Everything from `preprocess` inward speaks this type.
PeAxis = Literal[0, 1]
PE_AXES: tuple[PeAxis, ...] = get_args(PeAxis)


def readout_axis(pe_axis: PeAxis) -> PeAxis:
    """The readout axis: the in-plane axis that is not the phase-encode one.

    `1 - pe_axis` says this in fewer characters but evaluates to a plain `int`,
    which then has to be re-narrowed at each use. Naming it keeps the pair
    closed, and gives the readout baseline one definition: the ghost's RO mask
    pair, `SmoothnessResult.ro_axis`, and the artifact's RO point-spread curve
    are all this same fact.
    """
    return 1 if pe_axis == 0 else 0


# How much of the DICOM identity dcm2niix keeps in the BIDS sidecar it writes
# (`convert.dcm2niix`). "pii" strips the patient and keeps the dates, which is
# what a QA import wants: `convert.naming` builds the file name from the series'
# acquisition date and time, and "all" throws that date away. Named here rather
# than passed as dcm2niix's own `-ba o/y/n` so the choice reads as what it means.
Anonymize = Literal["pii", "all", "none"]
ANONYMIZE_MODES: tuple[Anonymize, ...] = get_args(Anonymize)

# Which name an imported series is filed under: the one `convert.naming` builds
# from the sidecar (date, time, zero-padded series, description), or whatever
# dcm2niix's own `-f` template produced. See `convert.naming` for why the two
# are not the same thing.
NameStyle = Literal["qa", "dcm2niix"]
NAME_STYLES: tuple[NameStyle, ...] = get_args(NameStyle)


# Fixed summary-ROI side (voxels). Glover/fBIRN uses 21; user-configurable.
FBIRN_ROI_SIZE = 21
