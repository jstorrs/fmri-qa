# Architecture Style Guide

This document describes the preferred architectural style for modules in this repository: **Functional Core, Imperative Shell** with value objects and facade-style public APIs. It is the concrete expression of several principles in [zen.md](zen.md) — *simple is better than complex*, *flat is better than nested*, and *explicit is better than implicit*.

## Core Principles

1. **Pure functions for logic** - Business logic lives in functions without side effects
2. **Lightweight classes as wrappers** - Classes provide ergonomic interfaces, not logic
3. **Short functions with helpers** - Extract helpers liberally to keep functions focused
4. **Flat over nested** - Guard clauses and early returns over rightward-drifting `if`/`else`
5. **Simple public interfaces** - External API should be minimal and intuitive
6. **Type-driven design** - Encode invariants in types so illegal states are hard to build; let the type checkers ([tooling.md](tooling.md)) enforce them

## Pure Functions for Logic

Implement core logic in pure functions that:
- Take inputs as parameters
- Return outputs (no mutation of inputs)
- Have no side effects (no I/O, no global state)

```python
# Good - pure function
def calculate_statistics(values: list[float]) -> Statistics:
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return Statistics(mean=mean, std_dev=variance ** 0.5)


# Avoid - logic mixed with I/O
def calculate_statistics(path: str) -> Statistics:
    values = load_values(path)  # I/O inside logic
    # ...
```

### Benefits

- **Testable**: No mocks needed, just pass inputs and check outputs
- **Composable**: Functions can be combined freely
- **Predictable**: Same inputs always produce same outputs

## Lightweight Class Wrappers

Classes should be thin wrappers that:
- Provide ergonomic interfaces to users
- Manage resources (files, connections)
- Delegate logic to pure functions

```python
class DataProcessor:
    """Thin wrapper providing convenient interface."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: Data | None = None

    def load(self) -> None:
        """Load data from file."""
        raw = self._path.read_bytes()
        self._data = parse_data(raw)  # delegate to pure function

    def analyze(self) -> Report:
        """Analyze loaded data."""
        if self._data is None:
            raise StateError("data not loaded")
        return generate_report(self._data)  # delegate to pure function
```

### Class vs Function Guidelines

| Use a class when | Use a function when |
|------------------|---------------------|
| Managing resources or state | Transforming data |
| Providing a multi-step workflow | Single operation |
| User-facing API ergonomics matter | Internal implementation |
| Context manager semantics needed | Stateless computation |

## Short Functions with Helpers

Keep functions short and focused. Extract helpers liberally:

```python
# Good - main function stays readable
def process_study(study: Study) -> Result:
    validated = validate_study(study)
    normalized = normalize_values(validated)
    statistics = compute_statistics(normalized)
    return build_result(study, statistics)


# Helpers handle the details
def validate_study(study: Study) -> Study:
    check_required_fields(study)
    check_value_ranges(study)
    return study


def normalize_values(study: Study) -> Study:
    # ...
```

### Guidelines

- If a function needs a comment explaining a block, extract that block
- If a function exceeds ~20 lines, look for extraction opportunities
- Helper functions can have complex signatures - they're internal
- Name helpers to describe what they do, not how

## Flat Over Nested

Deeply nested `if`/`else` blocks drift rightward and bury the main path. Keep the happy
path at the left margin: handle the exceptional cases first and return early.

```python
# Avoid - the real work is buried three levels deep
def load(path: Path) -> Config:
    if path.exists():
        if path.suffix == ".toml":
            raw = path.read_text()
            if raw.strip():
                return parse_config(raw)
            else:
                raise ConfigError("config file is empty")
        else:
            raise ConfigError("config must be a .toml file")
    else:
        raise ConfigError("config file does not exist")


# Prefer - guard clauses keep the happy path flat
def load(path: Path) -> Config:
    if not path.exists():
        raise ConfigError("config file does not exist")
    if path.suffix != ".toml":
        raise ConfigError("config must be a .toml file")

    raw = path.read_text()
    if not raw.strip():
        raise ConfigError("config file is empty")

    return parse_config(raw)
```

Techniques that keep the body flat:

- **Guard clauses** — validate preconditions and `raise`/`return` up front, so the body
  isn't wrapped in a giant `if`.
- **Early returns** — return the moment the answer is known instead of threading a result
  variable through nested branches. The `RET` ruff rules ([tooling.md](tooling.md)) flag the
  superfluous `else` after a `return`.
- **`continue` in loops** — skip the uninteresting iteration early rather than indenting the
  whole loop body inside an `if`.
- **Extract a helper** when nesting is genuinely needed — a named function flattens the
  caller even when its own body branches.

This is *flat is better than nested* from [zen.md](zen.md), made concrete.

## Simple Public Interfaces

Public APIs should be minimal and intuitive. Complexity stays internal.

