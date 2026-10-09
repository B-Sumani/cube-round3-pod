"""Prep Manager Agent: Round 3 Entry Point."""

import re
from shared.utils.records import build_record, build_output, check, utcnow
from shared.utils.server import make_app
from . import engine

STAGE = "prep"
AGENT_ID = "prep-manager@1.0.0"


def handle(request: dict) -> dict:
feature/prep-r3
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
            "evidence_refs": [i["ref"] for i in inputs if "ref" in i]
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
        captured_at=sample_row.get("captured_at") if sample_row else utcnow(),
        checks=formatted_checks,
        outcome=outcome,
        refs=refs,
        model={
            "name": model_name,
            "version": "1.0.0",
            "provider": engine.MODEL_PROVIDER,
            "prompt_version": engine.PROMPT_VERSION,
            "calls": 1
        },
        inputs=inputs,
        upstream_refs=upstream_refs,
        reason=f"Prep compliance evaluated {len(formatted_checks)} check(s).",
        payload={"prep_price_usd": prep_price_usd, "measurements": None},
        error=model_error,
        latency_ms=int(latency_ms) if latency_ms else None

    s = request["subject"]
    r = sample_data.row("prep", s["subject_id"], s["org_id"])
    refs = [p["ref"] for p in photos(r)]
    checks = [
        check(key, verdict_from(r[col], ok, bad), None, expected=sorted(ok)[0], observed=r[col],
              evidence_refs=refs, uncertain_reason="poor_image",
              detail=f"[STUB REPLAY] Replayed from sample data: {col}={r[col]}")
        for key, col, ok, bad in RULES if r[col] != "not_required"
    ]
    verdict = "FAIL" if any(c["verdict"] == "FAIL" for c in checks) else (
        "UNCERTAIN" if any(c["verdict"] == "UNCERTAIN" for c in checks) or not checks else "PASS")
    outcome = {"PASS": "compliant", "FAIL": "non_compliant", "UNCERTAIN": "pending_review"}[verdict]
    record = build_record(
        request, agent_id=AGENT_ID, record_id=r["record_id"], captured_at=r["captured_at"], operator_id=r["operator_id"],
        refs={"work_order_id": r["work_order_id"], "fba_shipment_id": r["fba_shipment_id"], "sku": r["sku"],
              "asin": r["asin"], "fnsku": r["fnsku"]},
        checks=checks, outcome=outcome, model=STUB_MODEL, inputs=photos(r),
        reason=f"[STUB] Replay of sample row (Prep agent not integrated yet); {sum(c['verdict'] == 'FAIL' for c in checks)} failed check(s)",
        payload={"implementation": "organiser-stub", "mode": "organiser-stub", "stub": True,
                 "prep_price_usd": float(r["prep_price_usd"]), "measurements": None},
main
    )
    return build_output(record)


app = make_app(STAGE, handle, version="1.0.0")