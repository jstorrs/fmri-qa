# The Zen of This Repository

These guides apply the **Zen of Python** (`import this`, PEP 20) to this repository. This
file maps each aphorism to the guide and tooling behind it.

When two principles conflict, the later aphorisms break the tie: *practicality beats
purity*, and *if the implementation is hard to explain, it's a bad idea*.

---

## Beautiful is better than ugly. Readability counts.

Code is read far more than it is written. Optimize for the reader with clear names, short
functions, and obvious control flow.
→ [documentation.md](documentation.md), [architecture.md](architecture.md)

## Explicit is better than implicit.

State intent in the types and the API, not in the reader's head.

- Default to a leading-underscore `_private` name and publish the surface with `__all__`.
- Don't catch with a bare `except Exception`, and don't use stringly-typed errors. Raise
  a named subclass of your package's base exception.
- Use positive boolean names (`is_valid`, not `not is_invalid`).
- Type your public API and let mypy/pyright check it.

→ [architecture.md](architecture.md), [exceptions.md](exceptions.md), [logging.md](logging.md), [tooling.md](tooling.md)

## Simple is better than complex. Complex is better than complicated.

Organize necessary complexity instead of tangling it. In the *functional core, imperative
shell* split, I/O lives at the edge in thin class wrappers and the pure core is testable
with plain values. → [architecture.md](architecture.md), [testing.md](testing.md)

## Flat is better than nested.

Handle exceptional cases first with guard clauses and early returns, so the happy path
stays at the left margin. The `RET` ruff rules push the same way. → [architecture.md](architecture.md#flat-over-nested)

## Sparse is better than dense.

Named intermediate bindings beat one dense comprehension chain. `ruff format` owns
whitespace. → [documentation.md](documentation.md), [tooling.md](tooling.md)

## Special cases aren't special enough to break the rules. Although practicality beats purity.

When you need an exception, make it narrow, explicit, and documented. Don't relax the rule
everywhere. Examples:

- A blanket `except`, `# type: ignore`, or `# noqa` is denied by default. Allow it at the
  one site that needs it, with a specific rule code and a reason
  (`# noqa: E402 — re-export ordering`).
- `print` is linted out of libraries (`T201`). `cli.py` and the `fmri-qa-cli`
  sources re-allow it through per-file-ignores.

→ [tooling.md](tooling.md), [stability.md](stability.md), [logging.md](logging.md)

## Errors should never pass silently. Unless explicitly silenced.

Fail fast with a message that names the bad value. Raise a named error, let it propagate,
and report once at the top. Never write a bare `except: pass`. When you do silence
something, say why (`except OSError: pass  # cleanup is best-effort`). Do the same for lint
and type-checker findings: fix them or silence them narrowly with a reason. Test each
exception type, since it is part of the contract. → [exceptions.md](exceptions.md), [stability.md](stability.md), [tooling.md](tooling.md), [testing.md](testing.md)

## In the face of ambiguity, refuse the temptation to guess.

Raise a clear error on ambiguous input instead of picking a default. Better, use types
whose every value is valid: a frozen dataclass that validates in `__post_init__`, a
`NewType`, an `Enum` for a closed set. Distinct types can also mark lifecycle state (e.g.
`UnsafeInput` vs `SafeInput`). → [exceptions.md](exceptions.md), [architecture.md](architecture.md#type-driven-design)

## There should be one — and preferably only one — obvious way to do it.

Prefer one canonical path: one base exception per package, one current writer per file
format, one module per concern. Remove a deprecated alias once migration is done. → [exceptions.md](exceptions.md), [stability.md](stability.md), [documentation.md](documentation.md)

## Now is better than never. Although never is often better than *right* now.

Make the breaking change, update the call sites, and move on. This code is
prototype-maturity: release tags carry compatibility, so a redesign can replace an API
outright and shims shouldn't linger. Don't build for a future that may never arrive: no
exception subclass, flag or abstraction added "just in case." Leftover
`breakpoint()`/`print` debugging and bare `TODO`s are noise. Linters and reviews exist to
catch them before they ship. → [stability.md](stability.md#code-maturity), [exceptions.md](exceptions.md)

## If the implementation is hard to explain, it's a bad idea. If it's easy to explain, it may be a good idea.

If a clear docstring is hard to write, fix the code. Tension between code and its
documentation means the abstraction is wrong. → [documentation.md](documentation.md)

## Namespaces are one honking great idea — let's do more of those!

Give every concept a clear home. `ls` on a package should answer questions. When a file
grows topic sections, split it into modules. Narrow public surfaces with `__all__`, keep
complexity in private modules and helpers, and group by domain, not by language construct.
→ [architecture.md](architecture.md#one-file-one-topic), [documentation.md](documentation.md)
