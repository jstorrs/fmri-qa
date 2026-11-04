"""Fill `web/vendor/` with everything the browser page inlines, verified.

The page boots Pyodide offline, so every byte it runs is embedded in it:
Pyodide's runtime, the Pyodide packages fmri-qa needs, nibabel (on PyPI, not in
Pyodide's lock) and the four workspace wheels. This collects them into
`web/vendor/` and writes `web/vendor/manifest.json`, which the page's build
(`web/scripts/vite-pyodide.mjs`) reads to inline them in order.

- The runtime is copied from the `pyodide` npm package in `web/node_modules`,
  so its version is the one `web/package.json` pins. The lock is written
  without `EXCLUDED` (`lock_without`), so Pyodide never asks for one.
- The Pyodide packages are the dependency closure of `ROOTS` in that
  package's `pyodide-lock.json`, less `EXCLUDED`, downloaded from the matching
  CDN release and checked against the lock's sha256.
- nibabel is the wheel `uv.lock` pins, checked against its hash there.
- The workspace wheels are built with `uv build`.

Finally every wheel that is not a Pyodide package must have each of its
`Requires-Dist` met, as Pyodide would evaluate the markers, by a vendored
wheel or a package in the closure: the page unpacks them without a resolver.
No vendored wheel, a Pyodide package included, may require an `EXCLUDED` one.

Run from the workspace root after `npm ci` in `web/`
(`make web-vendor` does both): `uv run python scripts/web_vendor.py`.
Downloads are cached: a file already present with the right hash is kept.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import asdict, dataclass
from email.parser import HeaderParser
from pathlib import Path
from typing import Literal, cast
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

__all__ = [
    "Asset",
    "closure",
    "emscripten_environment",
    "excluded_requirements",
    "lock_without",
    "main",
    "metadata_path",
    "nibabel_wheel",
    "requires_dist",
    "unmet_requirements",
]

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VENDOR = WEB / "vendor"
PYODIDE_NPM = WEB / "node_modules" / "pyodide"

# The Pyodide packages the workspace wheels require directly (fmri-qa-core:
# numpy, scipy, scikit-image; fmri-qa-io and nibabel: packaging; fmri-qa-report:
# matplotlib, cycler). The closure brings their dependencies.
ROOTS = ("numpy", "scipy", "scikit-image", "packaging", "matplotlib", "cycler")
# Lock dependencies left out of the closure. Pyodide's lock lists setuptools
# under networkx, but no vendored wheel requires it (`_check_requirements`
# fails if one does) and nothing the page runs imports it. It vendors
# autocommand, which is LGPL-3.0, a licence the page does not otherwise carry
# (web/THIRD_PARTY_NOTICES.md).
EXCLUDED = frozenset({"setuptools"})
# The workspace distributions the page runs, in the order they are unpacked.
WORKSPACE = ("fmri-qa-core", "fmri-qa-io", "fmri-qa-report", "fmri-qa-web")
# The runtime files `loadPyodide` reads, and whether the page stores each
# gzipped. A zip or wheel is already compressed; gzipping it gains nothing.
# pyodide.asm.mjs is not one: Vite bundles it into the worker from
# node_modules (web/scripts/vite-pyodide.mjs, `classicPyodideAsm`).
CORE_FILES = {
    "pyodide.asm.wasm": True,
    "python_stdlib.zip": False,
    "pyodide-lock.json": True,
}

type Kind = Literal["pyodide-core", "pyodide-package", "wheel"]


@dataclass(frozen=True, slots=True)
class Asset:
    """One file the page inlines: `name` is what Pyodide requests it by."""

    name: str
    file: str  # relative to web/vendor
    sha256: str
    kind: Kind
    gzip: bool


def _one[T](items: Iterable[T], what: str) -> T:
    """Return the only item; a `ValueError` naming `what` and the count otherwise."""
    found = list(items)
    if len(found) != 1:
        raise ValueError(f"expected exactly one {what}, found {len(found)}")
    return found[0]


def closure(
    lock: Mapping[str, Mapping[str, object]],
    roots: Iterable[str],
    excluded: AbstractSet[str] = frozenset(),
) -> list[str]:
    """Return the lock's packages `roots` need, each after its dependencies.

    `lock` is `pyodide-lock.json`'s `packages`, keyed by normalized name.
    A package in `excluded` (normalized names) is left out with what only it
    brings. Raises `KeyError` naming a package the lock does not have.
    """
    seen: list[str] = []

    def visit(name: str) -> None:
        key = canonicalize_name(name)
        if key in seen or key in excluded:
            return
        if key not in lock:
            raise KeyError(f"{key} is not in pyodide-lock.json")
        for dep in cast("list[str]", lock[key]["depends"]):
            visit(dep)
        seen.append(key)

    for root in roots:
        visit(root)
    return seen


def lock_without(
    lock_file: Mapping[str, object], excluded: AbstractSet[str]
) -> dict[str, object]:
    """Return `pyodide-lock.json` without the `excluded` packages.

    They leave both `packages` and every entry's `depends`: `loadPackage`
    resolves `depends` from the lock, so a package left out of the closure must
    leave the lock too, or it is requested (and refused: the page has no such
    file).
    """
    packages = cast("Mapping[str, Mapping[str, object]]", lock_file["packages"])
    kept = {
        name: {
            **entry,
            "depends": [
                d
                for d in cast("list[str]", entry["depends"])
                if canonicalize_name(d) not in excluded
            ],
        }
        for name, entry in packages.items()
        if name not in excluded
    }
    return {**lock_file, "packages": kept}


def emscripten_environment(python: str, platform: str) -> dict[str, str]:
    """Return the marker environment of Pyodide's interpreter.

    `python` is the lock's `info.python` (e.g. "3.14.2") and `platform` its
    `info.platform` (e.g. "emscripten_5_0_3"). `extra` is empty: no wheel is
    installed with an extra.
    """
    major, minor, *_ = python.split(".")
    release = platform.removeprefix("emscripten_").replace("_", ".")
    return {
        "implementation_name": "cpython",
        "implementation_version": python,
        "os_name": "posix",
        "platform_machine": "wasm32",
        "platform_python_implementation": "CPython",
        "platform_release": release,
        "platform_system": "Emscripten",
        "platform_version": "#1",
        "python_full_version": python,
        "python_version": f"{major}.{minor}",
        "sys_platform": "emscripten",
        "extra": "",
    }


def requires_dist(metadata: str) -> list[Requirement]:
    """Return the `Requires-Dist` entries of a wheel's METADATA text."""
    message = HeaderParser().parsestr(metadata)
    return [Requirement(r) for r in message.get_all("Requires-Dist") or []]


