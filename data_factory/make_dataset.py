"""Dataset factory CLI — Day 2.

    python -m data_factory.make_dataset --n-per-form 25 --seed 42 --out data/generated

Per claim: renders the clean page once, then derives noisy and ugly variants of
the SAME claim (tier-wise accuracy comparison on identical content). Ground
truth carries tier-correct bboxes. Split is at CLAIM level (all tiers of a doc
share a split — no leakage): 40% calibration / 60% test. The test manifest is
sha256-frozen into eval/splits/split_v1.json (committed; data/ is not).

Every degraded page passes the bbox-ink guardrail or generation aborts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from data_factory.generator import generate_claim, flatten_ground_truth
from data_factory.render_cms1500 import render as render_cms1500
from data_factory.generator_ub04 import generate_ub04, flatten_ub04
from data_factory.render_ub04 import render as render_ub04
from data_factory.degrade import degrade, check_bbox_ink

TIERS = ["clean", "noisy", "ugly"]
FORMS = {
    "cms1500": (generate_claim, flatten_ground_truth, render_cms1500),
    "ub04": (generate_ub04, flatten_ub04, render_ub04),
}


def doc_plan(n_per_form: int, seed: int, forms=None) -> list[tuple[str, int, str]]:
    """Deterministic (form, claim_seed, doc_id) plan — the single source of truth
    for what exists at a given (n, seed), independent of rendering."""
    plan = []
    for form in (forms or FORMS):
        for i in range(n_per_form):
            claim_seed = seed * 100_000 + (0 if form == "cms1500" else 50_000) + i
            plan.append((form, claim_seed, f"{form}_{seed}_{i:04d}"))
    return plan


def build(n_per_form: int, seed: int, out: Path, forms=None,
          start: int = 0, end: int | None = None) -> dict:
    manifest = {"master_seed": seed, "tiers": TIERS, "docs": []}
    for form in (forms or list(FORMS)):
        gen, flatten, render = FORMS[form]
        for form_, claim_seed, doc_id in doc_plan(n_per_form, seed, [form])[start:end]:
            claim = gen(claim_seed)
            flat = flatten(claim)
            clean_img, clean_bb = render(claim)

            missing = [k for k in flat if k not in clean_bb and flat[k]]
            if missing:
                raise RuntimeError(f"{doc_id}: fields with no bbox: {missing}")

            for tier in TIERS:
                # NB: never use hash(str) for seeds — randomized per process (PYTHONHASHSEED)
                img, bb, meta = degrade(clean_img, clean_bb, tier,
                                        seed=claim_seed * 10 + TIERS.index(tier))
                bad = check_bbox_ink(img, bb, sample=0)
                if bad:
                    raise RuntimeError(f"bbox ink guardrail FAILED {doc_id}/{tier}: {bad}")
                tdir = out / form / tier
                (tdir / "images").mkdir(parents=True, exist_ok=True)
                (tdir / "ground_truth").mkdir(parents=True, exist_ok=True)
                img.save(tdir / "images" / f"{doc_id}.png")
                gt = {"doc_id": doc_id, "page_id": "p1", "form": form, "tier": tier,
                      "seed": claim_seed, "degradation": meta,
                      "fields": {k: {"value": v, "bbox": [round(c, 1) for c in bb[k]]}
                                 for k, v in flat.items() if v}}
                (tdir / "ground_truth" / f"{doc_id}.json").write_text(
                    json.dumps(gt, indent=2), encoding="utf-8")
            manifest["docs"].append({"doc_id": doc_id, "form": form,
                                     "seed": claim_seed, "n_fields": len(flat)})
    return manifest


def split_claims(manifest: dict, seed: int, calibration_frac: float = 0.4) -> dict:
    """Claim-level split, stratified per form, deterministic. All tiers of a doc
    share its split — no leakage."""
    rng = random.Random(seed * 7 + 1)
    calibration, test = [], []
    for form in sorted({d["form"] for d in manifest["docs"]}):
        ids = sorted(d["doc_id"] for d in manifest["docs"] if d["form"] == form)
        rng.shuffle(ids)
        k = round(len(ids) * calibration_frac)
        calibration += sorted(ids[:k])
        test += sorted(ids[k:])
    test = sorted(test)
    digest = hashlib.sha256("\n".join(test).encode()).hexdigest()
    return {"version": "v1", "master_seed": seed, "calibration_frac": calibration_frac,
            "calibration": sorted(calibration), "test": test,
            "test_sha256": digest, "frozen": True,
            "note": "test set is FROZEN — never tune on it; final numbers only (Day 11)"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-form", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="data/generated")
    ap.add_argument("--splits-out", type=str, default="eval/splits/split_v1.json")
    ap.add_argument("--forms", type=str, default="",
                    help="comma-separated subset (chunked runs); default: all")
    ap.add_argument("--split-only", action="store_true",
                    help="write manifest+split from the deterministic plan, no rendering")
    ap.add_argument("--start", type=int, default=0, help="chunk start index within form")
    ap.add_argument("--end", type=int, default=None, help="chunk end index within form")
    args = ap.parse_args()

    out = Path(args.out)
    forms = [f for f in args.forms.split(",") if f] or None

    if args.split_only:
        plan = doc_plan(args.n_per_form, args.seed)
        manifest = {"master_seed": args.seed, "tiers": TIERS,
                    "docs": [{"doc_id": d, "form": f, "seed": s} for f, s, d in plan]}
    else:
        manifest = build(args.n_per_form, args.seed, out, forms, args.start, args.end)
    out.mkdir(parents=True, exist_ok=True)
    partial = bool(forms) or args.start or args.end is not None
    if partial:
        print(f"Partial chunk written ({len(manifest['docs'])} claims) — "
              "no manifest/split update; run --split-only after all chunks.")
        return
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    split_path = Path(args.splits_out)
    split = split_claims(manifest, args.seed)
    if split_path.exists():
        frozen = json.loads(split_path.read_text(encoding="utf-8"))
        if frozen.get("test_sha256") != split["test_sha256"]:
            raise RuntimeError(
                "Regenerated test split does not match the FROZEN manifest "
                f"({split_path}). Refusing to overwrite a frozen split.")
        print(f"Split matches frozen manifest ({split['test_sha256'][:12]}…) — unchanged.")
    else:
        split_path.parent.mkdir(parents=True, exist_ok=True)
        split_path.write_text(json.dumps(split, indent=2), encoding="utf-8")
        print(f"FROZE test split -> {split_path} (sha256 {split['test_sha256'][:12]}…)")

    pages = len(manifest["docs"]) * len(TIERS)
    fields = sum(d.get("n_fields", 0) for d in manifest["docs"])
    print(f"{'Planned' if args.split_only else 'Wrote'} {len(manifest['docs'])} claims "
          f"x {len(TIERS)} tiers = {pages} pages"
          + (f", {fields} unique ground-truth fields" if fields else "") + f" -> {out}")


if __name__ == "__main__":
    main()
