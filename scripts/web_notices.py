"""Write `web/THIRD_PARTY_NOTICES.md`, the licences of all the browser page bundles.

The page shows the file under "About & licences" (`web/src/main.ts`), so it
must cover every component in `web/dist/fmri-qa.html`:

- every asset in `web/vendor/manifest.json` (`scripts/web_vendor.py`): the
  Pyodide runtime, by the hand-kept texts in `web/notices/`, and each wheel,
  by the licence files the wheel itself ships, plus a hand-kept supplement in
  `web/notices/wheels/<name>.md` for what it links and does not mention;
- every npm package in `web/package.json`'s `dependencies`, by its own LICENSE
  file or, for pyodide and @niivue/dcm2niix, by `web/notices/`. The build
  (`web/scripts/vite-notices.mjs`) fails unless the packages with code in the
  page are exactly those.

Each hand-kept text starts with `For: <name> <version>`, the version it was
verified against (`web/notices/README.md`); a wheel supplement adds the
`Pyodide:` and `Emscripten:` versions whose build of the wheel it describes.
Rendering fails, naming the component, when one is missing, when a bundled
version no longer matches, or when a bundled component has no licence text.

Run from the workspace root after `make web-vendor`:
`uv run python scripts/web_notices.py` writes the file; `--check` fails if the
committed one is stale (the page's build runs it first,
`web/scripts/vite-notices.mjs`).
"""

import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from email.parser import HeaderParser
from pathlib import Path
from zipfile import ZipFile

from packaging.utils import canonicalize_name
from web_vendor import WORKSPACE, lock_without, metadata_path

__all__ = [
    "Fragment",
    "Inputs",
    "LicenceText",
    "MissingLicenceError",
    "NpmPackage",
    "Wheel",
    "check_pyodide_pin",
    "check_vendored_lock",
    "licence_label",
    "licence_texts",
    "main",
    "parse_fragment",
    "read_inputs",
    "render",
    "unknown_notice_files",
]

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VENDOR = WEB / "vendor"
NOTICES = WEB / "notices"
NODE_MODULES = WEB / "node_modules"
OUTPUT = WEB / "THIRD_PARTY_NOTICES.md"

# What `pyodide-core` assets the Pyodide sections cover.
CORE_ASSETS = frozenset({"pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"})
# The hand-kept texts for the runtime, by file, and the component each is for.
CORE_FRAGMENTS = {
    "pyodide.md": "pyodide",
    "cpython.md": "python",
    "pyodide-runtime.md": "pyodide",
    "emscripten.md": "emscripten",
    "dcm2niix.md": "@niivue/dcm2niix",
}
# The manifest kinds a wheel section covers.
WHEEL_KINDS = frozenset({"pyodide-package", "wheel"})
# npm packages whose texts are hand-kept rather than their own LICENSE file.
NPM_BY_FRAGMENT = frozenset({"pyodide", "@niivue/dcm2niix"})
LICENCE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)

