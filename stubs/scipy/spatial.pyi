"""Local partial stub for scipy.spatial — `ConvexHull.vertices` and `QhullError`."""

import numpy as np
import numpy.typing as npt

class QhullError(Exception): ...

class ConvexHull:
    vertices: npt.NDArray[np.intp]
    def __init__(self, points: npt.ArrayLike) -> None: ...
