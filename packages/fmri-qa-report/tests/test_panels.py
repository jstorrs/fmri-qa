"""The format-agnostic panels, and the package's import-time manners."""

import os
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest


def test_importing_the_package_leaves_the_matplotlib_backend_alone() -> None:
    """A library must not change a process-global its importer chose.

    `fmriqa_report` used to call `matplotlib.use("Agg")` at import time,
    overriding the backend the importing process had selected (e.g. a
    notebook's inline backend). This runs in a fresh interpreter with a
    non-default, display-free backend set via `MPLBACKEND`, so the probe is
    unaffected by what other tests did to `matplotlib`'s global state.
    """
    code = (
        "import matplotlib\n"
        "before = matplotlib.get_backend()\n"
        "import fmriqa_report\n"
        "after = matplotlib.get_backend()\n"
        "print(before)\n"
        "print(after)\n"
    )
    env = dict(os.environ, MPLBACKEND="svg")
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    before, after = result.stdout.strip().splitlines()
    assert before.lower() == after.lower() == "svg"


@pytest.mark.parametrize(
    ("values", "maximum", "upper", "unresolved"),
    [
        pytest.param([np.nan, np.nan, np.nan], None, 4.5, 3, id="nan-only"),
        pytest.param([np.inf, -np.inf, np.inf], None, 4.5, 3, id="inf-only"),
        pytest.param([2.0, np.nan, np.inf], 2.0, 3.0, 2, id="mixed"),
        pytest.param([0.0, 0.0, 0.0], 0.0, 4.5, 0, id="zero"),
        pytest.param([1.0, 2.0, 3.0], 3.0, 4.5, 0, id="ordinary"),
    ],
)
def test_rdc_panel_uses_finite_limits(values, maximum, upper, unresolved) -> None:
    from matplotlib.figure import Figure

    from fmriqa.analysis import WeisskoffCurve
    from fmriqa_report.panels.timeseries import plot_rdc

    widths = np.arange(1.0, 4.0)
    rdc = np.array(values)
    wk = WeisskoffCurve(roi_sizes=widths, cv=rdc, cv_ideal=widths, rdc=rdc)
    ax = Figure().add_subplot(111)
    plot_rdc(ax, wk)

    assert ax.get_ylim() == (0.0, upper)
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), rdc)
    np.testing.assert_array_equal(ax.lines[1].get_ydata(), widths)
    if maximum is None:
        assert len(ax.lines) == 2
    else:
        assert len(ax.lines) == 3
        np.testing.assert_array_equal(ax.lines[2].get_ydata(), [maximum, maximum])
    assert [t.get_text() for t in ax.texts] == (
        [f"{unresolved}/3 points unresolved"] if unresolved else []
    )


@pytest.mark.parametrize("failed", [0, 1, 38])
def test_motion_panel_marks_unresolved_frames(analysis, failed) -> None:
    from matplotlib.figure import Figure

    from fmriqa_report.panels.timeseries import plot_motion

    translation = np.zeros_like(analysis.curves.translation)
    translation[:failed] = np.nan
    curves = replace(
        analysis.curves,
        translation=translation,
        scale_pct=np.zeros_like(analysis.curves.scale_pct),
        shear_pct=np.zeros_like(analysis.curves.shear_pct),
    )
    ax = Figure().add_subplot(111)
    plot_motion(ax, curves)
    assert [t.get_text() for t in ax.texts] == (
        [f"{failed}/38 frames unresolved"] if failed else []
    )


def test_outlier_panel_shows_measured_percentages_without_a_chance_line(
    analysis,
) -> None:
    from matplotlib.figure import Figure

    from fmriqa_report.panels.timeseries import plot_outliers

    fractions = np.linspace(0.0, 0.02, analysis.curves.time.size)
    curves = replace(analysis.curves, outlier_fraction=fractions)
    ax = Figure().add_subplot(111)
    plot_outliers(ax, curves)

    assert len(ax.lines) == 1
    np.testing.assert_array_equal(ax.lines[0].get_xdata(), curves.time)
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), 100.0 * fractions)
    assert ax.get_legend() is None
    assert ax.get_ylabel() == "outliers (%)"
