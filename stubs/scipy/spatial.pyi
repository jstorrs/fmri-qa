"""Local partial stub for scipy.spatial — only `ConvexHull.vertices`."""

import numpy as np
import numpy.typing as npt

class ConvexHull:
    vertices: npt.NDArray[np.intp]
    def __init__(self, points: npt.ArrayLike) -> None: ...
