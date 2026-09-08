"""The one svglib defect the PDF driver has to work around.

svglib truncates the geometry of an image embedded in an SVG to whole points,
which slides the phantom raster off the vector overlays drawn around it. The fix
is a replacement converter installed into svglib itself, so it is kept here —
apart from the page composition — with the probe that proves the installed
release still needs it. `packages/fmri-qa-report/examples/` holds the standalone
reproduction this was derived from.
"""

from functools import cache
from importlib.metadata import version
from types import SimpleNamespace
from typing import Any

from reportlab.graphics.shapes import Group, Image
from svglib import svglib as _svglib

# svglib's `convertImage(self, node)`, taken unbound so it can be probed.
_ImageConverter = Any


def _truncates_image_geometry(convert_image: _ImageConverter) -> bool:
    """Probe a converter, returning whether it truncates fractional geometry."""

    class ProbeConverter:
        @staticmethod
        def convert_length_attrs(*args: object) -> tuple[float, float, float, float]:
            return (0.25, 1.25, 2.5, 3.5)

    node = SimpleNamespace(_resolved_target="alignment-probe")
    try:
        group = convert_image(ProbeConverter(), node)
        image = group.contents[0]
        geometry = (image.x, image.y, image.width, image.height)
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"svglib {version('svglib')} has an unsupported image converter API"
        ) from exc

    if geometry == (0.25, 4.75, 2.5, 3.5):
        return False
    if geometry == (0, 4, 2, 3):
        return True
    raise RuntimeError(
        f"svglib {version('svglib')} returned unexpected image geometry {geometry!r}"
    )


@cache
def ensure_installed() -> None:
    """Fix svglib truncating embedded-image geometry to whole points.

    svglib's `convertImage` builds the ReportLab `Image` from `int(x)`,
    `int(y + height)`, `int(width)`, `int(height)` while flipping the enclosing
    group by the *un*-truncated `(y + height) * 2`. For an `imshow` panel the
    raster then lands up to a point off from the mask contour and ROI box (which
    keep full precision), so the phantom outline visibly drifts off the image.
    The converter is behavior-probed before patching. A future svglib that keeps
    fractional geometry needs no patch; an unknown private API fails clearly
    instead of silently misaligning the raster and vector layers. The dependency
    range is capped in `pyproject.toml` until a newer release is verified.

    Called on the first render rather than at import: this mutates a third-party
    class for the whole process, so it should happen when a caller actually asks
    for a PDF, and an unrecognized svglib must fail that render rather than turn
    `import fmriqc_report` into an error. `cache` memoizes only a *successful*
    call, so an svglib whose API this build does not recognize keeps raising on
    every render rather than failing once and then silently rendering
    misaligned pages.
    """
    original = _svglib.Svg2RlgShapeConverter.convertImage
    if not _truncates_image_geometry(original):
        return

    def convertImage(self: Any, node: Any) -> Any:
        x, y, width, height = self.convert_length_attrs(
            node, "x", "y", "width", "height"
        )
        image = node._resolved_target
        image = Image(x, y + height, width, height, image)
        group = Group(image)
        group.translate(0, (y + height) * 2)
        group.scale(1, -1)
        return group

    _svglib.Svg2RlgShapeConverter.convertImage = convertImage

    if _truncates_image_geometry(convertImage):
        raise RuntimeError("failed to install the svglib image-alignment fix")
