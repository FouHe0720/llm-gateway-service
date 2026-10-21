"""Check raw/derived data and the source snapshot hash without altering observations."""

import csv
import hashlib
import json

from benchmarks.metrics import comparisons, summarize
from benchmarks.runtime import ROOT
from benchmarks.verify import verify_mock
from benchmarks.workloads import DATA


def verify(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    rows = [json.loads(line) for line in (folder / "requests.jsonl").read_text().splitlines()]
    with (folder / "requests.csv").open(newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert len(csv_rows) == len(rows), "CSV records differ from JSONL count"
    for recorded, exported in zip(rows, csv_rows, strict=True):
        assert recorded["request_id"] == exported["request_id"]
        assert recorded["answer"] == exported["answer"]
        assert recorded["latency_ms"] == float(exported["latency_ms"])
    assert len(rows) == manifest["requests"]
    assert len({r["request_id"] for r in rows}) == len(rows)
    assert hashlib.sha256(DATA.read_bytes()).hexdigest() == manifest["tasks_sha256"]
    snapshot = json.loads((folder / "source_snapshot.json").read_text())
    digest = hashlib.sha256()
    for name, content in sorted(snapshot.items()):
        digest.update(name.encode())
        digest.update(content.encode())
    assert digest.hexdigest() == manifest["source_sha256"], (
        "Source snapshot fingerprint mismatch"
    )
    summary = json.loads((folder / "summary.json").read_text())
    assert summarize(rows) == summary, "Summary does not match raw observations"
    assert comparisons(summary) == json.loads((folder / "comparisons.json").read_text())
    if manifest["mode"] == "mock":
        verify_mock(rows)
    print(
        f"{folder.name}: {len(rows)} raw records, source hash and derived statistics verified"
    )


def main():
    folders = [
        p.parent
        for p in (ROOT / "benchmarks/results").glob("*/manifest.json")
        if (p.parent / "summary.json").exists()
        and json.loads(p.read_text()).get("method_version") == 2
    ]
    for folder in folders:
        verify(folder)
    if not folders:
        raise SystemExit("No completed method_version=2 runs found")


if __name__ == "__main__":
    main()
