"""Write `web/src/generated/contract.json`, what the browser page checks against.

The page is built from this file, so it never restates the dcm2niix flags or
the `--json` schema version. `fmriqa_web.contract()` is the source. It also
returns the package versions, for the page to show; they are left out of this
file because they change with every release and would make it non-deterministic.
`packages/fmri-qa-web/tests/test_contract.py` fails when the
committed file drifts from `render()`.

Run from the workspace root: `uv run python scripts/web_contract.py`.
"""

import json
from pathlib import Path

from fmriqa_web import contract

__all__ = ["OUTPUT", "main", "render"]

OUTPUT = Path(__file__).resolve().parent.parent / "web/src/generated/contract.json"


def render() -> str:
    """Return the contract as the file's exact text: sorted keys, indent 2."""
    stable = {k: v for k, v in contract().items() if k != "versions"}
    return json.dumps(stable, sort_keys=True, indent=2) + "\n"


def main() -> None:
    """Write the file."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
