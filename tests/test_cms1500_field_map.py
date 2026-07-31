"""The official CMS-1500 mapping spec must stay derivable from the code it maps.

`eval/official/cms1500_field_map.yaml` is authored before any crop coordinate, so
a wrong name in it does not raise at runtime — `engine.governor.field_policy()`
silently returns defaults and the field is mis-governed. These tests re-derive
every mechanical claim in the file from the same functions the pipeline calls,
so drift between the spec and the engine fails here rather than in a scored run.

Synthetic placeholder values only; no organiser data is read.
"""
from __future__ import annotations

import re

import yaml

from engine.governor import field_policy
from eval.official.evaluator import claimroute_expected
from eval.official.normalization import classify_field
from eval.official.parsers import OfficialRecord

MAP = yaml.safe_load(open("eval/official/cms1500_field_map.yaml", encoding="utf-8"))
ROWS = MAP["fields"]
POLICY = yaml.safe_load(open("configs/field_policy.yaml", encoding="utf-8"))

STATUSES = {"mapped_supported", "blank_but_valid", "not_printed",
            "unsupported_schema", "ambiguous_spec"}
# Statuses whose rows describe a name that really reaches compare_fields.
SCOREABLE = {"mapped_supported", "blank_but_valid"}

# Field names produced by parse_nsf_bytes, mirrored here so a parser change that
# adds or drops a field breaks this test instead of silently orphaning the spec.
NSF_FIELDS = [
    "patient_control_no", "patient_name", "patient_dob", "patient_sex",
    "patient_address", "patient_city", "patient_state", "patient_zip",
    "insurance_plan_name", "patient_relationship", "insured_id", "insured_name",
    "referring_npi", "admission_date", "diagnosis_1", "diagnosis_2",
    "diagnosis_3", "diagnosis_4", "federal_tax_id", "provider_npi",
    "provider_name", "patient_account_no", "total_charge",
]
NSF_LINE_FIELDS = ["service_from", "service_to", "place_of_service",
                   "procedure_code", "modifiers", "charge", "diagnosis_pointer",
                   "units"]


def _evaluated_names(line_count: int = 3) -> set[str]:
    """The real NSF320 name space, via the same call the benchmark makes."""
    record = OfficialRecord(
        1, "NSF320", {name: "X" for name in NSF_FIELDS},
        [{name: "X" for name in NSF_LINE_FIELDS} for _ in range(line_count)],
    )
    return set(claimroute_expected(record))


def _expand(claimroute_field: str) -> list[str]:
    """Expand a `line{n}_` spec name into the concrete per-line names."""
    if claimroute_field is None:
        return []
    if "{n}" in claimroute_field:
        return [claimroute_field.replace("{n}", str(n)) for n in (1, 2, 3)]
    return [claimroute_field]


def _spec_rows(status_filter: set[str]) -> list[dict]:
    return [row for row in ROWS if row["status"] in status_filter]


# --------------------------------------------------------------------------
# Completeness: the spec covers the real name space, in both directions
# --------------------------------------------------------------------------

def test_every_evaluated_name_is_covered_by_the_mapping():
    """No scored field may be missing from the spec."""
    covered = {name for row in _spec_rows(SCOREABLE)
               for name in _expand(row["claimroute_field"])}
    missing = _evaluated_names() - covered
    assert not missing, f"evaluated but unmapped: {sorted(missing)}"


def test_every_scoreable_mapping_row_names_a_real_evaluated_field():
    """The reverse direction: the spec may not invent names that never occur."""
    evaluated = _evaluated_names()
    for row in _spec_rows(SCOREABLE):
        for name in _expand(row["claimroute_field"]):
            assert name in evaluated, (
                f"{row['claimroute_field']} is marked {row['status']} but never "
                f"reaches compare_fields")


def test_evaluated_field_count_in_meta_matches_the_code():
    assert MAP["meta"]["evaluated_field_count"] == len(_evaluated_names())


def test_service_line_cap_recorded_in_meta_is_the_real_cap():
    """More supplied lines must not produce more evaluated lines."""
    prefixes = {name.split("_")[0] for name in _evaluated_names(line_count=6)
                if name.startswith("line")}
    assert len(prefixes) == MAP["meta"]["service_line_cap"] == 3


# --------------------------------------------------------------------------
# No duplicate mappings
# --------------------------------------------------------------------------

