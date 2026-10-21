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
    # Latest observation per mode/experiment; a separate real C run must not hide D/E.
    latest = {}
    for run in runs:
        for row in run["summary"]:
            latest[(row["mode"], row["experiment"])] = run["manifest"]["run_id"]
    selected = {}
    for run in runs:
        rid = run["manifest"]["run_id"]
        summary = [r for r in run["summary"] if latest[(r["mode"], r["experiment"])] == rid]
        if summary:
            selected[rid] = {
                **run,
                "summary": summary,
                "variability": [
                    r for r in run["variability"] if latest[(r["mode"], r["experiment"])] == rid
                ],
            }
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
