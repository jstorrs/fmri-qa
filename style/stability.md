# Stability and API Changes

This document describes the philosophy for API stability and breaking changes in this repository. It is the concrete expression of *now is better than never* (rip bandaids early) and *there should be one obvious way to do it* (don't keep a deprecated alias beside its replacement) from [zen.md](zen.md).

## Core Principle

**The monorepo is the world.** Nothing outside the tree tracks `main`, so an API change is acceptable as long as all affected code within the repository is updated. Where something *does* need a fixed API, it pins a **release tag** rather than relying on `main` holding still; compatibility is a property of tags, not of the working branch (see [Code Maturity](#code-maturity)).

The exceptions to this freedom are anything a *user* has on disk or in a script — these are interfaces even though the code around them isn't:

- **On-disk file formats** — the `.npz` analysis artifact, and any self-identifying file a tool reads back later
- **Config / input file schemas** — user-authored, version-controlled files
- **CLI flags, subcommands, and positional arguments** that scripts may depend on
- **stdout output** that downstream tools parse (see [logging.md](logging.md))
- **Exit codes** that scripts check

## Code Maturity

Treat this code as **prototype-maturity: high quality, but not backwards-compatible by
contract.** "Prototype" here is about *commitment*, not polish — the code is still clean,
tested, and typed; what it does not do is freeze an API for its own sake. Released, pinned
versions carry the stability promise; `main` is where the design is still moving.

- **Redesigning an API? Tear off the bandaid.** If the current shape is a bad idea, replace
  it outright and update the call sites — don't preserve it behind a compatibility layer.
  The old shape still exists at its tag for anyone who needs it.
- **Shims are a strategic tool, not a maintained surface.** A temporary alias, adapter, or
  `DeprecationWarning` earns its place when it *advances* a migration — letting you land a
  big change in reviewable steps. It is not a permanent second way to do the same thing;
  remove it once the migration lands (see [When Deprecation Markers Help](#when-deprecation-markers-help)).
- **Specs develop in real time.** Much of this code is written to *discover* the need — the
  spec emerges as you build. Something poorly understood or poorly specified early on should
  not constrain later progress: revisit the design as understanding improves rather than
  building forward on a shape you already know is wrong.

This is *now is better than never; although never is often better than right now* from
[zen.md](zen.md), applied to whole APIs rather than single changes.

## Code API Stability

### Breaking Changes Are Fine

For Python APIs (functions, classes, modules):

- **Rename freely** - Update all call sites in the repo
- **Change signatures** - Grep for usages, update them
- **Remove functions** - If nothing uses it, delete it
- **Restructure modules** - Move code where it makes sense

The impact of any refactoring can be evaluated by studying all uses in this repository. There are no hidden consumers to worry about.

### Rip Bandaids Early

Avoid prolonged deprecation periods. When something needs to change:

1. Make the change
2. Update all affected code
3. Run tests
4. Done

Don't maintain backward compatibility shims, re-exports for old names, or `# deprecated` comments that linger for months. Clean breaks are better than accumulated cruft.

### When Deprecation Markers Help

Deprecation markers are useful *during* a refactoring session:

```python
import warnings


def old_function():
    warnings.warn("Use new_function instead", DeprecationWarning, stacklevel=2)
    return new_function()
```

This helps find call sites during migration. Remove the old function once migration is complete - don't leave it as a permanent compatibility layer.

### Evaluating Impact

Before making breaking changes:

```bash
# Find all usages of a function
rg "function_name\(" src/

# Find all imports of a module
rg "from mypackage import" src/
rg "import mypackage" src/
```

If you can see all the usages, you can update all the usages.

## Data Format Stability

**Data lives outside the repository.** File formats and schemas require careful handling because users have files on disk that must remain readable.

### What Requires Care

- The `.npz` analysis artifact — the seam between the two distributions, and the file a
  user keeps
- The JSON the CLI emits, and the per-scan table it prints
- Configuration and input file schemas
- Any binary or serialization format a later run has to read back

### Schema Versioning

The artifact carries its own version. `ARTIFACT_SCHEMA_VERSION` is written into every file
as `schema_version`, and the mapping between the dataclasses and the archive members is
spelled out field by field rather than derived by reflection — so adding a field is a
deliberate edit to the format, not a silent one.

Always provide a migration when changing the schema. `analysis/serialize.py` keeps one step
per version, so a file two versions old is walked forward one step at a time:

```python
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
}
```

An artifact outlives the build that wrote it. A version this build has no route from is
refused *loudly*, naming both versions — and so is a version from a newer build, because
neither has an honest answer.

### File Format Changes

When changing file formats:

1. **Increment version numbers** - Embed version in the file itself
2. **Support reading old versions** - New code reads old files, warning as it migrates them
3. **Write new version only** - Don't maintain old writers
4. **Document migrations** - If manual migration needed, document it

## CLI and Output Interfaces

A package's command-line surface is an interface too: users wire flags and piped output
into scripts. The "rip bandaids" philosophy still applies — just don't break someone's
script *silently*. A loud failure (a clear error naming the removed flag) is acceptable; a
silent behavior change is not.

### CLI flags and arguments

- **Add new flags freely** — defaults preserve existing behavior.
- **Renaming a flag**: keep the old name as an alias, mark it deprecated in `--help`, and
  remove it after the call sites are updated. `click` supports multiple option names on one
  parameter for exactly this.
- **Removing a flag**: prefer a clear error that names the removed flag over a silent no-op.

### stdout output and exit codes

- **stdout is semi-stable** — anything a downstream tool might parse. Keep result data on
  stdout and status/diagnostics on stderr ([logging.md](logging.md)) so a format change to
  one channel doesn't surprise a pipeline reading the other.
- **Exit codes are part of the contract** — scripts check them. `0` for success, non-zero
  for failure; don't repurpose a code's meaning without noting it.

## Summary

| What | Stability Requirement |
|------|----------------------|
| Python functions/classes | None - change freely, update call sites |
| Module structure | None - reorganize as needed |
| Internal APIs | None - refactor at will |
| Config / input file schemas | Backward-compatible reads; aliases for renames |
| CLI flags / arguments | Aliases for renames; loud failures over silent changes |
| stdout output formats | Semi-stable - users pipe to other tools |
| Exit codes | Stable - scripts check these |
| The `.npz` analysis artifact | Versioned; new code migrates old files forward |
| On-disk / binary formats | Versioned; new code reads old; document migrations |

**Code is cheap, data is precious.** Be bold with code changes, careful with anything a user has on disk or in a script.
