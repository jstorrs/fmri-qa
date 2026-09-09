"""The eroded phantom-core mask each hi/lo scan is reduced over.

`HILO_ERODE` is the number of voxel layers peeled off the phantom, tuning the
mask `phantom_core_mask` builds.
"""

import numpy as np
from scipy import ndimage

from ..prep.imaging import segment_phantom
from ..types import BoolArray, FloatArray

# Voxel layers peeled off the phantom to form the hi/lo core mask (AFNI
# 3dAutomask -erode 5) -- excludes edge / partial-volume / ghost-contaminated voxels.
HILO_ERODE = 5


def phantom_core_mask(volume: FloatArray, erode: int = HILO_ERODE) -> BoolArray:
    """Eroded phantom-core mask of a 3-D image (AFNI `3dAutomask -q -erode` analogue).

    Segments the phantom from the temporal-mean `volume` with the same watershed
    used in-plane (`segment_phantom`, applied to the whole volume — its Sobel /
    quantile / watershed steps are all dimension-agnostic), keeps the largest
    connected component with its interior holes filled, then peels `erode` voxel
    layers so the core excludes edge and partial-volume voxels — matching the
    note's `3dAutomask -q -erode 5`.
    """
    mask = ndimage.binary_fill_holes(segment_phantom(volume))
    labels, n = ndimage.label(mask)
    if n > 1:  # keep the largest connected component only
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        mask = labels == int(np.argmax(sizes))
    if erode > 0:
        mask = ndimage.binary_erosion(mask, iterations=erode)
    return np.asarray(mask, dtype=bool)
