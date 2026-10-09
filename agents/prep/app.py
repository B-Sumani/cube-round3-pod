"""Prep Manager Agent: Round 3 Entry Point."""

import re
from shared.utils.records import build_record, build_output, check, utcnow
from shared.utils.server import make_app
from . import engine

STAGE = "prep"
AGENT_ID = "prep-manager@1.0.0"


def handle(request: dict) -> dict:
    # 1. Tenant validation & sample row lookup
    upstream_refs, sample_row = engine.validate_tenant_and_extract_refs(request)

    workflow_id = request["workflow_id"]
    request_id = request.get("request_id", f"req_{workflow_id}")

    # Sanitize record_id format
    safe_req_id = re.sub(r"[^A-Za-z0-9._-]", "-", request_id)
    record_id = f"PRP-{safe_req_id}"

    inputs = request.get("inputs", [])

    # 2. Vision execution
    raw_checks, model_name, latency_ms, prep_price_usd, model_error = engine.call_gemini_vision(request, sample_row)

    formatted_checks = []
    for c in raw_checks:
        chk_kwargs = {
            "check_key": c.get("check_key", "unknown"),
            "verdict": c.get("verdict", "UNCERTAIN"),
            "confidence": c.get("confidence", 0.5),
            "detail": c.get("detail", "No detail provided"),
            "evidence_refs": [i["ref"] for i in inputs if "ref" in i],
        }
        if c.get("verdict") == "UNCERTAIN":
            chk_kwargs["uncertain_reason"] = c.get("uncertain_reason", "insufficient_evidence")

        formatted_checks.append(check(**chk_kwargs))

    verdicts = {c["verdict"] for c in formatted_checks}
    if model_error:
        overall_verdict = "UNCERTAIN"
        outcome = "pending_review"
        status = "pending"
    elif "FAIL" in verdicts:
        overall_verdict = "FAIL"
        outcome = "non_compliant"
        status = "completed"
    elif "UNCERTAIN" in verdicts or not formatted_checks:
        overall_verdict = "UNCERTAIN"
        outcome = "pending_review"
        status = "pending"
    else:
        overall_verdict = "PASS"
        outcome = "compliant"
        status = "completed"

    # Extract refs from sample row if available
    refs = {}
    if sample_row:
        refs = {
            "work_order_id": sample_row.get("work_order_id"),
            "fba_shipment_id": sample_row.get("fba_shipment_id"),
            "sku": sample_row.get("sku"),
            "asin": sample_row.get("asin"),
            "fnsku": sample_row.get("fnsku"),
        }

    record = build_record(
        request,
        agent_id=AGENT_ID,
        record_id=record_id,
        status=status,
        verdict=overall_verdict,
        captured_at=sample_row.get("captured_at") if sample_row else utcnow(),
        checks=formatted_checks,
        outcome=outcome,
        refs=refs,
        model={
            "name": model_name,
            "version": "1.0.0",
            "provider": engine.MODEL_PROVIDER,
            "prompt_version": engine.PROMPT_VERSION,
            "calls": 1,
        },
        inputs=inputs,
        upstream_refs=upstream_refs,
        reason=f"Prep compliance evaluated {len(formatted_checks)} check(s).",
        payload={"prep_price_usd": prep_price_usd, "measurements": None},
        error=model_error,
        latency_ms=int(latency_ms) if latency_ms else None,
    )
    return build_output(record)


app = make_app(STAGE, handle, version="1.0.0")