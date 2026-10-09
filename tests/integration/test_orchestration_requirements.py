"""Comprehensive test suite enforcing all six Orchestrator core requirements (Step 3 & Step 6).

Core Invariants:
1. Previous evidence and overrides are passed to every stage.
2. Every agent output is validated (schema, stage, workflow_id, tenant, hash, consistency) before acceptance.
3. Transient failures retry (retries/timeout_s); refusals (4xx, wrong tenant) never retry.
4. Every failure is recorded as a degraded evidence record plus an error. Failure is NEVER success.
5. Evidence is immutable, never deleted or replaced. Overrides require actor and reason, reference the evidence they supersede, and never mutate the original record.
6. Status and final outcome are DERIVED from evidence via pure functions (rollup.py): never copied from an agent's last answer. COMPLETED is impossible if a required stage is incomplete.
"""
from pathlib import Path
import pytest

from orchestration.orchestrator import (
    apply_override,
    bundle,
    load_flow,
    resume,
    run_workflow,
)
from orchestration.store import EvidenceConflict, MemoryStore, TenantViolation
from shared.utils.hashing import verify
from shared.utils.schema import errors
from tests.helpers import AgentRejected, AgentTimeout, AgentUnavailable, Boom, Fake, Mangle

ROOT = Path(__file__).resolve().parents[2]
FLOW = load_flow(ROOT / "orchestration/flow.json")
CASE_CLEAN = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0001", "route": "fba", "returned": False}
CASE_RETURN = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}
CASE_MFN = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0002", "route": "mfn", "returned": False}


def fakes(**verdicts):
    base = {s: Fake("PASS") for s in ("receiving", "prep", "pack", "returns", "recovery")}
    base.update({s: (v if hasattr(v, "run") else Fake(v)) for s, v in verdicts.items()})
    return base


def custom_flow(**defaults):
    return {**FLOW, "defaults": {**FLOW["defaults"], **defaults}}


# ------------------------------------------------------------
# 1. Previous evidence and overrides are passed to every stage
# ------------------------------------------------------------
def test_previous_evidence_and_overrides_passed_to_every_stage():
    captured_inputs = {}

    class CapturingFake(Fake):
        def __init__(self, stage, verdict="PASS"):
            super().__init__(verdict)
            self.stage = stage

        def run(self, request, timeout_s):
            captured_inputs[self.stage] = {
                "previous_evidence": list(request.get("previous_evidence", [])),
                "overrides": list(request.get("context", {}).get("overrides", [])),
            }
            return super().run(request, timeout_s)

    store = MemoryStore()
    clients = {s: CapturingFake(s) for s in ("receiving", "prep", "returns", "recovery")}
    wf = run_workflow(CASE_RETURN, FLOW, store, clients)
    assert wf["status"] == "COMPLETED"

    # Receiving has 0 previous evidence
    assert len(captured_inputs["receiving"]["previous_evidence"]) == 0
    # Prep sees Receiving
    assert len(captured_inputs["prep"]["previous_evidence"]) == 1
    assert captured_inputs["prep"]["previous_evidence"][0]["stage"] == "receiving"
    # Returns sees Receiving and Prep
    assert len(captured_inputs["returns"]["previous_evidence"]) == 2
    # Recovery sees all prior records
    assert len(captured_inputs["recovery"]["previous_evidence"]) == 3


# ------------------------------------------------------------
# 2. Every agent output is validated before acceptance
# ------------------------------------------------------------
@pytest.mark.parametrize(
    "mangle_mode,expected_err",
    [
        ("garbage", "invalid_output"),
        ("tampered", "invalid_output"),
        ("wrong_stage", "invalid_output"),
        ("disagree", "invalid_output"),
        ("other_tenant", "tenant_mismatch"),
    ],
)
def test_every_agent_output_validated_before_acceptance(mangle_mode, expected_err):
    store = MemoryStore()
    clients = fakes(receiving=Mangle("receiving", mangle_mode))
    wf = run_workflow(CASE_CLEAN, FLOW, store, clients)

    assert wf["status"] == "FAILED"
    sr = next(s for s in wf["stage_results"] if s["stage"] == "receiving")
    assert sr["state"] == "error"
    assert sr["error"]["code"] == expected_err

    # Degraded record is stored in evidence store
    deg = store.get_evidence(sr["record_id"], CASE_CLEAN["org_id"])
    assert deg["status"] != "completed"
    assert deg["decision"]["verdict"] == "UNCERTAIN"
    assert verify(deg)