def test_no_duplicate_claimroute_fields():
    seen: dict[str, str] = {}
    for row in ROWS:
        for name in _expand(row["claimroute_field"]):
            assert name not in seen, (
                f"{name} mapped twice: {seen[name]} and {row['official_field']}")
            seen[name] = str(row["official_field"])


def test_no_duplicate_official_fields():
    officials = [row["official_field"] for row in ROWS
                 if row["official_field"] is not None]
    assert len(officials) == len(set(officials)), "duplicate official_field rows"


# --------------------------------------------------------------------------
# Every declared attribute matches what the engine actually returns
# --------------------------------------------------------------------------

def test_normalization_family_matches_classify_field():
    for row in _spec_rows(SCOREABLE):
        for name in _expand(row["claimroute_field"]):
            assert classify_field(name) == row["normalization"], (
                f"{name}: spec says {row['normalization']}, "
                f"classify_field says {classify_field(name)}")


def test_declared_normalization_families_are_real():
    valid = {"text", "date", "money", "quantity", "code", None}
    for row in ROWS:
        assert row["normalization"] in valid, row["normalization"]


def test_validators_criticality_and_blankness_match_field_policy():
    for row in _spec_rows(SCOREABLE):
        for name in _expand(row["claimroute_field"]):
            policy = field_policy(name)
            assert policy["required_validators"] == row["validators"], name
            assert policy["criticality"] == row["criticality"], name
            assert policy["optional"] == row["may_be_blank"], name


def test_declared_validators_exist_in_the_registry():
    """A typo'd validator name would otherwise never run and never complain.

    `validate_field` turns an unknown name into an INAPPLICABLE stamp rather
    than raising, so a misspelled validator silently stops guarding its field.
    """
    from engine.validators.registry import _VALIDATORS

    for row in ROWS:
        for validator in row["validators"]:
            assert validator in _VALIDATORS, f"unknown validator {validator!r}"


def test_status_and_box_ambiguity_are_independent_axes():
    """A field may be fully scored and still sit in a contested box.

    Regression guard: the first draft collapsed these, marking a scored field
    `ambiguous_spec` and dropping it out of the completeness check.
    """
    evaluated = _evaluated_names()
    contested = [row for row in ROWS if row["box_ambiguous"]]
    assert contested, "expected at least one contested-box field"
    scored_and_contested = [
        row for row in contested
        if any(name in evaluated for name in _expand(row["claimroute_field"]))]
    assert scored_and_contested, (
        "box_ambiguous must be able to coexist with a scored status")
    for row in ROWS:
        assert isinstance(row["box_ambiguous"], bool), row["official_field"]


def test_ambiguous_spec_rows_have_policy_but_no_expected_value():
    """`ambiguous_spec` means extractable-but-unscoreable, not merely unclear."""
    evaluated = _evaluated_names()
    for row in ROWS:
        if row["status"] != "ambiguous_spec":
            continue
        for name in _expand(row["claimroute_field"]):
            assert name not in evaluated, (
                f"{name} is marked ambiguous_spec but IS scored; use "
                f"box_ambiguous for a scored field with an uncertain box")
            assert field_policy(name)["required_validators"] or \
                field_policy(name)["criticality"], name


def test_blank_but_valid_rows_are_exactly_the_optional_policy_fields():
    """`optional: true` fields are never escalated, so the two must agree."""
    for row in _spec_rows(SCOREABLE):
        for name in _expand(row["claimroute_field"]):
            expected = "blank_but_valid" if field_policy(name)["optional"] \
                else "mapped_supported"
            assert row["status"] == expected, (
                f"{name}: status {row['status']} contradicts "
                f"optional={field_policy(name)['optional']}")


# --------------------------------------------------------------------------
# Generated service-line names
# --------------------------------------------------------------------------

def test_service_line_rows_use_the_generated_name_form():
    for row in ROWS:
        if row["repeats"] and row["claimroute_field"] is not None:
            assert "{n}" in row["claimroute_field"], row["claimroute_field"]


