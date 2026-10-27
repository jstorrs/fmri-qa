"""Generate the two test phantoms (small = default; large = 64x64x28x200)."""
import sys
from pathlib import Path
from fmriqa_io.testing import write_phantom

out = Path(sys.argv[1])
for sub in ("small", "large"):
    (out / sub).mkdir(parents=True, exist_ok=True)
write_phantom(out / "small", "small")
write_phantom(out / "large", "large", n=64, z=28, t=200)