def unmet_requirements(
    requirements: Iterable[Requirement],
    available: Mapping[str, str],
    environment: Mapping[str, str],
) -> list[str]:
    """Return each requirement that applies in `environment` and is not met.

    `available` maps a normalized distribution name to its version. A
    requirement whose marker is false in `environment` does not apply.
    """
    unmet = []
    for req in requirements:
        if req.marker is not None and not req.marker.evaluate(dict(environment)):
            continue
        version = available.get(canonicalize_name(req.name))
        if version is None:
            unmet.append(f"{req} (not vendored)")
        elif not req.specifier.contains(version, prereleases=True):
            unmet.append(f"{req} (vendored {version})")
    return unmet


def excluded_requirements(
    requirements: Iterable[Requirement],
    excluded: AbstractSet[str],
    environment: Mapping[str, str],
) -> list[str]:
    """Return each requirement that applies in `environment` and is `excluded`."""
    return [
        str(req)
        for req in requirements
        if canonicalize_name(req.name) in excluded
        and (req.marker is None or req.marker.evaluate(dict(environment)))
    ]


def nibabel_wheel(uv_lock: Mapping[str, object]) -> tuple[str, str]:
    """Return the url and sha256 of the one nibabel wheel `uv.lock` pins."""
    packages = cast("list[dict[str, object]]", uv_lock["package"])
    nibabel = _one(
        (p for p in packages if p["name"] == "nibabel"), "nibabel in uv.lock"
    )
    wheel = _one(
        cast("list[dict[str, str]]", nibabel["wheels"]), "nibabel wheel in uv.lock"
    )
    algorithm, _, digest = wheel["hash"].partition(":")
    if algorithm != "sha256":
        raise ValueError(f"nibabel's wheel hash is {algorithm}, not sha256")
    return wheel["url"], digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path, sha256: str) -> None:
    """Fetch `url` to `target` unless it is there with `sha256`; verify it."""
    if target.exists() and _sha256(target) == sha256:
        return
    sys.stderr.write(f"downloading {url}\n")
    partial = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as f:  # noqa: S310 - fixed https URLs
        shutil.copyfileobj(response, f)
    if (actual := _sha256(partial)) != sha256:
        partial.unlink()
        raise SystemExit(f"{url}: sha256 {actual}, expected {sha256}")
    partial.replace(target)


def metadata_path(names: Iterable[str], wheel: str) -> str:
    """Return the path of a wheel's own METADATA among its archive `names`.

    It is the top-level dist-info's; a wheel that vendors others (setuptools
    does) nests theirs deeper. A `ValueError` names `wheel` unless there is one.
    """
    found = (
        n for n in names if n.endswith(".dist-info/METADATA") and n.count("/") == 1
    )
    return _one(found, f"top-level METADATA in {wheel}")


def _metadata(wheel: Path) -> str:
    with ZipFile(wheel) as z:
        return z.read(metadata_path(z.namelist(), wheel.name)).decode("utf-8")


def _pinned_pyodide() -> str:
    pinned = json.loads((WEB / "package.json").read_text())["dependencies"]["pyodide"]
    installed = json.loads((PYODIDE_NPM / "package.json").read_text())["version"]
    if installed != pinned:
        raise SystemExit(
            f"web/node_modules has pyodide {installed}, web/package.json pins "
            f"{pinned}; run `npm --prefix web ci`"
        )
    return str(pinned)


