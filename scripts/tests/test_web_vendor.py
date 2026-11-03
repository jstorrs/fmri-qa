"""The pure helpers `web_vendor` decides what the browser page vendors with.

The page unpacks wheels with no resolver, so a requirement these helpers
wrongly call met is a page that fails at import in the browser, not at build.
"""

import pytest
from packaging.requirements import Requirement
from web_vendor import (
    closure,
    emscripten_environment,
    nibabel_wheel,
    requires_dist,
    unmet_requirements,
)

LOCK: dict[str, dict[str, object]] = {
    "a": {"depends": ["b", "C_d"]},
    "b": {"depends": ["c-d"]},
    "c-d": {"depends": []},
    "e": {"depends": ["b"]},
}
ENV = emscripten_environment("3.14.2", "emscripten_5_0_3")


def test_closure_puts_each_package_after_its_dependencies_once() -> None:
    assert closure(LOCK, ["a", "e"]) == ["c-d", "b", "a", "e"]


def test_closure_normalizes_names() -> None:
    assert closure(LOCK, ["C.D"]) == ["c-d"]


def test_closure_names_a_package_the_lock_lacks() -> None:
    with pytest.raises(KeyError, match=r"zzz is not in pyodide-lock\.json"):
        closure({"a": {"depends": ["zzz"]}}, ["a"])


def test_the_environment_is_pyodides() -> None:
    assert ENV["sys_platform"] == "emscripten"
    assert ENV["platform_system"] == "Emscripten"
    assert ENV["python_version"] == "3.14"
    assert ENV["python_full_version"] == "3.14.2"
    assert ENV["platform_release"] == "5.0.3"


def test_requires_dist_reads_every_entry() -> None:
    metadata = (
        "Metadata-Version: 2.4\nName: x\nVersion: 1\n"
        "Requires-Dist: numpy>=2\n"
        "Requires-Dist: netCDF4>=1.7; sys_platform != 'emscripten'\n\nbody\n"
    )
    assert [str(r) for r in requires_dist(metadata)] == [
        "numpy>=2",
        'netCDF4>=1.7; sys_platform != "emscripten"',
    ]


def test_requires_dist_of_a_wheel_with_none_is_empty() -> None:
    assert requires_dist("Metadata-Version: 2.4\nName: x\nVersion: 1\n") == []


def _unmet(*reqs: str, **available: str) -> list[str]:
    return unmet_requirements([Requirement(r) for r in reqs], available, ENV)


def test_a_requirement_met_by_a_vendored_version_passes() -> None:
    assert _unmet("numpy>=2.3.4", numpy="2.4.6") == []


def test_a_missing_requirement_is_reported() -> None:
    assert _unmet("cycler>=0.10", numpy="2.4.6") == ["cycler>=0.10 (not vendored)"]


def test_a_too_old_version_is_reported() -> None:
    assert _unmet("numpy>=3", numpy="2.4.6") == ["numpy>=3 (vendored 2.4.6)"]


def test_names_are_normalized_before_lookup() -> None:
    assert _unmet("Scikit_Image>=0.25", **{"scikit-image": "0.26.0"}) == []


def test_a_requirement_for_another_platform_does_not_apply() -> None:
    assert _unmet("netCDF4>=1.7; sys_platform != 'emscripten'") == []
    assert _unmet("pywin32; platform_system == 'Windows'") == []


def test_a_requirement_for_emscripten_applies() -> None:
    assert _unmet("x; platform_system == 'Emscripten'") == [
        'x; platform_system == "Emscripten" (not vendored)'
    ]


def test_python_version_markers_use_314() -> None:
    assert _unmet("typing-extensions; python_version < '3.13'") == []
    assert _unmet("y; python_version >= '3.14'") == [
        'y; python_version >= "3.14" (not vendored)'
    ]


def test_an_extra_only_requirement_does_not_apply() -> None:
    assert _unmet("pytest; extra == 'test'") == []


def test_a_prerelease_version_can_meet_a_requirement() -> None:
    # Pyodide's lock can carry a release candidate; it is what the page runs.
    assert _unmet("numpy>=2.4", numpy="2.5.0rc1") == []


def _uv_lock(*packages: dict[str, object]) -> dict[str, object]:
    return {"package": list(packages)}


def test_nibabel_wheel_returns_url_and_digest() -> None:
    lock = _uv_lock(
        {"name": "numpy", "wheels": []},
        {
            "name": "nibabel",
            "wheels": [
                {
                    "url": "https://x/nibabel-5.4.2-py3-none-any.whl",
                    "hash": "sha256:ab12",
                }
            ],
        },
    )
    assert nibabel_wheel(lock) == ("https://x/nibabel-5.4.2-py3-none-any.whl", "ab12")


def test_nibabel_wheel_refuses_another_hash_algorithm() -> None:
    lock = _uv_lock({"name": "nibabel", "wheels": [{"url": "u", "hash": "md5:ab"}]})
    with pytest.raises(ValueError, match="md5, not sha256"):
        nibabel_wheel(lock)


def test_nibabel_wheel_needs_exactly_one_wheel() -> None:
    lock = _uv_lock(
        {"name": "nibabel", "wheels": [{"url": "u", "hash": "sha256:a"}] * 2}
    )
    with pytest.raises(
        ValueError, match=r"expected exactly one nibabel wheel in uv\.lock, found 2"
    ):
        nibabel_wheel(lock)


def test_nibabel_wheel_needs_nibabel_in_the_lock() -> None:
    with pytest.raises(
        ValueError, match=r"expected exactly one nibabel in uv\.lock, found 0"
    ):
        nibabel_wheel(_uv_lock({"name": "numpy", "wheels": []}))
