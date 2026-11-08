"""Where `--analysis-file` writes, and the collisions that make a run refuse to start.

An analysis file is written by moving a finished file over its destination, so a
destination that names an input, or that two scans share, destroys work. Both
are decided here, from the paths alone, before any analysis runs.
"""

# The `q.*` parameter annotations below name analysis file types behind `fmriqa`'s
# lazy re-exports. Evaluated at `def` time, they would load `fmriqa.analysis`
# just to import this module. Deferring them avoids that. That `--help` stays
# off scipy and scikit-image is checked by `tests/test_startup.py`.
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

import fmriqa as q
import fmriqa_io
from fmriqa_io.path_arguments import same_file
from fmriqa_io.paths import nifti_stem, sidecar_path

# Suffix for a saved analysis file, so a batch's files are recognizable at a glance.
ANALYSIS_SUFFIX = ".qa.nc"


def analysis_destinations(base: str, paths: Sequence[str]) -> list[tuple[str, Path]]:
    """Return `(input, destination)` pairs for every requested scan, in order.

    A batch can't share one file, so `BASE` is a directory and each scan gets
    `<scan stem>.qa.nc` inside it. A single-scan run writes `BASE` itself,
    unless `BASE` is an existing directory, which is filed into the same way a
    batch would be (`<scan stem>.qa.nc` inside it). A file and a directory can't
    share a name, so preferring the directory is never ambiguous.

    Without that rule, `mkdir results` then `--analysis-file results` would analyze
    the scan and fail moving the finished file onto a directory, with
    `[WinError 5] Access is denied` on Windows or `IsADirectoryError` elsewhere,
    neither of which names the mistake.

    An input named twice keeps both pairs. Collapsing them would silently
    forgive `fmri-qa a.nii.gz a.nii.gz --analysis-file out/`, which
    `analysis_collisions` below must refuse.
    """
    batch = len(paths) > 1
    if batch or Path(base).is_dir():
        return [
            (path, Path(base) / f"{nifti_stem(path)}{ANALYSIS_SUFFIX}")
            for path in paths
        ]
    return [(path, Path(base)) for path in paths]


def overwritten_inputs(
    destinations: Sequence[tuple[str, Path]],
) -> list[tuple[Path, str]]:
    """Return `(destination, input)` pairs where an analysis file overwrites an input.

    An analysis file is written by moving a finished file over its destination, and
    the scans (and their sidecars) are read before any is written. So an output
    that names an input succeeds and leaves an archive where the data was. Every
    destination is checked against every input file, not only its own scan's,
    because in a batch one scan's analysis file can land on another's file.
    """
    dests = [dest for _, dest in destinations]
    inputs = [str(f) for path, _ in destinations for f in (path, sidecar_path(path))]
    return [(dest, src) for dest in dests for src in inputs if same_file(dest, src)]


def analysis_collisions(
    destinations: Sequence[tuple[str, Path]],
) -> dict[Path, list[str]]:
    """Return destinations that more than one input scan would be written to.

    A batch names each analysis file by the scan's stem, so inputs in different
    directories with the same file name (`sub-01/qa.nii.gz`, `sub-02/qa.nii.gz`)
    collide. Writing them in turn would leave one file holding the last analysis
    and silently drop the rest. `main` checks this up front and refuses instead
    of analyzing work it can't keep.
    """
    by_dest: dict[Path, list[str]] = {}
    for path, dest in destinations:
        by_dest.setdefault(dest, []).append(path)
    return {dest: srcs for dest, srcs in by_dest.items() if len(srcs) > 1}


def report_destination_problems(destinations: Sequence[tuple[str, Path]]) -> bool:
    """Print every `--analysis-file` destination problem; return True to stop the run.

    Both checks use the paths alone and run before any scan is read, because
    either problem costs unrecoverable work. An analysis file written over an input
    destroys the data, and two scans sharing a destination leave one file
    holding the last analysis and silently drop the rest.
    """
    stop = False
    for destination, source in overwritten_inputs(destinations):
        print(
            f"ERROR: --analysis-file {destination} would overwrite the input {source}",
            file=sys.stderr,
        )
        stop = True
    if stop:  # a destination that eats an input is fatal on its own
        return True
    collisions = analysis_collisions(destinations)
    for destination, sources in sorted(collisions.items()):
        print(
            f"ERROR: {' and '.join(sources)} would both be saved as {destination}",
            file=sys.stderr,
        )
    if collisions:
        print(
            "ERROR: --analysis-file names each file after the scan, so scans "
            "sharing a name overwrite each other; rename them or analyze "
            "them in separate runs.",
            file=sys.stderr,
        )
    return bool(collisions)


def write_analysis(analysis: q.QAAnalysis, out: Path, info: TextIO) -> str | None:
    """Write one analysis file; return None if written, else the error as reported."""
    try:
        fmriqa_io.save_analysis(analysis, out)
    except (OSError, q.InvalidAnalysisFileError) as exc:
        # A bad destination is a user error, and an analysis file the reader would
        # refuse is a defect worth a line, not a traceback. Either way the
        # batch goes on.
        problem = f"could not write analysis file {out}: {exc}"
        print(f"ERROR: {problem}", file=sys.stderr)
        return problem
    print(f"# wrote {out}", file=info)
    return None
