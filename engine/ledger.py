"""Cost ledger — every operation logs (doc, page, field, operation, $, ms).

All cost/throughput numbers in the submission are queries over this ledger;
nothing is hand-calculated. Append-only JSONL.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class CostLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, *, doc_id: str, page_id: str = "", field_name: str = "",
            operation: str, cost_usd: float = 0.0, latency_ms: float = 0.0,
            meta: Optional[dict] = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "doc_id": doc_id, "page_id": page_id, "field": field_name,
            "operation": operation, "cost_usd": round(cost_usd, 8),
            "latency_ms": round(latency_ms, 2), "meta": meta or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    @contextmanager
    def timed(self, *, doc_id: str, operation: str, page_id: str = "",
              field_name: str = "", cost_usd: float = 0.0, meta: Optional[dict] = None):
        """Times a block and logs on exit: `with ledger.timed(...): ...`"""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.log(doc_id=doc_id, page_id=page_id, field_name=field_name,
                     operation=operation, cost_usd=cost_usd,
                     latency_ms=(time.perf_counter() - t0) * 1000, meta=meta)

    # ---- Queries (the cost analysis is built from these) ----

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def summary(self) -> dict:
        """Totals per operation + cost per page."""
        per_op = defaultdict(lambda: {"count": 0, "cost_usd": 0.0, "latency_ms": 0.0})
        pages = set()
        total = 0.0
        for e in self.entries():
            op = per_op[e["operation"]]
            op["count"] += 1
            op["cost_usd"] += e["cost_usd"]
            op["latency_ms"] += e["latency_ms"]
            total += e["cost_usd"]
            if e["page_id"]:
                pages.add((e["doc_id"], e["page_id"]))
        return {
            "total_cost_usd": round(total, 6),
            "pages": len(pages),
            "cost_per_page_usd": round(total / len(pages), 6) if pages else 0.0,
            "per_operation": {k: {"count": v["count"],
                                  "cost_usd": round(v["cost_usd"], 6),
                                  "latency_ms": round(v["latency_ms"], 1)}
                              for k, v in sorted(per_op.items())},
        }
