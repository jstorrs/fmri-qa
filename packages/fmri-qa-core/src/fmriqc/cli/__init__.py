"""Command-line entry points for the calculation half.

Three commands, one module each: `qa` (`fmri-qa`) analyzes one or more series
and reports the metrics; `hilo` (`fmri-qa-hilo`) runs the high/low flip-angle
noise separation; `dicom` (`fmri-qa-import`) converts a DICOM directory into the
NIfTI the other two read. The pieces the first two report through sit beside
them — `table` and `record` are the two output forms of a QA run,
`destinations` decides where `--artifact` writes, and `arguments` holds what
all three parse and warn with, plus the `--version` they share. Rendering an
artifact into a report is the separate `fmri-qa-report` distribution's job, so
nothing here imports matplotlib.
"""

from .dicom import import_main
from .hilo import hilo_main
from .qa import main

__all__ = ["hilo_main", "import_main", "main"]
