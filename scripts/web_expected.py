"""Write `web/test/fixtures/expected.json`, what the page must make of two studies.

`web/e2e/run.test.mjs` runs each study through the page (dcm2niix WASM, then
`names_json` and `analyze_json` under Pyodide) and compares the stems, records
and failures with the ones written here by native code: `import_dicom` with
native dcm2niix (the binary the launcher uses), then `name_outputs` and
`analyze_series` on those files' bytes, as the page does and as
`packages/fmri-qa-web/tests/test_launcher_parity.py` checks against the
launcher. `packages/fmri-qa-web/tests/test_expected.py` fails when the committed
file drifts from `render()`.

The studies are fmri-qa-io's fixtures: `dicom-qa/` (one series of 12 volumes,
which analyzes) and `dicom/` (two series of 2 volumes, too short to analyze).

Run from the workspace root: `uv run python scripts/web_expected.py`.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import fmriqa_io
from fmriqa_io.convert.dcm2niix import find_dcm2niix
from fmriqa_web import SeriesReport, analyze_series, name_outputs

__all__ = ["OUTPUT", "STUDIES", "main", "render"]

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "web/test/fixtures/expected.json"
STUDIES = tuple(
    f"packages/fmri-qa-io/tests/fixtures/{name}" for name in ("dicom-qa", "dicom")
)
NIFTI = ".nii.gz"


def expected(study: Path, binary: Path) -> list[dict[str, object]]:
    """Return what the page must give for each series of `study`, by stem.

    A report gives its record, a failure its stage and reason; both give the
    filed names of the series' files and the warnings.
    """
    with TemporaryDirectory() as tmp:
        raw = Path(tmp)
        fmriqa_io.import_dicom(study, raw, binary=binary, names="dcm2niix")
        files = {path.name: path.read_bytes() for path in sorted(raw.iterdir())}
    filed = name_outputs(files)
    renamed = {filed.get(name, name): data for name, data in files.items()}

    stems = sorted(n.removesuffix(NIFTI) for n in renamed if n.endswith(NIFTI))
    results: list[dict[str, object]] = []
    for stem in stems:
        result = analyze_series(
            renamed[stem + NIFTI], renamed.get(f"{stem}.json"), stem=stem
        )
        entry: dict[str, object] = {
            "stem": stem,
            "files": sorted(n for n in renamed if _owner(n, stems) == stem),
        }
        if isinstance(result, SeriesReport):
            entry |= {"kind": "report", "record": result.record}
        else:
            entry |= {"kind": "failure", "stage": result.stage, "reason": result.reason}
        results.append(entry | {"warnings": list(result.warnings)})
    return results


def _owner(name: str, stems: list[str]) -> str | None:
    """Return the stem `name` belongs to, by `filing.plan_names`' rule.

    A NIfTI belongs to its own stem; any other file to the longest stem it
    starts with followed by a dot.
    """
    if name.endswith(NIFTI):
        return name.removesuffix(NIFTI)
    return max((s for s in stems if name.startswith(f"{s}.")), key=len, default=None)


def render() -> str:
    """Return the file's exact text: studies by repo-relative path, indent 2."""
    binary = find_dcm2niix()
    document = {study: expected(ROOT / study, binary) for study in STUDIES}
    return json.dumps(document, indent=2, allow_nan=False) + "\n"


def main() -> None:
    """Write the file."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
