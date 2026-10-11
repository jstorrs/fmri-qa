# API reference

The reference is generated from the docstrings of the installed packages, so it
describes the code you have rather than the code that was documented. It has two
tiers.

The **public API** is what each distribution exports from its root, or from a
subpackage's own `__all__`: one page each for
{doc}`fmri-qa-core`, {doc}`fmri-qa-report` and {doc}`fmri-qa-launcher`. These
are the names to build on, and the ones kept stable.

The **building blocks** are the names a module lists in its own `__all__` but its
package does not re-export: the individual metrics, the preparation steps, the
launcher's panel state. They are documented concisely, module by module, on
{doc}`building-blocks`, for the reader who wants one step of the pipeline rather
than the whole of it. The command-line entry points are not in the reference;
the {doc}`user guide </user-guide/index>` covers the commands.

```{toctree}
fmri-qa-core
fmri-qa-report
fmri-qa-launcher
building-blocks
```
