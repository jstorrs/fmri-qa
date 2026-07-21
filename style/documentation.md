# Documentation and Naming Style Guide

This document describes the philosophy for documentation and naming in this repository. The core idea: **code and documentation should tell the same story**. It is the concrete expression of *readability counts* and *if the implementation is hard to explain, it's a bad idea* from [zen.md](zen.md).

## Core Principles

1. **Names should align with documentation** - Reading a function name and reading its docstring should produce the same mental model
2. **Code should be self-documenting** - Good names and structure reduce the need for explanation
3. **Docstrings describe the contract** - What the function does, not how
4. **Comments explain why** - Non-obvious context, constraints, and decisions
5. **Tension is a design signal** - Difficulty documenting indicates design problems

## The Coherence Test

Good code passes this test:

> Can someone read just the function signature and docstring, then read just the implementation, and arrive at the same mental model from both?

If not, either the names/structure don't match the abstraction, or the abstraction itself needs work.

## Tension as a Design Signal

| Symptom | Diagnosis |
|---------|-----------|
| Hard to write a clear docstring | Logic is too complex or conflated |
| Code unclear after reading docstring | Names/structure don't match the abstraction |
| Docstring just repeats the code | Good - code is self-documenting |
| Docstring reveals surprising behavior | API design needs work |
| Need to cross-reference docstring to understand code | Poor naming or structure |

When documentation is difficult to write, **fix the code first**.

## Naming Guidelines

### Functions

Names should describe what the function does, making the docstring almost redundant:

```python
# Good - name tells you what it does
def calculate_mean(values: Sequence[float]) -> float:
    """Calculate the arithmetic mean of values."""
    ...


def load_study_from_dicom(path: Path) -> Study:
    """Load a Study from a DICOM file."""
    ...


# Bad - name doesn't convey meaning
def process(data):
    """Calculate statistics and validate ranges."""
    ...


def do_stuff(x):
    """Load, parse, and transform the input."""
    ...
```

### Variables

Names should reflect what the value represents:

```python
# Good - names describe the data
mean_signal = calculate_mean(signal_values)
slice_count = len(slices)
is_valid = all(check_constraints(item) for item in items)

# Bad - generic or abbreviated names
x = calculate_mean(vals)
n = len(slices)
flag = all(check_constraints(i) for i in items)
```

### Booleans

Use positive names that read naturally in conditions:

```python
# Good
is_valid = ...
has_errors = ...
should_retry = ...

if is_valid:
    ...

# Avoid double negatives
if not is_invalid:  # confusing
    ...
```

### Types

