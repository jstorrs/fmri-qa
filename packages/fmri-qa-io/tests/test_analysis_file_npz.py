"""The retired `.npz` container.

Nothing writes one any more, and every analysis written before this one does --
so the reader stays, and these tests build the two forms by hand rather than
through a writer that no longer exists. The committed fixtures in
`test_analysis_file_fixtures.py` cover real historical bytes; these isolate the
stored form from the schema history the fixtures also exercise.
"""

import json
from dataclasses import asdict

# `netCDF4` is imported here and not in each test on purpose: the "without a
# warning" tests run under `simplefilter("error")`, and importing the wheel
# raises its own Cython `RuntimeWarning`. Taking the import at module scope
# means every test enters that filter with the library already loaded, so what
# the filter can catch is what opening the analysis does and nothing else.
import numpy as np
import pytest

import fmriqa as q
import fmriqa_io

# Nothing writes one any more, and every analysis written before this one does
# -- so the reader stays, and these build the two forms by hand rather than
# through a writer that no longer exists. The committed fixtures in
# `test_analysis_file_fixtures.py` cover real historical bytes; these isolate the
# stored form from the schema history the fixtures also exercise.


def _as_npz(path, document: str, arrays, document_member) -> None:
    """An `.npz` analysis in the layout the retired writer used."""
    np.savez_compressed(path, __document__=document_member(document), **arrays)


def _as_utf8_bytes(text: str) -> np.ndarray:
    """The document member as the last `.npz` builds wrote it."""
    return np.frombuffer(text.encode("utf-8"), dtype=np.uint8)


def test_load_rejects_a_damaged_npz(tmp_path, analysis, read_netcdf) -> None:
    """A zip that starts right and stops early is refused, not half-read.

    NumPy's loader answers a damaged archive with whichever of four libraries'
    exceptions it reached -- `BadZipFile`, an inflate error, a header-parse
    error, a truncated member -- and the reader turns all of them into the one
    thing a caller can act on.
    """
    saved = fmriqa_io.save_analysis(analysis, tmp_path / "new.qa.nc")
    document, arrays = read_netcdf(saved)
    old = tmp_path / "old.qa.npz"
    _as_npz(old, json.dumps(document), arrays, _as_utf8_bytes)

    whole = old.read_bytes()
    old.write_bytes(whole[: len(whole) // 2])
    assert old.read_bytes()[:4] == b"PK\x03\x04"  # still claims to be the container
    with pytest.raises(q.InvalidAnalysisFileError):
        fmriqa_io.load_analysis(old)


@pytest.mark.parametrize(
    "document_member", [_as_utf8_bytes, np.array], ids=["uint8", "unicode"]
)
def test_an_npz_analysis_still_loads(
    tmp_path, analysis, document_member, read_netcdf
) -> None:
    """Both stored forms of the old document member, opened by the same call.

    `uint8` is what the last `.npz` builds wrote; a NumPy `<U` string is what
    everything before them wrote. Neither is written now, and both must read.

    Compared as documents, not as analyses: the fixture's motion metrics are
    NaN, and NaN != NaN would fail a dataclass comparison for reasons that have
    nothing to do with the stored form.
    """
    saved = fmriqa_io.save_analysis(analysis, tmp_path / "new.qa.nc")
    document, arrays = read_netcdf(saved)
    old = tmp_path / "old.qa.npz"
    _as_npz(old, json.dumps(document), arrays, document_member)

    assert old.read_bytes()[:4] == b"PK\x03\x04"  # the other container, by its magic
    loaded = fmriqa_io.load_analysis(old)
    assert asdict(loaded.provenance) == asdict(analysis.provenance)
    assert asdict(loaded.settings) == asdict(analysis.settings)
    assert loaded.schema_version == analysis.schema_version
    assert loaded.measurements.snr == analysis.measurements.snr
    assert loaded.images.phantom_mask.dtype == np.bool_
