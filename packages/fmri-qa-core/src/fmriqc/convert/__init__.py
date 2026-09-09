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
"""
