"""Derived submission metrics must partition the frozen evaluated fields exactly.

These guard the numbers that leave the building in 01_Executive_Summary.pdf,
02_Architecture.pdf, and 05_Benchmark.xlsx. They read the frozen evidence and
never write to it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "submission"))

from evidence import EVIDENCE  # noqa: E402


def test_tp_fp_fn_partition_the_evaluated_fields_exactly():
    """Every evaluated field is exactly one of TP, FP, or FN.

    A field that received a wrong automated value is one field, not two. Counting
    it as both a false positive and a false negative made TP+FP+FN exceed the
    frozen ``evaluated_fields`` denominator, which is how recall drifted to the
    incorrect 98.043%.
    """
    counts = EVIDENCE.precision_recall()
    evaluated = EVIDENCE.blended["evaluated_fields"]

    total = counts.true_positives + counts.false_positives + counts.false_negatives
    assert total == evaluated, (
        f"TP+FP+FN = {total} but the frozen benchmark evaluated {evaluated} fields; "
        "a field is being counted in two categories at once"
    )


def test_derived_counts_match_the_frozen_benchmark():
    counts = EVIDENCE.precision_recall()

    assert counts.true_positives == 3106
    assert counts.false_positives == 3
    assert counts.false_negatives == 59


def test_precision_and_recall_are_the_corrected_values():
    counts = EVIDENCE.precision_recall()

    assert counts.precision == pytest.approx(0.99903506, abs=5e-9)
    assert counts.recall == pytest.approx(0.98135861, abs=5e-9)


def test_recall_is_not_the_exact_match_rate():
    """Recall and the automated exact-match rate are different quantities.

    ``automated_exact_match_rate`` is TP over *all* evaluated fields (3106/3168).
    Recall is TP over populated fields the pipeline should have answered
    (3106/3165). They are close, and conflating them is the specific error this
    guards against.
    """
    counts = EVIDENCE.precision_recall()
    exact_match = EVIDENCE.blended["automated_exact_match_rate"]

    assert counts.recall != pytest.approx(exact_match, abs=1e-7)
