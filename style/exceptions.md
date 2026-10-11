# Exception Best Practices for Python Modules

How modules in this repository define and handle exceptions. Fail fast, name the bad value,
and report once at the top ([zen.md](zen.md): *errors should never pass silently*).

## Core Principles

1. **Define a package base exception.** One base class per package is the error contract.
   You can add subclasses without breaking callers who catch the base.
2. **Wrap external exceptions to hide implementation details.**
3. **Carry structured context, not just a message.** Put the bad value on the exception.
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

When a caller might inspect a value (a path, an offset, an out-of-range number), also put
it on the exception as an attribute. A caller can't branch on a value buried in a message.

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

- **A plain message is fine** for a message you wrote or one named value:
  `raise NotFound(f"no archive at {path}")`.
- **Use attributes** for several distinct fields (`field`, `value`, `low`, `high`) or when
  downstream code branches on the payload.
- **Never flatten a foreign exception to a string.** Use `raise ... from e` so the
  traceback and underlying type survive.

## Documenting Exceptions

Declare exceptions in docstrings:

```python
def connect(host: str, port: int, timeout: float = 30.0) -> Connection:
    """Connect to the server.

    Parameters
    ----------
    host : str
        Server hostname.
    port : int
        Server port.
    timeout : float, optional
        Connection timeout in seconds. Default is 30.0.

    Returns
    -------
    Connection
        Active connection to the server.

    Raises
    ------
    ConnectionError
        If unable to establish a connection.
    TimeoutError
        If the connection times out.
    ValueError
        If `port` is not in the valid range.
    """
```

A documented exception is part of the contract. Test each one with a case that provokes it
(see [testing.md](testing.md)).

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

Log where you have context, then re-raise so the error still reaches the top and is reported
once (see [logging.md](logging.md): libraries diagnose, the binary decides how to present):

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
