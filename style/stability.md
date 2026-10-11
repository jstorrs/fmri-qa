# Stability and API Changes

How this repository handles API stability and breaking changes ([zen.md](zen.md): *now is better than never*, *one obvious way to do it*).

## Core Principle

**The monorepo is the world.** Nothing outside the tree tracks `main`, so you can change an API as long as you update all affected code here. Anything that needs a fixed API pins a **release tag** (see [Code Maturity](#code-maturity)).

Anything a user has on disk or in a script is an exception. These are interfaces:

- **On-disk file formats**: the `.qa.nc` analysis artifact, and any self-identifying file a tool reads back later
- **Config / input file schemas**: user-authored, version-controlled files
- **CLI flags, subcommands, and positional arguments** that scripts may depend on
- **stdout output** that downstream tools parse (see [logging.md](logging.md))
- **Exit codes** that scripts check

## Code Maturity

This code is **prototype-maturity: clean, tested and typed, but not backwards-compatible
by contract.** Released, pinned versions carry the stability promise. `main` is where the
design still moves.

- **Replace a bad API outright** and update the call sites. Don't keep it behind a
  compatibility layer. The old shape still exists at its tag.
- **Shims are temporary.** An alias, adapter, or `DeprecationWarning` is fine when it
  advances a migration, for example by splitting a big change into reviewable steps. Remove
  it once the migration lands (see [When Deprecation Markers Help](#when-deprecation-markers-help)).
- **Specs develop as you build.** A poorly understood early spec shouldn't constrain later
  progress. Revisit the design instead of building on a shape you know is wrong.

## Code API Stability

### Breaking Changes Are Fine

For Python APIs (functions, classes, modules), rename, change signatures, remove unused
functions, and restructure modules freely. Update every call site in the repo. There are no
hidden consumers.

### Rip Bandaids Early

Make the change, update all affected code, run the tests, and you're done. Don't keep compatibility shims, re-exports for old names, or `# deprecated` comments for months.

### When Deprecation Markers Help

During a refactoring session, a deprecation marker helps find call sites:

```python
import warnings


def old_function():
    warnings.warn("Use new_function instead", DeprecationWarning, stacklevel=2)
    return new_function()
```

Remove the old function once migration is complete.

### Evaluating Impact

Before a breaking change, find the usages:

```bash
# Find all usages of a function
rg "function_name\(" src/

# Find all imports of a module
rg "from mypackage import" src/
rg "import mypackage" src/
```

## Data Format Stability

**Data lives outside the repository.** Users' files on disk must stay readable.

### What Requires Care

- The `.qa.nc` analysis artifact. It is the seam between the two distributions and the file
  a user keeps. Its container changed once (a compressed `.npz` before netCDF-4). The
  promise did not: new code reads every old file. The container is recognized from the
  file's leading bytes, not its name
- The JSON the CLI emits, and the per-scan table it prints
- Configuration and input file schemas
- Any binary or serialization format a later run has to read back

### Schema Versioning

The artifact carries its own version. `ARTIFACT_SCHEMA_VERSION` is written into every file
as `schema_version`. The mapping between the dataclasses and the file's variables is written
out field by field, not derived by reflection. Adding a field is therefore an explicit edit
to the format.

Always provide a migration when changing the schema. `analysis/serialize/migrate.py` keeps one step
per version, so a file two versions old is walked forward one step at a time:

```python
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
}
```

An artifact outlives the build that wrote it. A version this build has no route from is
refused with an error naming both versions. So is a version from a newer build.

### File Format Changes

When changing file formats:

1. **Increment version numbers** - Embed version in the file itself
2. **Support reading old versions** - New code reads old files, warning as it migrates them
3. **Write new version only** - Don't maintain old writers
4. **Document migrations** - If manual migration needed, document it

A change of *container* is not a schema change and does not bump the version. An example is
the artifact's move from `.npz` to netCDF-4: same document, different envelope. The version
pins the document's layout, and bumping it would make older builds refuse a document they
understand. Tell containers apart by the file's leading bytes, because a version stored
inside a file can't be read until the container is open. The old container keeps a reader
and loses its writer.

## CLI and Output Interfaces

Users wire flags and piped output into scripts. Breaking changes are fine if they fail
loudly, with a clear error naming the removed flag. A silent behavior change is not.

### CLI flags and arguments

- **Add new flags freely.** Defaults preserve existing behavior.
- **Renaming a flag**: keep the old name as an alias, mark it deprecated in `--help`, and
  remove it after the call sites are updated. `click` supports multiple option names on one
  parameter.
- **Removing a flag**: prefer a clear error that names the removed flag over a silent no-op.

### stdout output and exit codes

- **stdout is semi-stable.** Downstream tools may parse it. Keep result data on stdout and
  status/diagnostics on stderr ([logging.md](logging.md)), so a format change to one
  channel doesn't surprise a pipeline reading the other.
- **Exit codes are part of the contract.** Scripts check them. Use `0` for success and
  non-zero for failure. Don't change a code's meaning without noting it.

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
| The `.qa.nc` analysis artifact | Versioned; new code migrates old files forward, and still reads the retired `.npz` container |
| On-disk / binary formats | Versioned; new code reads old; document migrations |

**Code is cheap, data is precious.** Be bold with code changes, careful with anything a user has on disk or in a script.