def test_generated_line_names_resolve_through_the_template_not_by_accident():
    """`line{n}_x` must resolve to service_line_template.x, not to defaults."""
    template = POLICY["service_line_template"]
    for row in ROWS:
        if not (row["repeats"] and row["claimroute_field"]):
            continue
        suffix = re.fullmatch(r"line\{n\}_(\w+)", row["claimroute_field"]).group(1)
        assert suffix in template, f"{suffix} absent from service_line_template"
        for name in _expand(row["claimroute_field"]):
            assert field_policy(name)["criticality"] == \
                {**POLICY["defaults"], **template[suffix]}["criticality"], name


def test_every_line_index_resolves_identically():
    """Line 1, 2 and 3 must be governed the same; only the index differs."""
    for row in ROWS:
        if not (row["repeats"] and row["claimroute_field"]):
            continue
        policies = [field_policy(name) for name in _expand(row["claimroute_field"])]
        assert all(p == policies[0] for p in policies), row["claimroute_field"]


# --------------------------------------------------------------------------
# Structural integrity of the document itself
# --------------------------------------------------------------------------

def test_every_row_declares_the_required_keys():
    required = {"official_field", "claimroute_field", "cms1500_box", "field_family",
                "normalization", "validators", "criticality", "may_be_blank",
                "printed_on_form", "schema_supported", "repeats", "status",
                "box_ambiguous", "present_in_dev_documents"}
    for row in ROWS:
        assert required <= set(row), f"{row.get('official_field')}: missing "\
                                     f"{sorted(required - set(row))}"


def test_statuses_are_from_the_declared_vocabulary():
    for row in ROWS:
        assert row["status"] in STATUSES, row["status"]


def test_unsupported_and_ambiguous_rows_are_not_silently_scoreable():
    """A row excluded from scoring must not also appear in the evaluated space."""
    evaluated = _evaluated_names()
    for row in ROWS:
        if row["status"] != "unsupported_schema":
            continue
        for name in _expand(row["claimroute_field"]):
            assert name not in evaluated, (
                f"{name} is marked unsupported but IS evaluated")


def test_presence_counts_are_within_the_development_set_size():
    for row in ROWS:
        assert 0 <= row["present_in_dev_documents"] <= 3, row["official_field"]


def test_presence_counts_match_the_measured_phi_safe_rows():
    """The counts must be measured, not asserted.

    Reads only field NAMES and booleans from the aggregate rows, and only for
    the three development source IDs. Skips if the rows are unavailable, since
    they are a generated artifact rather than a committed fixture.
    """
    import collections
    import json
    import pathlib

    rows_path = pathlib.Path("eval/official/results/official_sample_rows.jsonl")
    if not rows_path.exists():
        return  # generated artifact absent; the spec is still self-consistent
    development = set(MAP["meta"]["development_source_ids"])
    counts: collections.Counter = collections.Counter()
    for line in rows_path.read_text().splitlines():
        row = json.loads(line)
        if row.get("source_id") not in development:
            continue
        for name in {result["field_name"] for result in row["field_results"]}:
            counts[name] += 1

    for row in ROWS:
        field = row["claimroute_field"]
        if field is None:
            assert row["present_in_dev_documents"] == 0, row["official_field"]
            continue
        # Repeating rows declare the count for their first line instance.
        name = field.replace("{n}", "1")
        assert counts.get(name, 0) == row["present_in_dev_documents"], (
            f"{name}: measured {counts.get(name, 0)}, "
            f"spec declares {row['present_in_dev_documents']}")


def test_holdout_documents_are_not_referenced_anywhere_in_the_spec():
    """The spec must not name a holdout item, which would imply it was opened.

    The IDs are read from the frozen split manifest rather than duplicated
    here, so adding an item to the holdout automatically extends this guard.
    """
    import json
    import pathlib

    split = json.loads(pathlib.Path(
        "eval/official/splits/tier_a_split_v1.json").read_text())
    assert split["split_id"] == MAP["meta"]["split_id"]
    holdout = {item["source_id"] for item in split["holdout"]}
    holdout |= {item["source_id"] for item in split["excluded"]}
    assert holdout, "split manifest declared no holdout items"

    for path in ("eval/official/cms1500_field_map.yaml",
                 "docs/evaluation/official_cms1500_mapping.md"):
        text = pathlib.Path(path).read_text(encoding="utf-8")
        leaked = sorted(sid for sid in holdout if sid in text)
        assert not leaked, f"{path} references holdout items: {leaked}"

    assert MAP["meta"]["holdout_untouched"] is True


