"""Command-line entry points: the shell over core and io.

Four commands, one module each: `qa` (`fmri-qa`) analyzes one or more series
and reports the metrics; `hilo` (`fmri-qa-hilo`) runs the high/low flip-angle
noise separation; `dicom` (`fmri-qa-import`) converts a DICOM directory into the
NIfTI the other two read; `report` (`fmri-qa-report`) renders a saved artifact
into a one-file HTML report. Helpers: `table` and `record` are the two output
forms of a QA run, `destinations` decides where `--artifact` writes, and
`arguments` holds what the first three commands parse and warn with, plus
`--version`. The renderer is the `fmri-qa-report` library; `report` imports it
only to write a page, so nothing here imports matplotlib until then.
`python -m fmriqa_cli` runs `fmri-qa`.
"""

from .dicom import import_main
from .hilo import hilo_main
from .qa import main
from .report import report_main

__all__ = ["hilo_main", "import_main", "main", "report_main"]
