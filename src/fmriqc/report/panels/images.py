"""Phantom-image panels: signal, SFNR, noise, and the N/2 ghost overlay.

Each builder returns a labelled matplotlib `Figure` (a square-ish `imshow` panel
with the phantom hull and ROI drawn on top); `_panel_figs` assembles the row a
report shows. Format-agnostic — a driver embeds the returned figures.
"""

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle
from scipy.spatial import ConvexHull

import fmriqc as q
from fmriqc.types import BoolArray, FloatArray

_GHOST_SRC_RGB = (0.20, 0.85, 1.0)  # PE signal source region (cyan)
_GHOST_RGB = (1.0, 0.30, 0.30)  # PE ghost region (red)
_RO_SRC_RGB = (0.45, 1.0, 0.35)  # RO signal source region (green)
_RO_GHOST_RGB = (1.0, 0.72, 0.15)  # RO ghost region (amber)
_INVALID_RGB = (1.0, 0.15, 0.90)  # zeroed image edge, excluded from stats (magenta)


def _data_per_point(ax: Axes) -> float:
    """Length of one typographic point (1/72 in) in axes data units.

    `imshow` uses equal aspect, so x and y share a scale; `apply_aspect` finalizes
    that scaling first so the measured transform is the one that will render. The
    figure dpi cancels, making the result resolution-independent -- call only
    after the axes position (subplots_adjust) is final.
    """
    ax.apply_aspect()
    (x0, x1) = ax.transData.transform([(0, 0), (1, 0)])[:, 0]
    return float((ax.figure.dpi / 72.0) / abs(x1 - x0))


def _draw_roi(ax: Axes, roi: q.ROI, *, lw: float = 1.3) -> None:
    """Outline the ROI just outside its pixels so the stroke doesn't cover them.

    The ROI's outer boundary in imshow coordinates runs from `start - 0.5` to
    `stop - 0.5`. The stroke is centered on the path, so drawing on that boundary
    spills half the line width inward and hides the edge ROI pixels. Pad outward
    by exactly half the line width -- converted from points to data units via the
    axes scale -- so the stroke's inner edge lands back on the boundary and every
    ROI pixel stays visible.
    """
    (r, c) = roi.index
    pad = 0.5 * lw * _data_per_point(ax)
    ax.add_patch(
        Rectangle(
            (c.start - 0.5 - pad, r.start - 0.5 - pad),
            (c.stop - c.start) + 2 * pad,
            (r.stop - r.start) + 2 * pad,
            edgecolor="red",
            facecolor="none",
            lw=lw,
        )
    )


