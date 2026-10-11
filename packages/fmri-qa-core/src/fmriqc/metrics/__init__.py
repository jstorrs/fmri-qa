"""The physics tests: one module per QA metric family.

Each module measures one family over the preprocessed `QAImages` and returns a
`*Result` value object: `fbirn` (SNR, SFNR, RDC, drift, fluctuation),
`artifacts` (temporal and spectral spikes, outliers), `ghost` (Nyquist ghost
ratios and PE-axis estimation), `saturation`, `motion`, `center_of_mass` and
`smoothness`. The top-level `fmriqc` package re-exports the public names.
"""
