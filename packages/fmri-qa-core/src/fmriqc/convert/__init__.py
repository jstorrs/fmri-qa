"""DICOM -> NIfTI import: getting data in, in the form the metrics need.

`fmri-qa` is opinionated about how a QA series is converted (see the README's
*Saturation* section) because one of its checks reads the scanner's integers
directly. This subpackage is that opinion, executable: `dcm2niix` runs the
converter with the flags that decide whether the result can still be checked,
`naming` gives each series a file name a physicist can read and sort, and
`session` is the whole import — convert into a staging directory, name what came
out, and move it into place.

It sits beside `load` in the stack rather than under it: both are the tier that
gets data in, and this one produces exactly the files `load` reads. Nothing here
imports a metric, and nothing above imports this — an analysis never converts.

**Why this converts rather than reads.** `fmri-qa` takes NIfTI, and DICOM
support means running dcm2niix, not parsing DICOM. That is a deliberate scope
boundary, not a gap: reading DICOM directly would mean owning the vendor
complexity of turning it into a series, and that work is unbounded — Siemens
mosaics and CSA headers, GE private tags and compressed protocol blocks, Philips
scaling with two rescale conventions, enhanced multi-frame against classic, and
the grouping of frames into volumes across echoes, coils and dynamics. dcm2niix
does that, for every vendor, and keeps doing it as scanners change.

The phase-encode direction is the clearest case, and this package's own test
fixture shows it. `load.pe_axis` reads `PhaseEncodingDirection` first — and that
is not a DICOM tag. There is no tag that carries the BIDS axis-and-polarity
answer; dcm2niix derives it from vendor private data, which is why it writes the
weaker `PhaseEncodingAxis` (axis, no polarity) for the synthetic study in
`tests/fixtures/dicom`, which has no CSA header to derive polarity from. So the
loader already consumes dcm2niix's vendor conclusions. Reading DICOM here would
not remove a dependency; it would mean reimplementing it.
"""
