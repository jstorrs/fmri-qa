# Architecture Style Guide

The architectural style for modules in this repository: **Functional Core, Imperative Shell** with value objects and facade-style public APIs ([zen.md](zen.md): *simple*, *flat*, *explicit*).

## Core Principles

1. **Pure functions for logic** - Business logic lives in functions without side effects
2. **Lightweight classes as wrappers** - Classes provide ergonomic interfaces, not logic
3. **Short functions with helpers** - Extract helpers liberally to keep functions focused
4. **Flat over nested** - Guard clauses and early returns over nested `if`/`else`
5. **Simple public interfaces** - External API should be minimal and intuitive
6. **Type-driven design** - Encode invariants in types so illegal states are hard to build. The type checkers ([tooling.md](tooling.md)) enforce them

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
    return Statistics(mean=mean, std_dev=variance**0.5)


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

- If a block needs a comment to explain it, extract it
- If a function exceeds ~20 lines, look for something to extract
- Helpers are internal, so complex signatures are fine
- Name helpers for what they do, not how

## Flat Over Nested

Nested `if`/`else` blocks bury the main path. Handle exceptional cases first and return
early, so the happy path stays at the left margin.

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

- **Guard clauses.** Validate preconditions and `raise`/`return` up front.
- **Early returns.** Return as soon as the answer is known. The `RET` ruff rules
  ([tooling.md](tooling.md)) flag a superfluous `else` after a `return`.
- **`continue` in loops.** Skip the uninteresting iteration instead of indenting the body.
- **Extract a helper** when you need nesting. A named function flattens the caller.

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
) -> SegmentInfo: ...
```

### API Design Guidelines

- Fewer parameters is better for public functions
- Use sensible defaults
- Accept flexible input types (`str | Path`, `Iterable` vs `list`)
- Return concrete types
- Hide implementation details behind simple interfaces

## Frozen Dataclasses as Containers

Frozen dataclasses are the workhorse of [type-driven design](#type-driven-design). Use them
for data containers:

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

Design types so a mistake fails type-checking (mypy, pyright; see
[tooling.md](tooling.md)) instead of surfacing as a runtime bug. A state the types forbid
is a bug that can't be written.

### Make illegal states unrepresentable

Prefer a type whose every value is valid over a loose type plus runtime checks.

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

Validate once at the boundary and return a narrower type that proves the check happened.
Don't re-check a wide type downstream. A frozen dataclass with a validating `__post_init__`
(or a classmethod constructor) is the natural home for this. Once you hold the value, the
question is settled.

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
`NewType` costs nothing. It stops you passing a user id where a byte offset is expected:

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

When a fixed set of string values is the interface (JSON tags, CLI choices), use
`Literal["read", "write"]`. Put `typing.assert_never` in the final `else` of a `match`, so
an unhandled new case is a type error.

### Distinct types for distinct lifecycle states

Give each stage of a value's lifecycle its own type, so using it in the wrong state is a
type error. The classic case is untrusted versus trusted data: the only way to get the
trusted type is through the function that earns it.

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

Start with the two-type gate. Model a multi-state machine as separate types only when a
value has several stages with stage-specific operations.

### Guidelines

- **Immutable by default.** Use `frozen=True` containers and return new values where it's
  cheap.
- **Prefer comprehensions and expressions** over manual accumulation and sentinel values,
  within the density limits in [documentation.md](documentation.md).

## Module Structure

Organize modules by **domain operation**, not by language construct. In the uv-workspace
layout (`packages/<distribution>/src/<package>/`), a typical package:

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
  `common.py` and `misc.py`
  ([documentation.md](documentation.md#modules-and-files)). Internal helpers live in the
  operation module they serve.
- `types.py` and `exceptions.py` are acceptable generic names. They are well-understood
  conventions. Core domain value types can live in `types.py` or a named `model.py`.
- Keep the public surface narrow. `__init__.py` re-exports only what callers need and
  declares `__all__`. Everything else stays a private module or an underscore-prefixed name.

### One File, One Topic

A filename is a map: `ls` on a package should let you guess which file holds a concern.
Keep modules cohesive and reasonably sized: everything in a file should fit under its name. If you reach for *section banners* such as
`# ==== parsing ====`, split instead and promote each section to its own module
(`parse.py`, `validation.py`). When the sections share a parent concern, make them a
**subpackage**. A `codec.py` with a `# serialize` and a `# parse` banner becomes:

