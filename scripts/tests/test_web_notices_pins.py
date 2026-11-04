"""The committed notices name what web/package.json pins; needs no vendor or npm.

`packages/fmri-qa-web/tests/test_notices.py` re-renders the whole file, but
needs both; this catches a pin bumped without regenerating the notices.
"""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
NOTICES = (WEB / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
PINS: dict[str, str] = json.loads((WEB / "package.json").read_text("utf-8"))[
    "dependencies"
]
HEADINGS = re.findall(r"^## (.+)$", NOTICES, re.MULTILINE)


def test_every_npm_dependency_has_a_heading_at_its_pinned_version() -> None:
    for name, pin in PINS.items():
        if name == "pyodide":
            expected = f"Pyodide {pin}"
            assert expected in HEADINGS, expected
        elif name == "@niivue/dcm2niix":
            assert any(
                h.startswith("dcm2niix ") and h.endswith(f"(via {name} {pin})")
                for h in HEADINGS
            ), f"no dcm2niix heading via {name} {pin}"
        else:
            assert f"{name} {pin}" in HEADINGS, f"{name} {pin}"


def test_the_pyodide_asm_replacement_is_the_one_vite_config_applies() -> None:
    config = (WEB / "vite.config.mjs").read_text(encoding="utf-8")
    (url,) = re.findall(r"classicPyodideAsm\('([^']*)'\)", config)

    assert f"replaced with the string literal `{json.dumps(url)}`" in NOTICES
