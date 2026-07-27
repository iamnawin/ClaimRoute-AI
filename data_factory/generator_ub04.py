"""Synthetic UB-04 (CMS-1450) claim generator — Day 2 core scope (~19 flat fields
+ 3 revenue lines). Fully synthetic, deterministic per seed, valid NPI checksums.
"""
from __future__ import annotations

import random
from faker import Faker

from data_factory.generator import make_npi

REV_CODES = ["0250", "0300", "0450", "0510", "0730"]
REV_HCPCS = {"0250": "", "0300": "80053", "0450": "99284", "0510": "99213", "0730": "93005"}
TYPE_OF_BILL = ["0111", "0131", "0851"]
PAYERS = ["Aetna", "UnitedHealthcare", "Cigna", "BCBS", "Humana", "Medicare"]
ICD10_CODES = ["E11.9", "I10", "M54.5", "J06.9", "K21.9", "F41.1", "N39.0",
               "R51.9", "E78.5", "J45.909"]


_FAKE = Faker()  # module-level: constructing Faker per claim is ~100x slower


def generate_ub04(seed: int) -> dict:
    rng = random.Random(seed)
    fake = _FAKE
    Faker.seed(seed)

    last, first = fake.last_name(), fake.first_name()
    dob = fake.date_of_birth(minimum_age=18, maximum_age=90)
    adm_m, adm_d = rng.randint(1, 5), rng.randint(1, 28)
    stmt_from = f"{adm_m:02d}{adm_d:02d}26"
    stmt_to = f"{adm_m:02d}{min(adm_d + rng.randint(0, 3), 28):02d}26"

    n_lines = rng.randint(2, 3)
    lines, total_cents = [], 0
    for rev in rng.sample(REV_CODES, n_lines):
        units = rng.randint(1, 4)
        cents = rng.randrange(9500, 185000, 25)
        total_cents += cents
        lines.append({
            "rev_code": rev,
            "hcpcs": REV_HCPCS[rev],
            "service_date": stmt_from,
            "units": str(units),
            "charges": f"{cents // 100}.{cents % 100:02d}",
        })

    return {
        "provider_name": f"{fake.city()} General Hospital",
        "patient_control_no": f"PC{rng.randint(1000000, 9999999)}",
        "medical_record_no": f"MR{rng.randint(100000, 999999)}",
        "type_of_bill": rng.choice(TYPE_OF_BILL),
        "federal_tax_no": f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}",
        "statement_from": stmt_from,
        "statement_to": stmt_to,
        "patient_name": f"{last}, {first}",
        "patient_address": fake.street_address(),
        "patient_dob": dob.strftime("%m%d%Y"),
        "patient_sex": rng.choice(["M", "F"]),
        "admission_date": stmt_from,
        "payer_name": rng.choice(PAYERS),
        "provider_npi": make_npi(rng),
        "insured_name": f"{last}, {first}",
        "insured_id": f"{rng.choice('ABCDEFGHJK')}{rng.randint(100000000, 999999999)}",
        "principal_dx": rng.choice(ICD10_CODES),
        "attending_npi": make_npi(rng),
        "total_charges": f"{total_cents // 100}.{total_cents % 100:02d}",
        "revenue_lines": lines,
    }


def flatten_ub04(claim: dict) -> dict:
    flat = {k: v for k, v in claim.items() if k != "revenue_lines"}
    for i, line in enumerate(claim["revenue_lines"], start=1):
        for k, v in line.items():
            flat[f"line{i}_{k}"] = v
    return flat
