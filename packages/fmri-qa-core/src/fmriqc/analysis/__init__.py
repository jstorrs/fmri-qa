"""The analysis artifact: the calculation half's published, serializable output.

`artifact` defines the value objects, `build` projects a computed `QAResult`
into one (`analyze` runs the whole thing from a scan), and `serialize` moves an
artifact to and from a single `.npz`. Everything a report, a plot, or a trend
database needs sits in here; nothing in this subpackage reaches back into the
metric, prep, or load layers at read time.
"""

from ..pipeline import AnalysisSettings
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
from .build import analyze, build_artifact, core_version
from .serialize import load_artifact, save_artifact

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "AnalysisSettings",
    "ArtifactImages",
    "Curves",
    "GhostRegions",
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