def _core(lock_file: Mapping[str, object]) -> list[Asset]:
    out = VENDOR / "pyodide"
    out.mkdir(parents=True, exist_ok=True)
    assets = []
    for name, gz in CORE_FILES.items():
        if name == "pyodide-lock.json":
            text = json.dumps(lock_without(lock_file, EXCLUDED), separators=(",", ":"))
            (out / name).write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(PYODIDE_NPM / name, out / name)
        assets.append(
            Asset(name, f"pyodide/{name}", _sha256(out / name), "pyodide-core", gz)
        )
    return assets


def _packages(lock: Mapping[str, Mapping[str, object]], version: str) -> list[Asset]:
    out = VENDOR / "packages"
    out.mkdir(parents=True, exist_ok=True)
    cdn = f"https://cdn.jsdelivr.net/pyodide/v{version}/full/"
    assets = []
    for name in closure(lock, ROOTS, EXCLUDED):
        file_name, sha256 = str(lock[name]["file_name"]), str(lock[name]["sha256"])
        _download(cdn + file_name, out / file_name, sha256)
        assets.append(
            Asset(file_name, f"packages/{file_name}", sha256, "pyodide-package", False)
        )
    return assets


def _wheels() -> list[Asset]:
    out = VENDOR / "wheels"
    out.mkdir(parents=True, exist_ok=True)
    url, sha256 = nibabel_wheel(tomllib.loads((ROOT / "uv.lock").read_text()))
    nibabel = url.rsplit("/", 1)[1]
    _download(url, out / nibabel, sha256)
    assets = [Asset(nibabel, f"wheels/{nibabel}", sha256, "wheel", False)]
    for stale in out.glob("fmri_qa_*.whl"):
        stale.unlink()
    for package in WORKSPACE:
        subprocess.run(  # noqa: S603 - fixed arguments
            ["uv", "build", "--wheel", "--package", package, "-o", str(out), "-q"],  # noqa: S607 - uv on PATH
            check=True,
            cwd=ROOT,
        )
        pattern = f"{package.replace('-', '_')}-*.whl"
        wheel = _one(out.glob(pattern), f"{pattern} in {out}")
        assets.append(
            Asset(wheel.name, f"wheels/{wheel.name}", _sha256(wheel), "wheel", False)
        )
    return assets


def _check_requirements(
    wheels: Sequence[Path],
    packages: Sequence[Path],
    lock: Mapping[str, Mapping[str, object]],
    info: Mapping[str, str],
) -> dict[str, str]:
    """Fail unless every wheel's requirements are vendored; return their versions.

    `packages` (the Pyodide ones) are checked only against `EXCLUDED`: Pyodide
    patches some requirements away (scikit-image's tifffile) without editing
    their metadata, so the rest of theirs need not be met.
    """
    available = {
        name: str(lock[name]["version"]) for name in closure(lock, ROOTS, EXCLUDED)
    }
    metadata = {wheel: _metadata(wheel) for wheel in wheels}
    versions: dict[str, str] = {}
    for text in metadata.values():
        headers = HeaderParser().parsestr(text)
        versions[canonicalize_name(headers["Name"])] = headers["Version"]
    available |= versions
    environment = emscripten_environment(info["python"], info["platform"])
    # A requirement on an excluded package is reported once, as excluded.
    kept = {
        wheel: [
            r for r in requires_dist(text) if canonicalize_name(r.name) not in EXCLUDED
        ]
        for wheel, text in metadata.items()
    }
    problems = [
        f"{wheel.name}: {unmet}"
        for wheel, requirements in kept.items()
        for unmet in unmet_requirements(requirements, available, environment)
    ] + [
        f"{package.name}: {req} (excluded in scripts/web_vendor.py)"
        for package in [*packages, *wheels]
        for req in excluded_requirements(
            requires_dist(_metadata(package)), EXCLUDED, environment
        )
    ]
    if problems:
        raise SystemExit(
            "requirements the page does not vendor:\n" + "\n".join(problems)
        )
    return versions


def main() -> None:
    """Fill web/vendor and write its manifest."""
    if not PYODIDE_NPM.is_dir():
        raise SystemExit(
            "web/node_modules/pyodide is missing; run `npm --prefix web ci`"
        )
    version = _pinned_pyodide()
    lock_file = json.loads((PYODIDE_NPM / "pyodide-lock.json").read_text())
    lock = lock_file["packages"]
    assets = _core(lock_file) + _packages(lock, version) + _wheels()
    wheels = [VENDOR / a.file for a in assets if a.kind == "wheel"]
    packages = [VENDOR / a.file for a in assets if a.kind == "pyodide-package"]
    versions = _check_requirements(wheels, packages, lock, lock_file["info"])
    manifest = {
        "pyodide": version,
        "assets": [asdict(a) for a in assets],
        "versions": {name: versions[name] for name in WORKSPACE},
    }
    (VENDOR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    size = sum((VENDOR / a.file).stat().st_size for a in assets)
    sys.stderr.write(f"web/vendor: {len(assets)} assets, {size / 1e6:.1f} MB\n")


if __name__ == "__main__":
    main()
