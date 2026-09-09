"""`ArrayValue`: every array-holding value object copies in and freezes.

Pins the policy `_arrays.py` documents -- every frozen dataclass in this
package that holds an `ndarray` field inherits `ArrayValue`, not only the ones
published across the `analysis` seam -- against every current subclass, so a
class that quietly stops inheriting (or a new array field added to one that
does) fails a test rather than surfacing as a caller mutating a value out from
under a metric three calls later. `test_pipeline.py`'s
`test_preprocess_discards_the_full_volume` already covers `QAImages` from the
angle that matters there (detachment from the full 4-D series); this file
covers the rest of the family, plus the base contract in isolation.
"""

from dataclasses import dataclass, fields

import numpy as np
import pytest

from fmriqc._arrays import ArrayValue, readonly
from fmriqc.metrics.artifacts import OutlierResult
from fmriqc.metrics.center_of_mass import CenterOfMassResult
from fmriqc.metrics.fbirn import WeisskoffResult
from fmriqc.metrics.ghost import GhostResult
from fmriqc.metrics.motion import MotionResult
from fmriqc.metrics.smoothness import SmoothnessResult
from fmriqc.prep.geometry import ROI, PhantomGeometry


def test_readonly_marks_the_given_array_and_returns_it() -> None:
    arr = np.zeros(3)
    assert readonly(arr) is arr  # same object, not a copy -- the caller owns it
    with pytest.raises(ValueError, match="read-only"):
        arr[0] = 1.0


def test_array_value_copies_and_freezes_array_fields_in_place() -> None:
    """The base contract, isolated from any real value object's constructor."""

    @dataclass(frozen=True, eq=False)
    class Sample(ArrayValue):
        values: np.ndarray
        label: str

    given = np.array([1.0, 2.0, 3.0])
    sample = Sample(values=given, label="x")

    assert sample.values is not given  # detached: not the caller's array
    assert np.array_equal(sample.values, given)  # same content
    with pytest.raises(ValueError, match="read-only"):
        sample.values[0] = 99.0
    given[0] = 99.0  # mutating the caller's alias afterward
    assert sample.values[0] == 1.0  # ...does not reach the stored copy


# One minimal, directly-constructed instance per `ArrayValue` subclass outside
# `QAImages` (covered above), paired with the array field to probe. Builds
# each straight from its dataclass constructor -- not through the estimator
# that normally produces it -- so this stays a test of `ArrayValue`, not a
# second copy of each metric's own tests.
def _sample_instances() -> list[tuple[ArrayValue, str]]:
    return [
        (
            WeisskoffResult(
                roi_sizes=np.arange(1, 4),
                cv=np.array([0.1, 0.2, 0.3]),
                cv1=np.array([0.4, 0.5, 0.6]),
                cv1_pooled=0.4,
                rdc=4.0,
            ),
            "roi_sizes",
        ),
        (
            GhostResult(
                pe_axis=0,
                radius=1,
                pe_signal=np.zeros((4, 4), dtype=bool),
                pe_ghost=np.zeros((4, 4), dtype=bool),
                ro_signal=np.zeros((4, 4), dtype=bool),
                ro_ghost=np.zeros((4, 4), dtype=bool),
                pe_ratio=0.1,
                ro_ratio=0.1,
                pe_top_ratio=0.1,
            ),
            "pe_signal",
        ),
        (
            OutlierResult(fraction=np.array([0.0, 0.1, 0.2]), n_voxels=10, qthr=0.001),
            "fraction",
        ),
        (
            CenterOfMassResult(com=np.zeros((3, 2)), shape=(8, 8)),
            "com",
        ),
        (
            SmoothnessResult(
                fwhm_vox=(2.0, 2.0),
                lags=np.arange(3),
                acf=np.ones((2, 3)),
            ),
            "acf",
        ),
        (
            PhantomGeometry(
                phantom_mask=np.ones((4, 4), dtype=bool),
                roi_center=np.array([2, 2]),
                contrast=5.0,
            ),
            "roi_center",
        ),
        (ROI(center=np.array([2, 2]), size=3), "center"),
        (MotionResult(params=np.zeros((3, 5))), "params"),
    ]


@pytest.mark.parametrize(
    "instance,field_name",
    _sample_instances(),
    ids=[type(instance).__name__ for instance, _ in _sample_instances()],
)
def test_every_array_value_subclass_owns_a_readonly_copy(
    instance: ArrayValue, field_name: str
) -> None:
    array = getattr(instance, field_name)
    assert not array.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        array.flat[0] = 1


def test_every_array_field_on_every_sample_is_readonly() -> None:
    """Belt-and-suspenders: not just the one field each sample was picked for."""
    for instance, _ in _sample_instances():
        for field in fields(instance):
            value = getattr(instance, field.name)
            if isinstance(value, np.ndarray):
                assert not value.flags.writeable, (
                    f"{type(instance).__name__}.{field.name} is writable"
                )


def test_motion_result_equality_no_longer_raises_on_its_array_field() -> None:
    """Regression: `eq=True` on an array-holding dataclass raises, not compares.

    `MotionResult` inherited `ArrayValue` (which copies `params`) without also
    setting `eq=False`, so its generated `__eq__` tried `params == params` and
    then the truth value of the resulting array -- exactly the trap every other
    array-holding class here avoids with `eq=False`. Equality now falls back to
    identity, like its siblings.
    """
    a = MotionResult(params=np.zeros((2, 5)))
    b = MotionResult(params=np.zeros((2, 5)))
    assert a == a
    assert a != b
