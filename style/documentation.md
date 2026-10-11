# Documentation and Naming Style Guide

This document describes the philosophy for documentation and naming in this repository. The core idea: **code and documentation should tell the same story**. It is the concrete expression of *readability counts* and *if the implementation is hard to explain, it's a bad idea* from [zen.md](zen.md).

## Core Principles

1. **Names should align with documentation** - Reading a function name and reading its docstring should produce the same mental model
2. **Code should be self-documenting** - Good names and structure reduce the need for explanation
3. **Docstrings describe the contract** - What the function does, not how
4. **Comments explain why** - Non-obvious context, constraints, and decisions
5. **Tension is a design signal** - Difficulty documenting indicates design problems

## The Coherence Test

Good code passes this test:

> Can someone read just the function signature and docstring, then read just the implementation, and arrive at the same mental model from both?

If not, either the names/structure don't match the abstraction, or the abstraction itself needs work.

## Tension as a Design Signal

| Symptom | Diagnosis |
|---------|-----------|
| Hard to write a clear docstring | Logic is too complex or conflated |
| Code unclear after reading docstring | Names/structure don't match the abstraction |
| Docstring just repeats the code | Good - code is self-documenting |
| Docstring reveals surprising behavior | API design needs work |
| Need to cross-reference docstring to understand code | Poor naming or structure |

When documentation is difficult to write, **fix the code first**.

## Naming Guidelines

### Functions

Names should describe what the function does, making the docstring almost redundant:

```python
# Good - name tells you what it does
def calculate_mean(values: Sequence[float]) -> float:
    """Calculate the arithmetic mean of values."""
    ...


def load_study_from_dicom(path: Path) -> Study:
    """Load a Study from a DICOM file."""
    ...


# Bad - name doesn't convey meaning
def process(data):
    """Calculate statistics and validate ranges."""
    ...


def do_stuff(x):
    """Load, parse, and transform the input."""
    ...
```

### Variables

Names should reflect what the value represents:

```python
# Good - names describe the data
mean_signal = calculate_mean(signal_values)
slice_count = len(slices)
is_valid = all(check_constraints(item) for item in items)

# Bad - generic or abbreviated names
x = calculate_mean(vals)
n = len(slices)
flag = all(check_constraints(i) for i in items)
```

### Booleans

Use positive names that read naturally in conditions:

```python
# Good
is_valid = ...
has_errors = ...
should_retry = ...

if is_valid:
    ...

# Avoid double negatives
if not is_invalid:  # confusing
    ...
```

### Types

