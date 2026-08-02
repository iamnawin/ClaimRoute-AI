"""ONE guarded, paid OpenRouter call against ONE freshly generated synthetic crop.

    python scripts/openrouter_live_smoke.py

This is the only entry point in the repo that can spend money, and it is built so
that spending nothing is the default outcome. It refuses to run unless ALL of:

    live_provider.enabled: true      in configs/multimodal_providers.yaml
    CLAIMROUTE_MULTIMODAL_ENABLED=true
    CLAIMROUTE_LIVE_PROVIDER_TEST=true
    OPENROUTER_API_KEY=<a real key>

and even then engine/escalation/live_policy.py must independently authorise the
call against the model allowlist and the session and document budgets.

EXACTLY ONE CALL. There is no retry loop here and no second attempt on failure:
a failed paid call is a result to read, not a reason to buy another one. The
adapter's own transport retries are disabled for this run for the same reason.

DATA BOUNDARY: the crop is rendered in this process from the synthetic data
factory using a seed reserved for this script. It is not read from
data/generated, not from the organiser sample, and not from any development or
holdout split. Nothing that could be PHI is ever sent.

WHAT IS PRINTED: shape, cost and provenance only. The API key, the crop
contents, the expected value and any transcribed value are never printed — the
receipt reports THAT a value came back and whether it validated, never what it
said.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_factory.generator import generate_claim                    # noqa: E402
from data_factory.render_cms1500 import render                       # noqa: E402
from engine.escalation.client import (MultimodalClient, load_config,  # noqa: E402
                                      request_from_page)
from engine.escalation.live_policy import LiveCallGovernor, LiveDecision  # noqa: E402
from engine.escalation.providers import build_provider               # noqa: E402
from engine.schemas import Verdict                                   # noqa: E402
from engine.validators.registry import validate_field                # noqa: E402

# Seed reserved for this script, shared with no dataset, split, or committed
# artifact — so the crop is genuinely new every time and traceable to nothing.
SMOKE_SEED = 90211
SMOKE_FIELD = "provider_npi"
FALLBACK_FIELD = "billing_provider_npi"


def _fail(message: str) -> int:
    print(f"\nREFUSED: {message}")
    print("No provider call was made. Nothing was spent.")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--field", default=SMOKE_FIELD,
                    help=f"field to read (default {SMOKE_FIELD})")
    ap.add_argument("--seed", type=int, default=SMOKE_SEED)
    ap.add_argument("--receipt", default="", metavar="PATH",
                    help="write the JSON receipt here (never contains a value)")
    ap.add_argument("--balance", action="store_true",
                    help="additionally query the OpenRouter credit balance "
                         "(a SECOND network call; off by default)")
    args = ap.parse_args()

    config = load_config()
    live = config.get("live_provider") or {}

    # ------------------------------------------------ build the synthetic crop
    claim = generate_claim(args.seed)
    page, bboxes = render(claim)
    field = args.field if args.field in bboxes else FALLBACK_FIELD
    if field not in bboxes:
        return _fail(f"synthetic renderer emitted neither {args.field!r} nor "
                     f"{FALLBACK_FIELD!r}")

    request = request_from_page(page, bboxes[field], field,
                                doc_id=f"smoke_{args.seed}", page_id="p1",
                                synthetic=True)

    governor = LiveCallGovernor(config)
    model = governor.model
    limits = governor.limits

    # ------------------------------------------------------- pre-call disclosure
    # Deliberately minimal. Everything here is metadata; none of it is the key,
    # the pixels, or the value we are about to ask for.
    print("=" * 68)
    print("OpenRouter guarded smoke test — ONE paid call")
    print("=" * 68)
    print(f"  model id                 : {model}")
    print(f"  crop dimensions          : {request.crop.width} x {request.crop.height} px")
    print(f"  page fraction            : {request.crop.page_fraction:.4%}")
    print(f"  field                    : {field}")
    print(f"  field type               : {request.expectation}")
    print(f"  max calls (field/page/doc/batch): "
          f"{limits.max_calls_per_field}/{limits.max_calls_per_page}/"
          f"{limits.max_calls_per_document}/{limits.max_calls_per_batch}")
    print(f"  max paid attempts / field: {limits.max_paid_attempts_per_field}")
    print(f"  max session spend        : ${limits.max_session_spend_usd:.4f}")
    print(f"  max document spend       : ${limits.max_document_spend_usd:.4f}")
    print("=" * 68)

    # ------------------------------------------------------------- authorise
    spend_before = governor.session_spend_usd
    outcome = governor.authorize(request, model=model)
    print(f"\ngovernor decision          : {outcome.decision.value}")
    print(f"reason                     : {outcome.reason}")
    print(f"request fingerprint        : {outcome.fingerprint}")

    if not outcome.allowed:
        governor.release()
        print(f"route to human review      : {outcome.route_to_human_review}")
        return _fail(f"live-call policy refused the request "
                     f"({outcome.decision.value})")

    # ----------------------------------------------------------- one real call
    provider = build_provider(governor.provider_name,
                              (config.get("providers") or {})[governor.provider_name])
    # max_attempts=1: the adapter must not buy a second answer on our behalf.
    call_config = dict(config)
    call_config["transport"] = {**(config.get("transport") or {}), "max_attempts": 1,
                                "retry_on_invalid_response": False}

    client = MultimodalClient(config=call_config, provider=provider, enabled=True)
    print("\ncalling provider (exactly once) ...")
    result = client.read_field(request)
    governor.record_call(outcome, result)
    spend_after = governor.session_spend_usd

    # ------------------------------------------------- healthcare re-validation
    # The answer re-enters the ordinary validators, exactly as an OCR candidate
    # would. A paid answer gets no special standing.
    stamps = []
    if result.answer is not None and result.answer.value:
        stamps = validate_field(field, result.answer.value, {field: result.answer.value})
    validator_summary = [{"validator": s.validator, "verdict": s.verdict.value,
                          "detail": s.detail} for s in stamps]
    validators_passed = bool(stamps) and all(
        s.verdict is not Verdict.FAIL for s in stamps)

    # ------------------------------------------------------------ the receipt
    cost = result.cost
    usage = result.usage
    receipt = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": result.provider,
        "requested_model": model,
        "actual_model_used": result.actual_model or model,
        "model_substituted": result.model_substituted,
        "http_or_provider_outcome": result.error or "ok",
        "error_detail": result.error_detail,
        "called_provider": result.called_provider,
        "attempts": result.attempts,
        "structured_response_valid": result.answer is not None and not result.rejects,
        "rejects": list(result.rejects),
        "visible": result.answer.visible if result.answer else None,
        "confidence": result.answer.confidence if result.answer else None,
        "grounding_result": ("accepted" if result.ok else
                             ("rejected: " + "; ".join(result.rejects)
                              if result.rejects else "no answer")),
        "healthcare_validators": validator_summary,
        "healthcare_validators_passed": validators_passed,
        "governor_outcome": outcome.to_dict(),
        "usage": usage.to_dict(),
        "cost": cost.to_dict(),
        "provider_reported_cost_usd": cost.reported_usd,
        "locally_calculated_cost_usd": cost.measured_usd,
        "locally_calculated_cost_basis": (
            f"configs/prices.yaml row {cost.price_row!r}"
            if cost.measured_usd is not None else "no verified price row; not computed"),
        "latency_ms": result.latency_ms,
        "provider_latency_ms": result.provider_latency_ms,
        "session_spend_before_usd": round(spend_before, 8),
        "session_spend_after_usd": round(spend_after, 8),
        "session": governor.session_report(),
        "raw_response_sha256": result.raw_sha256,
        "raw_response_persisted": False,
        "crop": request.crop.safe_dict(),
        "openrouter_balance_usd": None,
        "external_calls_made": 1,
    }

    if args.balance:
        balance, extra = _credit_balance()
        receipt["openrouter_balance_usd"] = balance
        receipt["external_calls_made"] += extra

    _print_receipt(receipt)

    if args.receipt:
        Path(args.receipt).parent.mkdir(parents=True, exist_ok=True)
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n",
                                      encoding="utf-8")
        print(f"\nreceipt written to {args.receipt}")

    print("\nStopping after one call, by design. Re-running requires a "
          "deliberate re-invocation.")
    return 0 if result.error is None else 1


def _credit_balance() -> tuple:
    """-> (balance_usd_or_None, extra_calls_made). Never raises.

    Opt-in because it is a SECOND network call, and a receipt that claims one
    external call must be able to say so truthfully.
    """
    import urllib.error
    import urllib.request

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None, 0
    req = urllib.request.Request("https://openrouter.ai/api/v1/credits",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode()).get("data") or {}
        total, used = data.get("total_credits"), data.get("total_usage")
        if isinstance(total, (int, float)) and isinstance(used, (int, float)):
            return round(float(total) - float(used), 8), 1
        return None, 1
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        # Not retrievable safely — reported as unknown, never guessed.
        return None, 1


def _print_receipt(r: dict) -> None:
    u, c = r["usage"], r["cost"]
    print("\n" + "=" * 68)
    print("RECEIPT")
    print("=" * 68)
    rows = [
        ("provider", r["provider"]),
        ("requested model", r["requested_model"]),
        ("actual model used", r["actual_model_used"]),
        ("model substituted", r["model_substituted"]),
        ("outcome", r["http_or_provider_outcome"]),
        ("attempts", r["attempts"]),
        ("structured response valid", r["structured_response_valid"]),
        ("visible", r["visible"]),
        ("confidence", r["confidence"]),
        ("grounding", r["grounding_result"]),
        ("healthcare validators", r["healthcare_validators_passed"]),
        ("governor outcome", r["governor_outcome"]["decision"]),
        ("input tokens", u["input_tokens"]),
        ("output tokens", u["output_tokens"]),
        ("image tokens", u["image_tokens"]),
        ("cached tokens", u["cached_tokens"]),
        ("reasoning tokens", u["reasoning_tokens"]),
        ("cost basis", c["basis"]),
        ("provider-reported cost", _usd(r["provider_reported_cost_usd"])),
        ("locally calculated cost", _usd(r["locally_calculated_cost_usd"])),
        ("latency ms", r["latency_ms"]),
        ("session spend before", _usd(r["session_spend_before_usd"])),
        ("session spend after", _usd(r["session_spend_after_usd"])),
        ("session remaining", _usd(r["session"]["session_remaining_usd"])),
        ("openrouter balance", _usd(r["openrouter_balance_usd"])),
        ("raw response sha256", r["raw_response_sha256"][:32] or "n/a"),
        ("raw response persisted", r["raw_response_persisted"]),
        ("external calls made", r["external_calls_made"]),
    ]
    for label, value in rows:
        print(f"  {label:<26}: {value}")
    for stamp in r["healthcare_validators"]:
        print(f"    validator {stamp['validator']:<20} {stamp['verdict']}")


def _usd(value) -> str:
    return "unknown" if value is None else f"${value:.8f}"


if __name__ == "__main__":
    raise SystemExit(main())
