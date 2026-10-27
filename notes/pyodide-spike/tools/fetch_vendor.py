"""Download what build.py inlines into vendor/. Usage: fetch_vendor.py [spike_dir]

Run from the repo root with `uv run python`. Needs network, npm and uv.
"""
import json, shutil, subprocess, sys, tarfile, urllib.request
from pathlib import Path

PYODIDE = "314.0.7"
NIBABEL = "5.4.2"
CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/"

spike = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
vendor = spike / "vendor"
for sub in ("npm", "pyodide", "wheels", "pypi", "fmriqa"):
    (vendor / sub).mkdir(parents=True, exist_ok=True)

subprocess.run(["npm", "pack", f"pyodide@{PYODIDE}", "--pack-destination", vendor / "npm"], check=True)
with tarfile.open(vendor / "npm" / f"pyodide-{PYODIDE}.tgz") as tar:
    tar.extractall(vendor / "npm" / "x", filter="data")
package = vendor / "npm" / "x" / "package"
for name in ("pyodide.js", "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
    shutil.copy(package / name, vendor / "pyodide" / name)

lock = json.loads((vendor / "pyodide" / "pyodide-lock.json").read_text())["packages"]
seen: list[str] = []
def go(n):
    n = n.lower().replace("_", "-")
    if n in seen: return
    for d in lock[n]["depends"]: go(d)
    seen.append(n)
for n in ("numpy", "scipy", "scikit-image", "packaging"): go(n)
for n in seen:
    name = lock[n]["file_name"]
    target = vendor / "wheels" / name
    if not target.exists():
        urllib.request.urlretrieve(CDN + name, target)

subprocess.run([sys.executable, "-m", "pip", "download", f"nibabel=={NIBABEL}", "--no-deps",
                "--only-binary=:all:", "-d", vendor / "pypi"], check=True)
subprocess.run(["uv", "build", "--wheel", "packages/fmri-qa-core", "-o", vendor / "fmriqa"], check=True)
