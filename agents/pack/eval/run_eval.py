"""Evaluation script for Pack Manager against ground truth dataset (truth.csv).

Evaluates the Pack Manager on all 18 dev units, compares predicted verdicts
against ground-truth expected verdicts, and prints:
- Per-unit results table
- Overall match rate and accuracy
- Per-check confusion matrix (TP, TN, FP, FN)
- UNCERTAIN rate

Usage:
    python agents/pack/eval/run_eval.py          # Runs offline with MockVisionAdapter (deterministic)
    python agents/pack/eval/run_eval.py --live   # Runs live vision model (requires GEMINI_API_KEY)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add repo root to sys.path so modules can be imported directly
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.pack.engine import run_pack_pipeline, set_test_adapter
from agents.pack.evaluator import evaluate_pack_box, parse_order_lines
from agents.pack.mapping import map_verdict
from agents.pack.model_adapter import GeminiVisionAdapter, MockVisionAdapter
from agents.pack.parser import ImageQuality, ModelObservation, ObservedItem

EVAL_DIR = Path(__file__).resolve().parent
TRUTH_CSV = EVAL_DIR / "truth.csv"
DEV_INPUT_CSV = ROOT / "agents" / "pack" / "data" / "dev" / "input.csv"


def load_truth_data() -> List[Dict[str, str]]:
    with open(TRUTH_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_dev_inputs() -> Dict[str, Dict[str, str]]:
    with open(DEV_INPUT_CSV, newline="", encoding="utf-8") as f:
        return {r["unit_id"]: r for r in csv.DictReader(f)}


def build_mock_observation(truth_row: Dict[str, str]) -> ModelObservation:
    obs_dict = parse_order_lines(truth_row.get("observed_in_box", ""))
    items = [
        ObservedItem(
            sku=sku,
            count=count,
            count_confidence=0.95,
            identity_confidence=0.95,
        )
        for sku, count in obs_dict.items()
    ]
    ft = truth_row.get("failure_type", "")
    usable = False if ft == "bad_photo" else True
    issues = ["blur"] if ft == "bad_photo" else []
    occluded = True if "occluded" in ft else False
    return ModelObservation(
        observed_items=items,
        image_quality=ImageQuality(usable=usable, issues=issues),
        occlusion_suspected=occluded,
    )


def compute_expected_checks(failure_type: str) -> Dict[str, str]:
    """Derives ground-truth check expectations from the failure type.
    
    Positive = Defect (FAIL), Negative = Compliant (PASS), or UNCERTAIN.
    """
    if failure_type in ("occluded_hidden", "bad_photo", "occluded_absent"):
        return {
            "items_present": "UNCERTAIN",
            "quantities_correct": "UNCERTAIN",
            "no_extra_items": "UNCERTAIN",
        }
    if failure_type == "correct":
        return {
            "items_present": "PASS",
            "quantities_correct": "PASS",
            "no_extra_items": "PASS",
        }
    if failure_type == "missing":
        return {
            "items_present": "FAIL",
            "quantities_correct": "PASS",
            "no_extra_items": "PASS",
        }
    if failure_type in ("short_quantity", "under_pack", "over_pack"):
        return {
            "items_present": "PASS",
            "quantities_correct": "FAIL",
            "no_extra_items": "PASS",
        }
    if failure_type == "extra":
        return {
            "items_present": "PASS",
            "quantities_correct": "PASS",
            "no_extra_items": "FAIL",
        }
    if failure_type == "wrong_item":
        return {
            "items_present": "FAIL",
            "quantities_correct": "PASS",
            "no_extra_items": "FAIL",
        }
    return {
        "items_present": "PASS",
        "quantities_correct": "PASS",
        "no_extra_items": "PASS",
    }


def run_evaluation(live: bool = False) -> int:
    truth_rows = load_truth_data()
    dev_inputs = load_dev_inputs()

    print("=" * 80)
    print(f"PACK MANAGER EVALUATION HARNESS ({'LIVE GEMINI' if live else 'MOCK OBSERVATION'})")
    print(f"Truth set: {TRUTH_CSV.name} ({len(truth_rows)} units)")
    print("=" * 80)

    results = []
    total_units = len(truth_rows)
    matches = 0
    uncertain_count = 0

    # Per-check metrics: check -> {TP, TN, FP, FN, UNCERTAIN}
    # Here Positive = Defect (FAIL), Negative = Non-defect (PASS)
    checks_matrix = {
        "items_present": {"TP": 0, "TN": 0, "FP": 0, "FN": 0, "UNCERTAIN": 0},
        "quantities_correct": {"TP": 0, "TN": 0, "FP": 0, "FN": 0, "UNCERTAIN": 0},
        "no_extra_items": {"TP": 0, "TN": 0, "FP": 0, "FN": 0, "UNCERTAIN": 0},
    }

    for row in truth_rows:
        unit_id = row["unit_id"]
        org_id = row["org_id"]
        failure_type = row.get("failure_type", "")
        expected_verdict = row["expected_verdict"]  # SEAL, STOP_AND_FIX, UNCERTAIN

        # Build agent input
        agent_input = {
            "schema_version": "1.0",
            "request_id": f"EVAL-{unit_id}",
            "workflow_id": f"WF-{org_id}-{unit_id}",
            "stage": "pack",
            "subject": {"org_id": org_id, "subject_id": unit_id, "route": "mfn"},
            "inputs": [],
            "previous_evidence": [],
            "context": {"channel": "amazon_mfn"},
        }

        if live:
            adapter = GeminiVisionAdapter()
        else:
            mock_obs = build_mock_observation(row)
            adapter = MockVisionAdapter(mock_observation=mock_obs)

        out = run_pack_pipeline(agent_input, adapter=adapter)
        ev = out["evidence"]

        # Map predicted verdict:
        # SEAL = PASS, STOP_AND_FIX = FAIL, STOP = UNCERTAIN
        pred_verdict = out["verdict"]  # PASS, FAIL, UNCERTAIN
        if pred_verdict == "UNCERTAIN":
            uncertain_count += 1

        # Normalized verdict match comparison
        norm_expected = (
            "PASS" if expected_verdict == "SEAL"
            else ("FAIL" if expected_verdict == "STOP_AND_FIX" else "UNCERTAIN")
        )
        is_match = (pred_verdict == norm_expected)
        if is_match:
            matches += 1

        # Check results
        got_checks = {c["check_key"]: c["verdict"] for c in ev.get("checks", [])}
        expected_checks = compute_expected_checks(failure_type)

        for check_key in ("items_present", "quantities_correct", "no_extra_items"):
            pred_c = got_checks.get(check_key, "UNCERTAIN")
            exp_c = expected_checks.get(check_key, "PASS")

            if pred_c == "UNCERTAIN" or exp_c == "UNCERTAIN":
                checks_matrix[check_key]["UNCERTAIN"] += 1
            elif exp_c == "FAIL" and pred_c == "FAIL":
                checks_matrix[check_key]["TP"] += 1
            elif exp_c == "PASS" and pred_c == "PASS":
                checks_matrix[check_key]["TN"] += 1
            elif exp_c == "PASS" and pred_c == "FAIL":
                checks_matrix[check_key]["FP"] += 1
            elif exp_c == "FAIL" and pred_c == "PASS":
                checks_matrix[check_key]["FN"] += 1

        results.append({
            "unit_id": unit_id,
            "org_id": org_id,
            "failure_type": failure_type,
            "expected": expected_verdict,
            "norm_expected": norm_expected,
            "predicted": pred_verdict,
            "match": is_match,
            "checks": got_checks,
        })

    # Print results table
    print(f"\n{'Unit ID':<11} {'Org':<16} {'Failure Type':<18} {'Expected':<12} {'Predicted':<12} {'Match':<6}")
    print("-" * 78)
    for r in results:
        status_sym = "[OK]" if r["match"] else "[MISMATCH]"
        print(f"{r['unit_id']:<11} {r['org_id']:<16} {r['failure_type']:<18} {r['norm_expected']:<12} {r['predicted']:<12} {status_sym}")

    accuracy = (matches / total_units) * 100.0 if total_units else 0.0
    uncertain_rate = (uncertain_count / total_units) * 100.0 if total_units else 0.0

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Units:      {total_units}")
    print(f"Exact Matches:    {matches} / {total_units} ({accuracy:.1f}%)")
    print(f"UNCERTAIN Count:  {uncertain_count} / {total_units}")
    print(f"UNCERTAIN Rate:   {uncertain_rate:.1f}%")

    print("\n" + "=" * 80)
    print("PER-CHECK METRICS (Positive = Defect / FAIL)")
    print("=" * 80)
    print(f"{'Check Key':<22} {'TP':<6} {'TN':<6} {'FP':<6} {'FN':<6} {'UNCERTAIN':<10} {'Precision':<10} {'Recall':<10}")
    print("-" * 80)
    for k, m in checks_matrix.items():
        tp, tn, fp, fn, unc = m["TP"], m["TN"], m["FP"], m["FN"], m["UNCERTAIN"]
        prec = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else 100.0
        rec = (tp / (tp + fn) * 100.0) if (tp + fn) > 0 else 100.0
        print(f"{k:<22} {tp:<6} {tn:<6} {fp:<6} {fn:<6} {unc:<10} {prec:>6.1f}%    {rec:>6.1f}%")

    print("=" * 80)
    return 0 if matches == total_units else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Pack Manager against truth.csv")
    parser.add_argument("--live", action="store_true", help="Use live Gemini vision API instead of mock")
    args = parser.parse_args()
    sys.exit(run_evaluation(live=args.live))
