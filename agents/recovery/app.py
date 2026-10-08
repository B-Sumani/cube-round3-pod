"""Recovery Manager: agent entry point.

Round 3 Recovery Manager implementation for Pod 6.
Owner: @hayth31 (Haytham / Hayth)

Recovery Manager evaluates fee charges against accumulated upstream evidence from
Receiving, Prep, Pack, and Returns stages.

Check semantics for Recovery:
  CONTRADICTS -> FAIL  (evidence refutes the fee charge -> claim recommended)
  SUPPORTS    -> PASS  (evidence confirms the fee charge was justified -> no claim)
  SILENT      -> UNCERTAIN (evidence is silent / missing -> cannot claim)

Rules:
1. Tenancy check: refuse unknown subjects for org.
2. Inbound defect fee: refute if Prep/Receiving evidence shows compliance.
3. Refund item not returned: refute if Returns evidence confirms item returned.
4. Weight-tier fees: mark SILENT due to lack of upstream measured dimensions (F-07).
5. Lost inbound: mark SILENT due to supplier vs channel loss separation (F-10).
6. Zero-amount fees: mark SILENT (F-09).
"""
from shared.utils import sample_data
from shared.utils.records import build_output, build_record, check, utcnow
from shared.utils.server import make_app
from shared.utils.stubs import effective_verdict, previous

STAGE = "recovery"
AGENT_ID = "recovery@3.0.0"
MODEL_ID = {"name": "recovery-evaluator", "version": "3.0.0", "provider": "pod6", "calls": 1, "cost_usd": 0.0}


def position(line: dict, request: dict) -> tuple[str, str, list[str]]:
    """Determine position for a fee line: (CONTRADICTS | SUPPORTS | SILENT, detail, evidence_ids)."""
    ctype = line.get("charge_type")
    if ctype == "inbound_defect_fee":
        prep = previous(request, "prep")
        if prep and prep.get("status") == "completed":
            v = effective_verdict(request, prep)
            if v == "PASS":
                return "CONTRADICTS", "Prep evidence shows the unit compliant", [prep["record_id"]]
            if v == "FAIL":
                return "SUPPORTS", "Prep evidence shows a defect", [prep["record_id"]]
            return "SILENT", "Prep evidence is uncertain", [prep["record_id"]]
        
        # Fallback to Receiving evidence if Prep not present
        rcv = previous(request, "receiving")
        if rcv and rcv.get("status") == "completed":
            v = effective_verdict(request, rcv)
            if v == "PASS":
                return "CONTRADICTS", "Receiving evidence shows the unit compliant", [rcv["record_id"]]
            if v == "FAIL":
                return "SUPPORTS", "Receiving evidence shows a defect", [rcv["record_id"]]
            return "SILENT", "Receiving evidence is uncertain", [rcv["record_id"]]

        return "SILENT", "no usable Prep or Receiving record for this subject", []

    if ctype == "refund_issued_item_not_returned":
        ret = previous(request, "returns")
        if ret and ret.get("status") == "completed":
            v = effective_verdict(request, ret)
            if v == "PASS":
                return "CONTRADICTS", "Returns record shows the right item came back in good condition", [ret["record_id"]]
            if v == "FAIL":
                return "SUPPORTS", "Returns record confirms item was defective or unreturned", [ret["record_id"]]
            return "SILENT", "Returns evidence is uncertain", [ret["record_id"]]
        return "SILENT", "no usable Returns record", []

    if ctype == "fulfilment_fee_weight_tier":
        return "SILENT", "no measured weight/dimensions upstream (finding F-07)", []

    if ctype == "lost_inbound":
        return "SILENT", "receiving shortfall is supplier-side, not channel-side loss (finding F-10)", []

    return "SILENT", f"no rule for {ctype}", []


def handle(request: dict) -> dict:
    """Standard Round 3 handle entry point for Recovery Manager."""
    s = request["subject"]
    if not sample_data.has("receiving", s["subject_id"], s["org_id"]):
        raise LookupError(f"unknown subject {s['subject_id']} in {s['org_id']}")

    lines = sample_data.fee_lines(s["subject_id"], s["org_id"])
    checks, charges, claimable = [], [], 0.0

    for line in lines:
        pos, why, ids = position(line, request)
        amount = float(line.get("amount_usd", 0.0))
        if pos == "CONTRADICTS" and amount <= 0:
            pos, why = "SILENT", "amount is 0.00: nothing to claim, or the amount is missing (finding F-09)"

        verdict = {"CONTRADICTS": "FAIL", "SUPPORTS": "PASS", "SILENT": "UNCERTAIN"}[pos]
        checks.append(check(
            f"charge_{line['line_id'].lower().replace('-', '_')}",
            verdict,
            None,
            expected="charge supported by evidence",
            observed=pos,
            detail=why,
            evidence_refs=ids,
            uncertain_reason="insufficient_evidence" if pos == "SILENT" else None
        ))
        if pos == "CONTRADICTS":
            claimable += amount

        charges.append({
            "line_id": line["line_id"],
            "charge_type": line["charge_type"],
            "amount_usd": amount,
            "position": pos,
            "reason": why,
            "evidence_record_ids": ids
        })

    claim = any(c["position"] == "CONTRADICTS" for c in charges)
    silent = any(c["position"] == "SILENT" for c in charges)
    verdict = "FAIL" if claim else ("UNCERTAIN" if silent else "PASS")
    outcome = "claim_recommended" if claim else ("insufficient_evidence" if silent else "no_claim")

    record = build_record(
        request,
        agent_id=AGENT_ID,
        record_id=f"RCY-{s['subject_id']}",
        model=MODEL_ID,
        captured_at=max((l.get("posted_date", "2026-01-01") + "T00:00:00Z" for l in lines), default=utcnow()),
        checks=checks,
        outcome=outcome,
        verdict=verdict,
        needs_human=False,
        reason=f"recovery: {len(charges)} charge(s), {sum(c['position'] == 'CONTRADICTS' for c in charges)} contradicted",
        payload={
            "charges": charges,
            "claimable_usd": round(claimable, 2),
            "unclaimable": [c for c in charges if c["position"] != "CONTRADICTS"]
        },
    )
    return build_output(record, next_step="complete")


app = make_app(STAGE, handle)