def _draw_hull(
    ax: Axes, mask: BoolArray, *, color: str = "tab:cyan", lw: float = 1.0
) -> None:
    """Outline the convex hull of a boolean mask as a closed polygon.

    The hull smooths the ragged phantom-mask boundary into a clean convex
    outline. `imshow` maps column -> x and row -> y, so the mask's (row, col)
    pixel coordinates plot as (col, row).
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 3:
        return
    pts = np.column_stack([xs, ys]).astype(float)
    verts = ConvexHull(pts).vertices
    loop = np.append(verts, verts[0])  # close the polygon
    ax.plot(pts[loop, 0], pts[loop, 1], color=color, lw=lw)


def _panel_fig(
    img: FloatArray,
    title: str,
    *,
    mask: BoolArray | None = None,
    roi: q.ROI | None = None,
    log: bool = False,
    aspect: float = 1.15,
) -> Figure:
    """A single labelled image panel as a square-ish figure."""
    fig = Figure(figsize=(2.0, 2.0 * aspect))
    ax = fig.add_subplot(111)
    data = np.log(np.clip(img, 1e-9, None)) if log else img
    finite = data[np.isfinite(data)]
    vmin, vmax = np.percentile(finite, [2, 98]) if finite.size else (0, 1)
    ax.imshow(data, cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])
    # Fix the axes box before drawing the ROI: its pad is derived from the axes
    # scale (see `_draw_roi`/`_data_per_point`), which subplots_adjust finalizes.
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.90)
    if mask is not None:
        _draw_hull(ax, mask, lw=1.0)
    if roi is not None:
        _draw_roi(ax, roi)
    ax.set_title(title, fontsize=9)
    return fig


def _overlay(
    ax: Axes, mask: BoolArray, rgb: tuple[float, float, float], alpha: float = 0.45
) -> None:
    """Tint the True pixels of `mask` with a translucent color over the image."""
    rgba = np.zeros((*mask.shape, 4))
    rgba[mask] = (*rgb, alpha)
    ax.imshow(rgba, interpolation="nearest")


def _ghost_panel_fig(
    mean_image: FloatArray,
    phantom_mask: BoolArray,
    pe_axis: int | None,
    *,
    aspect: float = 1.15,
) -> Figure:
    """Mean image with the region-matched ghost/signal masks for both axes.

    Draws the exact masks the ghost metrics average: for each in-plane axis, the
    ghost patch (where the phantom rolled half the FOV lands clear of the phantom)
    and its source on the phantom (that patch rolled back). The PE pair (cyan/red)
    feeds ghost%; the readout pair (green/amber) feeds RO% -- the background-
    relative baseline whose difference from ghost% is ACRg -- so both reported
    percentages can be checked against where they are sampled. Any zeroed image
    edge dropped from the statistics (magenta) is marked when present. The ghost
    pairs are blank if the PE axis is unknown.
    """
    fig = Figure(figsize=(2.0, 2.0 * aspect))
    ax = fig.add_subplot(111)
    ax.imshow(
        mean_image,
        cmap="gray",
        vmin=0,
        vmax=np.percentile(mean_image, 99),
        interpolation="nearest",
    )
    valid_mask = q.edge_valid_mask(mean_image)
    handles = []
    if pe_axis in (0, 1):
        ro_axis = 1 - pe_axis
        ro_signal, ro_ghost = q.ghost_masks(
            phantom_mask, ro_axis, q.GHOST_RADIUS, valid_mask
        )
        signal_mask, ghost_mask = q.ghost_masks(
            phantom_mask, pe_axis, q.GHOST_RADIUS, valid_mask
        )
        _overlay(ax, ro_signal, _RO_SRC_RGB)
        _overlay(ax, ro_ghost, _RO_GHOST_RGB)
        _overlay(ax, signal_mask, _GHOST_SRC_RGB)
        _overlay(ax, ghost_mask, _GHOST_RGB)
        handles += [
            Patch(color=_GHOST_SRC_RGB, label="PE signal"),
            Patch(color=_GHOST_RGB, label="PE ghost"),
            Patch(color=_RO_SRC_RGB, label="RO signal"),
            Patch(color=_RO_GHOST_RGB, label="RO ghost"),
        ]
    invalid = ~valid_mask
    if invalid.any():
        _overlay(ax, invalid, _INVALID_RGB, alpha=0.9)
        handles.append(Patch(color=_INVALID_RGB, label="invalid edge"))
    if handles:
        ax.legend(
            handles=handles,
            fontsize=5,
            loc="lower right",
            framealpha=0.6,
            handlelength=1.0,
            borderpad=0.3,
            labelspacing=0.2,
        )
    ax.set_title("N/2 ghost", fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.90)
    return fig


def _panel_figs(result: q.QAResult) -> list[Figure]:
    """The summary image panels, in row order (last is the N/2 ghost overlay)."""
    images, geom, roi, m = result.images, result.geom, result.roi, result.metrics
    sfnr_img = np.where(
        geom.phantom_mask, images.mean_image / (images.fluctuation_noise + 1e-9), 0.0
    )
    return [
        _panel_fig(images.mean_image, "signal", mask=geom.phantom_mask, roi=roi),
        _panel_fig(sfnr_img, "SFNR", roi=roi),
        _panel_fig(
            images.fluctuation_noise,
            "fluct noise (log)",
            mask=geom.phantom_mask,
            roi=roi,
            log=True,
        ),
        _panel_fig(
            images.static_noise, "static noise", mask=geom.phantom_mask, roi=roi
        ),
        _ghost_panel_fig(images.mean_image, geom.phantom_mask, m.pe_axis),
    ]
