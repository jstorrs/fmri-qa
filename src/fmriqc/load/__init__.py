"""Loading infrastructure: the NIfTI + BIDS-sidecar I/O boundary.

`scan.QAScan.from_nifti` reads a NIfTI and its sidecar into the value objects
the pure pipeline consumes; `metadata` parses the sidecar into `ScanMeta`; and
`pe_axis` resolves the phase-encode axis from the sidecar and header. The public
surface is re-exported from the top-level `fmriqc` package.
"""