- **Nouns for data and value types**: `Study`, `Archive`, `Measurement`, `IndexEntry`
- **Nouns/verbs for processors and wrappers**: `Reader`, `Writer`, `Validator`, `Processor`
- **`Error` suffix for exceptions**: `ParseError`, `ValidationError` (see [exceptions.md](exceptions.md))
- **Enums name a closed set**: `Mode`, `Disposition` — prefer these to `bool`/`str`
  parameters ([architecture.md](architecture.md#type-driven-design))

### Modules and Files

File and directory names should be self-explanatory. Running `ls` or `tree` should answer questions, not reveal mysteries.

```
# Good - structure tells you what's here
mypackage/
    __init__.py
    reader.py
    writer.py
    validation.py
    exceptions.py
    types.py

# Bad - requires investigation to understand
mypackage/
    __init__.py
    core.py        # what's "core"?
    utils.py       # grab-bag of everything
    helpers.py     # how is this different from utils?
    misc.py        # mystery box
    v2.py          # version of what?
```

#### Guidelines

- **Use nouns for data/types**: `types.py`, `models.py`, `schema.py`
- **Use verbs/actions for operations**: `reader.py`, `writer.py`, `parser.py`, `validator.py`
- **Be specific**: `dicom_reader.py` over `reader.py` if multiple readers exist
- **Avoid generic names**: `utils.py`, `helpers.py`, `common.py`, `misc.py`
- **Group by domain, not by type**: `authentication/` not `classes/`

#### The `ls` Test

Ask yourself: if someone runs `ls` on this directory, will they understand what's here?

```
# Passes the ls test - clear purpose for each file
$ ls src/dcmdb/src/dcmdb/
__init__.py  archive.py  exceptions.py  index.py  reader.py  writer.py

# Fails the ls test - requires reading code to understand
$ ls src/mypackage/
__init__.py  base.py  core.py  impl.py  main.py  utils.py
```

#### When Generic Names Are Acceptable

- `types.py` - for type definitions and dataclasses (well-understood convention)
- `exceptions.py` - for exception hierarchy (well-understood convention)
- `constants.py` - for module-level constants
- `cli.py` - for command-line interface entry point

## Docstring Guidelines

### Purpose

Docstrings document the **contract** - what the function does from the caller's perspective:

- What it accepts
- What it returns
- What exceptions it raises
- Any important constraints or preconditions

Docstrings should **not** explain implementation details.

### When Docstrings Add Value

```python
def connect(
    host: str,
    port: int = 5432,
    timeout: float = 30.0,
    retry_count: int = 3,
) -> Connection:
    """Connect to the database server.

    Attempts to establish a connection, retrying on transient failures.
    The connection is not thread-safe; use a connection pool for
    concurrent access.

    Args:
        host: Database server hostname.
        port: Server port.
        timeout: Connection timeout in seconds.
        retry_count: Number of retry attempts on transient failures.

    Returns:
        An active database connection.

    Raises:
        ConnectionError: If all connection attempts fail.
        ValueError: If timeout is not positive.
    """
```

The docstring adds value by explaining:
- Retry behavior (not obvious from signature)
- Thread-safety constraint (important context)
- What "transient failures" means for retries

### When Docstrings Can Be Minimal

```python
def calculate_mean(values: Sequence[float]) -> float:
    """Calculate the arithmetic mean of values."""
    return sum(values) / len(values)
```

The function is simple, the name is clear, the types are explicit. A longer docstring would just repeat what's obvious.

## Comment Guidelines

### Comments Explain "Why"

Use inline comments for:
- Non-obvious constraints or requirements
- Broader context that affects the code
- Historical reasons for unusual choices
- Performance considerations
- Edge cases being handled

```python
def process_slices(slices: list[Slice]) -> list[Slice]:
    # Sort by instance number to ensure consistent ordering across
    # different DICOM sources (some vendors use acquisition time instead)
    sorted_slices = sorted(slices, key=lambda s: s.instance_number)

    # Skip first slice - often contains calibration data on Siemens scanners
    return sorted_slices[1:]
```

### Comments Should Not Explain "What"

```python
# Bad - explains what (obvious from code)
# Increment counter by one
counter += 1

# Calculate the sum of values
total = sum(values)

# Check if list is empty
if not items:
    return None


# Good - explains why (not obvious from code)
# Use multiplication instead of math.pow for 2x speedup in tight loop
result = value * value

# Threshold from ISO 14971 Table D.4
risk_threshold = 0.001
```

### TODO Comments

Use TODO comments for known issues or future work:

```python
# TODO: Replace with proper retry logic once circuit breaker is implemented
for _ in range(3):
    try:
        return fetch(url)
    except TimeoutError:
        pass
```

## Self-Documenting Code Techniques

### Extract Well-Named Functions

```python
# Before - needs comment to explain
# Check if study is valid for processing
if study.slice_count > 0 and study.modality in SUPPORTED and not study.is_localizer:
    process(study)

# After - self-documenting
if is_processable(study):
    process(study)


def is_processable(study: Study) -> bool:
    """Check if study meets criteria for processing."""
    return (
        study.slice_count > 0
        and study.modality in SUPPORTED_MODALITIES
        and not study.is_localizer
    )
```

### Use Named Constants

```python
# Before - magic number
if retries > 3:
    raise TooManyRetriesError()

# After - self-documenting
MAX_RETRY_ATTEMPTS = 3

if retries > MAX_RETRY_ATTEMPTS:
    raise TooManyRetriesError()
```

### Use Intermediate Variables

```python
# Before - dense and hard to follow
return [s for s in studies if s.date >= cutoff and s.modality == "MR" and s.complete]

# After - clear intent at each step
recent_studies = [s for s in studies if s.date >= cutoff]
mr_studies = [s for s in recent_studies if s.modality == "MR"]
complete_studies = [s for s in mr_studies if s.complete]
return complete_studies
```

## Summary

The goal is **coherence** between code and documentation:

- Names should make docstrings feel almost redundant
- Docstrings describe contracts, not implementations
- Comments explain why, not what
- If documentation is hard to write, the code needs work
- If code is hard to understand after reading docs, the code needs work

Good documentation doesn't compensate for unclear code - it complements clear code.
