"""Tuning constants shared across the QA pipeline.

Each value carries the provenance (FBIRN/AFNI/bxh/cran) that fixes it; see the
individual comments. Grouped here so a single file answers "what knob is this
and why is it set there?" without opening the operation modules.
"""

from typing import Literal, get_args

import numpy as np

# Closed sets of option strings, modeled as Literal so a bad value is a type
# error at the call site (see style/architecture.md). The runtime tuple each CLI
# and validator uses is derived from the Literal, so the set is defined once.
DetrendMethod = Literal["poly", "spline"]
DETREND_METHODS: tuple[DetrendMethod, ...] = get_args(DetrendMethod)

# ROI localization mode. "image": middle slice + image-center ROI (Glover).
# "phantom": largest-cross-section slice + detected phantom-center ROI.
RoiCenter = Literal["image", "phantom"]
ROI_CENTER_MODES: tuple[RoiCenter, ...] = get_args(RoiCenter)

# Detrend cutoff period (s). Drift slower than this is removed before noise is
# measured. `poly` and `spline` historically used 200 vs 256; kept distinct
# because only `poly` feeds the settled pipeline.
POLY_CUTOFF_S = 200.0
SPLINE_CUTOFF_S = 256.0

# Plausible ADC saturation rails. A clipped magnitude image piles up at a
# hardware 2**n - 1 ceiling; only these n are realistic for MR (12-bit -> 4095).
SATURATION_BITS = range(8, 17)  # 255 .. 65535

# Per-voxel tail probability for the outlier test (3dToutcount default): a clean
# voxel flags a sample this often by chance, so ~qthr is the expected fraction.
OUTLIER_QTHR = 0.001

# R `mad()` default scale constant: 1.4826 makes the MAD a consistent estimator
# of the SD for normal data. cran-fmriqa's spike scores divide by this MAD.
MAD_SCALE = 1.4826

# Per-volume registration budget (in-plane phantom motion). Phantom drift is
# sub-voxel, so a few Gauss-Newton steps converge; TOL is on the largest
# per-step parameter update (voxels for translation, fraction for strain).
MOTION_MAX_ITER = 12
MOTION_TOL = 1e-4

# Gaussian FWHM per standard deviation: sqrt(8 ln 2) (AFNI 3dFWHMx uses 2.35482).
SIGMA_TO_FWHM = float(np.sqrt(8.0 * np.log(2.0)))
# Lags (voxels) over which the directional noise autocorrelation / PSF is sampled.
SMOOTHNESS_MAX_LAG = 10

# Voxel layers peeled off the phantom to form the hi/lo core mask (AFNI
# 3dAutomask -erode 5) -- excludes edge / partial-volume / ghost-contaminated voxels.
HILO_ERODE = 5

# Fraction of the brightest ghost-region voxels averaged for the localized-ghost
# statistic (Greve / bxh fmriqa_ghostiness "top-10%"): catches a concentrated
# bright ghost that the region-mean ghost ratio dilutes.
GHOST_TOP_FRACTION = 0.10

# Fixed summary-ROI side (voxels). Glover/fBIRN uses 21; user-configurable.
FBIRN_ROI_SIZE = 21

# DICOM in-plane phase-encode axis -> row/col: NIfTI i (axis 0) is the DICOM
# row direction, j (axis 1) the column direction (verified against dcm2niix
# InPlanePhaseEncodingDirectionDICOM on a Siemens acquisition).
_PE_ROWCOL = {0: "row", 1: "col"}
