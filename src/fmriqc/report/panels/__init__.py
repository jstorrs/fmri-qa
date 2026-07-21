"""Format-agnostic report figures: matplotlib panels built from a `QAResult`.

`images` builds the labelled phantom-image panels (signal, SFNR, noise, N/2
ghost overlay); `timeseries` builds the stability plots (Weisskoff/RDC, signal,
residual, spectrum, outliers, motion, COM, PSF). Both return matplotlib
`Figure`/`Axes` objects with no output-format dependency, so any format driver
(see `report.formats`) can embed them.
"""
