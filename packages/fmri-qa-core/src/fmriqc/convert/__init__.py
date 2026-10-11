"""DICOM -> NIfTI import: getting data in, in the form the metrics need.

`fmri-qa` converts a QA series in a specific way (see the README's
*Saturation* section) because one check reads the scanner's integers directly.
`dcm2niix` runs the converter with flags that keep the result checkable,
`naming` gives each series a readable, sortable file name, and `session` is the
whole import: convert into a staging directory, name the results, move them into
place.

This sits beside `load` in the stack, not under it. It produces the files `load`
reads. Nothing here imports a metric, and nothing above imports this, since an
analysis never converts.

**Why this converts rather than reads.** `fmri-qa` takes NIfTI, and DICOM
support means running dcm2niix, not parsing DICOM. That is a deliberate scope
boundary, not a gap. Reading DICOM directly would mean owning an unbounded
amount of vendor handling: Siemens mosaics and CSA headers, GE private tags and
compressed protocol blocks, Philips scaling with two rescale conventions,
enhanced multi-frame against classic, and grouping frames into volumes across
echoes, coils and dynamics. dcm2niix does that for every vendor and keeps up as
scanners change.

Phase-encode direction is an example. No DICOM tag carries the BIDS
axis-and-polarity answer that `load.pe_axis` reads first
(`PhaseEncodingDirection`), so dcm2niix derives it from vendor private data. The
synthetic study in `tests/fixtures/dicom` has no CSA header, so dcm2niix writes
only the weaker `PhaseEncodingAxis` (axis, no polarity). The loader reads that
field too, ahead of the raw DICOM row/col tag. It already relies on dcm2niix's
vendor conclusions, and reading DICOM here would mean reimplementing them.
"""
