# API reference

The reference is generated from the docstrings of the installed packages, so it
describes the code you have. It has two tiers.

The **public API** is what each distribution exports from its root, or from a
subpackage's own `__all__`. There is one page each for {doc}`fmri-qa-core`,
{doc}`fmri-qa-report` and {doc}`fmri-qa-launcher`. Build on these names. They
are the ones kept stable.

The **building blocks** are the names a module lists in its own `__all__` but its
package does not re-export: the individual metrics, the preparation steps, the
launcher's panel state. {doc}`building-blocks` documents them concisely, module
by module, for readers who want one step of the pipeline. The command-line entry
points are not in the reference. The {doc}`user guide </user-guide/index>` covers
the commands.

```{toctree}
fmri-qa-core
fmri-qa-report
fmri-qa-launcher
building-blocks
```