HEADER = """\
# Third-party notices

web/dist/fmri-qa.html is a single file that bundles the components below, compiled, minified or compressed, so their licence terms apply to that file. It carries Pyodide (CPython compiled to WebAssembly with Emscripten, the Python standard library and the libraries Pyodide links in), the Python wheels the page installs into it (numpy, SciPy, scikit-image, matplotlib, nibabel and what they need), dcm2niix compiled to WebAssembly, the JavaScript libraries the page uses, and fmri-qa itself. Most licences are permissive: MIT, BSD (0-, 2- and 3-clause), Apache-2.0, the PSF licence, zlib, bzip2, HPND and MIT-CMU, BSL-1.0, the IJG, FreeType, libpng, libtiff, Anti-Grain Geometry and Qhull licences, the Unlicense, and public domain or CC0. Pyodide and its hiwire library are under the Mozilla Public License 2.0, which is copyleft for its own files only; see the Pyodide section for the two files this build modifies and where their source is. The fonts matplotlib ships include some under the SIL Open Font License 1.1. Many of these licences require the copyright notice and licence text to accompany the file when it is redistributed, and the IJG and FreeType licences require the statements given under them. The page therefore shows this very file under "About & licences". If you pass the HTML file on, keep that footer, or ship this file next to it.

How this was determined (scripts/web_notices.py writes this file; web/notices/README.md records how each hand-kept text was verified):
- The Pyodide runtime is version {pyodide} from the pyodide npm package. Its lock file gives CPython {python} and Emscripten {emscripten}, which Pyodide's Makefile.envs and changelog confirm. The libraries linked into pyodide.asm.wasm are those Pyodide's cpython/Makefile and Makefile.envs build and link at that tag.
- Each wheel's section is built from the wheel itself: every licence file in it (PEP 639 licenses/ entries, and LICENSE*, COPYING* and NOTICE* files anywhere in the wheel, each text once), and its License-Expression or License metadata. Where a Pyodide build links or ships code its own files leave out (scipy's OpenBLAS, Pillow's image libraries, matplotlib's Agg, qhull, FreeType and fonts), a supplement follows, taken from upstream at the version Pyodide's recipe pins.
- The npm packages are those with code in the page, read from the bundler's module list (web/scripts/vite-notices.mjs fails the build if that differs from web/package.json's dependencies). The bundler's own runtime helpers and Vite's empty browser stub are not listed. dcm2niix and what its jpeg build links come from dicom-util's notices, verified there against upstream; the other packages' texts are their own LICENSE files.
- {excluded_line}
"""  # noqa: E501 - one line per paragraph, as the page shows it


class MissingLicenceError(ValueError):
    """A bundled component has no licence text, or its hand-kept one is stale."""


@dataclass(frozen=True, slots=True)
class LicenceText:
    """One licence text a wheel ships, with every path it ships it at."""

    paths: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class Wheel:
    """A bundled wheel as its metadata and licence files describe it."""

    file: str
    name: str  # normalized
    version: str
    licence: str  # License-Expression, a short License, or the classifiers
    texts: tuple[LicenceText, ...]


@dataclass(frozen=True, slots=True)
class NpmPackage:
    """A runtime dependency in web/package.json, as installed."""

    name: str
    version: str
    licence: str
    text: str | None  # its LICENSE file, if it has one


@dataclass(frozen=True, slots=True)
class Fragment:
    """A hand-kept text: the component and version it was verified for, and its body."""

    name: str
    version: str
    body: str
    # For a wheel supplement: the Pyodide and Emscripten whose build it describes.
    pyodide: str | None = None
    emscripten: str | None = None


@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything `render` needs, read by `main`'s shell."""

    pyodide: str
    python: str
    emscripten: str
    core_assets: frozenset[str]
    wheels: tuple[Wheel, ...]
    npm: tuple[NpmPackage, ...]
    fragments: Mapping[str, Fragment]  # by file name in web/notices/
    supplements: Mapping[str, Fragment]  # by normalized wheel name
    repo_licence: str
    excluded: tuple[str, ...]  # in Pyodide's lock, left out of the page's
    asm_url: str  # what `import.meta.url` becomes in pyodide.asm.mjs


