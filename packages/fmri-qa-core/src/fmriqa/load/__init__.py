"""The scan value objects and the pure rules that read a BIDS sidecar.

`scan.QAScan` is the value object the pure pipeline consumes. The rules that
read a parsed sidecar are public in their modules and not re-exported from
`fmriqa`: `metadata.scan_meta` builds `ScanMeta`, `pe_axis.pe_axis_from_sidecar`
resolves the phase-encode axis, and `repetition_time.resolve_repetition_time`
the TR from the sidecar and the header value handed in. Core reads no files:
decoding a NIfTI and parsing the sidecar JSON is `fmriqa_io`'s
(`scan_from_bytes`, `load_scan`). `QAScan` and `ScanMeta` are re-exported from
the top-level `fmriqa` package.
"""