```
codec/
    __init__.py       # shared types/constants + re-exports: from .serialize import serialize
    serialize.py      # the encode half
    parse.py          # the decode half
```

Callers still reach `mypackage.codec.serialize`, and `ls mypackage/codec/` now answers
"where does parsing live?" without opening a 600-line file.

Don't over-split. `codec/serialize.py` earns its place because serializing is a nameable
half of the codec. A `codec/write_u16.py` would not. Split along topic seams.

### Layered Subpackages

Once a package grows past a handful of operation modules, group them into subpackages by
**domain layer**: a stage in the data's life (load, prepare, compute, aggregate, present).
This is the one-topic rule a level up. The shape `fmriqa` uses:

```
fmriqa/
    types.py            # shared vocabulary: array dtypes + closed-set Literals
    exceptions.py       # the package exception hierarchy
    load/               # value objects: QAScan and ScanMeta, plus the pure sidecar rules (no file IO)
    prep/               # preprocessing: raw-array ops -> the analysis images
    metrics/            # the domain operations, one family per module
    pipeline.py         # aggregation: orchestrate the operations + the combined result
    analysis/           # publication: the artifact and its schema (compose, decompose, migrate)
```

`fmriqa` is pure: it reads no files and runs under Pyodide. The file boundary is a
separate distribution, `fmri-qa-io` (`fmriqa_io`), which turns a file or bytes into
`load/`'s value objects and an artifact into a `.qa.nc` file. The imperative shell is
`fmri-qa-cli` (`fmriqa_cli`): one module per command, plus its output forms. Presentation is
`fmri-qa-report`, on top of `analysis/`. See
[Split the Product at Its Widest Seam](#split-the-product-at-its-widest-seam) below.

Three rules keep the layering clean:

- **Dependencies point down the stack.** `load < prep < metrics < pipeline < analysis`. A lower
  layer never imports a higher one. A leaf module (e.g. pure raw-array transforms) imports
  nothing but the shared vocabulary. If you want an upward import, the thing you want is
  usually in the wrong layer. Where a real domain dependency crosses layers (a loader
  needing a compute-layer estimate as a last-resort fallback), make it a single, documented
  edge.
- **Value objects live with the operation that produces them.** This is the domain-operation
  rule applied to types. Each `metrics/` module owns its result dataclass and the constants
  that tune it. The aggregator owns the combined result. A top-level `types.py` holding
  every dataclass is organized by language construct, which "organize by domain operation"
  warns against. Reserve `types.py` for the shared vocabulary every layer speaks (array
  aliases, option `Literal`s), the definitions that would otherwise force an arbitrary
  cross-module import.
- **Keep tuning constants next to the code they tune.** A knob used by one operation lives in
  that operation's module. Only cross-cutting vocabulary stays central. `grep` finds a
  scattered constant instantly. A central list of every knob is a grab-bag sorted by
  being-a-constant.

### Split the Product at Its Widest Seam

When two stages differ in almost everything (dependencies, speed, what changes them, who
deploys them), make the boundary a **package boundary**: separate distributions,
installable apart. In this repo the first seam is calculation versus presentation.
Computing needs numpy and scipy, and changes when the physics changes. Drawing needs
matplotlib, and changes when someone wants a different report. Only a result passes
between them.

The second seam is calculation versus IO. Reading a file, writing netCDF-4 and running
dcm2niix need a filesystem, a native library or a subprocess. The calculation needs none
of them, and a browser has none of them: the motivation is a single offline HTML page that
runs the pipeline under Pyodide. So core takes arrays and value objects (a `QAScan`) and returns values, and io decodes
bytes and files into them, and
every file touch lives in `fmri-qa-io`. Report is on the pure side too: an artifact
in memory in, an HTML string out, so it depends on core and matplotlib and never on io.
The commands are their own distribution too, so that core, io and report stay libraries
with no entry points. The applications (cli, launcher) load the artifact and write the page.

```
packages/
    fmri-qa-core/       # fmriqa          -- metrics, pipeline, and the artifact; reads no files
    fmri-qa-io/         # fmriqa_io       -- scans, the .qa.nc file, DICOM import; the file boundary
    fmri-qa-cli/        # fmriqa_cli      -- fmri-qa, fmri-qa-hilo, fmri-qa-import, fmri-qa-report
    fmri-qa-report/     # fmriqa_report   -- plots and an HTML report, from an artifact
    fmri-qa-launcher/   # fmriqa_launcher -- the application shell over the four above
    fmri-qa-web/        # fmriqa_web      -- private: the browser page's Python glue; bytes in, values out
```

Four rules make such a split hold:

- **One value object crosses, and it is complete.** Define the seam as a single published
  type (here `QAArtifact`). Resolve everything a consumer could need while producing it:
  derived properties settled into fields, curves extracted, masks and outlines
  materialized. If the consuming side has to compute something, the seam type has a gap.
  Don't reach back across. Nothing heavy or private crosses: the raw series stays behind.
- **Make the seam serializable, then use the serialized form.** If you can write the
  boundary to disk and read it back, you have proved it is complete. It also lets you render
  later, elsewhere, without the inputs. Version the layout and refuse an unknown version by
  name. Test that a round-tripped value behaves identically to a live one.
- **Keep the pure side pure, and mark the native side.** A package that must run in a
  browser declares only dependencies that have a browser build. Anything native goes in
  the IO package, with a `sys_platform != 'emscripten'` marker so a browser install skips
  it. Test it: an isolation test fails on any forbidden import in the pure side's sources,
  imports every module in a fresh interpreter, and checks the declared requirements, and a
  packaging test evaluates the markers. The browser-safe parts of the IO package
  are `fmriqa_io.decode` and `fmriqa_io.convert.filing` (file naming, with no
  filesystem); each is held to an import allowlist by its own isolation test,
  `tests/test_decode_isolation.py` and `tests/test_filing_isolation.py`.
- **Enforce the direction mechanically.** A rule like "the report half must not import the
  pipeline" erodes one convenient import at a time. Make it a test: parse the consuming
  package's sources and fail on any import outside the allowlist. Check the packaging claim
  too (install the lower wheel alone and assert the upper stack is absent).

Don't split on a narrow seam. Two distributions cost two release trains and a version
constraint between them. Don't pay that to separate modules that are always installed
together. See `notes/analysis_report_split.md` for the calculation/presentation split's
full rationale, and `notes/pyodide-spike/README.md` for the browser motivation.

### Separate Content from Format

In the presentation package, keep what a report says apart from how a format renders it.
The content (numbers, strings, and figures from an artifact) doesn't depend on the output
format. A per-format **driver** composes it into a document.

```
fmriqa_report/
    summary.py          # format-agnostic text/tiles from an artifact
    panels/             # format-agnostic figures from an artifact
    formats/
        html/           # one driver: composes summary + panels into one page
        # contact_sheet.py, ...  # a second format reuses summary + panels unchanged
```

A new format is a new entry in `formats/`, not an edit to every figure-building function.
A driver that outgrows one file becomes a subpackage. The HTML driver holds `figures`
(rendering each panel to a standalone SVG), `resources` (the packaged template and
stylesheet), and `run` (composing them into one page).

## The Web Page

The browser page is the same split, with the shell in TypeScript and the core in Python. It ships as one offline file, `web/dist/fmri-qa.html` ([web/README.md](../web/README.md)).

- **`web/`** is the Vite + TypeScript app. `src/core/` holds pure functions over plain data (naming, ZIP layout, dcm2niix arguments, DICOM headers); `src/shell/` does the IO: the DOM, files, downloads and the workers.
- **`fmriqa_web`** (`packages/fmri-qa-web`) is the Python glue. Its functions take bytes and return strings and bytes, with no file and no process, so they run under Pyodide, and the page calls them through one JSON bridge.
- **Two workers**, so a crash in one cannot take the other down: Pyodide, which runs `fmriqa_web`, and dcm2niix in WebAssembly, started per series and terminated afterwards.

What the page assumes about Python is committed, and a test fails when the two drift:

| Check | Guards | Lives in |
|---|---|---|
| `web/src/generated/contract.json` | the dcm2niix flags and schema versions the app reads, as `fmriqa_web.contract()` returns them (regenerate with `scripts/web_contract.py`) | `packages/fmri-qa-web/tests/test_contract.py` |
| `web/test/fixtures/expected.json` | native dcm2niix and fmri-qa results for the fixtures, which the e2e tests compare the page against (`scripts/web_expected.py`) | `packages/fmri-qa-web/tests/test_expected.py` |
| `web/THIRD_PARTY_NOTICES.md` | the licence of everything the page bundles (`scripts/web_notices.py`) | `packages/fmri-qa-web/tests/test_notices.py`, and `--check` in `vite build` |

`test_notices.py` skips without `web/vendor` and `web/node_modules`, so CI's `web` job runs it after `make web`. The size budget is checked by `web/scripts/size-check.mjs` in `npm run build`.

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
