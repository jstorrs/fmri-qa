"""The committed `web/src/generated/contract.json` matches Python's contract."""

import json

from web_contract import OUTPUT, render

from fmriqa_web import contract


def test_the_committed_contract_is_current() -> None:
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "web/src/generated/contract.json is stale; regenerate it with "
        "`uv run python scripts/web_contract.py`"
    )


def test_the_file_is_deterministic_and_leaves_out_the_versions() -> None:
    text = render()

    assert text.endswith("}\n")
    parsed = json.loads(text)
    assert list(parsed) == sorted(parsed)
    assert parsed == {k: v for k, v in contract().items() if k != "versions"}