# ------------------------------------------------------------
# 3. Transient failures retry; refusals never retry
# ------------------------------------------------------------
def test_transient_failure_retries_and_refusal_does_not():
    # Transient timeout: retries once (default retries=1)
    timeout_client = Boom(AgentTimeout("agent took too long"))
    wf, store = run_workflow(CASE_CLEAN, FLOW, MemoryStore(), fakes(receiving=timeout_client)), None
    assert timeout_client.calls == 2, "initial try + 1 retry"
    assert wf["status"] == "FAILED"

    # Refusal (4xx): never retries
    refusal_client = Boom(AgentRejected("HTTP 404: Not Found"))
    wf2 = run_workflow(CASE_CLEAN, FLOW, MemoryStore(), fakes(receiving=refusal_client))
    assert refusal_client.calls == 1, "refusal never retries"
    assert wf2["status"] == "FAILED"


# ------------------------------------------------------------
# 4. Failure is recorded as degraded record + error; NEVER success
# ------------------------------------------------------------
def test_failure_is_recorded_as_degraded_record_and_never_success():
    crash_client = Boom(RuntimeError("Out of memory in vision model"))
    store = MemoryStore()
    wf = run_workflow(CASE_CLEAN, FLOW, store, fakes(prep=crash_client))

    assert wf["status"] == "FAILED"
    assert wf["final_outcome"]["outcome"] == "INCOMPLETE"
    assert wf["final_outcome"]["provisional"] is True
    assert wf["final_outcome"]["outcome"] != "CLEAN"

    sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    assert sr["state"] == "error"
    assert sr["error"]["code"] == "agent_exception"
    rec = store.get_evidence(sr["record_id"], CASE_CLEAN["org_id"])
    assert rec["decision"]["verdict"] == "UNCERTAIN"
    assert rec["checks"] == []
    assert verify(rec)


# ------------------------------------------------------------
# 5. Evidence is immutable; overrides require actor and reason
# ------------------------------------------------------------
def test_evidence_immutability_and_overrides_chain():
    store = MemoryStore()
    wf = run_workflow(CASE_CLEAN, FLOW, store, fakes(prep="FAIL"))
    prep_sr = next(s for s in wf["stage_results"] if s["stage"] == "prep")
    prep_id = prep_sr["record_id"]

    orig_evidence = store.get_evidence(prep_id, CASE_CLEAN["org_id"])
    assert orig_evidence["decision"]["verdict"] == "FAIL"

    # Direct tamper fails with EvidenceConflict
    tampered = dict(orig_evidence)
    tampered["decision"] = {**tampered["decision"], "verdict": "PASS"}
    from shared.utils.hashing import seal
    with pytest.raises(EvidenceConflict):
        store.put_evidence(seal(tampered), CASE_CLEAN["org_id"])

    # Override without actor or reason fails
    with pytest.raises(ValueError):
        apply_override(wf["workflow_id"], store, record_id=prep_id, new_verdict="PASS", actor="", reason="test")
    with pytest.raises(ValueError):
        apply_override(wf["workflow_id"], store, record_id=prep_id, new_verdict="PASS", actor="op", reason=" ")

    # Valid override succeeds
    wf_after = apply_override(
        wf["workflow_id"],
        store,
        record_id=prep_id,
        new_verdict="PASS",
        actor="op_sarah",
        reason="Barcode label orientation adjusted; passes inspection",
    )
    # Original record untouched
    assert store.get_evidence(prep_id, CASE_CLEAN["org_id"]) == orig_evidence
    # Effective verdict updated
    assert wf_after["final_outcome"]["effective_verdicts"]["prep"] == "PASS"
    assert wf_after["final_outcome"]["outcome"] == "CLEAN"


