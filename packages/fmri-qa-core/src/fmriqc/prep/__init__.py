"""Preprocessing infrastructure: raw-array ops, detrending, geometry, images.

The transforms that turn a loaded `QAScan` into the `QAImages` every metric
reads from, plus the phantom/ROI geometry value objects. Pure and low-level:
nothing here depends on the `metrics` or `report` layers, so the operations can
be shared without import cycles. The public surface is re-exported from the
top-level `fmriqc` package.
"""
