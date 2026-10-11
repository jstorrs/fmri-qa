"""The script PyInstaller freezes into the single-file `fmri-qa-run`.

PyInstaller freezes a script, not an entry point. `fmriqc_launcher/__main__.py`
can't serve, since run as a top-level file it has no parent package for its
relative import. This is the same two lines with an absolute import. See
`fmri-qa-run.spec`.
"""

from fmriqc_launcher.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
