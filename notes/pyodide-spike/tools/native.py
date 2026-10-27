"""Run fmriqa natively on each phantom; dump measurements + timing as JSON."""
import dataclasses, json, sys, time, warnings
from pathlib import Path
import fmriqa

res = {}
for name in ("small", "large"):
    p = Path(sys.argv[1]) / name / f"{name}.nii.gz"
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        t0 = time.perf_counter()
        scan = fmriqa.QAScan.from_nifti(str(p))
        art = fmriqa.analyze(scan, name=p.name, source=p.name)
        dt = time.perf_counter() - t0
    res[name] = {"seconds": dt, "warnings": [str(x.message) for x in w],
                 "measurements": dataclasses.asdict(art.measurements)}
json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
for k, v in res.items():
    print(k, round(v["seconds"], 2), v["warnings"]); print(v["measurements"])
