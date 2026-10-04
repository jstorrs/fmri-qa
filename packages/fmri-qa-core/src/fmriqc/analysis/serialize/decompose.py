"""Split a `QAArtifact` into the JSON document and the named arrays.

The write half of the archive layout: every array becomes a member keyed by its
dotted path (`curves.weisskoff.cv`, `images.ghost.pe_ghost`), and everything
that is not an array goes into one JSON document. `compose` is the mirror image
and the two must be read together — a field added here needs a reader there.

The mapping is written out explicitly, section by section, rather than derived
by reflection over the dataclasses: the layout is a published contract pinned by
`ARTIFACT_SCHEMA_VERSION`, so adding a field should be a deliberate edit, not a
silent change of file format.
"""

from dataclasses import asdict
from typing import Any

from ...types import BoolArray, FloatArray
from ..artifact import ArtifactImages, Curves, QAArtifact

# An archive member: a float image/curve or a boolean mask, addressed by its
# dotted path. The two dtypes share one alias because the archive is keyed by
# name, not by kind; each reader re-narrows via `_floats`/`_bools`.
type Member = FloatArray | BoolArray


def decompose(artifact: QAArtifact) -> tuple[dict[str, Any], dict[str, Member]]:
    """Split an artifact into its JSON document and its named arrays."""
    curves, curve_arrays = _curves_section(artifact.curves)
    images, image_arrays = _images_section(artifact.images)
    document = {
        "schema_version": artifact.schema_version,
        "settings": asdict(artifact.settings),
        "provenance": asdict(artifact.provenance),
        "measurements": asdict(artifact.measurements),
        "curves": curves,
        "images": images,
    }
    return document, {**curve_arrays, **image_arrays}


def _curves_section(curves: Curves) -> tuple[dict[str, Any], dict[str, Member]]:
    """Split the curve scalars from every trace keyed by its dotted path."""
    psf = curves.psf
    document = {
        "outlier_qthr": curves.outlier_qthr,
        "psf": {
            "labels": list(psf.labels),
            "fwhm": list(psf.fwhm),
            "unit": psf.unit,
            "xmax": psf.xmax,
        },
    }
    arrays: dict[str, Member] = {
        "curves.time": curves.time,
        "curves.roi_signal": curves.roi_signal,
        "curves.roi_trend": curves.roi_trend,
        "curves.roi_residual": curves.roi_residual,
        "curves.outlier_fraction": curves.outlier_fraction,
        "curves.spectrum_hz": curves.spectrum_hz,
        "curves.spectrum_magnitude": curves.spectrum_magnitude,
        "curves.translation": curves.translation,
        "curves.scale_pct": curves.scale_pct,
        "curves.shear_pct": curves.shear_pct,
        "curves.com_deviation": curves.com_deviation,
        "curves.weisskoff.roi_sizes": curves.weisskoff.roi_sizes,
        "curves.weisskoff.cv": curves.weisskoff.cv,
        "curves.weisskoff.cv_ideal": curves.weisskoff.cv_ideal,
        "curves.weisskoff.rdc": curves.weisskoff.rdc,
        "curves.psf.displacement": psf.displacement,
        "curves.psf.empirical": psf.empirical,
        "curves.psf.model_x": psf.model_x,
        "curves.psf.model": psf.model,
    }
    return document, arrays


def _images_section(
    images: ArtifactImages,
) -> tuple[dict[str, Any], dict[str, Member]]:
    """Split the image scalars from every image/mask keyed by its dotted path."""
    document = {"roi": asdict(images.roi), "has_ghost": images.ghost is not None}
    arrays: dict[str, Member] = {
        "images.signal": images.signal,
        "images.sfnr": images.sfnr,
        "images.fluctuation_noise": images.fluctuation_noise,
        "images.static_noise": images.static_noise,
        "images.phantom_mask": images.phantom_mask,
        "images.invalid_mask": images.invalid_mask,
        "images.phantom_hull": images.phantom_hull,
    }
    if images.ghost is not None:
        arrays |= {
            "images.ghost.pe_signal": images.ghost.pe_signal,
            "images.ghost.pe_ghost": images.ghost.pe_ghost,
            "images.ghost.ro_signal": images.ghost.ro_signal,
            "images.ghost.ro_ghost": images.ghost.ro_ghost,
        }
    return document, arrays