# ------------------------------------------------------------
# 6. Status & Final Outcome derived via pure functions
# ------------------------------------------------------------
def test_status_and_final_outcome_derivation_precedence():
    store = MemoryStore()

    # Clean route -> COMPLETED / CLEAN
    wf_clean = run_workflow(CASE_CLEAN, FLOW, store, fakes())
    assert (wf_clean["status"], wf_clean["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")
    assert wf_clean["final_outcome"]["provisional"] is False
    assert wf_clean["final_outcome"]["contributing_records"]

    # Exception route -> COMPLETED / EXCEPTION
    wf_exc = run_workflow(CASE_CLEAN, FLOW, MemoryStore(), fakes(prep="FAIL"))
    assert (wf_exc["status"], wf_exc["final_outcome"]["outcome"]) == ("COMPLETED", "EXCEPTION")

    # Claim route -> COMPLETED / CLAIM_RECOMMENDED
    wf_claim = run_workflow(
        CASE_RETURN,
        FLOW,
        MemoryStore(),
        fakes(recovery=Fake("FAIL", needs_human=False, payload={"claimable_usd": 18.50})),
    )
    assert (wf_claim["status"], wf_claim["final_outcome"]["outcome"]) == ("COMPLETED", "CLAIM_RECOMMENDED")
    assert wf_claim["final_outcome"]["claimable_usd"] == 18.50
    assert wf_claim["final_outcome"]["contributing_records"]

    # Incomplete required stage -> FAILED / INCOMPLETE, never COMPLETED
    wf_inc = run_workflow(CASE_CLEAN, FLOW, MemoryStore(), fakes(receiving=Boom(RuntimeError("crash"))))
    assert wf_inc["status"] == "FAILED"
    assert wf_inc["final_outcome"]["outcome"] == "INCOMPLETE"
    assert wf_inc["final_outcome"]["provisional"] is True


# ------------------------------------------------------------
# 7. UNCERTAIN with needs_human leads to BLOCKED / NEEDS_REVIEW, then resume
# ------------------------------------------------------------
def test_uncertain_with_needs_human_blocks_and_resumes():
    flow_block = custom_flow(on_uncertain="block")
    store = MemoryStore()
    clients = fakes(receiving="UNCERTAIN")

    wf = run_workflow(CASE_CLEAN, flow_block, store, clients)
    assert wf["status"] == "BLOCKED"
    assert wf["final_outcome"]["outcome"] == "INCOMPLETE"
    assert wf["final_outcome"]["needs_human"] is True
    assert wf["final_outcome"]["provisional"] is True

    # Record human override
    rcv_id = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "receiving")
    wf_overridden = apply_override(
        wf["workflow_id"],
        store,
        record_id=rcv_id,
        new_verdict="PASS",
        actor="supervisor_dan",
        reason="Manual check verified intact carton seal",
        org_id=CASE_CLEAN["org_id"],
    )
    assert wf_overridden["status"] == "BLOCKED", "Override alone does not resume"

    # Resume clears halt and completes workflow
    wf_resumed = resume(wf["workflow_id"], flow_block, store, clients, org_id=CASE_CLEAN["org_id"])
    assert (wf_resumed["status"], wf_resumed["final_outcome"]["outcome"]) == ("COMPLETED", "CLEAN")
    assert wf_resumed["final_outcome"]["provisional"] is False


# ------------------------------------------------------------
# 8. Idempotency & Tenant Isolation
# ------------------------------------------------------------
def test_workflow_idempotency_and_tenant_isolation():
    store = MemoryStore()
    clients = fakes()

    # Running twice does not advance or duplicate evidence
    wf1 = run_workflow(CASE_CLEAN, FLOW, store, clients)
    wf2 = run_workflow(CASE_CLEAN, FLOW, store, clients)
    assert wf1["evidence_references"] == wf2["evidence_references"]
    assert wf1["stage_results"] == wf2["stage_results"]

    # Cross-tenant access is rejected at store level
    with pytest.raises(TenantViolation):
        store.get_evidence(wf1["evidence_references"][0], org_id="org_other_tenant")
