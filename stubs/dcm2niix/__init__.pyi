"""Local stub for the `dcm2niix` wrapper package: the one attribute we use.

The package is a thin wrapper around a bundled dcm2niix binary and ships no type
information, so `convert.dcm2niix` could not import it under strict typing. That
module still guards `import dcm2niix` with `except ImportError`, although the
package is a plain dependency of `fmri-qa-core`: an install that cannot import it
(no wheel for the platform, or a pruned environment) falls back to PATH. A stub
types the import whether or not the package is installed, so the type checkers
agree with that guard, which a mypy override could not.

Only `bin` is stubbed. The wrapper's `main` runs the binary through
`subprocess.run` with no typing and no control over the arguments, which is
exactly what `convert.dcm2niix.run` does for itself.
"""

bin: str
