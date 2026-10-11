"""ADC-saturation detection: rail inference and pile-up counting."""

import numpy as np
import pytest

from fmriqc.exceptions import InvalidScanError
from fmriqc.metrics.saturation import _saturation_bits, detect_saturation


def test_saturation_bits_recognizes_hardware_rails() -> None:
    assert _saturation_bits(4095.0) == 12  # classic 12-bit ADC
    assert _saturation_bits(255.0) == 8
    assert _saturation_bits(65535.0) == 16


def test_saturation_bits_rejects_off_rail_and_out_of_range() -> None:
    assert _saturation_bits(4096.0) is None  # a power of two, not 2**n - 1
    assert _saturation_bits(100.0) is None  # arbitrary maximum
    assert _saturation_bits(127.0) is None  # 2**7 - 1, but n=7 below the range


def test_detect_saturation_clean_series_reports_nothing() -> None:
    data = np.linspace(0, 3000, 4 * 4 * 1 * 8).reshape(4, 4, 1, 8)
    result = detect_saturation(data)
    assert result is not None
    assert not result.suspected
    assert not result.clipped
    assert result.bits is None


def test_detect_saturation_counts_and_splits_at_trim() -> None:
    data = np.zeros((2, 2, 1, 4))
    data[0, 0, 0, 1] = 4095.0  # clip in a dropped warm-up volume
    data[1, 1, 0, 3] = 4095.0  # clip in an analyzed volume
    result = detect_saturation(data, trim=2)
    assert result is not None
    assert result.suspected and result.bits == 12
    assert result.ceiling == 4095.0
    assert result.n_clipped_pre == 1
    assert result.n_clipped_kept == 1
    assert result.n_clipped == 2
    assert result.clipped_kept


def test_detect_saturation_recovers_stored_integer_with_slope() -> None:
    # image units = slope * stored; a 12-bit rail stored as 4095 shows as 8190
    data = np.zeros((2, 2, 1, 3))
    data[0, 0, 0, 2] = 8190.0
    result = detect_saturation(data, slope=2.0, inter=0.0)
    assert result is not None
    assert result.bits == 12


def test_non_integer_storage_is_not_determinable_rather_than_clean() -> None:
    """Float storage gives no answer, and "clean" would be the wrong one.

    The rail is an integer artifact of the receiver's ADC. A converter that wrote
    floats and rescaled destroyed it, so saturated and clean acquisitions look
    alike. A "no clipping" result would hide the runs this check exists to
    catch, so there is no result.
    """
    saturated = np.zeros((2, 2, 1, 4))
    saturated[0, 0, 0, 1] = 4095.0  # would be found, on integer storage

    assert detect_saturation(saturated, stored_integer=False) is None
    # ...and the same series, stored as the scanner's integers, is found.
    found = detect_saturation(saturated, stored_integer=True)
    assert found is not None and found.suspected


@pytest.mark.parametrize("slope", [0.0, float("nan"), float("inf")])
def test_detect_saturation_refuses_an_unusable_slope(slope) -> None:
    """A zero or non-finite slope cannot recover stored units.

    The rail test is then meaningless, and a clean result would be wrong, not a
    safe default. It must raise instead of returning `suspected=False`.
    """
    data = np.zeros((2, 2, 1, 3))
    with pytest.raises(InvalidScanError) as excinfo:
        detect_saturation(data, slope=slope)
    assert excinfo.value.field == "slope"
