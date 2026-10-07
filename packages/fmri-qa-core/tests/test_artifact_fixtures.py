"""Fixture archives: a real file an old build actually wrote still loads.

`test_artifact_archive.py`'s migration tests (see its `_ADDED_IN`) take a
*current* artifact, delete the fields that `_ADDED_IN` says a given version
predates, and check that the matching `_vN_to_vN1` puts them back as unknown.
That proves each migration step does what `_ADDED_IN` claims -- but `_ADDED_IN`
is, by its own comment, the reverse of `serialize.migrate._MIGRATIONS`, so
those tests check one hand-maintained description of the schema history
against another. They cannot catch an array renamed, resized or changed
dtype between versions; a field whose *meaning* changed rather than its
presence; a document layout the current writer could no longer produce at
all; or a key-ordering/encoding difference that only shows up in bytes an old
build actually wrote.

This module is the other half. The `tests/fixtures/schema_v*` archives are not
synthesized: each is the literal file produced by checking out that
schema version's own commit (the last commit before the next schema bump) and
running *that build's* `save_artifact` over the same synthetic phantom the
rest of this suite uses (`conftest.synthetic_series`, seed 0). Loading one
here exercises real historical bytes, not today's writer's idea of what an
old file looked like -- including the *container* those bytes are in, which is
why the fixtures are discovered by either suffix: every committed one so far is
a `.qa.npz`, because that is what the builds that wrote them wrote, and the
next one will be a `.qa.nc`. Neither half of the suite replaces the other: a bug
that broke a migration step and its exact inverse in the same commit could
still pass a single fixture, and a fixture proves nothing about a step in
isolation the way `test_artifact_archive.py` does.

A schema bump is not finished until a fixture of the version it retired is
committed here (see `serialize/migrate.py`'s module docstring) -- otherwise
this file's own coverage quietly regresses to only the versions before it.
"""

import math
import re
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc.analysis import ARTIFACT_SCHEMA_VERSION
from fmriqc.analysis.serialize.migrate import _MIGRATIONS

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURE_NAME = re.compile(r"schema_v(\d+)\.qa\.(?:npz|nc)$")

# Which section of `QAArtifact` each field named below lives in, so the tables
# below can name a field once instead of nesting them by section.
_SECTION_OF = {
    "snr": "measurements",
    "sfnr": "measurements",
    "phantom_fraction": "measurements",
    "roi_inside_phantom": "measurements",
    "phantom_mask_ok": "measurements",
    "phantom_contrast": "measurements",
    "clipped_any": "measurements",
    "n_clipped_kept": "measurements",
    "n_trimmed": "provenance",
    "slice_index": "provenance",
    "n_slices": "provenance",
}

# What each version's own writer could not yet record, independent of
# `serialize.migrate`'s `_MIGRATIONS`/docstrings -- this table is read off the
# schema history in `analysis/artifact.py`'s `ARTIFACT_SCHEMA_VERSION` comment,
# not copied from the migration code, so it does not just check that code
# against its own account of itself.
_UNKNOWN_AT: dict[int, tuple[str, ...]] = {
    1: (
        "phantom_fraction",
        "roi_inside_phantom",
        "phantom_mask_ok",
        "phantom_contrast",
        "n_trimmed",
        "slice_index",
        "n_slices",
    ),
    2: ("phantom_mask_ok", "phantom_contrast", "n_trimmed", "slice_index", "n_slices"),
    3: ("phantom_contrast", "n_trimmed", "slice_index", "n_slices"),
    4: ("phantom_contrast", "slice_index", "n_slices"),
    5: (),
    # Schema 6 recorded every field above. The clipping block it *also* always
    # answered is deliberately not listed: schema 7 lets it be unknown, but a
    # schema 6 document carries a real bool, which migrates forward as the
    # measurement that build made (see `serialize.migrate._v6_to_v7`).
    6: (),
}

# What each fixture's own writer *did* measure on the shared synthetic
# phantom, captured once from the real archives: not just "present", but
# reading back the exact value that build recorded. `snr`/`sfnr` shift in the
# last few digits from schema 4 onward -- real history (a numerical fix
# landed between the schema-3 and schema-4 commits), not a fixture mistake.
_KNOWN_AT: dict[int, dict[str, object]] = {
    1: {"snr": 154.80051191601368, "sfnr": 149.84960132655738},
    2: {
        "snr": 154.80051191601368,
        "sfnr": 149.84960132655738,
        "phantom_fraction": 0.1884765625,
        "roi_inside_phantom": True,
    },
    3: {
        "snr": 154.80051191601368,
        "sfnr": 149.84960132655738,
        "phantom_fraction": 0.1884765625,
        "roi_inside_phantom": True,
        "phantom_mask_ok": True,
    },
    4: {
        "snr": 154.8005119160131,
        "sfnr": 149.84960132655735,
        "phantom_fraction": 0.1884765625,
        "roi_inside_phantom": True,
        "phantom_mask_ok": True,
        "n_trimmed": 2,
    },
    5: {
        "snr": 154.8005119160131,
        "sfnr": 149.84960132655735,
        "phantom_fraction": 0.1884765625,
        "roi_inside_phantom": True,
        "phantom_mask_ok": True,
        "n_trimmed": 2,
        "slice_index": 1,
        "n_slices": 3,
        "phantom_contrast": 52.71573552713314,
    },
    6: {
        "snr": 154.8005119160131,
        "sfnr": 149.84960132655735,
        "phantom_fraction": 0.1884765625,
        "roi_inside_phantom": True,
        "phantom_mask_ok": True,
        "n_trimmed": 2,
        "slice_index": 1,
        "n_slices": 3,
        "phantom_contrast": 52.71573552713314,
        # Schema 6 ran the rail test unconditionally and found no pile-up on
        # this phantom. Under schema 7 that False still means "no rail found",
        # not "the storage was checked" -- it is the value that build reached.
        "clipped_any": False,
        "n_clipped_kept": 0,
    },
}


