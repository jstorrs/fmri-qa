"""The pure core of `web_notices`: what is a licence text, and each gap it refuses.

A gap rendered silently is a page shipped without a licence it must carry, so
each refusal names the component.
"""

from dataclasses import replace

import pytest
from web_notices import (
    Fragment,
    Inputs,
    LicenceText,
    MissingLicenceError,
    NpmPackage,
    Wheel,
    check_pyodide_pin,
    check_vendored_lock,
    licence_label,
    licence_texts,
    parse_fragment,
    render,
    unknown_notice_files,
)

MIT = "MIT License\n\nCopyright (c) 2026 Judd Storrs"


def _fragment(name: str, version: str) -> Fragment:
    return Fragment(name, version, f"## {name} text")


def _supplement(
    name: str, version: str, pyodide: str = "314.0.7", emscripten: str = "5.0.3"
) -> Fragment:
    return Fragment(name, version, f"## {name} text", pyodide, emscripten)


def _wheel(name: str, version: str, *texts: str) -> Wheel:
    return Wheel(
        file=f"{name}-{version}-py3-none-any.whl",
        name=name,
        version=version,
        licence="MIT (License-Expression)",
        texts=tuple(LicenceText((f"{name}.dist-info/LICENSE",), t) for t in texts),
    )


def _inputs() -> Inputs:
    return Inputs(
        pyodide="314.0.7",
        python="3.14.2",
        emscripten="5.0.3",
        core_assets=frozenset({"pyodide.asm.wasm", "python_stdlib.zip"}),
        wheels=(
            _wheel("numpy", "2.4.6", "numpy licence"),
            *(_wheel(n, "0.1.0", MIT) for n in ("fmri-qa-core", "fmri-qa-io")),
            *(_wheel(n, "0.1.0", MIT) for n in ("fmri-qa-report", "fmri-qa-web")),
        ),
        npm=(
            NpmPackage("@niivue/dcm2niix", "1.3.20260724", "BSD-2-Clause", None),
            NpmPackage("fflate", "0.8.3", "MIT", "fflate licence"),
            NpmPackage("pyodide", "314.0.7", "MPL-2.0", None),
        ),
        fragments={
            "pyodide.md": _fragment("pyodide", "314.0.7"),
            "cpython.md": _fragment("python", "3.14.2"),
            "pyodide-runtime.md": _fragment("pyodide", "314.0.7"),
            "emscripten.md": _fragment("emscripten", "5.0.3"),
            "dcm2niix.md": _fragment("@niivue/dcm2niix", "1.3.20260724"),
        },
        supplements={},
        repo_licence=MIT,
        excluded=("setuptools",),
        asm_url="https://pyodide.invalid/pyodide.asm.mjs",
    )


def test_a_complete_set_renders_every_component_once() -> None:
    text = render(_inputs())

    for heading in (
        "## Pyodide 314.0.7",
        "## python text",
        "## emscripten text",
        "## numpy 2.4.6",
        "## @niivue/dcm2niix text",
        "## fflate 0.8.3",
    ):
        assert text.count(f"\n{heading}\n") == 1, heading
    assert "## fmri-qa 0.1.0 (fmri-qa-core, fmri-qa-io" in text
    assert "dicom-util" in text
    assert text.endswith("\n")
    assert text == render(_inputs())


def test_a_supplement_follows_its_wheels_own_texts() -> None:
    inputs = replace(_inputs(), supplements={"numpy": _supplement("numpy", "2.4.6")})

    text = render(inputs)

    assert text.index("numpy licence") < text.index("## numpy text")


def test_a_wheel_with_no_licence_text_is_refused_by_name() -> None:
    inputs = _inputs()
    bare = replace(inputs, wheels=(_wheel("numpy", "2.4.6"), *inputs.wheels[1:]))

    with pytest.raises(MissingLicenceError, match=r"^numpy: .* has no licence text"):
        render(bare)


def test_a_supplement_alone_is_a_licence_text() -> None:
    inputs = _inputs()
    bare = replace(
        inputs,
        wheels=(_wheel("numpy", "2.4.6"), *inputs.wheels[1:]),
        supplements={"numpy": _supplement("numpy", "2.4.6")},
    )

    assert "## numpy text" in render(bare)


def test_a_supplement_verified_for_another_version_is_refused() -> None:
    inputs = replace(_inputs(), supplements={"numpy": _supplement("numpy", "2.4.5")})

    with pytest.raises(MissingLicenceError, match=r"^numpy: .*2\.4\.5.*2\.4\.6"):
        render(inputs)


@pytest.mark.parametrize(
    "supplement",
    [
        _supplement("numpy", "2.4.6", pyodide="314.0.6"),
        _supplement("numpy", "2.4.6", emscripten="5.0.2"),
        _fragment("numpy", "2.4.6"),  # no build versions at all
    ],
)
def test_a_supplement_for_another_pyodide_build_is_refused(
    supplement: Fragment,
) -> None:
    inputs = replace(_inputs(), supplements={"numpy": supplement})

    with pytest.raises(MissingLicenceError, match=r"^numpy: .*built by Pyodide"):
        render(inputs)


