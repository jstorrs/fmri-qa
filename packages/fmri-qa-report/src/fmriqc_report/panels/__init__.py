"""Format-agnostic report figures: matplotlib panels from a `QAArtifact`.

`images` builds the labeled phantom-image panels (signal, SFNR, noise, N/2
ghost overlay); `timeseries` builds the stability plots (Weisskoff/RDC, signal,
residual, spectrum, outliers, motion, COM, PSF). Every image, mask, outline and
trace they draw comes ready-made from the artifact, so a panel only chooses
colors, labels and limits. Both return matplotlib `Figure`/`Axes` objects with
no output-format dependency, so any format driver (see `formats`) can embed them.
"""
