# The Zen of This Repository

These style guides are the **Zen of Python** (`import this`, PEP 20) made concrete for the
Python in this repository. The Zen is native here — it is the language's own design creed —
so this file is just the index that maps each aphorism to the guide where it's detailed and
the tooling that enforces it. Read the other guides when you need the detail.

When two principles pull against each other, the later aphorisms are the tie-breakers:
*practicality beats purity*, and *if the implementation is hard to explain, it's a bad
idea*.

---

## Beautiful is better than ugly. Readability counts.

Code is read far more than it is written. Optimize the call site for the reader. Clear
names, short functions, and obvious control flow are features, not polish applied later.
→ [documentation.md](documentation.md), [architecture.md](architecture.md)

## Explicit is better than implicit.

State intent in the types and the API, not in the reader's head.

- A public name is a deliberate choice; default to a leading-underscore `_private` name and
  publish the surface deliberately with `__all__`.
- Don't hide behind a bare `except Exception` or a stringly-typed error — raise a named
  subclass of your package's base exception.
- Positive boolean names (`is_valid`, not `not is_invalid`).
- Type your public API and let mypy/pyright/pyrefly check it; annotations are the contract
  written down.

→ [architecture.md](architecture.md), [exceptions.md](exceptions.md), [logging.md](logging.md), [tooling.md](tooling.md)

## Simple is better than complex. Complex is better than complicated.

Some problems are irreducibly complex; organize that complexity instead of tangling it.
The *functional core, imperative shell* split is exactly this — necessary I/O complexity
lives at the edge in thin class wrappers, the core stays pure (and, as a payoff, testable
with plain values). → [architecture.md](architecture.md), [testing.md](testing.md)

## Flat is better than nested.

Prefer early returns and guard clauses over rightward-drifting nests of `if`/`else`. Handle
the exceptional cases first and return, keeping the happy path at the left margin. The
`RET` ruff rules (superfluous `else` after `return`, unnecessary branches) push in this
direction. → [architecture.md](architecture.md#flat-over-nested)

## Sparse is better than dense.

Give the reader room: intermediate bindings with meaningful names beat one dense
comprehension chain. Let `ruff format` own whitespace so the diff is about meaning, not
layout. → [documentation.md](documentation.md), [tooling.md](tooling.md)

## Special cases aren't special enough to break the rules. Although practicality beats purity.

Hold the line on consistency — but when reality demands an exception, make it *narrow,
explicit, and documented* rather than relaxing the rule everywhere. The workspace's own
examples:

- A blanket `except`, a `# type: ignore`, or a `# noqa` is denied by default and allowed
  only at the one site that needs it, carrying a specific rule code and a reason
  (`# noqa: E402 — re-export ordering`), never a bare blanket.
- `print` is linted out of libraries (`T201`); `cli.py`/`main.py` re-allow it in one place
  via per-file-ignores, because talking to the terminal is their job.

→ [tooling.md](tooling.md), [stability.md](stability.md), [logging.md](logging.md)

## Errors should never pass silently. Unless explicitly silenced.

Fail fast with a message that names the bad value. Don't swallow exceptions with a bare
`except: pass`. Raise a named error, let it propagate, and report once at the top; prefer
loud failures over silent behavior changes. When you *do* silence something, make it a
deliberate, visible decision (`except OSError: pass  # cleanup is best-effort`). The same
goes for lint and type-checker findings: fix them, or silence them narrowly with a reason —
never let them accumulate. Exception types are part of the contract, so cover each one with
a test. → [exceptions.md](exceptions.md), [stability.md](stability.md), [tooling.md](tooling.md), [testing.md](testing.md)

## In the face of ambiguity, refuse the temptation to guess.

When an input is ambiguous, raise a clear error instead of quietly picking a default and
hoping. Validate early and name what was wrong. Better still, design types whose every
value is valid — a frozen dataclass that validates in `__post_init__`, a `NewType`, an
`Enum` for a closed set — so the ambiguous state can't be constructed in the first place,
and distinct types mark lifecycle state (e.g. `UnsafeInput` vs `SafeInput`) so data can't
be used in the wrong context. → [exceptions.md](exceptions.md), [architecture.md](architecture.md#type-driven-design)

## There should be one — and preferably only one — obvious way to do it.

Prefer a single canonical path over several overlapping ones: one base exception per
package, one current writer for a file format, one obvious module for a given concern.
Don't keep a deprecated alias alongside its replacement once migration is done.
→ [exceptions.md](exceptions.md), [stability.md](stability.md), [documentation.md](documentation.md)

## Now is better than never. Although never is often better than *right* now.

Rip bandaids early — make the breaking change, update the call sites, move on; don't let
deprecation shims linger. Most of this code is prototype-maturity: compatibility is carried
by release tags, not in-code shims, so a redesign can replace an API outright — and since
code is often written to *discover* the need, an early, poorly-understood spec shouldn't
constrain later progress. But don't build for a future that may never arrive: no exception
subclass, flag, or abstraction added "just in case." Leftover `breakpoint()`/`print`
debugging and bare `TODO`s are noise the linters and reviews exist to flush out before they
ship. → [stability.md](stability.md#code-maturity), [exceptions.md](exceptions.md)

## If the implementation is hard to explain, it's a bad idea. If it's easy to explain, it may be a good idea.

The strongest design signal in these guides. If a clear docstring is hard to write, the
code — not the doc — needs work. Tension between code and its documentation means the
abstraction is wrong. → [documentation.md](documentation.md)

## Namespaces are one honking great idea — let's do more of those!

Use the module and package system to give every concept a clear home — a place for
everything, and everything in its place. `ls` on a package should answer questions, not
raise them, so that a correct guess about which file to open is a file you didn't have to
read. When a file starts growing topic-sections, split it into separate modules rather than
section it in place. Narrow public surfaces with `__all__`; keep complexity in
leading-underscore modules or private helpers. Group by domain, not by language construct.
→ [architecture.md](architecture.md#one-file-one-topic), [documentation.md](documentation.md)
