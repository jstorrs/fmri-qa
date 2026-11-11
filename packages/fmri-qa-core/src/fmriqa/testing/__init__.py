"""The synthetic phantom, shared by every package, the docs and the spikes.

This is the deterministic test and doc phantom, shipped so they all measure
against one definition. It is a uniform disk rendered from its exact k-space
after Guerquin-Kern et al. [1]_, with seeded complex k-space noise, so its
magnitude image has a Rayleigh air background (see `NOISE_SIGMA`). An N/2
ghost and a linear signal drift can be added as an acquisition produces them.
`synthetic_series` is the raw array. `phantom_scan` is the `QAScan` that
loading the file `fmriqa_io.testing.write_phantom` writes gives back, built
without touching a file. A parity test in `fmri-qa-io` pins the two together.

The phantom lives in `series.py` and the analytic k-space kernel in `kspace.py`.

Pure: no file IO. Import it as `fmriqa.testing`. It is not part of the
`fmriqa` public surface.

References
----------
.. [1] M. Guerquin-Kern, L. Lejeune, K. P. Pruessmann, M. Unser, "Realistic
   Analytical Phantoms for Parallel Magnetic Resonance Imaging," IEEE Trans.
   Med. Imaging 31(3):626-636, 2012. doi:10.1109/TMI.2011.2174158
"""

from .series import (
    NOISE_SIGMA,
    PE_AXIS,
    PHANTOM_SIGNAL,
    TR_SEC,
    VOXEL_MM,
    phantom_scan,
    synthetic_series,
)

__all__ = [
    "NOISE_SIGMA",
    "PE_AXIS",
    "PHANTOM_SIGNAL",
    "TR_SEC",
    "VOXEL_MM",
    "phantom_scan",
    "synthetic_series",
]
