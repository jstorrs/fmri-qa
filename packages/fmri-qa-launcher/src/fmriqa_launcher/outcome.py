"""What a run reports: one outcome per series, and the run's overall result.

These are plain frozen values with only standard-library dependencies. Modules
that just present a finished run (`results`, `worker`, `panel_state`, `panel`,
`cli`) can import them without the analysis and report stack that
`session.run_session` needs.
"""

from dataclasses import dataclass
from pathlib import Path

__all__ = ["Failed", "Published", "Refused", "RunResult", "SeriesOutcome"]


@dataclass(frozen=True, slots=True)
class Published:
    """One series filed under `output_dir / name`.

    Holds its scan, artifact and report, and its sidecar when dcm2niix wrote
    one.
    """

    name: str
    directory: Path
    scan: Path
    sidecar: Path | None
    artifact: Path
    report: Path
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Refused:
    """A series whose name already exists in `output_dir`.

    Never overwritten (see `run_session`'s docstring). The converter imported
    it into staging, but analysis, render and publish are skipped. That costs
    no analysis or render time, only the import it shared with every other
    series.
    """

    name: str
    existing: Path


@dataclass(frozen=True, slots=True)
class Failed:
    """A series that raised somewhere between import and publish.

    `reason` is `str(exc)`, or the exception's type name if that is empty.
    Anything staged for this series is discarded; nothing partial reaches
    `output_dir`.
    """

    name: str
    reason: str
    warnings: tuple[str, ...] = ()


#: What happened to one series: `Published`, `Refused` or `Failed`.
type SeriesOutcome = Published | Refused | Failed


@dataclass(frozen=True, slots=True)
class RunResult:
    """Every series a run touched, in the order it found them."""

    output_dir: Path
    outcomes: tuple[SeriesOutcome, ...]
    cancelled: bool = False

    @property
    def published(self) -> tuple[Published, ...]:
        """The series that made it all the way to `output_dir`."""
        return tuple(o for o in self.outcomes if isinstance(o, Published))

    @property
    def complete(self) -> bool:
        """Whether every series found was published and nothing was cancelled.

        False for a run that found nothing: "0 of 0, complete" is not a
        success.
        """
        return (
            bool(self.outcomes)
            and not self.cancelled
            and all(isinstance(o, Published) for o in self.outcomes)
        )
