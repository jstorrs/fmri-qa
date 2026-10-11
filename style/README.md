# Style Guides

Conventions for Python packages in this repository. The workspace tooling (`ruff`,
`mypy`/`pyright`, `pytest`; see [tooling.md](tooling.md)) enforces many of them.

**Start with [zen.md](zen.md).** It maps the Zen of Python (PEP 20) to the other seven
guides.

## The guides

| Guide | Covers |
|-------|--------|
| [zen.md](zen.md) | The guiding principles (the Zen of Python), mapped to where each is detailed and enforced. Read first. |
| [architecture.md](architecture.md) | Functional core / imperative shell, short functions, flat-over-nested control flow, simple public APIs, type-driven design, module layout. |
| [documentation.md](documentation.md) | Naming, numpydoc docstrings (contract, not implementation), API tiers, comments that explain *why*, the coherence test between code and docs. |
| [exceptions.md](exceptions.md) | Per-package exception hierarchies, wrapping foreign errors, structured payloads, when to use stdlib exceptions, when to raise vs. silence. |
| [logging.md](logging.md) | Libraries stay silent and return values; binaries talk. stdout-vs-stderr discipline, keeping `print` out of libraries, and the `logging` module conventions. |
| [tooling.md](tooling.md) | `uv`, `ruff` format/lint, the `mypy`/`pyright` type checkers, local stubs for third-party types, `pytest`, supply-chain posture, pre-commit, and the standard `make` loop. |
| [stability.md](stability.md) | Code is cheap, data is precious: refactor internal APIs freely; treat on-disk formats, CLI flags, and output as interfaces. |
| [testing.md](testing.md) | Test the pure core with values and the shell with I/O; assert behavior not implementation; round-trips, property tests, and error cases; deterministic tests. |

## Living documents

These guides describe current preference, not settled law. If a rule produces awkward code
or conflicts with another principle, **say so**. Don't quietly comply or ignore it. A good
counterexample is how a guide gets revised. [zen.md](zen.md) covers ordinary tension
between principles. Raise the conflicts it doesn't resolve.

## In short

- **Libraries are silent and return values; binaries talk and decide.**
- **Explicit over implicit** in APIs, errors, and output. Type your public surface.
- **Let the tools and type checkers enforce the rules.** `ruff` and `mypy`/`pyright` run
  strict. Design types so illegal states can't be constructed.
- **Errors never pass silently.** Fail fast, name the bad value, report once at the top.
- **If it's hard to explain, fix the code, not the doc.**
- **Be bold with code, careful with anything a user has on disk or in a script.**
- **Test behavior, not implementation.** The pure core makes this cheap. Keep tests
  deterministic.
