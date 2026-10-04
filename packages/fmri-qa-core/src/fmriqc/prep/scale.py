"""The in-plane voxel size, and the unit every length measured against it carries.

Three metrics report a length: `motion` a translation, `center_of_mass` a
centroid displacement, `smoothness` a FWHM. Each measures in voxels and each
reports millimetres *when the header said how big a voxel is*, which is a
question with three parts -- is the size known, what is it along this axis, and
what unit does that make the answer -- that every one of them used to answer for
itself. `VoxelSize` is that one answer.

The unit is the part worth centralizing. `Measurements.displacement_unit` exists
because a build once published these peaks in voxels while labelling them
millimetres (see `analysis.serialize.migrate._v5_to_v6`, and the schema bump it
came with): the rule was written down in several places and one of them was
wrong. Here it is a property of the thing that decides it, so a caller cannot
hold the length and reach the wrong unit.

`LengthUnit` itself stays in `types` -- it is a published option set an artifact
reader switches on, the same relationship `RoiCenter` has to `geometry`: the
closed set is vocabulary, the code that acts on it is an operation.
"""

from dataclasses import dataclass
from typing import Self

import numpy as np

from ..types import FloatArray, LengthUnit, PeAxis


@dataclass(frozen=True, slots=True)
class VoxelSize:
    """In-plane millimetres per voxel, or None when the header did not say.

    Constructing one coerces the pair to plain floats: the header hands these
    over as numpy scalars, and a result object that stores them raw publishes a
    numpy type where a `float` was promised -- which survives every in-process
    check and surfaces only when the artifact is serialized. Coercing here is
    what makes the stored value true of its annotation, so nothing downstream
    re-normalizes.

    Positivity is *not* checked here. `load.metadata._scan_meta` already refuses
    a non-positive or non-finite voxel size against the file it came from, which
    is where a reader can act on it; repeating the test here would only be able
    to name a tuple.

    The default is the unknown size, so a metric estimated without a header
    reports voxels rather than having to be told to.
    """

    mm: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        """Coerce `mm` to a pair of floats."""
        if self.mm is not None:
            object.__setattr__(self, "mm", (float(self.mm[0]), float(self.mm[1])))

    @classmethod
    def in_plane(cls, voxel_mm: tuple[float, float, float]) -> Self:
        """Build the in-plane size from a header's (row, col, slice spacing) triple.

        The one place the row/col pair is taken off the triple `ScanMeta.voxel_mm`
        carries: a caller that sliced it for itself could as easily take the
        slice spacing, and both would type-check as a pair of floats.
        """
        return cls((voxel_mm[0], voxel_mm[1]))

    @property
    def unit(self) -> LengthUnit:
        """The unit a length measured against this voxel size is reported in.

        The single definition of "mm when the voxel size is known, else vox" --
        what `Measurements.fwhm_unit` and `displacement_unit` publish, and what
        `PsfCurves.unit` labels its curves with.
        """
        return "vox" if self.mm is None else "mm"

    def per_axis(self, axis: PeAxis) -> float:
        """Millimetres per voxel along `axis`, or 1.0 when the size is unknown.

        The 1.0 is not a guess at the voxel size: it is the scale factor that
        leaves a length in voxels, which `unit` then reports it as.
        """
        return 1.0 if self.mm is None else self.mm[axis]

    def magnitude(self, deviations: FloatArray) -> FloatArray:
        """(n, 2) per-axis displacements -> (n,) magnitudes, in `unit`.

        Scales each axis by its own millimetres-per-voxel before combining, so
        an anisotropic in-plane voxel gives a true length rather than a
        hypotenuse of two differently-sized voxel counts. NaN rows stay NaN,
        which is how a failed motion fit keeps its frame undefined.
        """
        scaled = deviations if self.mm is None else deviations * np.asarray(self.mm)
        return np.hypot(scaled[:, 0], scaled[:, 1])


# The "the header did not say" voxel size, named so the three result objects
# that default to it say *what* they default to. Safe to share: `VoxelSize` is
# frozen and slotted, so this single instance cannot be mutated by any holder --
# which is also why a bare `VoxelSize()` default would have been correct, if
# indistinguishable at a glance from the mutable default RUF009 exists to catch.
UNKNOWN_VOXEL_SIZE = VoxelSize()
