"""Local stub for the `dcm2niix` wrapper package — the one attribute we use.

The package is a thin wrapper around a bundled dcm2niix binary and ships no type
information, so `convert.dcm2niix` could not import it under strict typing. It
is also an *optional* dependency (`fmri-qa-core[dicom]`), which is the reason
this is a stub rather than a mypy override: a stub types the import whether or
not the package is installed, so the type checkers agree with the `try: import
dcm2niix / except ImportError` that decides at run time whether the bundled
binary exists.

Only `bin` is stubbed. The wrapper's `main` runs the binary through
`subprocess.run` with no typing and no control over the arguments, which is
exactly what `convert.dcm2niix.run` does for itself.
"""

from pathlib import Path

bin: str
bin_path: Path
