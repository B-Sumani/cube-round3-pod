
"""Round 3 Returns Manager agent adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from shared.utils import sample_data
from shared.utils.records import (
    build_output,
    build_record,
    check,
    pending_output,
)
from shared.utils.server import make_app

from .engine import MissingRequiredInputError, analyze_return
from .r2_logic.models import ReturnCase


STAGE = "returns"
AGENT_ID = "returns-manager@1.0.0"
ROOT = Path(__file__).resolve().parents[2]


def input_root() -> Path:
    """Return the configured Round 3 data/input root."""
    return Path(
        os.environ.get("INPUT_DIR", ROOT / "data" / "input")
    ).resolve()


def resolve_input_ref(ref: str) -> Path:
    """Resolve an input reference safely inside INPUT_DIR."""
    root = input_root()
    path = (root / ref).resolve()

    if path != root and root not in path.parents:
        raise ValueError(f"Input reference escapes INPUT_DIR: {ref}")

    return path


def validate_previous_evidence(request: dict) -> list[dict]:
    """Reject evidence from another workflow, organisation, or subject."""
    subject = request["subject"]
    org_id = subject["org_id"]
    subject_id = subject["subject_id"]
    workflow_id = request["workflow_id"]
    previous = request.get("previous_evidence", [])

    for evidence in previous:
        if evidence.get("workflow_id") != workflow_id:
            raise LookupError(
                "Previous evidence belongs to another workflow."
            )

        evidence_subject = evidence.get("subject") or {}

        if evidence_subject.get("org_id") != org_id:
            raise LookupError(
                "Previous evidence belongs to another organisation."
            )

        if evidence_subject.get("subject_id") != subject_id:
            raise LookupError(
                "Previous evidence belongs to another subject."
            )

    return previous


def validate_synthetic_tenant_request(request: dict) -> None:
    """Validate tenant ownership for input-free synthetic test requests."""
    context = request.get("context") or {}

    if request.get("inputs") or not isinstance(context.get("case"), dict):
        return

    subject = request["subject"]

    # Raises LookupError if the unit does not belong to this tenant.
    sample_data.row(
        "returns",
        subject["subject_id"],
        subject["org_id"],
    )


def load_return_case(request: dict) -> tuple[ReturnCase, list[dict]]:
    """Load a Returns case document and its associated images."""
    subject = request["subject"]
    org_id = subject["org_id"]
    subject_id = subject["subject_id"]

    documents = [
        item
        for item in request.get("inputs", [])
        if item.get("kind") == "document"
        and Path(item["ref"]).name.lower()
        in {"return_case.json", "case.json"}
    ]

    if not documents:
        raise MissingRequiredInputError(
            "Required Returns case document is missing."
        )

    if len(documents) > 1:
        raise MissingRequiredInputError(
            "Multiple Returns case documents were supplied; "
            "expected exactly one."
        )

    document_ref = documents[0]["ref"]
    document_path = resolve_input_ref(document_ref)

    try:
        data = json.loads(
            document_path.read_text(encoding="utf-8-sig")
        )
    except FileNotFoundError as exc:
        raise MissingRequiredInputError(
            f"Returns case document not found: {document_ref}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in Returns case document: {document_ref}"
        ) from exc

    if data.get("org_id") != org_id:
        raise LookupError(
            "Returns case belongs to another organisation."
        )

    data_subject = data.get("subject_id") or data.get("unit_id")
    if data_subject and data_subject != subject_id:
        raise LookupError(
            "Returns case belongs to another subject."
        )

    image_inputs = [
        item
        for item in request.get("inputs", [])
        if item.get("kind") == "image"
    ]

    if not image_inputs:
        raise MissingRequiredInputError(
            "At least one returned-item image is required."
        )

    photo_refs = [
        str(resolve_input_ref(item["ref"]))
        for item in image_inputs
    ]

    captured_at = data.get("captured_at")
    if not captured_at:
        raise MissingRequiredInputError(
            "Returns case document must contain captured_at."
        )

    case = ReturnCase(
        record_id=data.get("record_id") or f"RTN-{subject_id}",
        unit_id=subject_id,
        org_id=org_id,
        photo_refs=photo_refs,
        operator_id=data.get("operator_id"),
        captured_at=captured_at,
        order_id=data.get("order_id"),
        ordered_sku=data.get("ordered_sku"),
        ordered_asin=data.get("ordered_asin"),
        identity_match=data.get("identity_match"),
        parts_list=data.get("parts_list") or [],
        parts_missing=data.get("parts_missing") or [],
        observed_state=data.get("observed_state"),
        amazon_condition=data.get("amazon_condition"),
        operator_disposition=data.get("operator_disposition"),
    )

    return case, image_inputs


def apply_upstream_context(
    case: ReturnCase,
    previous_evidence: list[dict],
) -> tuple[ReturnCase, list[str]]:
    """Use matching upstream evidence as read-only context."""
    upstream_refs = [
        evidence["record_id"]
        for evidence in previous_evidence
        if evidence.get("record_id")
    ]

    for evidence in reversed(previous_evidence):
        evidence_subject = evidence.get("subject") or {}
        refs = evidence_subject.get("refs") or {}

        if not case.order_id and refs.get("order_id"):
            case.order_id = str(refs["order_id"])

        if not case.ordered_sku and refs.get("sku"):
            case.ordered_sku = str(refs["sku"])

        if not case.ordered_asin and refs.get("asin"):
            case.ordered_asin = str(refs["asin"])

    return case, upstream_refs


def to_round3_check(
    result,
    *,
    expected: Any = None,
    observed: Any = None,
    evidence_refs: list[str] | None = None,
) -> dict:
    """Convert a Round 2 check to the Round 3 representation."""
    return check(
        result.check_key,
        result.verdict,
        result.confidence,
        expected=expected,
        observed=observed,
        detail=result.detail,
        evidence_refs=evidence_refs or [],
        uncertain_reason=(
            "insufficient_or_ambiguous_evidence"
            if result.verdict == "UNCERTAIN"
            else None
        ),
    )


def handle(request: dict) -> dict:
    """Round 3 in-process Returns agent entry point."""
    if request.get("stage") != STAGE:
        raise LookupError("This agent only handles stage='returns'.")

    subject = request.get("subject") or {}

    if not subject.get("org_id"):
        raise ValueError("subject.org_id is required.")

    if not subject.get("subject_id"):
        raise ValueError("subject.subject_id is required.")

    if not request.get("workflow_id"):
        raise ValueError("workflow_id is required.")

    # Validate synthetic test ownership before returning a pending result.
    validate_synthetic_tenant_request(request)

    try:
        # Validate evidence before missing inputs can short-circuit processing.
        previous_evidence = validate_previous_evidence(request)
        case, image_inputs = load_return_case(request)
        case, upstream_refs = apply_upstream_context(
            case,
            previous_evidence,
        )
    except MissingRequiredInputError as exc:
        return pending_output(
            request,
            code="missing_required_input",
            message=str(exc),
            retryable=True,
            agent_id=AGENT_ID,
        )

    image_refs = [item["ref"] for item in image_inputs]
    evidence_refs = [*image_refs, *upstream_refs]

    try:
        result = analyze_return(case)
    except MissingRequiredInputError as exc:
        return pending_output(
            request,
            code="missing_required_input",
            message=str(exc),
            retryable=True,
            agent_id=AGENT_ID,
        )
    except Exception as exc:
        return pending_output(
            request,
            code="agent_exception",
            message=f"{type(exc).__name__}: {exc}",
            retryable=False,
            agent_id=AGENT_ID,
        )

    working_case = result["case"]
    results = result["checks"]

    round3_checks = [
        to_round3_check(
            results[0],
            expected=working_case.ordered_sku,
            observed=working_case.identity_match,
            evidence_refs=evidence_refs,
        ),
        to_round3_check(
            results[1],
            expected=working_case.parts_list,
            observed={"missing": working_case.parts_missing},
            evidence_refs=evidence_refs,
        ),
        to_round3_check(
            results[2],
            expected=working_case.amazon_condition,
            observed=working_case.observed_state,
            evidence_refs=evidence_refs,
        ),
    ]

    context = request.get("context") or {}

    payload = {
        "observed_state": working_case.observed_state,
        "amazon_condition": working_case.amazon_condition,
        "operator_disposition": working_case.operator_disposition,
        "operator_disposition_is_reference": True,
        "recommended_disposition": result["recommended_disposition"],
        "upstream_override_context": context.get("overrides") or [],
    }

    record = build_record(
        request,
        agent_id=AGENT_ID,
        record_id=working_case.record_id,
        captured_at=working_case.captured_at,
        operator_id=working_case.operator_id,
        refs={
            "order_id": working_case.order_id,
            "sku": working_case.ordered_sku,
            "asin": working_case.ordered_asin,
        },
        checks=round3_checks,
        outcome=result["recommended_disposition"],
        confidence=min(
            [
                item["confidence"]
                for item in round3_checks
                if item["confidence"] is not None
            ],
            default=None,
        ),
        reason=(
            "Returns recommendation derived from identity, completeness, "
            "condition and available evidence."
        ),
        model={
            "name": "fixture-vision",
            "version": "fixture-vision-v1",
            "provider": None,
            "prompt_version": None,
            "calls": 0,
            "cost_usd": 0,
        },
        inputs=request.get("inputs", []),
        upstream_refs=upstream_refs,
        payload=payload,
        status="completed",
    )

    return build_output(record)


app = make_app(
    STAGE,
    handle,
    version="1.0.0",
)