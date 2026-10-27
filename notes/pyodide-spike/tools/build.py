#!/usr/bin/env python3
"""Assemble dist/fmriqa-spike.html from vendor/. Usage: build.py [spike_dir] [--drop-matplotlib]"""
import base64, gzip, json, sys
from pathlib import Path

spike = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path(__file__).resolve().parent.parent
vendor = spike / "vendor"
DROP = "--drop-matplotlib" in sys.argv
LOCK_TEXT = (vendor / "pyodide/pyodide-lock.json").read_text()
lock = json.loads(LOCK_TEXT)["packages"]
if DROP:  # variant: networkx without its matplotlib/setuptools deps (networkx.drawing is the only user)
    lock["networkx"]["depends"] = ["decorator", "numpy"]
    full = json.loads(LOCK_TEXT); full["packages"] = lock
    LOCK_TEXT = json.dumps(full)

def closure(names):
    seen = []
    def go(n):
        n = n.lower().replace("_", "-")
        if n in seen: return
        for d in lock[n]["depends"]: go(d)
        seen.append(n)
    for n in names: go(n)
    return seen

pkgs = closure(["numpy", "scipy", "scikit-image", "packaging"])
# (published name, path, gzip-in-page?)
assets = [
    ("pyodide.asm.wasm", vendor / "pyodide/pyodide.asm.wasm", True),
    ("pyodide.asm.mjs", vendor / "pyodide/pyodide.asm.mjs", True),
    ("python_stdlib.zip", vendor / "pyodide/python_stdlib.zip", False),
    ("pyodide-lock.json", None, True),
    ("nibabel.whl", next((vendor / "pypi").glob("nibabel-*.whl")), False),
    ("fmriqa.whl", next((vendor / "fmriqa").glob("fmri_qa_core-*.whl")), False),
]
assets += [(lock[n]["file_name"], vendor / "wheels" / lock[n]["file_name"], False) for n in pkgs]

sizes = []
blocks = []
for name, path, gz in assets:
    raw = LOCK_TEXT.encode() if path is None else path.read_bytes()
    data = gzip.compress(raw, 9) if gz else raw
    b64 = base64.b64encode(data).decode()
    sizes.append((name, len(raw), len(data), len(b64)))
    blocks.append(f'<script type="application/octet-stream" data-name="{name}"{" data-gz=1" if gz else ""}>{b64}</script>')

tpl = (spike / "tools/template.html").read_text()
pyjs = (vendor / "pyodide/pyodide.js").read_text()
assert "</script" not in pyjs
html = tpl.replace("__ASSETS__", "\n".join(blocks)).replace("__PYODIDE_JS__", pyjs)
out = spike / ("dist/fmriqa-spike-nomatplotlib.html" if DROP else "dist/fmriqa-spike.html")
out.write_text(html)
(spike / ("dist/sizes-nomatplotlib.json" if DROP else "dist/sizes.json")).write_text(json.dumps({"closure": pkgs, "assets": sizes, "html": len(html.encode())}, indent=1))
print(f"{out}: {len(html.encode())/1e6:.1f} MB")
for n, r, d, b in sorted(sizes, key=lambda s: -s[3]): print(f"{n:70s} raw {r/1e6:6.2f}  stored {d/1e6:6.2f}  b64 {b/1e6:6.2f}")
