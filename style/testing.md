# Testing Style Guide

How packages in this workspace are tested. The architecture is built for this: a pure
functional core (see [architecture.md](architecture.md)) is testable with plain values, no
fixtures or mocks.

## Core Principles

1. **Test the core with values; test the shell with I/O** — pure logic gets fast,
   plentiful unit tests; the thin imperative shell gets a few integration tests.
2. **Assert behavior, not implementation** — tests pin the contract a caller depends on,
   so refactors that preserve behavior don't break them (mirrors the coherence test in
   [documentation.md](documentation.md#the-coherence-test)).
3. **Tests are deterministic** — no wall-clock, randomness, network, or reliance on
   filesystem ordering. Same inputs, same result, every run.
4. **A failing test names the bad value** — like exceptions, an assertion should make it
   obvious what was expected and what was found. `assert result == expected` already does
   this; a bare `assert result` does not.

## Unit vs Integration

| Kind | Where | Tests |
|------|-------|-------|
| Unit | `tests/test_*.py` beside the package | Pure functions and value objects, called directly |
| Integration | `tests/` exercising the imported package | The public API end to end, as a caller sees it |

Unit tests may reach private helpers (`_normalize`, a module-level function) — they live
alongside the code. Integration tests go through the import surface a real caller uses
(`import mypackage; mypackage.load(path)`), which makes them a second check that the public
API ([architecture.md](architecture.md#simple-public-interfaces)) is actually usable.

The workspace pins the layout once, in the root `pyproject.toml` — one `pytest` run
covers every package, so a change to the artifact is tested on both sides of the seam
together:

```toml
[tool.pytest.ini_options]
testpaths = [
    "packages/fmri-qa-core/tests",
    "packages/fmri-qa-report/tests",
    "packages/fmri-qa-launcher/tests",
    "scripts/tests",
]
pythonpath = ["scripts"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short --import-mode=importlib"
```

`--import-mode=importlib` is what lets every package name a test file for what it tests —
each has a `test_cli.py` — without the module names colliding.

## `assert` and `pytest.raises` Are the Assertion

[exceptions.md](exceptions.md) says fail fast in library code and don't lean on bare
`assert` for validation — **that rule is about library and binary code, not tests.** In a
test, a plain `assert` *is* the check, and `with pytest.raises(ValidationError):` *is* how
you assert an error path. If it fails, the test fails with a location and a diff, which is
exactly what you want.

```python
def test_rejects_zero_port() -> None:
    with pytest.raises(ConfigError, match="port"):
        Port(0)
```

The workspace already relaxes the relevant lints under `**/tests/**` in its ruff
`per-file-ignores`: `S101` (assert), `PLR2004` (magic values), and `ARG` (unused fixture
arguments). You don't have to fight the linter to write direct tests.

## Naming

- Name a test for the behavior it checks, not the function it calls:
  `rejects_zero_port`, `round_trips_empty_archive`, `diff_of_identical_docs_is_empty` — not
  `test_1` or `test_process`.
- One behavior per test where practical; a test that asserts five unrelated things reports
  failure ambiguously.

## What to Cover

- **The happy path** of every public operation.
- **Each exception you promise** — if a docstring's `Raises` section lists `ValidationError`, a
  test provokes it. Exceptions are part of the contract ([exceptions.md](exceptions.md));
  cover them like one.
- **Boundaries** — empty input, a single element, the off-by-one edges of any range.
- **Round-trips and inverses** — where the code has an algebraic property, assert it
  directly: `decode(encode(x)) == x` for a codec, `apply(base, diff(base, target)) ==
  target` for a diff/apply pair. These catch whole classes of bugs a hand-picked example
  misses.

## Property-Based Testing

Hand-picked examples test the cases you thought of. For round-trips and invariants, reach
for **hypothesis** (a workspace dev dependency): `@given(...)` generates hundreds of inputs
and shrinks any failure to a minimal counterexample — exactly where round-trip and inverse
properties pay off most.

```python
from hypothesis import given, strategies as st


@given(st.binary())
def test_round_trips_arbitrary_bytes(payload: bytes) -> None:
    assert decode(encode(payload)) == payload
```

Keep hypothesis deterministic: it manages its own seeds and example database — let it,
rather than seeding a strategy from the wall clock. A property that only holds "usually"
is a bug in the property or the code, not a reason to retry.

## Performance

There is no benchmark suite here, and the test run is not one. **Benchmarks measure; tests
assert** — so don't smuggle a timing assertion into the correctness tests, where a loaded
CI runner turns it into a flake and violates the determinism rule above. If a metric's cost
starts to matter, measure it in a scratch script and record the number in `notes/`; add a
real benchmark harness (and a `make` target for it) only once the measurement needs to be
repeatable, and keep it out of `make check`.

## Fixtures and Test Data

- **Construct values in code when you can** — a literal frozen dataclass is clearer and
  more maintainable than a file loaded from disk.
- **Use real sample files only when the format itself is under test** (e.g. parsing real
  DICOM). Keep them small, committed under `tests/`, and document where each came from and
  what makes it interesting.
- **Share setup with small helper functions, not elaborate frameworks** — a
  `def sample_archive() -> Archive` beats a fixture harness. Reach for a pytest `fixture`
  when a test genuinely needs managed setup/teardown (a temp dir, an open connection), not
  as a default.

## Running

Part of the standard loop in [tooling.md](tooling.md):

```bash
make test        # uv run pytest across every package
make all         # lint typecheck pyright test
make check       # the gate: the above, plus a 90% coverage floor
```

Coverage is opt-in — `make check` passes `--cov --cov-fail-under=90`, so a bare
`uv run pytest packages/fmri-qa-core/tests/test_ghost.py` stays fast and doesn't trip the
workspace-wide floor. Green across the workspace is the bar before a change is done; CI
runs `make check`.

## Don't

- Don't assert on private implementation detail (a helper's exact intermediate value) —
  test through the contract so refactors stay free ([stability.md](stability.md)).
- Don't write tests that depend on time, randomness, or directory iteration order.
- Don't commit large or sensitive fixture files; keep sample data small and
  non-confidential ([logging.md](logging.md) on sensitive payloads applies here too).
- Don't leave a `@pytest.mark.skip` or commented-out test as a permanent fixture — fix it
  or delete it ([zen.md](zen.md): never is often better than right now).
