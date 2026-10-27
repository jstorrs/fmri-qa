"""The in-plane voxel size, and the unit every length measured against it carries.

Three metrics report a length: `motion` a translation, `center_of_mass` a
centroid displacement, `smoothness` a FWHM. Each measures in voxels and reports
millimeters when the header gives the voxel size. `VoxelSize` answers whether
the size is known, what it is along an axis, and which unit results, so the
metrics don't each work that out.

The unit is the part worth centralizing. `Measurements.displacement_unit` exists
because a build once published these peaks in voxels labeled as millimeters (see
`analysis.serialize.migrate._v5_to_v6`). The rule was written in several places
and one was wrong. Now the unit comes from the object that decides it, so a
caller can't pair a length with the wrong unit.

`LengthUnit` stays in `types`, like `RoiCenter`: it is a published option set
that an artifact reader switches on, and the code acting on it lives here.
"""

from dataclasses import dataclass
from typing import Self

import numpy as np

from ..types import FloatArray, LengthUnit, PeAxis

__all__ = [
    "UNKNOWN_VOXEL_SIZE",
    "VoxelSize",
]


@dataclass(frozen=True, slots=True)
class VoxelSize:
    """In-plane millimeters per voxel, or None when the header did not say.

    Constructing one coerces the pair to plain floats. The header hands these
    over as numpy scalars, and a result object storing them raw would publish a
    numpy type where a `float` was promised, which passes every in-process check
    and fails only at serialization.

    Positivity is not checked here. `load.metadata.scan_meta` already refuses a
    non-positive or non-finite voxel size against the file it came from, where
    the error can name the file.

    The default is the unknown size, so a metric estimated without a header
    reports voxels.
    """

    mm: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        """Coerce `mm` to a pair of floats."""
        if self.mm is not None:
            object.__setattr__(self, "mm", (float(self.mm[0]), float(self.mm[1])))

    @classmethod
    def in_plane(cls, voxel_mm: tuple[float, float, float]) -> Self:
        """Build the in-plane size from a header's (row, col, slice spacing) triple.

        The one place the row/col pair is taken off the `ScanMeta.voxel_mm`
        triple. A caller slicing it by hand could as easily take the slice
        spacing, and both would type-check as a pair of floats.
        """
        return cls((voxel_mm[0], voxel_mm[1]))

    @property
    def unit(self) -> LengthUnit:
        """The unit a length measured against this voxel size is reported in.

        The single definition of "mm when the voxel size is known, else vox".
        `Measurements.fwhm_unit` and `displacement_unit` publish it, and
        `PsfCurves.unit` labels its curves with it.
        """
        return "vox" if self.mm is None else "mm"

    def per_axis(self, axis: PeAxis) -> float:
        """Return the millimeters per voxel along `axis`, or 1.0 if unknown.

        The 1.0 is not a guess at the voxel size. It is the scale factor that
        leaves a length in voxels, which `unit` then reports.
        """
        return 1.0 if self.mm is None else self.mm[axis]

    def magnitude(self, deviations: FloatArray) -> FloatArray:
        """Combine (n, 2) per-axis displacements into (n,) magnitudes, in `unit`.

        Scales each axis by its own millimeters-per-voxel before combining, so
        an anisotropic in-plane voxel gives a true length and not a hypotenuse
        of two differently sized voxel counts. NaN rows stay NaN, which is how a
        failed motion fit keeps its frame undefined.
        """
        scaled = deviations if self.mm is None else deviations * np.asarray(self.mm)
        return np.hypot(scaled[:, 0], scaled[:, 1])


# The "header did not say" voxel size, named so the three result objects that
# default to it say what they default to. Safe to share: `VoxelSize` is frozen
# and slotted, so no holder can mutate this instance. A bare `VoxelSize()`
# default would also be correct, but looks like the mutable default RUF009
# exists to catch.
#: The `VoxelSize` for a header that gave no voxel size.
UNKNOWN_VOXEL_SIZE = VoxelSize()
