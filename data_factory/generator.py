"""Synthetic CMS-1500 claim record generator.

Fully synthetic (zero PHI by construction), deterministic per seed.
NPIs are generated with VALID Luhn check digits (80840 prefix per the NPI spec)
so the pipeline's npi_checksum validator has real work to do.
"""
from __future__ import annotations

import random
from faker import Faker

# Small curated code lists — enough variety for benchmarking, hand-checkable.
CPT_CODES = ["99213", "99214", "99203", "99204", "80053", "85025", "93000",
             "71046", "97110", "90837", "20610", "36415"]
ICD10_CODES = ["E11.9", "I10", "M54.5", "J06.9", "K21.9", "F41.1", "N39.0",
               "M25.561", "R51.9", "E78.5", "J45.909", "Z00.00"]
PLACE_OF_SERVICE = ["11", "22", "21", "12"]
RELATIONSHIPS = ["Self", "Spouse", "Child", "Other"]
PLANS = ["Aetna PPO", "UnitedHealth Choice", "Cigna OAP", "BCBS Standard",
         "Humana Gold", "Medicare Part B"]


def luhn_check_digit(digits: str) -> int:
    """Luhn check digit for a digit string (doubling from the rightmost)."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:          # rightmost digit of the base gets doubled
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def make_npi(rng: random.Random) -> str:
    """Valid 10-digit NPI: 9 base digits (leading 1 or 2), Luhn over '80840' + base."""
    base = str(rng.choice([1, 2])) + "".join(str(rng.randint(0, 9)) for _ in range(8))
    return base + str(luhn_check_digit("80840" + base))


def validate_npi(npi: str) -> bool:
    """Reference implementation for tests (the engine validator mirrors this)."""
    if len(npi) != 10 or not npi.isdigit():
        return False
    return luhn_check_digit("80840" + npi[:9]) == int(npi[9])


_FAKE = Faker()  # module-level: constructing Faker per claim is ~100x slower


def generate_claim(seed: int) -> dict:
    """One synthetic CMS-1500 claim as a flat ground-truth dict."""
    rng = random.Random(seed)
    fake = _FAKE
    Faker.seed(seed)

    patient_last, patient_first = fake.last_name(), fake.first_name()
    dob = fake.date_of_birth(minimum_age=18, maximum_age=85)
    self_insured = rng.random() < 0.6
    relationship = "Self" if self_insured else rng.choice(RELATIONSHIPS[1:])
    insured_name = (f"{patient_last}, {patient_first}" if self_insured
                    else f"{fake.last_name()}, {fake.first_name()}")

    n_dx = rng.randint(1, 4)
    dx = rng.sample(ICD10_CODES, n_dx)

    n_lines = rng.randint(1, 3)
    rendering_npi = make_npi(rng)
    lines, total_cents = [], 0
    svc_year = 2026
    for _ in range(n_lines):
        month, day = rng.randint(1, 6), rng.randint(1, 28)
        date = f"{month:02d} {day:02d} {svc_year % 100:02d}"   # CMS-1500 MM DD YY style
        units = rng.randint(1, 3)
        charge_cents = rng.randrange(4500, 42500, 25) * units
        total_cents += charge_cents
        lines.append({
            "date_from": date, "date_to": date,
            "place_of_service": rng.choice(PLACE_OF_SERVICE),
            "cpt_code": rng.choice(CPT_CODES),
            "diagnosis_pointer": chr(ord("A") + rng.randrange(n_dx)),
            "charges": f"{charge_cents // 100}.{charge_cents % 100:02d}",
            "units": str(units),
            "rendering_npi": rendering_npi,
        })

    claim = {
        "insured_id": f"{rng.choice('ABCDEFGHJK')}{rng.randint(100000000, 999999999)}",
        "patient_name": f"{patient_last}, {patient_first}",
        "patient_dob": dob.strftime("%m %d %Y"),
        "patient_sex": rng.choice(["M", "F"]),
        "insured_name": insured_name,
        "patient_address": fake.street_address(),
        "patient_city": fake.city(),
        "patient_state": fake.state_abbr(),
        "patient_zip": fake.zipcode(),
        "patient_relationship": relationship,
        "insurance_plan_name": rng.choice(PLANS),
        "federal_tax_id": f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}",
        "patient_account_no": f"ACCT{rng.randint(10000, 99999)}",
        "amount_paid": "0.00",
        "total_charge": f"{total_cents // 100}.{total_cents % 100:02d}",
        "billing_provider_name": f"{fake.last_name()} Medical Group",
        "billing_provider_npi": make_npi(rng),
        "referring_provider_npi": make_npi(rng),
        "service_lines": lines,
    }
    for i, code in enumerate(dx):
        claim[f"diagnosis_code_{chr(ord('a') + i)}"] = code
    return claim


def flatten_ground_truth(claim: dict) -> dict:
    """Flatten service lines to line{N}_{field} keys — the benchmark's field namespace."""
    flat = {k: v for k, v in claim.items() if k != "service_lines"}
    for i, line in enumerate(claim["service_lines"], start=1):
        for k, v in line.items():
            flat[f"line{i}_{k}"] = v
    return flat
