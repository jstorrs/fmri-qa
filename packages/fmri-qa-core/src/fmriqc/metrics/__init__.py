"""The physics tests: one module per QA metric family.

Each module owns a family of measurements over the preprocessed `QAImages` and
the `*Result` value object it returns: `fbirn` (SNR/SFNR/RDC/drift/fluctuation),
`artifacts` (temporal/spectral spikes and outliers), `ghost` (Nyquist ghost
ratios + PE-axis estimation), `saturation`, `motion`, `center_of_mass`, and
`smoothness`. The public surface is re-exported from the top-level `fmriqc`
package.
"""
