"""Write the boot test's series and what native Python makes of it.

`web/e2e/boot.test.mjs` runs `analyze_json` on these bytes in the browser and
compares the record to the one written here by the same function under native
CPython. Writes `phantom.nii.gz`, `phantom.json` (the synthetic phantom of
`fmriqa_io.testing.write_phantom`, seeded) and `native.json` (the parsed
`analyze_json` result, minus the report page) into the directory given.

Run from the workspace root: `uv run python web/scripts/make_boot_fixture.py DIR`.
"""

import json
import sys
from pathlib import Path

from fmriqa_io.testing import write_phantom
from fmriqa_web.bridge import analyze_json

STEM = "phantom"


def main(argv: list[str]) -> None:
    """Write the fixture into `argv[0]`."""
    if len(argv) != 1:
        sys.exit(__doc__)
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    nifti = write_phantom(out, STEM)
    sidecar = out / f"{STEM}.json"
    result = json.loads(analyze_json(nifti.read_bytes(), sidecar.read_bytes(), STEM))
    if result["kind"] != "report":
        sys.exit(f"the fixture does not analyze natively: {result}")
    del result["html"]
    (out / "native.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
