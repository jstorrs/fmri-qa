# Style Guides

Conventions for Python packages in this repository. Many of these rules are enforced by the
workspace tooling (`ruff`, `mypy`/`pyright`, `pytest` — see
[tooling.md](tooling.md)); the guides explain the *why* behind them.

**Start with [zen.md](zen.md).** It is the index of principles these guides descend from —
the Zen of Python (PEP 20) made concrete for this repo. The other seven are detailed
expressions of those principles; read them when you need the specifics.

## The guides

| Guide | Covers |
|-------|--------|
| [zen.md](zen.md) | The guiding principles (the Zen of Python), mapped to where each is detailed and enforced. Read first. |
| [architecture.md](architecture.md) | Functional core / imperative shell, short functions, flat-over-nested control flow, simple public APIs, type-driven design, module layout. |
| [documentation.md](documentation.md) | Naming, docstrings (contract, not implementation), comments that explain *why*, the coherence test between code and docs. |
| [exceptions.md](exceptions.md) | Per-package exception hierarchies, wrapping foreign errors, structured payloads, when to use stdlib exceptions, when to raise vs. silence. |
| [logging.md](logging.md) | Libraries stay silent and return values; binaries talk. stdout-vs-stderr discipline, keeping `print` out of libraries, and the `logging` module conventions. |
| [tooling.md](tooling.md) | `uv`, `ruff` format/lint, the `mypy`/`pyright` type checkers, local stubs for third-party types, `pytest`, supply-chain posture, pre-commit, and the standard `make` loop. |
| [stability.md](stability.md) | Code is cheap, data is precious: refactor internal APIs freely; treat on-disk formats, CLI flags, and output as interfaces. |
| [testing.md](testing.md) | Test the pure core with values and the shell with I/O; assert behavior not implementation; round-trips, property tests, and error cases; deterministic tests. |

## Living documents

These guides describe current preference, not settled law. If a rule here produces awkward
code, seems wrong for a case in front of you, or pulls against another principle in an
interesting way — **surface it** rather than silently complying or silently ignoring it. A
good counterexample is how a guide earns its next revision. [zen.md](zen.md) already handles
ordinary tension between principles (*practicality beats purity*); the conflicts worth
raising are the ones those tie-breakers don't cleanly resolve.

## In short

- **Libraries are silent and return values; binaries talk and decide.**
- **Explicit over implicit** — in APIs, errors, and output; type your public surface.
- **Let the tools and the type checkers enforce the rules** — `ruff` and
  `mypy`/`pyright` run aggressively; design types so illegal states can't be
  constructed.
- **Errors never pass silently** — fail fast, name the bad value, report once at the top.
- **If it's hard to explain, the code (not the doc) needs work.**
- **Be bold with code, careful with anything a user has on disk or in a script.**
- **Test behavior, not implementation** — the pure core makes this cheap; keep tests
  deterministic.
