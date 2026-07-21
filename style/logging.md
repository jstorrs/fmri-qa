# Logging and Output Style Guide

How packages in this repository emit user-facing output and diagnostics.

## Core Principles

1. **Libraries are silent; binaries talk** — a library returns values and raises
   exceptions, it does not print. Diagnostics are the caller's concern.
2. **Output belongs to the CLI** — only entry-point modules (`cli.py`, `main.py`) write to
   the terminal, and the tooling makes that an explicit, greppable decision.
3. **stdout is the result; stderr is everything else** — a user piping a tool into another
   must get clean stdout.
4. **Logging is for diagnostics, not results** — "what happened / what was decided / what
   failed" is logging; the actual answer the user asked for is output.

## Output: stdout vs stderr

Keep the two channels strictly separate so a CLI composes in a pipeline:

| Channel | Purpose |
|---------|---------|
| `stdout` (`print(...)`) | The user-facing result: the report, the list, the dumped data — whatever another tool might parse |
| `stderr` (`print(..., file=sys.stderr)`, or a logging handler) | Progress lines, status, prompts, and user-facing error messages |

Result data that a downstream tool might parse goes to stdout; "what happened" goes to
stderr. A `click`-based CLI uses `click.echo(...)` / `click.echo(..., err=True)` for the
same split.

## Keep `print` out of libraries

Library code returns a value or raises a descriptive exception ([exceptions.md](exceptions.md))
and lets the binary decide how to present it. To keep stray `print` debugging out of
libraries, the workspace's ruff config ([tooling.md](tooling.md)) enables `T201`
(flake8-print) and re-allows it only where output is the job:

```toml
# root pyproject.toml — [tool.ruff.lint.per-file-ignores]
"**/cli.py" = ["T201"]
"**/cli/**" = ["T201"]
"**/main.py" = ["T201"]
```

This makes "this module talks to a terminal" an explicit, greppable decision instead of a
`print` that slipped in. Errors propagate up and are reported once at the top level — the
CLI catches the package's base exception, prints `error: {e}` to stderr, and sets a
non-zero exit code, rather than scattering error prints through the call tree. See
[exceptions.md](exceptions.md) for the exception-hierarchy conventions.

## Logging with the `logging` module

Logging is for diagnostics, not results. When a package needs to surface *what it's doing*
(a `--verbose` mode, tracing why a decision was made), use the standard `logging` module —
never `print` — and follow the library/application split.

### Package `__init__.py`

Add a `NullHandler` so the library never emits "No handler found" warnings and never
configures logging on the user's behalf:

```python
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())
```

### Module files

Use a module-level logger named with `__name__`, which gives hierarchical names for free:

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
- Use lazy `%`-formatting: `logger.debug("value: %s", value)` — the args are only formatted
  if the level is enabled
- Use appropriate log levels (see below)
- Document logger names if users need to configure them

### Don't

- Call `logging.basicConfig()` in library code — that's the application's job
- Add handlers (`StreamHandler`, `FileHandler`, …) in library code
- Set log levels on your loggers — let the application control verbosity
- Use f-strings or `.format()` in log calls — they defeat lazy evaluation (the ruff `G`
  rules flag logging-format issues)
- `print` from a library — return a value or raise a descriptive exception
- Include sensitive payloads (credentials, PHI/PII, raw file contents) in output or logs by
  default — assume logs get shipped somewhere and retained

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

The application — not the library — configures handlers and levels, in exactly one place
(the CLI entry point):

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

This works with the standard library and integrates with structured-logging backends like
`structlog` if the application chooses to install one — the choice stays with the
application, per the same principle above.
