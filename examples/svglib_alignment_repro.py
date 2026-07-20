"""Reproduce the svglib int()-truncation misalignment of embedded images.

An SVG <image> and a <rect> are placed at the *same* fractional coordinates.
svglib renders the rect vector at full precision but truncates the raster's
geometry to whole points, so the two drift apart. We convert with svg2rlg,
walk the resulting ReportLab drawing, and compare the transformed bounds of
the Image against the Rect.
"""

import base64
import io

from PIL import Image as PILImage
# mmult/transformPoint are exported at runtime but missing from reportlab's stubs.
from reportlab.graphics.shapes import Group, Image, Rect, mmult, transformPoint  # noqa: E501  # pyright: ignore[reportAttributeAccessIssue]
from svglib import svglib as _svglib
from svglib.svglib import svg2rlg

# Fractional placement — the fractional parts are what get truncated away.
X, Y, W, H = 10.7, 20.7, 50.7, 50.7


def make_png_data_uri():
    """A solid 8x8 PNG as a data: URI (content is irrelevant, only geometry)."""
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), (0, 0, 0)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_svg():
    href = make_png_data_uri()
    return f"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="100" height="100">
  <image x="{X}" y="{Y}" width="{W}" height="{H}" xlink:href="{href}"/>
  <rect  x="{X}" y="{Y}" width="{W}" height="{H}" fill="none" stroke="red"/>
</svg>
"""


def transformed_bounds(node, ctm):
    """(minx, miny, maxx, maxy) of an Image/Rect after the cumulative transform."""
    x0, y0 = node.x, node.y
    x1, y1 = node.x + node.width, node.y + node.height
    corners = [transformPoint(ctm, (x, y)) for x, y in
               ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return min(xs), min(ys), max(xs), max(ys)


def find(node, ctm, out):
    t = getattr(node, "transform", None)
    if t is not None:
        ctm = mmult(ctm, t)
    if isinstance(node, Image):
        out["image"] = transformed_bounds(node, ctm)
    elif isinstance(node, Rect):
        out["rect"] = transformed_bounds(node, ctm)
    for child in getattr(node, "contents", []):
        find(child, ctm, out)


def measure():
    drawing = svg2rlg(io.BytesIO(build_svg().encode()))
    out = {}
    find(drawing, (1, 0, 0, 1, 0, 0), out)
    img, rect = out["image"], out["rect"]
    dx = img[0] - rect[0]
    dy = img[1] - rect[1]
    return img, rect, dx, dy


def patched_convert_image(self, node):
    """report.py's fix: identical to svglib's convertImage minus the int() casts.

    (Valid here because width/height are given explicitly, so svglib's
    intrinsic-size fallback branch is never taken.)
    """
    x, y, width, height = self.convert_length_attrs(
        node, "x", "y", "width", "height")
    image = node._resolved_target
    image = Image(x, y + height, width, height, image)
    group = Group(image)
    group.translate(0, (y + height) * 2)
    group.scale(1, -1)
    return group


def report(label):
    img, rect, dx, dy = measure()
    print(f"--- {label} ---")
    print(f"  rect  bounds: ({rect[0]:.3f}, {rect[1]:.3f})")
    print(f"  image bounds: ({img[0]:.3f}, {img[1]:.3f})")
    print(f"  misalignment: dx={dx:+.3f} pt   dy={dy:+.3f} pt")
    print()
    return dx, dy


print(f"placement: x={X} y={Y} w={W} h={H} (fractional)\n")
sdx, sdy = report("stock svglib")

_orig = _svglib.Svg2RlgShapeConverter.convertImage
_svglib.Svg2RlgShapeConverter.convertImage = patched_convert_image
try:
    pdx, pdy = report("patched (report.py)")
finally:
    _svglib.Svg2RlgShapeConverter.convertImage = _orig

ok = abs(sdy) > 0.1 and abs(pdy) < 1e-6 and abs(pdx) < 1e-6
print("REPRODUCED: stock misaligns, patch aligns" if ok else "did NOT reproduce")