def _text(data: bytes) -> str:
    """Decode a licence file; normalize line ends and the surrounding blank lines."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def licence_texts(entries: Mapping[str, bytes], dist_info: str) -> list[LicenceText]:
    """Return a wheel's licence texts, each once, its own dist-info's first.

    `entries` maps the wheel's paths to their bytes (only candidates need be
    there); `dist_info` is its top-level `<name>-<version>.dist-info`. A
    licence file is anything under a `.dist-info/licenses/` directory (PEP
    639) or named LICENSE*, COPYING* or NOTICE* anywhere.
    """

    def is_licence(path: str) -> bool:
        return ("/licenses/" in path and ".dist-info/" in path) or bool(
            LICENCE_NAME.match(path.rsplit("/", 1)[-1])
        )

    def order(path: str) -> tuple[bool, str]:
        return (not path.startswith(f"{dist_info}/"), path)

    by_text: dict[str, list[str]] = {}
    for path in sorted((p for p in entries if is_licence(p)), key=order):
        by_text.setdefault(_text(entries[path]), []).append(path)
    return [LicenceText(tuple(paths), text) for text, paths in by_text.items() if text]


def parse_fragment(text: str, where: str) -> Fragment:
    """Parse a hand-kept text: its header lines, a blank line, the body.

    The header is `For: <name> <version>`, then optionally `Pyodide: <version>`
    and `Emscripten: <version>`, in that order.
    """
    head, _, body = text.partition("\n\n")
    match = re.fullmatch(
        r"For: (\S+) (\S+)(?:\nPyodide: (\S+)\nEmscripten: (\S+))?", head
    )
    if match is None or not body:
        raise MissingLicenceError(
            f"{where}: must start with 'For: <name> <version>' (then optionally "
            "'Pyodide: <version>' and 'Emscripten: <version>') and a blank line"
        )
    return Fragment(match[1], match[2], body.strip("\n"), match[3], match[4])


def check_pyodide_pin(installed: str, vendored: str) -> None:
    """Fail unless the npm install and web/vendor hold the same Pyodide.

    The excluded packages are the lock difference between the two, so a
    mismatch would list every package one Pyodide has and the other lacks.
    """
    if installed != vendored:
        raise MissingLicenceError(
            f"pyodide: web/node_modules has {installed}, web/vendor/manifest.json "
            f"{vendored}; run `make web-vendor`"
        )


def check_vendored_lock(
    vendored: str, upstream: Mapping[str, object], excluded: Iterable[str]
) -> None:
    """Fail unless the vendored lock is exactly what the MPL section says it is.

    That is the npm package's lock less `excluded`, written by `lock_without`
    and `json.dumps(..., separators=(",", ":"))`.
    """
    expected = json.dumps(lock_without(upstream, set(excluded)), separators=(",", ":"))
    if vendored != expected:
        raise MissingLicenceError(
            "pyodide-lock.json: web/vendor/pyodide/pyodide-lock.json is not "
            "web/node_modules/pyodide/pyodide-lock.json changed as the Pyodide "
            "section states; run `make web-vendor`"
        )


def unknown_notice_files(paths: Iterable[str]) -> list[str]:
    """Return the files under web/notices/ (relative paths) that nothing reads."""
    known = {*CORE_FRAGMENTS, "README.md"}
    return sorted(
        p for p in paths if p not in known and not re.fullmatch(r"wheels/[^/]+\.md", p)
    )


def _fragment(inputs: Inputs, file: str, version: str) -> str:
    """Return the body of `web/notices/<file>`; fail unless it is for `version`."""
    fragment = inputs.fragments.get(file)
    component = CORE_FRAGMENTS[file]
    if fragment is None:
        raise MissingLicenceError(f"{component}: web/notices/{file} is missing")
    if (fragment.name, fragment.version) != (component, version):
        raise MissingLicenceError(
            f"{component}: web/notices/{file} was verified for {fragment.name} "
            f"{fragment.version}, the page bundles {version}; verify it again"
        )
    return fragment.body


def _check_supplement(inputs: Inputs, wheel: Wheel, supplement: Fragment) -> None:
    """Fail unless `supplement` was verified for this wheel, as built here."""
    verified = (supplement.name, supplement.version, supplement.pyodide)
    bundled = (wheel.name, wheel.version, inputs.pyodide)
    if verified != bundled or supplement.emscripten != inputs.emscripten:
        raise MissingLicenceError(
            f"{wheel.name}: web/notices/wheels/{wheel.name}.md was verified for "
            f"{supplement.name} {supplement.version} built by Pyodide "
            f"{supplement.pyodide} (Emscripten {supplement.emscripten}); the page "
            f"bundles {wheel.version} built by Pyodide {inputs.pyodide} (Emscripten "
            f"{inputs.emscripten}); verify it again"
        )


def _wheel_section(inputs: Inputs, wheel: Wheel, supplement: Fragment | None) -> str:
    if not wheel.texts and supplement is None:
        raise MissingLicenceError(f"{wheel.name}: {wheel.file} has no licence text")
    parts = [
        f"## {wheel.name} {wheel.version}\n"
        f"Licence: {wheel.licence}\n"
        f"Source: the licence files in {wheel.file}"
    ]
    for item in wheel.texts:
        also = "".join(f" (also {p})" for p in item.paths[1:])
        parts.append(f"### {item.paths[0]}{also}\n\n{item.text}")
    if supplement is not None:
        _check_supplement(inputs, wheel, supplement)
        parts.append(
            "What this build links or ships that the licence files above leave "
            f"out (web/notices/wheels/{wheel.name}.md):\n\n{supplement.body}"
        )
    return "\n\n".join(parts)


def _npm_section(package: NpmPackage) -> str:
    if package.text is None:
        raise MissingLicenceError(
            f"{package.name}: web/node_modules/{package.name} has no LICENSE file"
        )
    return (
        f"## {package.name} {package.version}\n"
        f"Licence: {package.licence}\n"
        f"Source: the npm package {package.name}\n\n{package.text}"
    )


def _excluded(inputs: Inputs) -> str:
    return ", ".join(inputs.excluded) if inputs.excluded else "none"


def _pyodide_section(inputs: Inputs) -> str:
    mpl = _fragment(inputs, "pyodide.md", inputs.pyodide)
    removed = (
        f"with the entries for {_excluded(inputs)} deleted from `packages` and from "
        "every entry's `depends`"
        if inputs.excluded
        else "with no entry changed"
    )
    return f"""\
