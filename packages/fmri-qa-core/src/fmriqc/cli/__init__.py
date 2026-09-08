"""Command-line entry points for the calculation half.

Two commands, one module each: `qa` (`fmri-qa`) analyzes one or more series and
reports the metrics; `hilo` (`fmri-qa-hilo`) runs the high/low flip-angle noise
separation. The pieces they report through sit beside them — `table` and
`record` are the two output forms of a QA run, `destinations` decides where
`--artifact` writes, and `arguments` holds what both commands parse and warn
with. Rendering an artifact into a PDF is the separate `fmri-qa-report`
distribution's job, so nothing here imports matplotlib or ReportLab.
"""

from .hilo import hilo_main
from .qa import main

__all__ = ["hilo_main", "main"]
