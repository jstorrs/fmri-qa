# Testing Style Guide

How packages in this workspace are tested. The pure functional core (see
[architecture.md](architecture.md)) is testable with plain values, no fixtures or mocks.

## Core Principles

1. **Test the core with values; test the shell with I/O.** Pure logic gets many fast unit
   tests. The thin imperative shell gets a few integration tests.
2. **Assert behavior, not implementation.** Tests pin the contract a caller depends on, so
   behavior-preserving refactors don't break them.
3. **Tests are deterministic.** No wall-clock, randomness, network, or filesystem ordering.
4. **A failing test names the bad value.** Prefer `assert result == expected` to a bare
   `assert result`.

## Unit vs Integration

| Kind | Where | Tests |
|------|-------|-------|
| Unit | `tests/test_*.py` beside the package | Pure functions and value objects, called directly |
| Integration | `tests/` exercising the imported package | The public API end to end, as a caller sees it |

Unit tests may call private helpers (`_normalize`). Integration tests use the import
surface a real caller uses (`import mypackage; mypackage.load(path)`), which also checks
that the public API ([architecture.md](architecture.md#simple-public-interfaces)) is usable.

The root `pyproject.toml` pins the layout. One `pytest` run covers every package, so an
artifact change is tested on both sides of the seam:

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

`--import-mode=importlib` lets every package name a test file for what it tests (each has a
`test_cli.py`) without the module names colliding.

## `assert` and `pytest.raises` Are the Assertion

The ban on bare `assert` for validation ([exceptions.md](exceptions.md)) covers library
and binary code, not tests. In a test, a plain `assert` is the check, and
`with pytest.raises(ValidationError):` asserts an error path.

```python
def test_rejects_zero_port() -> None:
    with pytest.raises(ConfigError, match="port"):
        Port(0)
```

Ruff `per-file-ignores` relax `S101` (assert), `PLR2004` (magic values), and `ARG`
(unused fixture arguments) under `**/tests/**`.

## Naming

- Name a test for the behavior it checks, not the function it calls:
  `rejects_zero_port`, `round_trips_empty_archive`, `diff_of_identical_docs_is_empty`, not
  `test_1` or `test_process`.
- Test one behavior per test where practical. A test that asserts five unrelated things
  reports failure ambiguously.

## What to Cover

- **The happy path** of every public operation.
- **Each exception you promise.** If a docstring's `Raises` section lists `ValidationError`,
  a test provokes it. Exceptions are part of the contract ([exceptions.md](exceptions.md)).
- **Boundaries.** Empty input, a single element, the off-by-one edges of any range.
- **Round-trips and inverses.** Where the code has an algebraic property, assert it
  directly: `decode(encode(x)) == x` for a codec, `apply(base, diff(base, target)) ==
  target` for a diff/apply pair. These catch classes of bugs that hand-picked examples
  miss.

## Property-Based Testing

For round-trips and invariants, use **hypothesis** (a workspace dev dependency).
`@given(...)` generates hundreds of inputs and shrinks any failure to a minimal
counterexample.

```python
from hypothesis import given, strategies as st


@given(st.binary())
def test_round_trips_arbitrary_bytes(payload: bytes) -> None:
    assert decode(encode(payload)) == payload
```

Let hypothesis manage its own seeds. A property that holds only "usually" is a bug in the
property or the code. Don't retry it.

## Performance

There is no benchmark suite, and the test run is not one. Don't put a timing assertion in a
correctness test, because a loaded CI runner makes it flaky. If a metric's cost starts to
matter, measure it in a scratch script and record the number in `notes/`. Add a benchmark
harness and `make` target only once the measurement must be repeatable, and keep it out of
`make check`.

## Fixtures and Test Data

- **Construct values in code when you can.** A literal frozen dataclass is clearer than a
  file loaded from disk.
- **Use real sample files only when the format itself is under test** (e.g. parsing real
  DICOM). Keep them small, committed under `tests/`, and document where each came from and
  what makes it interesting.
- **Share setup with small helper functions.** A `def sample_archive() -> Archive` beats a
  fixture harness. Use a pytest `fixture` only when a test genuinely needs managed
  setup/teardown (a temp dir, an open connection), not as a default.

## Running

Part of the standard loop in [tooling.md](tooling.md):

```bash
make test        # uv run pytest across every package
make all         # lint typecheck pyright test
make check       # the gate: the above, plus a 90% coverage floor
```

Coverage is opt-in: `make check` passes `--cov --cov-fail-under=90`, so a bare
`uv run pytest packages/fmri-qa-core/tests/test_ghost.py` stays fast. A change is done when
the whole workspace is green. CI runs `make check`.

## Don't

- Don't assert on private implementation detail (a helper's intermediate value). Test
  through the contract so refactors stay free ([stability.md](stability.md)).
- Don't write tests that depend on time, randomness, or directory iteration order.
- Don't commit large or sensitive fixture files; keep sample data small and
  non-confidential ([logging.md](logging.md) on sensitive payloads applies here too).
- Don't leave a `@pytest.mark.skip` or commented-out test in place. Fix it or delete it
  ([zen.md](zen.md): never is often better than right now).
