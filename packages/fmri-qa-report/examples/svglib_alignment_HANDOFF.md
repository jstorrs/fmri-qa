# Hand-off: svglib embedded-image misalignment

**Status (2026-07-21):** maintainer (owner `deeplook`) confirmed the casts have
no good reason and requested a small PR — filed as #492, now open and awaiting
review/merge. CI so far: `pre-commit.ci` and the greeting workflow pass; the
pytest matrix (`test.yml`) has **not run yet** — as a first-time contributor it
needs a maintainer to approve the workflow run. No review or comments yet.
**Upstream issue:** https://github.com/deeplook/svglib/issues/490
**Upstream PR:** https://github.com/deeplook/svglib/pull/492 (removes the four
`int()` casts + adds a regression test; verified locally, `tests/test_basic.py`
→ 89 passed, 1 skipped)

## The problem

svglib's `Svg2RlgShapeConverter.convertImage` places an embedded raster
`<image>` from **integer-truncated** coordinates while flipping the enclosing
group by the **un-truncated** value:

```python
# svglib main: src/svglib/svglib.py, convertImage (~line 2374)
image = Image(int(x), int(y + height), int(width), int(height), image)
group = Group(image)
group.translate(0, (y + height) * 2)   # un-truncated
group.scale(1, -1)
```

So a raster embedded from a matplotlib SVG lands up to ~1 pt off from vector
overlays drawn at the same coordinates. Because `width`/`height` are truncated
too, the error is a **scale + shift, not a constant offset** (it grows toward
the far edge), so it can't be cancelled by shifting the overlay.

In our reports this showed up as the phantom mask contour / ROI box drifting
off the underlying image panel.

## What's in this repo right now

- **Local workaround:** `src/fmriqc/report.py` → `_patch_svglib_image_alignment()`
  monkey-patches `convertImage` to reinstate the method **verbatim minus the
  `int()` casts**. It runs at import time. Only the PDF path uses it.
- **Reproduction / regression check:** `examples/svglib_alignment_repro.py`
  — builds an SVG with an `<image>` and a `<rect>` at identical fractional
  coords, converts with `svg2rlg`, and shows the raster drifts off the vector
  under stock svglib and aligns under our patch. Run: `uv run python
  examples/svglib_alignment_repro.py`.

### Known risk with the current workaround

Our patch copies the *whole* `convertImage` body as it existed in svglib 2.0.2.
On `main`, that method has since gained an **intrinsic-size fallback** (derives
missing `width`/`height` from the image when the SVG omits them). If we ever
bump svglib past 2.0.2, our verbatim override keeps fixing the alignment but
**silently drops that fallback**. Pinned to svglib 2.0.2 in `uv.lock`; revisit
on any upgrade.

## Options considered (so we don't re-derive them)

1. **Narrower, upgrade-safe wrapper patch** — call the original `convertImage`,
   then overwrite the returned `Image`'s four attrs with un-truncated values and
   rebuild the flip, only when the SVG gives explicit width/height (matplotlib
   always does). Keeps upstream's sizing logic; ~10 lines. Preferred local fix
   if we keep patching.
2. **Correct-by-construction plots** — make matplotlib emit integer `<image>`
   geometry so `int()` is a no-op and the patch can be deleted. Verified recipe:
   (a) `savefig(dpi=…)` a multiple of 72 (so 1 pt = 1 px, no pixel-snap
   fractions), (b) each image axes pinned to an integer-point grid, (c) square
   image in a square box so `aspect='equal'` doesn't reshrink. Works, but it's
   an *implicit invariant* across all panels/layouts — any restyle (colorbar,
   title, non-square matrix, dpi change) silently reintroduces the drift. Only
   robust if paired with a test asserting integer `<image>` attrs.
3. **Upstream fix** — drop the four `int()` casts in svglib; both repro deltas
   go to 0.000. This is issue #490. The real cure; removes the need for any
   local patch once released.

## Next steps — after PR #492 merges + releases

Maintainer confirmed it's a bug (option 3, the real cure). PR #492 is filed.

- **When #492 is released:** bump svglib in `pyproject.toml`/`uv.lock` to the
  release that contains it, then **delete** `_patch_svglib_image_alignment` +
  its call in `report.py`. Confirm with the repro that deltas stay 0.000 on the
  new stock svglib (no patch).
- **Until then:** stay pinned to svglib 2.0.2 with the local monkeypatch. Note
  the patch is the verbatim-2.0.2-body override, which silently drops the
  intrinsic-size fallback that `main` has since gained (see "Known risk" above)
  — but we don't need to switch to the narrower wrapper (option 1) since the
  upstream fix is on the way; just don't bump svglib until #492 ships.
- **Either way:** keep `examples/svglib_alignment_repro.py` as the regression
  guard, and re-sync the patch against the new `convertImage` body if svglib is
  bumped before #492 is released.

## Reference facts

- Truncation has been in svglib since embedded-image support was added
  (#93, 2017); no rationale found in history. Re-touched by #175 (2019),
  int() unchanged.
- Versions at time of filing: svglib 2.0.2, reportlab 5.0.0, Pillow 12.3.0,
  Python 3.13.
- Measured drift for `x=10.7,y=20.7,w=50.7,h=50.7`: near-edge x −0.525 pt,
  far-edge x −1.050 pt (patch → 0.000 / 0.000).
