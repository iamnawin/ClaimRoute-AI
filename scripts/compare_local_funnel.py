"""Diff two local-funnel measurements produced by measure_local_funnel.py.

    python scripts/compare_local_funnel.py baseline.json after.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _pct(value) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _delta(before, after) -> str:
    if before is None or after is None:
        return "     -"
    return f"{(after - before) * 100:+6.1f}pp"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()

    before = {row["family"]: row
              for row in json.loads(args.baseline.read_text())["families"]}
    after = {row["family"]: row
             for row in json.loads(args.after.read_text())["families"]}

    header = (f"{'family':26s} {'coverage':>19s} {'primary':>19s} "
              f"{'retry':>19s} {'unresolved':>14s}")
    print(header)
    print("-" * len(header))
    for family in after:
        old, new = before.get(family), after[family]
        if old is None:
            continue
        print(f"{family:26s} "
              f"{_pct(old['validated_local_coverage']):>7s}->"
              f"{_pct(new['validated_local_coverage']):>7s}"
              f"{_delta(old['validated_local_coverage'], new['validated_local_coverage'])} "
              f"{_pct(old['primary_ocr_resolution_rate']):>7s}->"
              f"{_pct(new['primary_ocr_resolution_rate']):>7s}"
              f"{_delta(old['primary_ocr_resolution_rate'], new['primary_ocr_resolution_rate'])} "
              f"{_pct(old['retry_contribution_rate']):>7s}->"
              f"{_pct(new['retry_contribution_rate']):>7s}"
              f"{_delta(old['retry_contribution_rate'], new['retry_contribution_rate'])} "
              f"{old['unresolved_fields']:5d}->{new['unresolved_fields']:5d} "
              f"{new['unresolved_fields'] - old['unresolved_fields']:+4d}")

    for label, report in (("baseline", args.baseline), ("after", args.after)):
        data = json.loads(report.read_text())
        latency = [row["latency_ms"] for row in data["documents"]]
        print(f"\n{label}: {data['elapsed_seconds']}s wall, "
              f"mean document latency {sum(latency) / max(1, len(latency)):.0f} ms, "
              f"external calls {data['external_calls_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
