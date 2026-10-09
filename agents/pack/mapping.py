"""Mapping layer between internal Pack Manager evaluation and contract vocabularies.

Translates internal verdicts, outcomes, and failure reason codes to the
standard schema values defined in EVIDENCE-CONTRACT.md and shared/schemas/.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.utils.records import check as make_check

# Contract-allowed uncertain_reasons from shared/schemas/evidence.schema.json
VALID_UNCERTAIN_REASONS = {
    "poor_image",
    "occluded",
    "insufficient_evidence",
    "model_error",
    "rule_unavailable",
    "conflicting_evidence",
    "other",
}

# Reason code to contract uncertain_reason mapping
UNCERTAIN_REASON_MAP: Dict[str, str] = {
    "IMAGE_UNUSABLE": "poor_image",
    "ITEM_OCCLUDED": "occluded",
    "COUNT_OCCLUDED": "occluded",
    "UNVERIFIED_UNDER_OCCLUSION": "occluded",
    "LOW_IDENTITY_CONFIDENCE": "insufficient_evidence",
    "LOW_COUNT_CONFIDENCE": "insufficient_evidence",
    "LOW_CONFIDENCE_EXTRA_ITEM": "insufficient_evidence",
    "UNVERIFIED_UNDER_QUALITY_DEFECT": "insufficient_evidence",
    "ORDER_LINES_MISSING": "insufficient_evidence",
    "NO_ORDER_LINES": "insufficient_evidence",
    "FILE_NOT_FOUND": "insufficient_evidence",
    "INSUFFICIENT_EVIDENCE": "insufficient_evidence",
    "SHA256_MISMATCH": "conflicting_evidence",
    "MODEL_TIMEOUT": "model_error",
    "MODEL_PROVIDER_ERROR": "model_error",
    "MODEL_PARSING_ERROR": "model_error",
}

VERDICT_MAP: Dict[str, str] = {
    "SEAL": "PASS",
    "STOP_AND_FIX": "FAIL",
    "UNCERTAIN": "UNCERTAIN",
}

OUTCOME_MAP: Dict[str, str] = {
    "SEAL": "seal",
    "STOP_AND_FIX": "stop_and_fix",
    "UNCERTAIN": "pending_review",
}


def map_verdict(raw_verdict: str) -> str:
    return VERDICT_MAP.get(raw_verdict, "UNCERTAIN")


def map_outcome(raw_verdict: str) -> str:
    return OUTCOME_MAP.get(raw_verdict, "pending_review")


def map_uncertain_reason(reason_code: str) -> str:
    return UNCERTAIN_REASON_MAP.get(reason_code, "insufficient_evidence")


def to_contract_check(
    check_key: str,
    check_result: Any,
    evidence_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Converts an internal CheckResult into a contract-valid check dictionary."""
    verdict = check_result.result
    uncertain_reason = (
        map_uncertain_reason(check_result.reason_code)
        if verdict == "UNCERTAIN"
        else None
    )

    return make_check(
        check_key=check_key,
        verdict=verdict,
        confidence=check_result.confidence,
        expected=check_result.expected,
        observed=check_result.observed,
        detail=check_result.reason,
        evidence_refs=evidence_refs or [],
        uncertain_reason=uncertain_reason,
    )