def test_a_new_pyodide_fails_every_supplement() -> None:
    inputs = replace(
        _inputs(),
        supplements={"numpy": _supplement("numpy", "2.4.6")},
        fragments={
            **_inputs().fragments,
            "pyodide.md": _fragment("pyodide", "315.0.0"),
            "pyodide-runtime.md": _fragment("pyodide", "315.0.0"),
        },
        pyodide="315.0.0",
    )

    with pytest.raises(MissingLicenceError, match=r"^numpy: .*Pyodide 315\.0\.0"):
        render(inputs)


def test_the_excluded_packages_are_named_in_the_header_and_the_mpl_section() -> None:
    text = render(replace(_inputs(), excluded=("alpha", "setuptools")))
    header, mpl = text.split("\n## Pyodide ", 1)

    assert (
        "Left out of the page, though Pyodide's lock lists them: alpha, setuptools"
        in header
    )
    assert "entries for alpha, setuptools deleted from `packages`" in mpl


def test_with_nothing_excluded_the_lock_is_only_rewritten() -> None:
    text = render(replace(_inputs(), excluded=()))

    assert "Nothing in Pyodide's lock is left out of the page." in text
    assert 'separators=(",", ":"))`, with no entry changed.' in text


def test_the_mpl_section_states_the_exact_replacement() -> None:
    text = render(replace(_inputs(), asm_url="https://x.invalid/a.mjs"))

    assert 'replaced with the string literal `"https://x.invalid/a.mjs"`' in text


def test_a_workspace_wheel_missing_from_the_page_is_refused() -> None:
    inputs = _inputs()
    wheels = tuple(w for w in inputs.wheels if w.name != "fmri-qa-io")

    with pytest.raises(MissingLicenceError, match=r"^fmri-qa-io: not bundled"):
        render(replace(inputs, wheels=wheels))


def test_a_hand_kept_npm_package_missing_from_package_json_is_refused() -> None:
    inputs = _inputs()
    npm = tuple(p for p in inputs.npm if p.name != "@niivue/dcm2niix")

    with pytest.raises(MissingLicenceError, match=r"^@niivue/dcm2niix: not in web"):
        render(replace(inputs, npm=npm))


@pytest.mark.parametrize(
    ("headers", "classifiers", "label"),
    [
        (
            {"License-Expression": "MIT", "License": "BSD"},
            [],
            "MIT (License-Expression)",
        ),
        ({"License": " BSD-2-Clause "}, [], "BSD-2-Clause (License metadata)"),
        (
            {"License": "Copyright (c) x\n\nlong text"},
            ["License :: OSI Approved :: BSD License", "Topic :: Science"],
            "OSI Approved :: BSD License (classifiers)",
        ),
        ({"License": "x" * 81}, [], "as in the texts below"),
        ({}, [], "as in the texts below"),
    ],
)
def test_licence_label_prefers_the_expression_then_a_short_license(
    headers: dict[str, str], classifiers: list[str], label: str
) -> None:
    assert licence_label(headers, classifiers) == label


def test_unknown_notice_files_are_named() -> None:
    paths = [
        "README.md",
        "cpython.md",
        "wheels/scipy.md",
        "wheels/old/x.md",
        "typo.md",
        "wheels/scipy.txt",
    ]

    assert unknown_notice_files(paths) == [
        "typo.md",
        "wheels/old/x.md",
        "wheels/scipy.txt",
    ]


def test_a_supplement_header_carries_its_build() -> None:
    text = "For: scipy 1.18.0\nPyodide: 314.0.7\nEmscripten: 5.0.3\n\n### body\n"

    assert parse_fragment(text, "s.md") == Fragment(
        "scipy", "1.18.0", "### body", "314.0.7", "5.0.3"
    )


def test_a_supplement_for_a_wheel_no_longer_bundled_is_refused() -> None:
    inputs = replace(_inputs(), supplements={"scipy": _supplement("scipy", "1.18.0")})

    with pytest.raises(MissingLicenceError, match=r"^scipy: "):
        render(inputs)


@pytest.mark.parametrize(
    ("inputs", "component"),
    [
        (replace(_inputs(), python="3.14.3"), "python"),
        (replace(_inputs(), emscripten="5.0.4"), "emscripten"),
        (replace(_inputs(), pyodide="314.0.8"), "pyodide"),
    ],
)
def test_a_runtime_text_verified_for_another_version_is_refused(
    inputs: Inputs, component: str
) -> None:
    with pytest.raises(MissingLicenceError, match=rf"^{component}: .*verify it"):
        render(inputs)


