"""Dataset factory CLI.

    python -m data_factory.make_dataset --n 10 --seed 42 --out data/raw/cms1500

Emits per page: page image (PNG), ground-truth JSON (values + bboxes), and a
manifest tying everything to the master seed for exact reproducibility.
Degradation tiers (noisy/ugly) arrive on Day 2 — this produces the clean tier.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_factory.generator import generate_claim, flatten_ground_truth
from data_factory.render_cms1500 import render


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="data/raw/cms1500")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "ground_truth").mkdir(parents=True, exist_ok=True)

    manifest = {"form": "cms1500", "tier": "clean", "master_seed": args.seed, "pages": []}
    for i in range(args.n):
        page_seed = args.seed * 100_000 + i
        doc_id = f"cms1500_{args.seed}_{i:04d}"
        claim = generate_claim(page_seed)
        img, bboxes = render(claim)
        img.save(out / "images" / f"{doc_id}.png")

        flat = flatten_ground_truth(claim)
        gt = {"doc_id": doc_id, "page_id": "p1", "form": "cms1500",
              "seed": page_seed, "tier": "clean",
              "fields": {k: {"value": v, "bbox": bboxes.get(k)} for k, v in flat.items()}}
        (out / "ground_truth" / f"{doc_id}.json").write_text(
            json.dumps(gt, indent=2), encoding="utf-8")
        manifest["pages"].append({"doc_id": doc_id, "seed": page_seed,
                                  "n_fields": len(flat)})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {args.n} pages -> {out} "
          f"({sum(p['n_fields'] for p in manifest['pages'])} ground-truth fields)")


if __name__ == "__main__":
    main()
