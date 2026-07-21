# Tooling Style Guide

Formatters, linters, and type checkers are not optional polish — they are how this
workspace keeps the rest of these guides true without relying on reviewer vigilance. Use
them aggressively, wire them into `make` and pre-commit, and treat their output as part of
the build.

## Core Principles

1. **Automate what a guide would otherwise have to police** — every rule a tool can
   enforce is one fewer thing a human has to catch in review.
2. **No warnings left standing** — a lint hit or type error is either worth fixing or worth
   silencing explicitly, with a reason. Don't let them accumulate as background noise.
3. **The type checkers are your always-on checker — design for them** — Python's types are
   checked by `mypy`/`pyright`/`pyrefly`, not the interpreter. Lean on them by shaping types
   so invalid states don't typecheck (see [architecture.md](architecture.md#type-driven-design)).

## Package Management: `uv`

The repo is a single [uv](https://docs.astral.sh/uv/) workspace — the root `pyproject.toml`
declares `[tool.uv.workspace]` members, `.python-version` pins the interpreter (3.13), and
`uv.lock` is committed so every checkout resolves identically.

- Everything runs through `uv run` — `uv run pytest`, `uv run ruff check`, `uv run mypy`.
  Don't reach for a system `python`/`pip`; the locked environment is the source of truth.
- Sync with **`uv sync --all-extras`** — in this workspace, syncing a subset breaks other
  packages' optional deps. Always take all extras.

## Formatting: `ruff format`

Formatting is settled, not debated. `ruff format` (the successor to `black`) owns
whitespace, line breaks, and layout so that diffs are about meaning and reviews are about
substance.

- Config lives in the root `pyproject.toml` `[tool.ruff.format]` (double quotes, space
  indent, line length 88) and is the single source of truth — don't hand-format against it.
- Run `uv run ruff format` (or `make format`) before committing; `make check` runs
  `ruff format --check` and fails on drift.
- Never reformat unrelated lines in a change; let the formatter, not the author, decide
  layout so the diff stays minimal.

## Linting: `ruff check`

`ruff check` replaces the old flake8 + isort + pyupgrade + bugbear stack with one fast tool.
The root config selects a broad rule set — the notable groups:

| Group | Catches |
|-------|---------|
| `E`/`W`/`F` | pycodestyle + Pyflakes: style, unused imports, undefined names |
| `I` | import sorting (isort) |
| `B` | bugbear — common bugs and design smells |
| `UP` | pyupgrade — modern syntax for the target version |
| `SIM`, `RET`, `PIE`, `FURB`, `C4` | simplifications: flatten `if`/`else`, drop dead branches, prefer comprehensions |
| `S` | flake8-bandit security checks |
| `PERF` | performance anti-patterns |
| `TCH` | move type-only imports under `TYPE_CHECKING` |
| `PLE`/`PLC`/`PLW` | pylint errors, conventions, warnings |
| `PTH` | prefer `pathlib` over `os.path` |
| `G` | logging-format correctness (see [logging.md](logging.md)) |
| `A` | shadowing builtins |

- Run `uv run ruff check` (or `--fix` to auto-apply, `make lint`). A hit fails the build.
- **Fix, don't suppress.** A ruff hit usually points at a real simplification — the `SIM`,
  `RET`, and `FURB` groups are the flat-over-nested and self-documenting rules from
  [architecture.md](architecture.md#flat-over-nested) made mechanical.
- When a rule is genuinely wrong for a site, silence it *narrowly and with a reason*: a
  scoped `# noqa: RULE` on the one line, or a targeted `[tool.ruff.lint.per-file-ignores]`
  entry with a comment. Never blanket a whole package to dodge one line — this is the
  *practicality beats purity* exception from [zen.md](zen.md), made explicit.
- The workspace already uses `per-file-ignores` deliberately: tests re-allow `assert`
  (`S101`) and magic values (`PLR2004`); `cli.py`/`main.py` re-allow `print` (`T201`) —
  that last one is the "output belongs to the binary" rule from [logging.md](logging.md)
  turned into config.
- Add or tighten a rule when a class of mistake recurs; the rule set is itself a living
  part of the style.

## Type Checking: the always-on checker

Rust has a compiler; Python has a stack of type checkers, and this workspace runs several —
a clean pass on each is the bar:

- **`mypy`** — per package `strict = true`, with `warn_unused_ignores` and
  `warn_return_any`; third-party stubs live in `stubs/`.
- **`pyright`** — `typeCheckingMode = "standard"`; fast, and stricter than mypy on some
  inference.
- **`pyrefly`** and **`ty`** — newer, very fast checkers run as their own targets.

Why more than one? Each catches things the others miss, and they disagree at the edges of
inference — **agreement across them is strong signal** that the types are sound.
`make typecheck` runs mypy + pyright; `make pyrefly` and `make ty` are separate targets.

This is the type-design counterpart to linting aggressively. The leverage is in *what you
give the checkers to check* — see [architecture.md → Type-Driven Design](architecture.md#type-driven-design):
`NewType` over bare primitives, `Enum` over `bool`/`str` flags, frozen dataclasses whose
every value is valid. A loosely-typed program passes the checker but pushes correctness onto
runtime and reviewers; a well-typed one makes the checker reject mistakes for free.

- Design so `# type: ignore` is rarely needed. When you do use it, make it *specific*
  (`# type: ignore[arg-type]`) with a short reason — a blanket ignore hides the next bug too.
- `warn_unused_ignores` deletes the suppression for you once it stops being necessary, so
  ignores don't rot in place.

## Security and Supply Chain

Python code pulls in dependencies and touches the filesystem, so security scanning is part
of the loop (`make security`):

- **`bandit`** — static security analysis (config in `bandit.yaml`); complements ruff's `S`.
- **`pip-audit`** — flags dependencies with known CVEs.
- **`semgrep`** — pattern-based static analysis.
- **`licensecheck`** — audits dependency licenses for compatibility.

## Pre-commit

`.pre-commit-config.yaml` runs the same tools earlier: `ruff --fix`, `ruff-format`, and
per-package `mypy` on every commit. Install once with `uv run pre-commit install`; run
across everything with `uv run pre-commit run --all-files`. The hook isn't a different
standard — it's the standard loop moved left so drift never reaches a branch.

## The Standard Loop

Before considering a change done:

```bash
uv run ruff format .      # or: make format
uv run ruff check .       # or: make lint       — a hit fails the build
make typecheck            # mypy + pyright  (+ make pyrefly / make ty)
make test                 # uv run pytest      — see testing.md
```

Or just `make all` (= `lint typecheck test`). Green on all is the bar; CI enforces the same,
so running it locally just shortens the feedback loop. `make -j` runs the packages in
parallel.

## Don't

- Don't commit unformatted code, or reformat unrelated lines in a feature change.
- Don't let lint hits or type errors pile up — fix them, or silence them narrowly with a
  reason.
- Don't disable a rule workspace-wide to avoid fixing one call site.
- Don't reach for a runtime check where a type would make the bad state impossible.
