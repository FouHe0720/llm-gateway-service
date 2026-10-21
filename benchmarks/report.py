"""Self-contained offline dashboard. Empty cells stay untested, no imputed observations."""

import csv
import json
from pathlib import Path

from benchmarks.runtime import ROOT


def build_report():
    runs = []
    for path in sorted((ROOT / "benchmarks/results").glob("*/manifest.json")):
        folder = path.parent
        if not (folder / "summary.json").exists():
            continue
        manifest = json.loads(path.read_text())
        gpu_samples = []
        resource_path = folder / "resources.csv"
        if resource_path.exists():
            with resource_path.open() as f:
                gpu_samples = [
                    [float(r["time_s"]), float(r["gpu_used_mib"])]
                    for r in csv.DictReader(f)
                    if r.get("gpu_used_mib")
                ]
        runs.append(
            {
                "manifest": manifest,
                "gpu_samples": gpu_samples,
                "comparisons": json.loads((folder / "comparisons.json").read_text())
                if (folder / "comparisons.json").exists()
                else [],
                "summary": json.loads((folder / "summary.json").read_text()),
                "variability": json.loads((folder / "variability.json").read_text()),
            }
        )
    # The latest run of each mode is displayed; older raw artifacts remain linked and untouched.
    selected = {}
    for run in runs:
        selected[run["manifest"]["mode"]] = run
    data = json.dumps({"runs": list(selected.values())}, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    template = (Path(__file__).with_name("report_template.html")).read_text()
    target = ROOT / "benchmarks/reports/index.html"
    target.parent.mkdir(exist_ok=True)
    target.write_text(template.replace("__DATA__", data))
    return target


if __name__ == "__main__":
    print(build_report().relative_to(ROOT))
