"""Where `--artifact` writes, and the collisions that make a run refuse to start.

An artifact is written by moving a finished file over its destination, so a
destination that names an input, or that two scans share, destroys work. Both
are decided here, up front, from the paths alone — before any analysis runs.
"""

# The `q.*` parameter annotations below name artifact types that live behind
# `fmriqc`'s lazy re-exports; evaluated at `def` time they would resolve the
# whole calculation stack just to import this module. Deferring them keeps a
# `--help` or a usage error from paying for numpy, scipy and nibabel.
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

import fmriqc as q
from fmriqc.load.paths import nifti_stem, same_file, sidecar_path

# Suffix for a saved artifact, so a batch's files are recognizable at a glance.
ARTIFACT_SUFFIX = ".qa.npz"


def artifact_path(base: str, path: str, batch: bool) -> Path:
    """Where one scan's artifact is written under `--artifact BASE`.

    A single-scan run writes exactly `BASE`. A batch cannot share one file, so
    `BASE` is a directory and each scan gets `<scan stem>.qa.npz` inside it.
    """
    if not batch:
        return Path(base)
    return Path(base) / f"{nifti_stem(path)}{ARTIFACT_SUFFIX}"


def overwritten_inputs(base: str, paths: Sequence[str]) -> list[tuple[Path, str]]:
    """`(destination, input)` pairs where an artifact would replace an input.

    An artifact is written by moving a finished file over its destination, and
    the scans (and their sidecars) are read before any is written — so an
    output that names an input succeeds, and leaves an archive where the data
    was. Every destination is checked against every input file, not only its
    own scan's: in a batch, one scan's artifact can land on another's file.
    """
    destinations = [artifact_path(base, path, batch=len(paths) > 1) for path in paths]
    inputs = [str(f) for path in paths for f in (path, sidecar_path(path))]
    return [
        (dest, src) for dest in destinations for src in inputs if same_file(dest, src)
    ]


def artifact_collisions(base: str, paths: Sequence[str]) -> dict[Path, list[str]]:
    """Destinations that more than one input scan would be written to.

    A batch names each artifact by the scan's stem, so inputs from different
    directories with the same file name (`sub-01/qa.nii.gz`, `sub-02/qa.nii.gz`)
    collide. Writing them in turn would leave one file holding the last scan's
    analysis and silently drop the rest, and a later `fmri-qa-report BASE/*.npz`
    would render a packet quietly missing scans. `main` checks this up front and
    refuses rather than analyze work it cannot keep.
    """
    destinations: dict[Path, list[str]] = {}
    for path in paths:
        destinations.setdefault(artifact_path(base, path, batch=True), []).append(path)
    return {dest: srcs for dest, srcs in destinations.items() if len(srcs) > 1}


def report_destination_problems(base: str, paths: Sequence[str]) -> bool:
    """Print every `--artifact` destination problem; True if the run must stop.

    Both checks are made against the paths alone, before a single scan is read,
    because either one costs work that cannot be recovered: an artifact written
    over an input destroys the data, and two scans sharing a destination leave
    one file holding the last analysis and silently drop the rest.
    """
    stop = False
    for destination, source in overwritten_inputs(base, paths):
        print(
            f"ERROR: --artifact {destination} would overwrite the input {source}",
            file=sys.stderr,
        )
        stop = True
    if stop:  # a destination that eats an input is fatal on its own
        return True
    collisions = artifact_collisions(base, paths) if len(paths) > 1 else {}
    for destination, sources in sorted(collisions.items()):
        print(
            f"ERROR: {' and '.join(sources)} would both be saved as {destination}",
            file=sys.stderr,
        )
    if collisions:
        print(
            "ERROR: --artifact names each file after the scan, so scans "
            "sharing a name overwrite each other; rename them or analyze "
            "them in separate runs.",
            file=sys.stderr,
        )
    return bool(collisions)


def write_artifact(
    artifact: q.QAArtifact, base: str, path: str, batch: bool, info: TextIO
) -> str | None:
    """Write one artifact. Returns None if written, else the error as reported."""
    out = artifact_path(base, path, batch)
    try:
        q.save_artifact(artifact, out)
    except (OSError, q.InvalidArtifactError) as exc:
        # A bad destination is a user error, and an artifact the reader would
        # refuse is a defect worth a line, not a traceback; either way the
        # batch goes on.
        problem = f"could not write artifact {out}: {exc}"
        print(f"ERROR: {problem}", file=sys.stderr)
        return problem
    print(f"# wrote {out}", file=info)
    return None