def _discover_fixtures() -> dict[int, Path]:
    """Map schema version to its committed fixture, from what is on disk.

    Driving the parametrization from the directory listing (rather than a
    hard-coded version list) means a fixture removed by mistake shrinks the
    test count silently; `test_fixture_directory_covers_every_migratable_version`
    below is what turns that into a failure instead.
    """
    found = {}
    for path in sorted(FIXTURES_DIR.glob("schema_v*")):
        match = _FIXTURE_NAME.match(path.name)
        if match:
            found[int(match.group(1))] = path
    return found


_FIXTURES = _discover_fixtures()


def _is_unknown(value: object) -> bool:
    """True for the documented "not recorded" marker: `None` or NaN.

    Not every NaN in the artifact means this -- `max_translation` is a
    genuine NaN on this fixture because its motion fit did not converge, a
    measurement outcome, not a migration gap -- so this is only applied to
    the fields `_UNKNOWN_AT` names for a given version.
    """
    return value is None or (isinstance(value, float) and math.isnan(value))


@pytest.mark.parametrize("version", sorted(_FIXTURES), ids=lambda v: f"schema_v{v}")
def test_a_real_archive_from_an_older_build_still_loads(version: int) -> None:
    """`load_artifact` reads a file an old build actually wrote.

    If a future change silently made one of these unreadable -- an array
    renamed or reshaped, a field repurposed, a document key no longer where
    the reader expects it -- this is the test that notices; the migration
    steps could still look correct against `test_artifact_archive.py`'s own
    synthesized documents.
    """
    path = _FIXTURES[version]
    with pytest.warns(UserWarning, match="migrated to"):
        loaded = q.load_artifact(path)

    assert loaded.schema_version == ARTIFACT_SCHEMA_VERSION

    # Same phantom, same settings, same seed on every fixture -- these never
    # depended on the schema version and so must never move.
    assert loaded.provenance.scan == "scan.nii.gz"
    assert loaded.provenance.source == "scan.nii.gz"
    assert loaded.provenance.tr == 2.0
    assert loaded.provenance.n_frames == 38
    assert loaded.provenance.voxel_mm == (3.0, 3.0, 3.0)
    assert loaded.provenance.matrix == (32, 32)
    assert loaded.provenance.pe_dir == "col"
    assert loaded.provenance.flip_angle == 77
    assert loaded.settings.roi_size == 9
    assert loaded.settings.trim_sec == 5.0
    # Older builds stored the flip angle as an int; it loads as a float, or a
    # re-save would publish it as NC_INT.
    assert type(loaded.provenance.flip_angle) is float
    assert loaded.images.phantom_mask.sum() == 193
    assert loaded.curves.time[:3].tolist() == [0.0, 2.0, 4.0]

    # Schema <= 5 always measured peak motion in voxels regardless of the known
    # voxel size (see `serialize.migrate._v5_to_v6`), so "vox" there is a
    # recorded historical fact rather than a placeholder. Schema 6 onward
    # records the unit it actually used, which on this phantom -- 3 mm isotropic
    # in the header -- is mm.
    expected_unit = "vox" if version <= 5 else "mm"
    assert loaded.measurements.displacement_unit == expected_unit

    for name in _UNKNOWN_AT[version]:
        section = getattr(loaded, _SECTION_OF[name])
        assert _is_unknown(getattr(section, name)), (
            f"{_SECTION_OF[name]}.{name} should read back unknown at schema {version}"
        )

    for name, expected in _KNOWN_AT[version].items():
        section = getattr(loaded, _SECTION_OF[name])
        actual = getattr(section, name)
        if isinstance(expected, float):
            assert actual == pytest.approx(expected)
        else:
            assert actual == expected


def test_fixture_directory_covers_every_migratable_version() -> None:
    """A schema bump that forgets to commit a fixture is visible, not silent.

    `_MIGRATIONS` names every version this build knows how to migrate from --
    every one of those should have a real archive behind it (see the module
    docstring for why a synthesized document is not a substitute).
    """
    assert _FIXTURES, f"no fixture archives found in {FIXTURES_DIR}"
    missing = set(_MIGRATIONS) - set(_FIXTURES)
    assert not missing, (
        f"no committed fixture for schema version(s) {sorted(missing)}; "
        f"see serialize/migrate.py on generating one"
    )