def test_a_missing_runtime_text_is_refused() -> None:
    inputs = _inputs()
    fragments = {k: v for k, v in inputs.fragments.items() if k != "emscripten.md"}

    with pytest.raises(MissingLicenceError, match=r"^emscripten: .* is missing"):
        render(replace(inputs, fragments=fragments))


def test_an_npm_package_with_no_licence_file_is_refused_by_name() -> None:
    inputs = _inputs()
    npm = (*inputs.npm, NpmPackage("left-pad", "1.3.0", "WTFPL", None))

    with pytest.raises(MissingLicenceError, match=r"^left-pad: .* no LICENSE file"):
        render(replace(inputs, npm=npm))


def test_an_unknown_core_asset_is_refused() -> None:
    inputs = replace(_inputs(), core_assets=frozenset({"pyodide.asm.data"}))

    with pytest.raises(MissingLicenceError, match=r"^pyodide\.asm\.data: "):
        render(inputs)


def test_a_workspace_wheel_must_carry_the_repo_licence() -> None:
    inputs = _inputs()
    wheels = (*inputs.wheels[:-1], _wheel("fmri-qa-web", "0.1.0", "other"))

    with pytest.raises(MissingLicenceError, match=r"^fmri-qa-web: .*repo LICENSE"):
        render(replace(inputs, wheels=wheels))


def test_licence_texts_take_pep_639_entries_and_licence_names_anywhere() -> None:
    entries = {
        "x-1.dist-info/licenses/vendored/dragon4_LICENSE.txt": b"dragon4",
        "x-1.dist-info/LICENSE": b"main\r\n",
        "x/data/COPYING_QHULL.txt": b"qhull",
        "x/_vendor/y-2.dist-info/NOTICE": b"notice",
        "x/__init__.py": b"code",
    }

    texts = licence_texts(entries, "x-1.dist-info")

    assert [(t.paths, t.text) for t in texts] == [
        (("x-1.dist-info/LICENSE",), "main"),
        (("x-1.dist-info/licenses/vendored/dragon4_LICENSE.txt",), "dragon4"),
        (("x/_vendor/y-2.dist-info/NOTICE",), "notice"),
        (("x/data/COPYING_QHULL.txt",), "qhull"),
    ]


def test_licence_texts_list_a_repeated_text_once_with_every_path() -> None:
    entries = {"x/ma/LICENSE": b"same", "x-1.dist-info/licenses/x/ma/LICENSE": b"same"}

    assert licence_texts(entries, "x-1.dist-info") == [
        LicenceText(("x-1.dist-info/licenses/x/ma/LICENSE", "x/ma/LICENSE"), "same")
    ]


def test_a_fragment_names_its_component_and_version() -> None:
    fragment = parse_fragment("For: @niivue/dcm2niix 1.3.1\n\n## body\n", "f.md")

    assert fragment == Fragment("@niivue/dcm2niix", "1.3.1", "## body")


@pytest.mark.parametrize(
    "text",
    [
        "## body\n",
        "For: numpy\n\nbody",
        "For: a 1\nbody",
        "For: a 1\nPyodide: 314.0.7\n\nbody",
        "For: a 1\n\n",
    ],
)
def test_a_fragment_without_its_for_line_is_refused(text: str) -> None:
    with pytest.raises(MissingLicenceError, match=r"^f\.md: must start with"):
        parse_fragment(text, "f.md")


def test_a_pyodide_install_unlike_the_vendored_one_is_refused() -> None:
    check_pyodide_pin("314.0.7", "314.0.7")
    with pytest.raises(MissingLicenceError, match=r"^pyodide: .*315\.0\.0.*314\.0\.7"):
        check_pyodide_pin("315.0.0", "314.0.7")


UPSTREAM: dict[str, object] = {
    "info": {"python": "3.14.2"},
    "packages": {
        "networkx": {"depends": ["setuptools"]},
        "setuptools": {"depends": []},
    },
}
VENDORED = '{"info":{"python":"3.14.2"},"packages":{"networkx":{"depends":[]}}}'


def test_the_vendored_lock_written_as_stated_passes() -> None:
    check_vendored_lock(VENDORED, UPSTREAM, ["setuptools"])


@pytest.mark.parametrize(
    ("vendored", "excluded"),
    [
        (VENDORED, []),  # more removed than stated
        (VENDORED.replace(":", ": "), ["setuptools"]),  # written otherwise
        (
            '{"info":{"python":"3.14.3"},"packages":{"networkx":{"depends":[]}}}',
            ["setuptools"],
        ),
    ],
)
def test_a_vendored_lock_unlike_the_statement_is_refused(
    vendored: str, excluded: list[str]
) -> None:
    with pytest.raises(
        MissingLicenceError,
        match=r"^pyodide-lock\.json: .*web/vendor/.*web/node_modules/",
    ):
        check_vendored_lock(vendored, UPSTREAM, excluded)