- **Nouns for data and value types**: `Study`, `Archive`, `Measurement`, `IndexEntry`
- **Nouns/verbs for processors and wrappers**: `Reader`, `Writer`, `Validator`, `Processor`
- **`Error` suffix for exceptions**: `ParseError`, `ValidationError` (see [exceptions.md](exceptions.md))
- **Enums name a closed set**: `Mode`, `Disposition` — prefer these to `bool`/`str`
  parameters ([architecture.md](architecture.md#type-driven-design))

### Modules and Files

File and directory names should be self-explanatory. Running `ls` or `tree` should answer questions, not reveal mysteries.

```
# Good - structure tells you what's here
mypackage/
    __init__.py
    reader.py
    writer.py
    validation.py
    exceptions.py
    types.py

# Bad - requires investigation to understand
mypackage/
    __init__.py
    core.py        # what's "core"?
    utils.py       # grab-bag of everything
    helpers.py     # how is this different from utils?
    misc.py        # mystery box
    v2.py          # version of what?
```

#### Guidelines

- **Use nouns for data/types**: `types.py`, `models.py`, `schema.py`
- **Use verbs/actions for operations**: `reader.py`, `writer.py`, `parser.py`, `validator.py`
- **Be specific**: `dicom_reader.py` over `reader.py` if multiple readers exist
- **Avoid generic names**: `utils.py`, `helpers.py`, `common.py`, `misc.py`
- **Group by domain, not by type**: `authentication/` not `classes/`

#### The `ls` Test

Ask yourself: if someone runs `ls` on this directory, will they understand what's here?

```
# Passes the ls test - clear purpose for each file
$ ls packages/fmri-qa-core/src/fmriqc/
__init__.py  analysis/  cli/  convert/  exceptions.py  hilo/  load/  metrics/
path_arguments.py  pipeline.py  prep/  rename.py  settings.py  types.py
validation.py  version.py  warn.py

# Fails the ls test - requires reading code to understand
$ ls src/mypackage/
__init__.py  base.py  core.py  impl.py  main.py  utils.py
```

#### When Generic Names Are Acceptable

- `types.py` - for type definitions and dataclasses (well-understood convention)
- `exceptions.py` - for exception hierarchy (well-understood convention)
- `constants.py` - for module-level constants
- `cli.py` - for command-line interface entry point

## Docstring Guidelines

### Purpose

Docstrings document the **contract** - what the function does from the caller's perspective:

- What it accepts
- What it returns
- What exceptions it raises
- Any important constraints or preconditions

Docstrings should **not** explain implementation details. Rationale, history
and workarounds go in `#` comments next to the code they explain.

### Format: numpydoc

Docstrings use [numpydoc](https://numpydoc.readthedocs.io/) sections. The format is
the contract, written down in a fixed place: the same sections in the same order
mean a reader (and the rendered reference) always finds the type of a parameter,
the units of a result, and the failure modes where they expect them. Sphinx
renders these docstrings into the API reference, so the format is not optional
decoration; it is how the reference gets written.

**Sections**, in this order, omitting any that do not apply: Parameters, Returns,
Yields, Raises, Warns, See Also, Notes, References, Examples.

**Summary line**: one line, at most 75 characters, ending in a period.

- Functions and methods are **imperative**: "Compute...", "Measure...", "Return...",
  "Plot...". Ruff enforces this (D401). It also suits the functional style: a
  calculation is a verb applied to data, and the summary reads as the call.
- Classes, dataclasses and properties are **noun phrases**: "Voxel dimensions of an
  acquisition."

**Types** are written for the reader, not for the type checker (annotations already
do that). Name the array shape and dtype: `mean_image : (X, Y) ndarray of float64`,
`series : (X, Y, T) ndarray of float64`. Use `pe_axis : {0, 1}` for closed sets,
`radius : int, optional` for optional arguments, and say "Default is ..." in the
description.

**Units**: every physical quantity names its unit (s, mm, voxels, %, or "in
`voxel.unit`").

**NaN versus None**: every value that can be NaN or None says when. NaN means the
estimator ran and could not resolve a value. None means the quantity does not apply
or was not measured. A reader should never have to guess which absence they hold.

**Notes** carry method and background: the equation, why it is that equation,
assumptions. Put short equations in `.. math::`. **References** are numbered
`.. [1]` and cited as `[1]_` in Notes. Include a DOI where one exists, and never
invent one; a source without a DOI is cited without it.

**Examples** are doctests: self-contained, built from numpy, deterministic and
quick. Print floats with format strings, never numpy scalar reprs. A plotting
example ends with `plt.close(ax.figure)`.

**Markup**: single backticks are cross-references and parameter names (`roi`).
Double backticks are literals and expressions (``np.nan``). Never a bare `|`; it is
reST syntax.

**Records**: library-produced records (results the caller receives) document their
fields under `Attributes`. Records the user constructs (settings, requests, form
values, exceptions) document them under `Parameters`, because that is how they are
called. Properties and methods document themselves.

**Constants** get a `#:` comment on the line above, which Sphinx picks up as the
description. Module-level data without one does not appear in the reference at all.
A constant re-exported from a package root is documented where it is defined, and the
reference lists it once.

**Plotting functions** take the data first and a keyword `ax=None`, return the Axes,
and are styled through `matplotlib.rc_context`, not through style keywords.

### API Tiers

How much a name's docstring must say depends on who calls it. There are four tiers:

- **Public**: in a root or subpackage `__all__`. Full numpydoc, listed in the
  reference.
- **Building block**: in its module's `__all__` only. Concise numpydoc (summary,
  Parameters, Returns), listed on the "Building blocks" reference page, linked from
  the analysis page and from its caller's See Also.
- **Internal**: no leading underscore and in no `__all__`; shared across modules or
  distributions. Not in the reference. A concise docstring.
- **Private**: a leading underscore. Local to its module; the docstring may be
  minimal or absent when the name says it all.

Full numpydoc is for names in an `__all__`. Everywhere else, write a concise
one-to-three-line docstring. A name that needs more than that is either doing too
much or belongs in a higher tier.

### When Docstrings Add Value

This example is illustrative, not an existing function. The docstring earns its
length: the NaN case, the units, the equation and its source are not in the
signature.

```python
def compute_snr(
    first: NDArray[np.float64],
    second: NDArray[np.float64],
    roi: NDArray[np.bool_],
) -> float:
    r"""Compute the signal-to-noise ratio from two repeated images.

    Parameters
    ----------
    first, second : (X, Y) ndarray of float64
        Consecutive images of a static phantom, in scanner intensity units.
    roi : (X, Y) ndarray of bool
        Voxels over which signal and noise are measured.

    Returns
    -------
    snr : float
        Mean signal in `roi` divided by the noise standard deviation in
        `roi`. NaN when the difference image is constant over `roi`, so
        the noise cannot be resolved.

    Raises
    ------
    ValueError
        If `first`, `second` and `roi` do not share a shape, or `roi`
        selects no voxels.

    See Also
    --------
    fmriqc.metrics.fbirn.sfnr : Fluctuation noise over a full time series.

    Notes
    -----
    Noise is estimated from the difference of two images, which cancels
    static structure [1]_:

    .. math::

        \mathrm{SNR} = \frac{\bar{S}}{\sigma_D / \sqrt{2}}

    where :math:`\bar{S}` is the mean of both images over `roi` and
    :math:`\sigma_D` is the standard deviation of their difference over
    `roi`. The factor :math:`\sqrt{2}` converts the variance of a
    difference to the variance of one image.

    References
    ----------
    .. [1] Friedman L, Glover GH. Report on a multicenter fMRI quality
           assurance protocol. J Magn Reson Imaging. 2006;23(6):827-839.
           doi:10.1002/jmri.20583

    Examples
    --------
    >>> import numpy as np
    >>> first = np.full((4, 4), 100.0)
    >>> second = first.copy()
    >>> first[0, 0] += 2.0
    >>> roi = np.ones((4, 4), dtype=bool)
    >>> print(f"{compute_snr(first, second, roi):.1f}")
    292.3
    """
```

The docstring adds value by explaining:
- When the result is NaN (the estimator ran and could not resolve)
- The units and shapes of every input
- The method, with its source, in Notes where it does not clutter the contract

### When Docstrings Can Be Minimal

```python
def calculate_mean(values: Sequence[float]) -> float:
    """Calculate the arithmetic mean of values."""
    return sum(values) / len(values)
```

The function is simple, the name is clear, the types are explicit. A longer docstring would just repeat what's obvious. Building-block, internal and private names usually look like this.

## Comment Guidelines

### Comments Explain "Why"

Use inline comments for:
- Non-obvious constraints or requirements
- Broader context that affects the code
- Historical reasons for unusual choices
- Performance considerations
- Edge cases being handled

```python
def process_slices(slices: list[Slice]) -> list[Slice]:
    # Sort by instance number to ensure consistent ordering across
    # different DICOM sources (some vendors use acquisition time instead)
    sorted_slices = sorted(slices, key=lambda s: s.instance_number)

    # Skip first slice - often contains calibration data on Siemens scanners
    return sorted_slices[1:]
```

### Comments Should Not Explain "What"

```python
# Bad - explains what (obvious from code)
# Increment counter by one
counter += 1

# Calculate the sum of values
total = sum(values)

# Check if list is empty
if not items:
    return None


# Good - explains why (not obvious from code)
# Use multiplication instead of math.pow for 2x speedup in tight loop
result = value * value

# Threshold from ISO 14971 Table D.4
risk_threshold = 0.001
```

### TODO Comments

Use TODO comments for known issues or future work:

```python
# TODO: Replace with proper retry logic once circuit breaker is implemented
for _ in range(3):
    try:
        return fetch(url)
    except TimeoutError:
        pass
```

## Self-Documenting Code Techniques

### Extract Well-Named Functions

```python
# Before - needs comment to explain
# Check if study is valid for processing
if study.slice_count > 0 and study.modality in SUPPORTED and not study.is_localizer:
    process(study)

# After - self-documenting
if is_processable(study):
    process(study)


def is_processable(study: Study) -> bool:
    """Check if study meets criteria for processing."""
    return (
        study.slice_count > 0
        and study.modality in SUPPORTED_MODALITIES
        and not study.is_localizer
    )
```

### Use Named Constants

```python
# Before - magic number
if retries > 3:
    raise TooManyRetriesError()

# After - self-documenting
MAX_RETRY_ATTEMPTS = 3

if retries > MAX_RETRY_ATTEMPTS:
    raise TooManyRetriesError()
```

### Use Intermediate Variables

```python
# Before - dense and hard to follow
return [s for s in studies if s.date >= cutoff and s.modality == "MR" and s.complete]

# After - clear intent at each step
recent_studies = [s for s in studies if s.date >= cutoff]
mr_studies = [s for s in recent_studies if s.modality == "MR"]
complete_studies = [s for s in mr_studies if s.complete]
return complete_studies
```

## Summary

The goal is **coherence** between code and documentation:

- Names should make docstrings feel almost redundant
- Docstrings describe contracts, not implementations
- Comments explain why, not what
- If documentation is hard to write, the code needs work
- If code is hard to understand after reading docs, the code needs work

Good documentation doesn't compensate for unclear code - it complements clear code.