def test_development_ids_in_the_spec_match_the_frozen_split():
    """The spec may only claim development items the manifest actually lists."""
    import json
    import pathlib

    split = json.loads(pathlib.Path(
        "eval/official/splits/tier_a_split_v1.json").read_text())
    assert set(MAP["meta"]["development_source_ids"]) == \
        {item["source_id"] for item in split["development"]}


# --------------------------------------------------------------------------
# Proof-field selection
# --------------------------------------------------------------------------

def _row_for(claimroute_field: str) -> dict:
    for row in ROWS:
        if claimroute_field in _expand(row["claimroute_field"]):
            return row
    raise AssertionError(f"{claimroute_field} absent from the mapping")


def test_five_proof_fields_are_selected():
    assert len(MAP["proof_fields"]["selected"]) == 5


def test_proof_fields_are_scored_unambiguous_and_never_legitimately_blank():
    """Each proof field must be able to fail loudly if the crop is wrong."""
    evaluated = _evaluated_names()
    for entry in MAP["proof_fields"]["selected"]:
        name = entry["claimroute_field"]
        row = _row_for(name)
        assert name in evaluated, f"{name} is not scored"
        assert row["status"] == "mapped_supported", f"{name}: {row['status']}"
        assert row["box_ambiguous"] is False, f"{name} sits in a contested box"
        assert field_policy(name)["optional"] is False, (
            f"{name} is optional; an absent value would ACCEPT and prove nothing")


def test_proof_fields_are_present_in_all_three_development_documents():
    for entry in MAP["proof_fields"]["selected"]:
        row = _row_for(entry["claimroute_field"])
        assert row["present_in_dev_documents"] == 3, entry["claimroute_field"]


def test_proof_fields_cover_every_normalization_family_once():
    """The whole point of the selection: one field per classify_field branch."""
    families = [classify_field(entry["claimroute_field"])
                for entry in MAP["proof_fields"]["selected"]]
    assert sorted(families) == ["code", "date", "money", "quantity", "text"]


def test_proof_field_declared_attributes_match_the_mapping_row():
    for entry in MAP["proof_fields"]["selected"]:
        row = _row_for(entry["claimroute_field"])
        assert entry["normalization"] == row["normalization"]
        assert entry["criticality"] == row["criticality"]
        assert str(entry["cms1500_box"]) == str(row["cms1500_box"])


def test_proof_field_pool_size_matches_the_recorded_eligibility_rule():
    """Re-derive the eligible pool so the stated 18 cannot silently drift."""
    eligible = {name for row in ROWS
                if row["status"] == "mapped_supported"
                and not row["box_ambiguous"]
                and row["present_in_dev_documents"] == 3
                for name in _expand(row["claimroute_field"])
                if name in _evaluated_names()}
    # line2/line3 names are not present in all three dev documents, so the
    # per-row count of 3 applies to the line1 instance only.
    eligible = {name for name in eligible
                if not name.startswith(("line2_", "line3_"))}
    assert len(eligible) == MAP["proof_fields"]["eligible_pool_size"]
    for entry in MAP["proof_fields"]["selected"]:
        assert entry["claimroute_field"] in eligible


def test_naming_compatibility_renames_match_the_evaluator():
    """Both form paths must keep resolving to their own policy entries."""
    compat = MAP["naming_compatibility"]
    for entry in compat["format_conditional_renames"]:
        nsf = OfficialRecord(1, "NSF320", {entry["official_field"]: "X"}, [])
        ub = OfficialRecord(1, "UB192", {entry["official_field"]: "X"}, [])
        assert entry["nsf320_name"] in claimroute_expected(nsf)
        assert entry["ub192_name"] in claimroute_expected(ub)
    for entry in compat["unconditional_renames"]:
        record = OfficialRecord(1, "NSF320", {entry["from"]: "X"}, [])
        assert entry["to"] in claimroute_expected(record)


def test_the_singular_plural_total_split_is_preserved_on_both_forms():
    """total_charge (CMS-1500) and total_charges (UB-04) must stay distinct."""
    split = MAP["naming_compatibility"]["intentional_singular_plural_split"][0]
    assert split["cms1500"] != split["ub04"]
    for name in (split["cms1500"], split["ub04"]):
        assert classify_field(name) == "money"
        assert field_policy(name)["required_validators"], name