## Pyodide {inputs.pyodide}
Licence: MPL-2.0
Source: the pyodide npm package {inputs.pyodide}, https://www.npmjs.com/package/pyodide/v/{inputs.pyodide} (pyodide.mjs, pyodide.asm.mjs, pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json), built from https://github.com/pyodide/pyodide/tree/{inputs.pyodide}. The npm package has no licence file; the text below is that tag's LICENSE.

Two of these files are modified in this page. Each modification is described here in full, so the Source Code Form of the modified file is the file from the npm package {inputs.pyodide} with that change made:
- pyodide.asm.mjs: every occurrence (there are three) of the expression `import.meta.url` is replaced with the string literal `{json.dumps(inputs.asm_url)}`, so the module can run inside a classic worker. Nothing else in the file changes.
- pyodide-lock.json: parsed and written again as JSON with Python's `json.dumps(lock, separators=(",", ":"))`, {removed}.
The other files are unmodified.

{mpl}"""  # noqa: E501 - one line per paragraph, as the page shows it


def _check_coverage(inputs: Inputs) -> None:
    unknown = inputs.core_assets - CORE_ASSETS
    if unknown:
        raise MissingLicenceError(
            f"{', '.join(sorted(unknown))}: a Pyodide core asset no section covers"
        )
    bundled = {w.name for w in inputs.wheels}
    stale = sorted(set(inputs.supplements) - bundled)
    if stale:
        raise MissingLicenceError(
            f"{', '.join(stale)}: web/notices/wheels/ has a supplement for a wheel "
            "the page no longer bundles; remove it"
        )


def _workspace_section(inputs: Inputs, wheels: Sequence[Wheel]) -> str:
    for wheel in wheels:
        if [t.text for t in wheel.texts] != [inputs.repo_licence]:
            raise MissingLicenceError(
                f"{wheel.name}: {wheel.file}'s licence files are not the repo LICENSE"
            )
    names = ", ".join(w.name for w in wheels)
    versions = sorted({w.version for w in wheels})
    return (
        f"## fmri-qa {', '.join(versions)} ({names})\n"
        "Licence: MIT\n"
        "Source: LICENSE at the root of this repository, which each wheel ships\n"
        "The code copied from dicom-util into web/ (web/VENDORED.md) is by the same "
        "author and is included under this licence.\n\n"
        f"{inputs.repo_licence}"
    )


def render(inputs: Inputs) -> str:
    """Return the file's exact text; raise `MissingLicenceError` naming a gap."""
    _check_coverage(inputs)
    ours = {canonicalize_name(n) for n in WORKSPACE}
    workspace = [w for w in inputs.wheels if w.name in ours]
    if {w.name for w in workspace} != ours:
        raise MissingLicenceError(
            f"{', '.join(sorted(ours - {w.name for w in workspace}))}: not bundled"
        )
    npm = {p.name: p for p in inputs.npm}
    for name in NPM_BY_FRAGMENT:
        if name not in npm:
            raise MissingLicenceError(f"{name}: not in web/package.json")
    sections = [
        HEADER.format(
            pyodide=inputs.pyodide,
            python=inputs.python,
            emscripten=inputs.emscripten,
            excluded_line=(
                f"Left out of the page, though Pyodide's lock lists them: "
                f"{_excluded(inputs)} (EXCLUDED in scripts/web_vendor.py): nothing "
                "bundled needs them."
                if inputs.excluded
                else "Nothing in Pyodide's lock is left out of the page."
            ),
        ).rstrip("\n"),
        "# Python runtime (pyodide.asm.wasm, pyodide.asm.mjs, python_stdlib.zip)",
        _pyodide_section(inputs),
        _fragment(inputs, "cpython.md", inputs.python),
        _fragment(inputs, "pyodide-runtime.md", inputs.pyodide),
        _fragment(inputs, "emscripten.md", inputs.emscripten),
        "# Python packages (the wheels the page installs)",
        *(
            _wheel_section(inputs, w, inputs.supplements.get(w.name))
            for w in inputs.wheels
            if w.name not in ours
        ),
        "# fmri-qa",
        _workspace_section(inputs, workspace),
        "# dcm2niix and the JavaScript libraries",
        _fragment(inputs, "dcm2niix.md", npm["@niivue/dcm2niix"].version),
        *(_npm_section(p) for p in inputs.npm if p.name not in NPM_BY_FRAGMENT),
    ]
    return "\n\n".join(sections) + "\n"


