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
by module, for readers who want one step of the pipeline.

The commands' options are not listed here. The user guide covers each command:
{doc}`fmri-qa-run </user-guide/fmri-qa-run>`,
{doc}`the panel </user-guide/panel>`,
{doc}`fmri-qa-import </user-guide/fmri-qa-import>`,
{doc}`fmri-qa and fmri-qa-hilo </user-guide/fmri-qa>` and
{doc}`fmri-qa-report </user-guide/fmri-qa-report>`.
{doc}`/user-guide/developers` gives an overview of the packages and the
pipeline.

```{toctree}
fmri-qa-core
fmri-qa-io
fmri-qa-cli
fmri-qa-report
fmri-qa-launcher
building-blocks
```
