"""Deterministic rules layer for Pack Manager.

Ported from Round 2 rules/evaluator.py.
- Check keys renamed to: items_present, quantities_correct, no_extra_items.
- One home per check (orthogonal failure partitioning).
- Confidence gates decisions: low confidence gates PASS or FAIL to UNCERTAIN.
- Occlusion and quality downgrade gating.
- Pure Python with zero external dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agents.pack.config import DEFAULT_CONFIG, PackConfig
from agents.pack.parser import ModelObservation, ObservedItem


@dataclass
class CheckResult:
    result: str  # "PASS", "FAIL", "UNCERTAIN"
    reason_code: str
    reason: str
    cause: Optional[str] = None  # "occlusion", "recognition", or None
    expected: Any = None
    observed: Any = None
    confidence: Optional[float] = None


def parse_order_lines(order_lines_str: str) -> Dict[str, int]:
    """Parses order lines string into a dictionary of SKU -> quantity.

    Accepts formats:
    - 'SKU-PUZZLE-500:1;SKU-BOTTLE-750:2'
    - 'SKU-PUZZLE-500: 1, SKU-BOTTLE-750: 2'
    - Multiline 'SKU-PUZZLE-500:1\\nSKU-BOTTLE-750:2'
    """
    lines: Dict[str, int] = {}
    if not order_lines_str or not order_lines_str.strip():
        return lines

    raw_tokens = re.split(r"[;,\n\r]+", order_lines_str.strip())
    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            sku_part, qty_part = token.split(":", 1)
            sku = sku_part.strip()
            try:
                qty = int(qty_part.strip())
            except ValueError:
                qty = 1
            if sku:
                lines[sku] = lines.get(sku, 0) + qty
        else:
            sku = token.strip()
            if sku:
                lines[sku] = lines.get(sku, 0) + 1
    return lines


def evaluate_pack_box(
    order_lines_str: str,
    observation: ModelObservation,
    candidate_skus: Optional[List[str]] = None,
    config: Optional[PackConfig] = None,
) -> Tuple[Dict[str, CheckResult], str, str]:
    """Compares ModelObservation against expected order lines with deterministic rules.

    Renamed checks:
    - items_present: presence & identity of required order SKUs (observed count >= 1).
    - quantities_correct: piece count accuracy for ordered SKUs (short or surplus).
    - no_extra_items: absence of foreign, decoy, or unrecognised items.

    Returns:
        (checks_dict, verdict, operator_action)
        - checks_dict: mapping check_key -> CheckResult
        - verdict: 'SEAL', 'STOP_AND_FIX', or 'UNCERTAIN'
        - operator_action: 'go' (SEAL) or 'STOP' (STOP_AND_FIX / UNCERTAIN)
    """
    cfg = config or DEFAULT_CONFIG
    expected_lines = parse_order_lines(order_lines_str)

    observed_by_sku: Dict[str, List[ObservedItem]] = {}
    for item in observation.observed_items:
        observed_by_sku.setdefault(item.sku, []).append(item)

    image_usable = observation.image_quality.usable
    quality_issues = (
        ", ".join(observation.image_quality.issues)
        if observation.image_quality.issues
        else "unusable image"
    )

    # =========================================================================
    # CHECK 1: items_present (Identity / Presence)
    # Home: Are all required order SKUs present in the box (observed count >= 1)?
    # =========================================================================
    if not image_usable:
        check_identity = CheckResult(
            result="UNCERTAIN",
            reason_code="IMAGE_UNUSABLE",
            reason=f"Photo quality is insufficient to verify item presence: {quality_issues}",
            cause="recognition",
            expected=sorted(expected_lines.keys()),
            observed=sorted(observed_by_sku.keys()),
            confidence=None,
        )
    else:
        missing_skus: List[str] = []
        occluded_skus: List[str] = []
        low_conf_skus: List[Tuple[str, float]] = []
        identity_confs: List[float] = []

        for sku in expected_lines.keys():
            obs_list = observed_by_sku.get(sku, [])
            total_count = sum(item.count for item in obs_list)

            if total_count == 0:
                if observation.occlusion_suspected:
                    occluded_skus.append(sku)
                else:
                    missing_skus.append(sku)
            else:
                for item in obs_list:
                    identity_confs.append(item.identity_confidence)
                    if item.partially_occluded:
                        occluded_skus.append(sku)
                        break
                    elif item.identity_confidence < cfg.identity_confidence_threshold:
                        low_conf_skus.append((sku, item.identity_confidence))
                        break

        avg_conf = (sum(identity_confs) / len(identity_confs)) if identity_confs else None

        if occluded_skus:
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="ITEM_OCCLUDED",
                reason=f"Cannot confirm presence of {', '.join(set(occluded_skus))} due to occlusion in box",
                cause="occlusion",
                expected=sorted(expected_lines.keys()),
                observed=sorted(observed_by_sku.keys()),
                confidence=avg_conf,
            )
        elif low_conf_skus:
            sku_name, conf = low_conf_skus[0]
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="LOW_IDENTITY_CONFIDENCE",
                reason=f"Identity confidence for {sku_name} ({conf:.2f}) is below threshold ({cfg.identity_confidence_threshold:.2f})",
                cause="recognition",
                expected=sorted(expected_lines.keys()),
                observed=sorted(observed_by_sku.keys()),
                confidence=conf,
            )
        elif missing_skus:
            check_identity = CheckResult(
                result="FAIL",
                reason_code="MISSING_ITEMS",
                reason=f"Required item(s) missing from open box: {', '.join(missing_skus)}",
                cause="recognition",
                expected=sorted(expected_lines.keys()),
                observed=sorted(observed_by_sku.keys()),
                confidence=avg_conf,
            )
        else:
            check_identity = CheckResult(
                result="PASS",
                reason_code="ALL_ITEMS_PRESENT",
                reason="All required order SKUs are clearly present in the box",
                expected=sorted(expected_lines.keys()),
                observed=sorted(observed_by_sku.keys()),
                confidence=avg_conf,
            )

    # =========================================================================
    # CHECK 2: quantities_correct (Piece Count)
    # Home: Do the piece counts of ordered items match expected quantities?
    # =========================================================================
    check_count: Optional[CheckResult] = None
    if not image_usable:
        check_count = CheckResult(
            result="UNCERTAIN",
            reason_code="IMAGE_UNUSABLE",
            reason=f"Photo quality is insufficient to count quantities: {quality_issues}",
            cause="recognition",
            expected=expected_lines,
            observed={k: sum(it.count for it in v) for k, v in observed_by_sku.items()},
            confidence=None,
        )
    else:
        short_items: List[str] = []
        surplus_items: List[str] = []
        count_occluded: List[str] = []
        count_low_conf: List[Tuple[str, float]] = []
        present_count = 0
        count_confs: List[float] = []

        for sku, expected_qty in expected_lines.items():
            obs_list = observed_by_sku.get(sku, [])
            total_observed = sum(item.count for item in obs_list)

            if total_observed == 0:
                continue

            present_count += 1
            for item in obs_list:
                count_confs.append(item.count_confidence)
                if item.partially_occluded:
                    count_occluded.append(sku)
                    break
                if item.count_confidence < cfg.count_confidence_threshold:
                    count_low_conf.append((sku, item.count_confidence))
                    break

            if total_observed < expected_qty:
                short_items.append(f"{sku} (expected {expected_qty}, observed {total_observed})")
            elif total_observed > expected_qty:
                surplus_items.append(f"{sku} (expected {expected_qty}, observed {total_observed})")

        observed_counts = {k: sum(it.count for it in v) for k, v in observed_by_sku.items() if k in expected_lines}
        avg_count_conf = (sum(count_confs) / len(count_confs)) if count_confs else None

        if count_occluded:
            check_count = CheckResult(
                result="UNCERTAIN",
                reason_code="COUNT_OCCLUDED",
                reason=f"Occlusion prevents accurate piece count for {', '.join(set(count_occluded))}",
                cause="occlusion",
                expected=expected_lines,
                observed=observed_counts,
                confidence=avg_count_conf,
            )
        elif count_low_conf:
            check_count = CheckResult(
                result="UNCERTAIN",
                reason_code="LOW_COUNT_CONFIDENCE",
                reason=f"Count confidence for {sku_name} ({conf:.2f}) is below threshold ({cfg.count_confidence_threshold:.2f})",
                cause="recognition",
                expected=expected_lines,
                observed=observed_counts,
                confidence=conf,
            )
        elif short_items:
            check_count = CheckResult(
                result="FAIL",
                reason_code="SHORT_QUANTITY",
                reason=f"Short quantity for required item(s): {', '.join(short_items)}",
                cause="recognition",
                expected=expected_lines,
                observed=observed_counts,
                confidence=avg_count_conf,
            )
        elif surplus_items:
            check_count = CheckResult(
                result="FAIL",
                reason_code="SURPLUS_QUANTITY",
                reason=f"Excess quantity packed for ordered item(s): {', '.join(surplus_items)}",
                cause="recognition",
                expected=expected_lines,
                observed=observed_counts,
                confidence=avg_count_conf,
            )
        elif present_count == 0 and len(expected_lines) > 0:
            # Per EVIDENCE-CONTRACT.md line 93: non-applicable checks are omitted, not marked PASS
            check_count = None
        else:
            check_count = CheckResult(
                result="PASS",
                reason_code="QUANTITIES_MATCH",
                reason="Observed item counts exactly match the order line quantities",
                expected=expected_lines,
                observed=observed_counts,
                confidence=avg_count_conf,
            )

    # =========================================================================
    # CHECK 3: no_extra_items (Surplus / Decoys / Foreign Items)
    # Home: Are there unauthorized items (decoys or unrecognised items) in the box?
    # =========================================================================
    if not image_usable:
        check_extra = CheckResult(
            result="UNCERTAIN",
            reason_code="IMAGE_UNUSABLE",
            reason=f"Photo quality is insufficient to verify absence of extra items: {quality_issues}",
            cause="recognition",
            expected=[],
            observed=[],
            confidence=None,
        )
    else:
        unrecognised_found: List[str] = []
        decoys_found: List[str] = []
        low_conf_extra: List[Tuple[str, float]] = []

        if observation.unrecognised_items:
            for unrec in observation.unrecognised_items:
                desc = unrec.description or "unrecognised object"
                unrecognised_found.append(desc)

        order_skus_normalized = {k.strip().upper() for k in expected_lines.keys()}
        for item in observation.observed_items:
            sku_clean = item.sku.strip().upper()
            if sku_clean not in order_skus_normalized and item.count > 0:
                if item.identity_confidence < cfg.identity_confidence_threshold:
                    low_conf_extra.append((item.sku, item.identity_confidence))
                else:
                    decoys_found.append(f"{item.sku} (count: {item.count})")

        observed_extras = unrecognised_found + decoys_found

        if low_conf_extra:
            sku_name, conf = low_conf_extra[0]
            check_extra = CheckResult(
                result="UNCERTAIN",
                reason_code="LOW_CONFIDENCE_EXTRA_ITEM",
                reason=f"Low confidence ({conf:.2f}) identifying possible extra item {sku_name}",
                cause="recognition",
                expected=[],
                observed=observed_extras,
                confidence=conf,
            )
        elif unrecognised_found:
            check_extra = CheckResult(
                result="FAIL",
                reason_code="UNRECOGNISED_ITEMS_PRESENT",
                reason=f"Unrecognised foreign item(s) found in box: {', '.join(unrecognised_found)}",
                cause="recognition",
                expected=[],
                observed=observed_extras,
                confidence=None,
            )
        elif decoys_found:
            check_extra = CheckResult(
                result="FAIL",
                reason_code="DECOY_ITEM_PRESENT",
                reason=f"Unauthorized decoy SKU(s) found in box: {', '.join(decoys_found)}",
                cause="recognition",
                expected=[],
                observed=observed_extras,
                confidence=None,
            )
        else:
            check_extra = CheckResult(
                result="PASS",
                reason_code="NO_EXTRA_ITEMS",
                reason="No extra, decoy, or foreign items observed in the box",
                expected=[],
                observed=[],
                confidence=None,
            )

    # -------------------------------------------------------------------------
    # Ambiguity / Quality Downgrade Gating
    # -------------------------------------------------------------------------
    quality_issues_lower = {iss.lower().strip() for iss in observation.image_quality.issues}
    quality_defect = bool(quality_issues_lower & {"blur", "glare", "box_not_in_frame"})
    occlusion_defect = bool(observation.occlusion_suspected)

    if quality_defect or occlusion_defect:
        gate_cause = "occlusion" if occlusion_defect else "recognition"
        gate_reason_prefix = (
            "Occlusion suspected in carton"
            if occlusion_defect
            else f"Image quality issues observed ({quality_issues})"
        )

        if check_identity.result == "FAIL" and check_identity.reason_code == "MISSING_ITEMS":
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="ITEM_OCCLUDED" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: cannot verify if missing item(s) are absent or concealed",
                cause=gate_cause,
                expected=check_identity.expected,
                observed=check_identity.observed,
                confidence=check_identity.confidence,
            )
        elif check_identity.result == "PASS":
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="UNVERIFIED_UNDER_OCCLUSION" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: item presence cannot be verified",
                cause=gate_cause,
                expected=check_identity.expected,
                observed=check_identity.observed,
                confidence=check_identity.confidence,
            )

        if check_count is not None and check_count.result == "PASS":
            check_count = CheckResult(
                result="UNCERTAIN",
                reason_code="UNVERIFIED_UNDER_OCCLUSION" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: item quantities cannot be verified",
                cause=gate_cause,
                expected=check_count.expected,
                observed=check_count.observed,
                confidence=check_count.confidence,
            )

        if check_extra.result == "PASS":
            check_extra = CheckResult(
                result="UNCERTAIN",
                reason_code="UNVERIFIED_UNDER_OCCLUSION" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: carton contents cannot be verified as free of extra items",
                cause=gate_cause,
                expected=check_extra.expected,
                observed=check_extra.observed,
                confidence=check_extra.confidence,
            )

    # -------------------------------------------------------------------------
    # Box Verdict Synthesis
    # Precedence: FAIL > UNCERTAIN > PASS
    # -------------------------------------------------------------------------
    checks: Dict[str, CheckResult] = {
        "items_present": check_identity,
        "no_extra_items": check_extra,
    }
    if check_count is not None:
        checks["quantities_correct"] = check_count

    all_results = [c.result for c in checks.values()]

    if "FAIL" in all_results:
        verdict = "STOP_AND_FIX"
        operator_action = "STOP"
    elif "UNCERTAIN" in all_results:
        verdict = "UNCERTAIN"
        operator_action = "STOP"
    else:
        verdict = "SEAL"
        operator_action = "go"

    return checks, verdict, operator_action
