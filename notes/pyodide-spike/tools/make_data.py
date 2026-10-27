"""Generate the two test phantoms (small = conftest default; large = 64x64x28x200)."""
import sys
from pathlib import Path
sys.path.insert(0, "/home/claude/fmri-qa-wip/packages/fmri-qa-core/tests")
from conftest import _write_phantom  # noqa: E402

out = Path(sys.argv[1])
for sub in ("small", "large"):
    (out / sub).mkdir(parents=True, exist_ok=True)
_write_phantom(out / "small", name="small")
_write_phantom(out / "large", name="large", n=64, z=28, t=200)