# The imperative shell: read web/vendor, web/node_modules and web/notices.


def licence_label(headers: Mapping[str, str], classifiers: Iterable[str]) -> str:
    """Return a wheel's licence in a line, from its metadata or classifiers."""
    if expression := headers.get("License-Expression"):
        return f"{expression} (License-Expression)"
    short = (headers.get("License") or "").strip()
    if short and "\n" not in short and len(short) <= 80:
        return f"{short} (License metadata)"
    licences = [c.removeprefix("License :: ") for c in classifiers if "License" in c]
    if licences:
        return f"{'; '.join(licences)} (classifiers)"
    return "as in the texts below"


def _read_wheel(path: Path) -> Wheel:
    with ZipFile(path) as z:
        names = z.namelist()
        metadata = metadata_path(names, path.name)
        message = HeaderParser().parsestr(z.read(metadata).decode("utf-8"))
        candidates = {
            n: z.read(n)
            for n in names
            if not n.endswith("/")
            and ("/licenses/" in n or LICENCE_NAME.match(n.rsplit("/", 1)[-1]))
        }
    dist_info = metadata.rsplit("/", 1)[0]
    headers = {k: v for k, v in message.items() if k != "Classifier"}
    return Wheel(
        file=path.name,
        name=canonicalize_name(message["Name"]),
        version=message["Version"],
        licence=licence_label(headers, message.get_all("Classifier") or []),
        texts=tuple(licence_texts(candidates, dist_info)),
    )


def _read_npm(name: str) -> NpmPackage:
    directory = NODE_MODULES / name
    package = json.loads((directory / "package.json").read_text(encoding="utf-8"))
    files = sorted(
        p for p in directory.iterdir() if p.is_file() and LICENCE_NAME.match(p.name)
    )
    text = "\n\n".join(_text(p.read_bytes()) for p in files) or None
    return NpmPackage(name, package["version"], package.get("license", "?"), text)


