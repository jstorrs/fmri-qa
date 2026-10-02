"""The package's lazy re-export: eager names stay eager, heavy ones resolve lazily."""

import sys

import pytest

import fmriqc_launcher


def test_a_request_name_is_reachable() -> None:
    assert fmriqc_launcher.RunRequest is not None
    assert fmriqc_launcher.parse_form is not None


def test_an_outcome_name_is_reachable() -> None:
    assert fmriqc_launcher.Published is not None


def test_run_session_resolves_lazily() -> None:
    assert fmriqc_launcher.run_session is not None


def test_an_unknown_name_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no attribute"):
        fmriqc_launcher.not_a_real_name  # noqa: B018


def test_dir_lists_the_public_names() -> None:
    assert dir(fmriqc_launcher) == sorted(fmriqc_launcher.__all__)


def test_all_is_sorted_and_has_no_duplicates() -> None:
    names = fmriqc_launcher.__all__
    assert names == sorted(names)
    assert len(names) == len(set(names))


def test_every_exported_name_resolves() -> None:
    for name in fmriqc_launcher.__all__:
        assert getattr(fmriqc_launcher, name) is not None, (
            f"fmriqc_launcher.{name} resolved to None"
        )


def test_bare_import_does_not_load_scipy_or_matplotlib() -> None:
    """The lazy-import claim, from a fresh interpreter.

    A bare `import fmriqc_launcher` still imports `.request`, which pulls in
    numpy through `fmriqc.settings`/`fmriqc.types` -- see the package
    docstring -- so this only checks that `.session`'s heavier stack (scipy,
    matplotlib) stays unloaded, not that numpy does.
    """
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, fmriqc_launcher; "
            "print(sorted(m for m in ('numpy', 'scipy', 'matplotlib') "
            "if m in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "['numpy']", result.stderr
