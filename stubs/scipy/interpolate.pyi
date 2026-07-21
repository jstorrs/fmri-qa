"""Local partial stub for scipy.interpolate — only least-squares B-splines.

`make_lsq_spline` returns a `BSpline`; the pipeline immediately evaluates it on
the sample grid, so only its callable form is modelled here.
"""

import numpy as np
import numpy.typing as npt

class BSpline:
    def __call__(self, x: npt.ArrayLike) -> npt.NDArray[np.float64]: ...

def make_lsq_spline(
    x: npt.ArrayLike, y: npt.ArrayLike, t: npt.ArrayLike, k: int = ...
) -> BSpline: ...
