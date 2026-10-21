"""The package's lazy re-export: eager names stay eager, heavy ones resolve lazily."""

import sys

import pytest

import fmriqa_launcher


def test_a_request_name_is_reachable() -> None:
    assert fmriqa_launcher.RunRequest is not None
    assert fmriqa_launcher.parse_form is not None


def test_an_outcome_name_is_reachable() -> None:
    assert fmriqa_launcher.Published is not None


def test_run_session_resolves_lazily() -> None:
    assert fmriqa_launcher.run_session is not None


def test_an_unknown_name_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no attribute"):
        fmriqa_launcher.not_a_real_name  # noqa: B018


def test_dir_lists_the_public_names() -> None:
    assert dir(fmriqa_launcher) == sorted(fmriqa_launcher.__all__)


def test_all_is_sorted_and_has_no_duplicates() -> None:
    names = fmriqa_launcher.__all__
    assert names == sorted(names)
    assert len(names) == len(set(names))


def test_every_exported_name_resolves() -> None:
    for name in fmriqa_launcher.__all__:
        assert getattr(fmriqa_launcher, name) is not None, (
            f"fmriqa_launcher.{name} resolved to None"
        )


def test_bare_import_does_not_load_scipy_or_matplotlib() -> None:
    """Check the lazy-import claim from a fresh interpreter.

    A bare `import fmriqa_launcher` still pulls in numpy through `.request`
    (see the package docstring), so this only checks that `.session`'s heavier
    stack (scipy, matplotlib) stays unloaded.
    """
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, fmriqa_launcher; "
            "print(sorted(m for m in ('numpy', 'scipy', 'matplotlib') "
            "if m in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "['numpy']", result.stderr
