"""The analysis artifact: the calculation half's published, serializable output.

`artifact` defines the value objects. `build` projects a computed `QAResult`
into one (`analyze` runs the whole thing from a scan). `validation` checks them
against the published contract. `serialize` reads and writes an artifact as a
single netCDF-4 file. Everything a report, a plot or a trend database needs is
here. Nothing in this subpackage reaches back into the metric, prep, or load
layers at read time.

The two halves are imported differently. The artifact, its validator and its
serializer are cheap, so they load eagerly. So does `InvalidArtifactError`, the
one error `load_artifact` raises. `fmriqc.exceptions` imports nothing, and a
reader that crosses only this seam must be able to catch it by name. `build` is
not eager: projecting a `QAResult` imports the pipeline, and behind it the whole
metric, prep and load stack, including scikit-image, scipy and nibabel.
Re-exporting `analyze` and `build_artifact` eagerly would charge that cost to
every reader of a finished artifact, which is the dependency the
published-artifact seam exists to prevent. So `__getattr__` below (PEP 562)
imports `build` on first access to either name. Reading an artifact never pays
for the machinery that computes one.
"""

from typing import TYPE_CHECKING

from ..exceptions import InvalidArtifactError
from ..settings import AnalysisSettings
from ..version import core_version
from .artifact import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactImages,
    Curves,
    GhostRegions,
    Measurements,
    Provenance,
    PsfCurves,
    QAArtifact,
    RoiBox,
    WeisskoffCurve,
)
from .serialize import load_artifact, save_artifact

if TYPE_CHECKING:
    # Imported directly (not through the lazy `__getattr__` below) so mypy and
    # pyright resolve both names statically. Never executed at runtime.
    from .build import analyze, build_artifact

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "AnalysisSettings",
    "ArtifactImages",
    "Curves",
    "GhostRegions",
    "InvalidArtifactError",
    "Measurements",
    "Provenance",
    "PsfCurves",
    "QAArtifact",
    "RoiBox",
    "WeisskoffCurve",
    "analyze",
    "build_artifact",
    "core_version",
    "load_artifact",
    "save_artifact",
]

# The two names `build` defines, and the only ones resolved on first access.
_LAZY = frozenset({"analyze", "build_artifact"})


def __getattr__(name: str) -> object:
    """Resolve the projection half by importing `build` on first access.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name. Later accesses are plain attribute lookups, same
    as an eager re-export.
    """
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import build

    value = getattr(build, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
