# Tooling Style Guide

Formatters, linters, and type checkers keep these guides true without relying on reviewers.
Run them strict, in `make` and pre-commit.

## Core Principles

1. **Automate what a guide would otherwise have to police.**
2. **No warnings left standing.** Fix a lint hit or type error, or silence it explicitly
   with a reason.
3. **Design for the type checkers.** Shape types so invalid states don't typecheck (see
   [architecture.md](architecture.md#type-driven-design)).

## Package Management: `uv`

The repo is a single [uv](https://docs.astral.sh/uv/) workspace. The root `pyproject.toml`
declares `[tool.uv.workspace]` members, `.python-version` pins the interpreter (3.13), and
`uv.lock` is committed so every checkout resolves identically.

- Run everything through `uv run` (`uv run pytest`, `uv run ruff check`, `uv run mypy`),
  never a system `python`/`pip`.
- Sync with **`uv sync --all-packages`** (`make sync`). Syncing one member leaves out the
  others' dependencies, and the gate runs across every package.
- **Put development tooling in a root dependency group, not a package's extras.** Extras
  are published metadata that anyone installing `fmri-qa-core` is offered. The notebook
  stack (JupyterLab, nilearn, dcm2bids) is a `notebooks` group outside the default sync
  (`make sync-notebooks`). The Sphinx stack for the docs site (`make docs`, into
  `build/site`) is a `docs` group (`make sync-docs`).

## Formatting: `ruff format`

`ruff format` (the successor to `black`) owns whitespace and layout.

- Config lives in the root `pyproject.toml` `[tool.ruff.format]` (double quotes, space
  indent, line length 88).
- Run `uv run ruff format` (or `make format`) before committing. `make check` runs
  `ruff format --check` and fails on drift.
- Don't reformat unrelated lines in a change.

## Linting: `ruff check`

`ruff check` replaces flake8, isort, pyupgrade and bugbear. The root config selects these
groups, among others:

| Group | Catches |
|-------|---------|
| `E`/`W`/`F` | pycodestyle + Pyflakes: style, unused imports, undefined names |
| `I` | import sorting (isort) |
| `B` | bugbear — common bugs and design smells |
| `UP` | pyupgrade — modern syntax for the target version |
| `SIM`, `RET`, `PIE`, `FURB`, `C4` | simplifications: flatten `if`/`else`, drop dead branches, prefer comprehensions |
| `S` | flake8-bandit security checks |
| `BLE` | blind `except` (a justified batch catch carries a scoped `noqa`) |
| `PERF` | performance anti-patterns |
| `PLE`/`PLC`/`PLW` | pylint errors, conventions, warnings |
| `PTH` | prefer `pathlib` over `os.path` |
| `G` | logging-format correctness (see [logging.md](logging.md)) |
| `A` | shadowing builtins |
| `T20` | `print` outside a binary (see [logging.md](logging.md)) |
| `RUF` | ruff's own rules, including ambiguous Unicode |
| `D` | pydocstyle, with `convention = "numpy"`: docstring structure and numpydoc section layout (see [documentation.md](documentation.md)) |

`D401` is on: a function or method summary is imperative ("Compute..."), while properties,
classes and dataclasses use noun phrases. Tests (`**/tests/**`), `stubs/**` and
`__main__.py` are exempt from `D`. `TC` (moving type-only imports under `TYPE_CHECKING`) is
left out for now, as the config notes.

- Run `uv run ruff check` (or `--fix` to auto-apply, `make lint`). A hit fails the build.
- **Fix, don't suppress.** A hit usually points at a real simplification. `SIM`, `RET`, and
  `FURB` turn the rules in [architecture.md](architecture.md#flat-over-nested) into checks.
- When a rule is wrong for a site, silence it narrowly with a reason: a scoped
  `# noqa: RULE` on the one line, or a targeted `[tool.ruff.lint.per-file-ignores]` entry
  with a comment. Never blanket a package to dodge one line.
- Current `per-file-ignores` (see `pyproject.toml`):
  - Tests re-allow `assert` (`S101`) and magic values (`PLR2004`), and skip unused
    fixture arguments (`ARG`) and docstring rules (`D`).
  - `cli.py`, the `fmri-qa-cli` sources (`packages/fmri-qa-cli/src/**`) and
    `__main__.py` re-allow `print` (`T201`), which enforces the
    "output belongs to the binary" rule from [logging.md](logging.md). `__main__.py` also
    skips `D`.
  - `packages/fmri-qa-report/**` allows the intentional typography in its text (`RUF001`).
  - `stubs/**` allows names that mirror external signatures (`A001`, `A002`) and skips `D`.
- Add or tighten a rule when a class of mistake recurs.

## Type Checking: the always-on checker

This workspace runs two type checkers. A clean pass on each is the bar:

- **`mypy`**: `strict = true` at the workspace root, with `warn_unused_ignores` and
  `warn_return_any`. Third-party stubs live in `stubs/`.
- **`pyright`**: `typeCheckingMode = "standard"`. It is fast, and stricter than mypy on some
  inference.

Each catches things the other misses, so agreement is a strong sign the types are sound.
Both read the same sources and local stubs. `make typecheck` runs mypy, `make pyright` runs
pyright, and `make all` runs both.

Give the checkers something to check (see
[architecture.md → Type-Driven Design](architecture.md#type-driven-design)): `NewType` over
bare primitives, `Enum` over `bool`/`str` flags, frozen dataclasses whose every value is
valid.

- Design so `# type: ignore` is rarely needed. When you use it, be specific
  (`# type: ignore[arg-type]`) and give a short reason.
- `warn_unused_ignores` flags a suppression once it's no longer needed.

### Local stubs for third-party types

The scientific stack (`nibabel`, `scipy`, `scikit-image`) types its public API unevenly:
some packages ship nothing, some ship stubs that are wrong or too broad for how we call
them. Work down this ladder and take the first option that fits:

1. **The library ships good types: use them.** `numpy` and `matplotlib` are here.
2. **A genuine `Optional` or error return is not a stub gap: handle it.** If a call can
   return `None`, guard it and `raise` ([exceptions.md](exceptions.md)). Don't stub the
   `None` away.
3. **A one-off narrowing of a correct-but-broad type: use a scoped `cast`.** When a shipped
   signature is accurate but wider than the form you use at one site, use
   `typing.cast(Target, expr)` with a one-line reason. Write a stub once the narrowing
   recurs.
4. **Shipped types wrong or absent for a small, well-defined surface: write a local partial
   stub** in `stubs/`. `nibabel` and `scipy.ndimage` hit this. nibabel types its image classes
   as the `FileBasedImage` base class, which lacks the NIfTI accessors `fmriqa_io.decode`
   uses (`get_fdata`, `affine`, the scaled `dataobj` proxy, the spatial header), and it
   mistypes `get_zooms`. The stub declares those, plus `from_bytes` and the `Nifti2Image`
   class `fmriqa_io.decode` constructs. `ndimage`'s transforms are overloaded so their
   returns come back as broad unions. A few lines of `.pyi` pin the forms we use, and
   unlike a `cast`, every call site is checked against them.
5. **Untyped across a large or awkward surface, or you monkeypatch its internals: treat it
   as `Any`.** In the mypy override, `follow_imports = "skip"` (plus `ignore_missing_imports`)
   renders the package as `Any`, so calls aren't flagged as untyped. `scikit-image` uses
   this, because stubbing its full surface costs more than it's worth.

Writing a local stub:

- **Both checkers read `stubs/`**: `mypy_path = "stubs"` and pyright `stubPath = "stubs"`.
  When you stub a package, drop it from the `follow_imports = "skip"` list so its calls are
  checked against your stub instead of treated as `Any`.
- **Stub only the surface you call.** Use the library's real parameter names even when they
  shadow a builtin (scipy's `input`), since callers may pass them by keyword. That is why
  `stubs/**` carries a narrow `A002` per-file-ignore.
- **Open each stub with a docstring saying why the shipped types were inadequate**, so the
  next reader knows when an upstream fix makes it deletable.
- **Prefer a narrow local stub over a broad stub dependency.** Published packages
  (`types-*`, `scipy-stubs`) suit a large surface. Don't add one to fix two return types.

## Security and Supply Chain

Security checks are part of the standard loop, not a separate audit:

- **ruff's `S` group** (flake8-bandit) runs on every `make lint`.
- **`uv.lock` is committed**, and CI syncs with `--locked`, so a dependency change shows up
  in a diff.
- **Dependency bounds are floors with a stated reason** when it isn't obvious (`cycler` is
  declared because the `Theme` builds a prop cycle directly). A ceiling always carries a
  comment saying what breaks above it.

There is no separate scanner suite (no bandit config, no `make security`). If a class of
finding recurs, add the tool and a `make` target.

## Pre-commit

`.pre-commit-config.yaml` runs `ruff check --fix`, `ruff format`, and `mypy` on every
commit. Install with `uv run pre-commit install`. Run across everything with
`uv run pre-commit run --all-files`.

**Every hook is `local` and runs through `uv run`**, so it uses the versions pinned in
`uv.lock`. A remote hook (`ruff-pre-commit`) pins its own version, which drifts from the
locked one and makes the hook and `make check` disagree about formatting. If a hook needs a
tool, add it to the dev group.

## The Standard Loop

Before considering a change done:

```bash
uv run ruff format .      # or: make format
uv run ruff check .       # or: make lint       — a hit fails the build
make typecheck            # mypy
make pyright              # pyright
make test                 # uv run pytest      — see testing.md
```

Or run `make all` (= `lint typecheck pyright test`). `make check` is the gate. It runs the
same steps with `ruff format --check` instead of a rewrite, plus a coverage floor, a `cmp`
that each package's shipped `LICENSE` matches the root one, and a `make docs` build into
`build/site`. The site's figures are rendered by running the pipeline, so a clean `-W`
build (warnings are errors) checks that the docs still describe the package. The Sphinx
stack is an opt-in group (`make sync-docs`). CI runs `make check` verbatim.

## Don't

- Don't commit unformatted code.
- Don't let lint hits or type errors pile up.
- Don't disable a rule workspace-wide to avoid fixing one call site.
- Don't use a runtime check where a type would make the bad state impossible.