```python
# Public API - simple
def load(path: str | Path) -> Archive:
    """Load an archive from disk."""
    ...


def save(archive: Archive, path: str | Path) -> None:
    """Save an archive to disk."""
    ...


# Internal - complex signatures are fine
def _write_index_segment(
    writer: BinaryWriter,
    entries: list[IndexEntry],
    compression: CompressionConfig,
    checksum_algorithm: str,
    alignment: int,
) -> SegmentInfo:
    ...
```

### API Design Guidelines

- Fewer parameters is better for public functions
- Use sensible defaults
- Accept flexible input types (`str | Path`, `Iterable` vs `list`)
- Return concrete types
- Hide implementation details behind simple interfaces

## Frozen Dataclasses as Containers

Frozen dataclasses are the workhorse of [type-driven design](#type-driven-design) in
Python: small, immutable, and shaped so that holding the value means it's already valid.
Use them for data containers:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Measurement:
    """A single measurement reading."""

    timestamp: datetime
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class Statistics:
    """Computed statistics."""

    mean: float
    std_dev: float
    min_value: float
    max_value: float
    count: int
```

### Benefits

- **Immutable**: No accidental mutation
- **Hashable**: Can be used in sets and as dict keys
- **Clear**: Fields are explicitly declared
- **Lightweight**: `slots=True` reduces memory overhead

### When to Use

| Use frozen dataclass | Use regular class |
|---------------------|-------------------|
| Data containers | Resource management |
| Function inputs/outputs | Stateful workflows |
| Configuration objects | Mutable state needed |
| Value objects | Identity matters |

## Type-Driven Design

The type checkers (mypy, pyright, pyrefly — see [tooling.md](tooling.md)) are an always-on
check that runs on every file. The leverage is in *what you give them to check*. Design
types so a mistake fails type-checking rather than surfacing as a runtime bug that a
reviewer has to catch — a state the types forbid is a bug that can't be written, reviewed
for, or tested. This is *in the face of ambiguity, refuse the temptation to guess* from
[zen.md](zen.md), pushed into the type system.

### Make illegal states unrepresentable

Prefer a type whose every value is valid over a loose type guarded by scattered runtime
checks.

```python
# Avoid - every caller must remember the invariant
@dataclass
class Connection:
    host: str
    is_open: bool  # what does host mean when is_open is False?


# Prefer - the two states are exclusive and self-describing
@dataclass(frozen=True, slots=True)
class Open:
    host: str
    socket: socket.socket


class Closed:
    pass


Connection = Open | Closed
```

### Parse, don't validate

Validate once at the boundary and return a *narrower type* that proves the check happened,
rather than re-checking a wide type everywhere downstream. A frozen dataclass with a
validating `__post_init__` (or a classmethod constructor) is the natural home for this:
once you hold the value, the question is settled.

```python
@dataclass(frozen=True, slots=True)
class Port:
    """A validated TCP port. Constructing one proves it is in range."""

    value: int

    def __post_init__(self) -> None:
        if not 1 <= self.value <= 65535:
            raise ValidationError(f"port must be in [1, 65535], got {self.value}")


# Downstream takes `Port`, never a bare `int` - the "is it in range?" question is settled.
def connect(host: str, port: Port) -> Connection: ...
```

For a bare wrapper that carries no invariant but shouldn't be confused with a plain `int`,
`NewType` costs nothing and stops you from passing a user id where a byte offset was
expected:

```python
from typing import NewType

UserId = NewType("UserId", int)
ByteOffset = NewType("ByteOffset", int)

# get_user(offset) is now a type error, even though both are ints at runtime.
```

### Enums over booleans and stringly-typed values

Model a closed set of cases as an `Enum`, not a `bool` or a bare `str` that callers must
guess at. The type checker then forces every case to be handled and rejects typos.

```python
# Avoid - what are the valid strings? what does True mean here?
def open_file(path: Path, mode: str, binary: bool) -> IO: ...


# Prefer - the options are named, closed, and self-documenting
class Mode(Enum):
    READ = auto()
    WRITE = auto()
    APPEND = auto()


def open_file(path: Path, mode: Mode) -> IO: ...
```

When a fixed set of *string* values is genuinely the interface (JSON tags, CLI choices),
`Literal["read", "write"]` gives the same exhaustiveness without inventing an enum. Use
`typing.assert_never` in the final `else` of a `match` so adding a case that isn't handled
becomes a type error.

### Distinct types for distinct lifecycle states

Give each stage of a value's lifecycle its own type, so a value can only be used in the
context its type allows — the type checker makes "used in the wrong state" an error. The
classic case is separating untrusted from trusted data: the only way to obtain the trusted
type is to pass through the function that earns it.

```python
@dataclass(frozen=True, slots=True)
class UnsafeInput:
    """Straight from the user or network."""

    raw: str


@dataclass(frozen=True, slots=True)
class SafeInput:
    """Sanitized. The only constructor is `sanitize`."""

    value: str


def sanitize(raw: UnsafeInput) -> SafeInput:
    return SafeInput(strip_control_chars(raw.raw))


# Sensitive sinks demand SafeInput, so unsanitized data cannot reach them -
# it's not a convention or a lint, it fails type-checking.
def run_query(query: SafeInput) -> Rows: ...
```

Reach for the simple two-type gate first; only model a multi-state machine as separate
types when a value genuinely has several stages with stage-specific operations.

### Guidelines

- **Focused types over primitives** — a `NewType` or a one-field frozen dataclass costs
  almost nothing and buys type safety.
- **Enums over booleans and magic strings** — a closed set of cases is an `Enum` or a
  `Literal`, not a `bool` or a `str`.
- **Validate at the boundary, then trust the type** — parse into a narrow type once; don't
  re-check the same invariant downstream.
- **Immutable by default** — `frozen=True` containers; return new values instead of mutating
  in place where it's cheap.
- **Prefer comprehensions and expressions** — over manual accumulation and sentinel values,
  within the density limits in [documentation.md](documentation.md).

## Module Structure

Organize modules by **domain operation**, not by language construct. In the uv-workspace
layout (`src/<package>/src/<package>/`), a typical package:

```
mypackage/
    __init__.py         # public API re-exports (see below)
    exceptions.py       # exception hierarchy
    types.py            # frozen dataclasses, type aliases
    reader.py           # a named operation (parse / load)
    writer.py           # a named operation (serialize / save)
    validation.py       # another named operation
    wrapper.py          # lightweight class wrappers (when needed)
```

Notes on this layout:

- Name modules for the operation they perform (`reader`, `writer`, `validation`), not for
  the construct they hold. Avoid grab-bag names like `core.py`, `helpers.py`, `utils.py`,
  `common.py`, `misc.py` — [documentation.md](documentation.md#modules-and-files) covers
  this. Internal helpers live in the operation module they serve, not a shared `helpers.py`.
- `types.py` and `exceptions.py` are acceptable generic names — they're well-understood
  conventions. Core domain value types can live in `types.py` or a named `model.py`.
- Keep the public surface narrow: `__init__.py` re-exports only what callers need and
  declares `__all__`; everything else stays a private module or an underscore-prefixed name.

### One File, One Topic

A module's filename is a map. Someone scanning `ls` on a package should be able to guess
which file holds a given concern and be right — every correct guess is a file they didn't
have to open. That payoff only holds if each file has a single, nameable purpose.

Keep modules cohesive and reasonably sized: everything in a file should plausibly fit under
the file's name. The clearest signal a file has outgrown its purpose is when you reach for
*section banners* — `# ==== parsing ====`, `# ==== validation ====` comments that sort a
long file into topics. The urge to section is the urge to split: promote each section to
its own module (`parse.py`, `validation.py`) instead. Sections hide several topics behind
one filename; files surface them.

When the sections all belong to one parent concern, promote them into a **subpackage**
rather than scattering them at the top level. A `codec.py` that has grown a `# serialize`
and a `# parse` banner becomes:

```
codec/
    __init__.py       # shared types/constants + re-exports: from .serialize import serialize
    serialize.py      # the encode half
    parse.py          # the decode half
```

Callers still reach `mypackage.codec.serialize`, and `ls mypackage/codec/` now answers
"where does parsing live?" without opening a 600-line file.

Don't over-correct into fragments, though. A file per function is its own kind of noise —
`codec/serialize.py` earns its place because *serializing* is a nameable half of the codec;
a `codec/write_u16.py` would not. Split along topic seams, not arbitrarily. *Reasonable-size,
single-purpose* is the target, not *smallest possible*. This is *namespaces are one honking
great idea* from [zen.md](zen.md).

## Example: Complete Pattern

```python
# types.py
@dataclass(frozen=True, slots=True)
class Config:
    input_path: Path
    threshold: float = 0.5


@dataclass(frozen=True, slots=True)
class Result:
    values: tuple[float, ...]
    passed: bool


# processing.py (pure functions)
def validate_config(config: Config) -> None:
    if not 0 <= config.threshold <= 1:
        raise ValidationError(f"threshold must be in [0, 1], got {config.threshold}")


def process_values(values: Sequence[float], threshold: float) -> Result:
    filtered = tuple(v for v in values if v >= threshold)
    return Result(values=filtered, passed=len(filtered) > 0)


# wrapper.py (thin class)
class Processor:
    def __init__(self, config: Config) -> None:
        validate_config(config)
        self._config = config

    def run(self) -> Result:
        raw = load_values(self._config.input_path)  # I/O here
        return process_values(raw, self._config.threshold)  # logic delegated


# __init__.py (simple public API)
from .types import Config, Result
from .wrapper import Processor

__all__ = ["Config", "Processor", "Result"]
```
