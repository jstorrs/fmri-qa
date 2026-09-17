"""Per-scan reduction to the mean/SD maps `run_hilo` pools over the shared core."""

from ..load.scan import QAScan
from ..prep.detrend import Detrender
from ..prep.imaging import fluctuation_noise, trim_initial
from ..types import BoolArray, DetrendMethod, FloatArray
from .mask import phantom_core_mask


def hilo_stats(
    scan: QAScan, trim_sec: float, detrend: DetrendMethod, erode: int
) -> tuple[FloatArray, FloatArray, BoolArray]:
    """(temporal-mean map, temporal-SD-of-residual map, eroded core mask) for a scan.

    The whole 3-D volume is used (not a single slice): thermal/instability
    separation is a global scanner property. The series is trimmed like the rest
    of the pipeline, the mean map is taken on the trimmed signal, and the SD map
    on the per-voxel detrended residual (poly degree scaled to this scan's own run
    length, as elsewhere). The core mask comes from the mean map.
    """
    data = trim_initial(scan.data, tr=scan.tr, trim_sec=trim_sec)  # (X, Y, Z, T)
    mean_map = data.mean(axis=-1)
    detrender = Detrender.for_series(data, scan.tr, detrend)
    sd_map = fluctuation_noise(detrender(data))
    return mean_map, sd_map, phantom_core_mask(mean_map, erode)
