# API reference

The reference is generated from the docstrings of the installed packages, so it
describes the code you have. It has two tiers.

The **public API** is what each distribution exports from its root, or from a
subpackage's own `__all__`. There is one page each for {doc}`fmri-qa-core`,
{doc}`fmri-qa-io`, {doc}`fmri-qa-cli`, {doc}`fmri-qa-report` and
{doc}`fmri-qa-launcher`. Build on these names. They are the ones kept stable.

The **building blocks** are the names a module lists in its own `__all__` but its
package does not re-export: the individual metrics, the preparation steps, the
launcher's panel state. {doc}`building-blocks` documents them concisely, module
by module, for readers who want one step of the pipeline. The command-line entry
points are listed on {doc}`fmri-qa-cli`, which covers only `fmri-qa`,
`fmri-qa-hilo` and `fmri-qa-import`, and without their options. Each command's
`--help` has those, and the repository's `README.md` covers them. The
{doc}`user guide </user-guide/index>` covers `fmri-qa-report`, `fmri-qa-run` and
the desktop panel.

```{toctree}
fmri-qa-core
fmri-qa-io
fmri-qa-cli
fmri-qa-report
fmri-qa-launcher
building-blocks
```