def _asm_url() -> str:
    """Return the URL web/vite.config.mjs gives `classicPyodideAsm` (its source)."""
    config = (WEB / "vite.config.mjs").read_text(encoding="utf-8")
    found = re.findall(r"classicPyodideAsm\('([^']*)'\)", config)
    if len(found) != 1:
        raise SystemExit(
            "web/vite.config.mjs must call classicPyodideAsm('<url>') exactly once, "
            f"found {len(found)}; scripts/web_notices.py states that URL"
        )
    return str(found[0])


def read_inputs() -> Inputs:
    """Read web/vendor, web/node_modules and web/notices; exit if one is unusable."""
    manifest_path = VENDOR / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} is missing; run `make web-vendor` first")
    unknown = unknown_notice_files(
        p.relative_to(NOTICES).as_posix() for p in NOTICES.rglob("*") if p.is_file()
    )
    if unknown:
        raise SystemExit(f"web/notices/{', web/notices/'.join(unknown)}: not read")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest["assets"]
    kinds = {a["kind"] for a in assets} - WHEEL_KINDS - {"pyodide-core"}
    if kinds:
        raise SystemExit(
            f"web/vendor/manifest.json: unknown asset kind {', '.join(sorted(kinds))}"
        )
    upstream_path = NODE_MODULES / "pyodide/pyodide-lock.json"
    if not upstream_path.exists():
        raise SystemExit(f"{upstream_path} is missing; run `make web-vendor` first")
    installed = json.loads((NODE_MODULES / "pyodide/package.json").read_text("utf-8"))
    check_pyodide_pin(installed["version"], manifest["pyodide"])
    lock_text = (VENDOR / "pyodide/pyodide-lock.json").read_text("utf-8")
    lock = json.loads(lock_text)
    upstream = json.loads(upstream_path.read_text("utf-8"))
    excluded = tuple(sorted(set(upstream["packages"]) - set(lock["packages"])))
    check_vendored_lock(lock_text, upstream, excluded)
    dependencies = json.loads((WEB / "package.json").read_text("utf-8"))["dependencies"]
    fragments = {
        name: parse_fragment((NOTICES / name).read_text("utf-8"), f"web/notices/{name}")
        for name in CORE_FRAGMENTS
        if (NOTICES / name).exists()
    }
    supplements = {
        p.stem: parse_fragment(p.read_text("utf-8"), f"web/notices/wheels/{p.name}")
        for p in sorted((NOTICES / "wheels").glob("*.md"))
    }
    return Inputs(
        pyodide=manifest["pyodide"],
        python=lock["info"]["python"],
        emscripten=lock["info"]["platform"]
        .removeprefix("emscripten_")
        .replace("_", "."),
        core_assets=frozenset(a["name"] for a in assets if a["kind"] == "pyodide-core"),
        wheels=tuple(
            _read_wheel(VENDOR / a["file"]) for a in assets if a["kind"] in WHEEL_KINDS
        ),
        npm=tuple(_read_npm(name) for name in sorted(dependencies)),
        fragments=fragments,
        supplements=supplements,
        repo_licence=_text((ROOT / "LICENSE").read_bytes()),
        excluded=excluded,
        asm_url=_asm_url(),
    )


def main(argv: Sequence[str] = sys.argv[1:]) -> None:
    """Write the file, or with `--check` fail if the committed one is stale."""
    try:
        text = render(read_inputs())
    except ValueError as error:  # MissingLicenceError, or a wheel's METADATA
        raise SystemExit(f"web_notices: {error}") from None
    if list(argv) == ["--check"]:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            raise SystemExit(
                "web/THIRD_PARTY_NOTICES.md is stale or missing; regenerate it with "
                "`uv run python scripts/web_notices.py` and commit it"
            )
        return
    if argv:
        raise SystemExit("usage: web_notices.py [--check]")
    OUTPUT.write_text(text, encoding="utf-8")
    sys.stderr.write(f"{OUTPUT.relative_to(ROOT)}: {len(text.encode()):,} bytes\n")


if __name__ == "__main__":
    main()
