"""The netCDF layout before a file exists.

It declares every array the artifact publishes, and `netcdf.encode` refuses an
array the layout does not declare, of the wrong rank, disagreeing about an axis,
or in a dtype the container would narrow.
"""

import numpy as np
import pytest

from fmriqc.analysis.serialize.decompose import decompose


def test_the_layout_declares_every_array_the_artifact_publishes(
    artifact, encode
) -> None:
    """`decompose` and the netCDF layout are one contract in two files.

    A field added to one and not the other would be an array with no declared
    axes. `encode` refuses it, and this says so before a save has to.
    """
    document, arrays = decompose(artifact)
    content = encode(document, arrays)
    assert set(content.variables) == set(arrays)


def test_encode_refuses_an_array_the_layout_does_not_declare(artifact, encode) -> None:
    document, arrays = decompose(artifact)
    with pytest.raises(ValueError, match="not an array this artifact layout"):
        encode(document, arrays | {"curves.invented": np.zeros(3)})


def test_encode_refuses_an_array_of_the_wrong_rank(artifact, encode) -> None:
    document, arrays = decompose(artifact)
    with pytest.raises(ValueError, match="rank 2"):
        encode(document, arrays | {"curves.time": np.zeros((3, 3))})


def test_encode_refuses_two_arrays_that_disagree_about_one_axis(
    artifact, encode
) -> None:
    """A shared dimension is a claim, and a file cannot make it two ways."""
    document, arrays = decompose(artifact)
    with pytest.raises(ValueError, match="already fixed it at"):
        encode(document, arrays | {"curves.roi_signal": np.zeros(3)})


def test_encode_refuses_a_dtype_the_container_would_narrow(artifact, encode) -> None:
    """A QA number quietly stored at half its precision is a silent loss."""
    document, arrays = decompose(artifact)
    narrowed = arrays["curves.time"].astype(np.float32)
    with pytest.raises(ValueError, match="dtype float32"):
        encode(document, arrays | {"curves.time": narrowed})
