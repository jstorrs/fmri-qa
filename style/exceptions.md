# Exception Best Practices for Python Modules

This document describes how modules in this repository should handle and define exceptions.
It is the concrete expression of *errors should never pass silently* and *in the face of
ambiguity, refuse the temptation to guess* from [zen.md](zen.md): fail fast, name the bad
value, and report once at the top.

## Core Principles

1. **Define a package base exception for catchability** — one base class per package is the
   error contract; new subclasses can be added without breaking callers who catch the base
2. **Wrap external exceptions to hide implementation details**
3. **Carry structured context, not just a message** — put the bad value on the exception
4. **Fail fast with clear error messages**

## Standard Pattern

### Package Exception Hierarchy

Create `exceptions.py` with a base exception and specific subclasses:

```python
# mypackage/exceptions.py

class MyPackageError(Exception):
    """Base exception for mypackage."""
    pass


class ConfigurationError(MyPackageError):
    """Invalid or missing configuration."""
    pass


class ValidationError(MyPackageError):
    """Data validation failed."""
    pass


class ParseError(MyPackageError):
    """Failed to parse input data."""
    pass
```

### Export from Package Root

```python
# mypackage/__init__.py
from .exceptions import (
    MyPackageError,
    ConfigurationError,
    ValidationError,
    ParseError,
)
```

### Usage in Modules

```python
# mypackage/validation.py
from .exceptions import ValidationError, ParseError


def process(data: dict) -> Result:
    if "required_field" not in data:
        raise ValidationError("missing required field 'required_field'")
    # ...
```

## Rules

### Do

- Create a base exception class for each package
- Inherit custom exceptions from your base exception
- Include useful context in error messages
- Use `raise ... from e` to preserve exception chains
- Document raised exceptions in docstrings
- Validate inputs early (fail fast)
- Export exceptions from package `__init__.py`

### Don't

- Raise generic `Exception`
- Catch `Exception` or `BaseException` without re-raising
- Silence exceptions without explicit justification
- Leak implementation details through third-party exceptions
- Create custom exceptions for standard error conditions

## Wrapping External Exceptions

Hide implementation details by wrapping exceptions from dependencies:

```python
import toml
from .exceptions import ParseError


def load_config(path: str) -> dict:
    try:
        return toml.load(path)
    except toml.TomlDecodeError as e:
        raise ParseError(f"invalid config file {path}: {e}") from e
```

The `from e` clause preserves the original traceback for debugging.

## Use Standard Exceptions When Appropriate

Don't create custom exceptions for well-known error conditions:

| Condition | Use |
|-----------|-----|
| Wrong argument type | `TypeError` |
| Wrong argument value | `ValueError` |
| Missing dictionary key | `KeyError` |
| Missing attribute | `AttributeError` |
| File not found | `FileNotFoundError` |
| Permission denied | `PermissionError` |
| Not implemented | `NotImplementedError` |
| Index out of range | `IndexError` |

## Error Message Guidelines

Include enough context to diagnose the problem:

```python
# Bad - no context
raise ValueError("invalid value")

# Good - includes actual value and expectation
raise ValueError(f"expected positive integer, got {value!r}")

# Good - includes location/identifier
raise ValidationError(f"field 'age' must be positive, got {age}")
```

## Structured Payloads, Not Just Messages

A message string is enough when the caller only ever prints the error. But when a variant
carries a value a caller might want to *inspect* — a path, an offset, an out-of-range number
— put it on the exception as an attribute, not only interpolated into the message. A
stringified value reads fine in a log but throws away everything a caller could branch on.

```python
class OutOfRange(ValidationError):
    """A value fell outside its permitted range."""

    def __init__(self, field: str, value: float, low: float, high: float) -> None:
        super().__init__(f"{field} must be in [{low}, {high}], got {value}")
        self.field = field
        self.value = value
        self.low = low
        self.high = high


# A caller can recover programmatically, not just print:
try:
    validate(config)
except OutOfRange as e:
    if e.field == "threshold":
        config = replace(config, threshold=e.high)  # clamp and retry
```

Keep it proportionate — don't mint a struct-like exception for a value that is only ever
displayed:

- **A message you wrote, or one lone value being named, is fine as a plain message.**
  `raise NotFound(f"no archive at {path}")` discards nothing — there was no extra field to
  lose.
- **Reach for attributes when you have *several* distinct fields** a caller or log might use
  (`field`, `value`, `low`, `high`), or when downstream code needs to branch on the payload.
- **Wrapping a foreign exception is different — never flatten it to a string.** Preserve the
  original with `raise ... from e` (below) so the traceback and the underlying type survive.

In short: a message for what *you* wrote; attributes for what a caller might inspect; `from
e` for what a *dependency* handed you.

## Documenting Exceptions

Declare exceptions in docstrings:

```python
def connect(host: str, port: int, timeout: float = 30.0) -> Connection:
    """Connect to the server.

    Args:
        host: Server hostname.
        port: Server port.
        timeout: Connection timeout in seconds.

    Returns:
        Active connection to the server.

    Raises:
        ConnectionError: If unable to establish connection.
        TimeoutError: If connection times out.
        ValueError: If port is not in valid range.
    """
```

A documented exception is part of the contract — cover each one with a test that provokes
it, the same way you test the happy path (see [testing.md](testing.md)).

## Exception Handling Patterns

### Catch Specific Exceptions

```python
# Bad - catches too much
try:
    value = config[key]
except Exception:
    value = default

# Good - catches only expected error
try:
    value = config[key]
except KeyError:
    value = default
```

### Re-raise After Logging

Log at the point you have context, then re-raise so the error still propagates to the top
and is reported once (see [logging.md](logging.md) — libraries diagnose, the binary decides
how to present):

```python
try:
    result = risky_operation()
except OperationError:
    logger.exception("Operation failed")
    raise  # re-raises the same exception
```

### Acceptable Silencing

Only silence exceptions with explicit justification:

```python
# Acceptable - cleanup failure is not critical
try:
    temp_file.unlink()
except OSError:
    pass  # file may already be deleted

# Acceptable - optional feature
try:
    import optional_speedup
except ImportError:
    optional_speedup = None
```

## User-Facing Benefits

Users can catch errors at the granularity they need:

```python
import mypackage

# Catch specific error
try:
    mypackage.load(path)
except mypackage.ParseError:
    print("Invalid file format")

# Catch all errors from package
try:
    mypackage.process(data)
except mypackage.MyPackageError as e:
    print(f"Processing failed: {e}")
```
