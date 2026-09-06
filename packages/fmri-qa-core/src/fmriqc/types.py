"""Shared type vocabulary: array dtypes, closed-set Literals, and the ROI size.

The type primitives every layer speaks in — the three numpy array aliases and
the `Literal` sets whose values are passed and published as strings. Kept
central (not scattered to the operation modules) precisely because they are the
cross-cutting vocabulary: nearly every module annotates against them, and a
closed option set defined once is a set that can't drift. The one constant here
is here for the same reason: `FBIRN_ROI_SIZE` is spoken by the layer that
resolves an ROI and by the artifact that records the one a run asked for, and
the artifact may not import the prep layer to learn it.

The frozen dataclass *value objects* used to live here too; they now sit with
the operation that produces them (`ls` the package): `QAImages` in
`prep.images`, `PhantomGeometry`/`ROI` in `prep.geometry`, `ScanMeta` in
`load.metadata`, each metric's `*Result` in its `metrics.*` module, and the
aggregate `QAMetrics`/`QAResult` in `pipeline`.
"""

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

# Fixed summary-ROI side (voxels). Glover/fBIRN uses 21; user-configurable.
FBIRN_ROI_SIZE = 21
