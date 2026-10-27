"""Map a `QAArtifact` to and from the document and arrays its file holds.

This is the schema half of the artifact file: pure functions between the value
objects and a JSON document plus named arrays, with no file in sight. The file
those travel in (the netCDF-4 container, and the retired `.npz` one) lives in
`fmriqa_io.artifact`, so a reader with no filesystem (the browser) can use this.

The mapping is written out section by section, not derived by reflection over the
dataclasses. The layout is a published contract pinned by
`ARTIFACT_SCHEMA_VERSION`, so adding a field should be a deliberate edit. Bumping
the version is also deliberate and comes with a migration: older layouts are
brought forward on read (`migrate`), not refused.

The JSON document uses Python's `NaN` and `Infinity` tokens. A NaN measurement
means an estimator could not resolve the value, which differs from the `null`
that says the quantity does not apply, so NaN is preserved.

`ls` this package to find a concern:

* `decompose` -- artifact -> (JSON document, named arrays)
* `compose`   -- (JSON document, named arrays) -> artifact
* `migrate`   -- an older document's layout, brought forward on read
"""

__all__: list[str] = []
