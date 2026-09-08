"""Loading infrastructure: the NIfTI + BIDS-sidecar I/O boundary.

`scan.QAScan.from_nifti` reads a NIfTI and its optional sidecar into the value
objects the pure pipeline consumes; `metadata` parses the sidecar into
`ScanMeta`; `paths` holds the NIfTI/sidecar naming rules; `pe_axis` resolves
the phase-encode axis and `repetition_time` the TR, both from the sidecar and
header. The public surface is re-exported from
the top-level `fmriqc` package.
"""
