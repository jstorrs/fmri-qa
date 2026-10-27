# Logging and Output Style Guide

How packages in this repository emit user-facing output and diagnostics.

## Core Principles

1. **Libraries are silent; binaries talk.** A library returns values and raises
   exceptions. It does not print.
2. **Output belongs to the CLI.** Only entry-point modules (`cli.py`, `main.py`) write to
   the terminal.
3. **stdout is the result; stderr is everything else.** Piped output must be clean.
4. **Logging is for diagnostics, not results.** What happened, what was decided, and what
   failed is logging. The answer the user asked for is output.

## Output: stdout vs stderr

| Channel | Purpose |
|---------|---------|
| `stdout` (`print(...)`) | The user-facing result: the report, the list, the dumped data — whatever another tool might parse |
| `stderr` (`print(..., file=sys.stderr)`, or a logging handler) | Progress lines, status, prompts, and user-facing error messages |

A `click`-based CLI uses `click.echo(...)` / `click.echo(..., err=True)` for the same
split.

## Keep `print` out of libraries

Library code returns a value or raises a descriptive exception ([exceptions.md](exceptions.md))
and lets the binary decide how to present it. Ruff's `T201` (flake8-print, see
[tooling.md](tooling.md)) enforces this, and per-file-ignores re-allow `print` where output
is the job:

```toml
# root pyproject.toml — [tool.ruff.lint.per-file-ignores]
"**/cli.py" = ["T201"]
"packages/fmri-qa-cli/src/**" = ["T201"]
```

Errors propagate up and are reported once at the top. The CLI catches the package's base
exception, prints `error: {e}` to stderr, and sets a non-zero exit code. See
[exceptions.md](exceptions.md).

## Logging with the `logging` module

To show what a package is doing (a `--verbose` mode, tracing a decision), use the standard
`logging` module, never `print`.

### Package `__init__.py`

Add a `NullHandler` so the library never warns "No handler found" or configures logging for
the user:

```python
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())
```

### Module files

Use a module-level logger named with `__name__`. This gives hierarchical names for free:

```python
import logging

logger = logging.getLogger(__name__)


def process(data: Sequence[Record]) -> Report:
    logger.debug("processing %d records", len(data))
    ...
    logger.info("processing complete")
```

## Rules

### Do

- Use `logging.getLogger(__name__)` for hierarchical names
- Add `NullHandler` in the package `__init__.py`
- Use lazy `%`-formatting: `logger.debug("value: %s", value)`. The args are formatted only
  if the level is enabled
- Use appropriate log levels (see below)
- Document logger names if users need to configure them

### Don't

- Call `logging.basicConfig()` in library code. That's the application's job
- Add handlers (`StreamHandler`, `FileHandler`, …) in library code
- Set log levels on your loggers. Let the application control verbosity
- Use f-strings or `.format()` in log calls. They defeat lazy evaluation (the ruff `G`
  rules flag these)
- `print` from a library. Return a value or raise a descriptive exception
- Include sensitive payloads (credentials, PHI/PII, raw file contents) in output or logs by
  default. Assume logs get shipped somewhere and retained

## Log Levels

| Level | Use for |
|-------|---------|
| `DEBUG` | Detailed diagnostic information for investigating an issue |
| `INFO` | Major lifecycle events; confirmation things are working |
| `WARNING` | Something unexpected happened, but the operation continues |
| `ERROR` | A function failed to complete its task |
| `EXCEPTION` | Same as `ERROR` but includes the traceback — use inside an `except` block |

## Examples

### Good

```python
logger.debug("processing file %s", filepath)
logger.info("loaded %d records", count)
logger.warning("config file not found, using defaults")
logger.error("failed to connect to %s", host)

try:
    risky_operation()
except OperationError:
    logger.exception("operation failed")  # includes traceback
    raise
```

### Bad

```python
# Eager string formatting - always evaluates, even when DEBUG is off
logger.debug(f"processing file {filepath}")
logger.debug("processing file {}".format(filepath))

# Configuring handlers in a library - clobbers the application's setup
logging.basicConfig(level=logging.DEBUG)
logger.addHandler(logging.StreamHandler())
```

## Application Configuration

The application, not the library, configures handlers and levels. It does so in one place,
the CLI entry point:

```python
import logging

# See all debug messages from a specific module
logging.getLogger("mypackage.reader").setLevel(logging.DEBUG)

# Silence a noisy dependency
logging.getLogger("chatty_dependency").setLevel(logging.WARNING)
```

## Structured Logging

For complex diagnostic data, pass fields via `extra` rather than interpolating them into
the message:

```python
logger.info(
    "request processed",
    extra={"user_id": uid, "duration_ms": elapsed, "status": status},
)
```

This works with the standard library and with structured-logging backends like `structlog`.
The application chooses whether to install one.
