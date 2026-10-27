"""DICOM -> NIfTI conversion rules: how a series is converted and named.

`fmri-qa` converts a QA series in a specific way (see the README's
*Saturation* section) because one check reads the scanner's integers directly.
This package holds the rules, as pure code with no binary to run: `dcm2niix`
gives the flags that keep the result checkable, and `naming` gives each series a
readable, sortable file name. `fmriqa_io.convert` runs the converter and files
the results; a converter elsewhere (a browser's) can follow the same rules.

This sits beside `load` in the stack, not under it. It describes the files
`load` reads. Nothing here imports a metric, and nothing above imports this,
since an analysis never converts.
"""
