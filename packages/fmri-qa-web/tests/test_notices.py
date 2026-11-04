"""The committed `web/THIRD_PARTY_NOTICES.md` covers what the page bundles now.

It is rendered from `web/vendor/` and `web/node_modules/` (`make web-vendor`),
so it is skipped when either is missing. The page's build runs
`scripts/web_notices.py --check` first, so a page cannot ship with stale
notices either way, and `scripts/tests/test_web_notices_pins.py` checks the
npm pins without either.
"""

import pytest
from web_notices import NODE_MODULES, OUTPUT, VENDOR, read_inputs, render

pytestmark = pytest.mark.skipif(
    not (VENDOR / "manifest.json").exists()
    or not (NODE_MODULES / "pyodide/pyodide-lock.json").exists(),
    reason="web/vendor or web/node_modules is missing; run `make web-vendor`",
)


def test_the_committed_notices_are_current() -> None:
    assert OUTPUT.read_text(encoding="utf-8") == render(read_inputs()), (
        "web/THIRD_PARTY_NOTICES.md is stale; regenerate it with "
        "`uv run python scripts/web_notices.py`"
    )


def test_the_notices_name_the_runtime_and_the_main_packages() -> None:
    text = OUTPUT.read_text(encoding="utf-8")

    for heading in ("## Pyodide ", "## CPython ", "## dcm2niix ", "## numpy "):
        assert f"\n{heading}" in text, heading
    assert "\n## setuptools " not in text
